"""Which checkpoint is installed, and whether it is the pinned one."""

import re

from pi.config import Config
from pi.ollama import OllamaClient


class CheckpointError(Exception):
    """The pinned checkpoint is not the one installed."""


def inspect_checkpoint(config: Config, client: OllamaClient) -> dict:
    """Describe the runtime and the installed model, refusing any but the pinned one."""
    name = config.model.name
    version = client.version()

    installed = client.installed_digest(name)
    if installed is None:
        raise CheckpointError(f"{name} is not installed; run `ollama pull {name}`")
    if installed != config.model.digest:
        raise CheckpointError(
            f"the installed {name} has digest {installed}, "
            f"but the configuration pins {config.model.digest}"
        )

    description = client.describe(name)
    return {
        "runtime": {"name": "ollama", "version": version},
        "model": {
            "name": name,
            "digest": installed,
            "weights": _weights(description.get("modelfile", "")),
            "format": description["details"]["format"],
            "parameter_size": description["details"]["parameter_size"],
            "quantization": description["details"]["quantization_level"],
            "default_parameters": description.get("parameters", ""),
            "tokenizer": _tokenizer(description.get("model_info", {})),
        },
    }


_BLOB = re.compile(r"^FROM .*?(sha256-[0-9a-f]{64})\s*$", re.MULTILINE)


def _weights(modelfile: str) -> str | None:
    """The content hash of the weights file the model was built from."""
    match = _BLOB.search(modelfile)
    return match.group(1) if match else None


def _tokenizer(model_info: dict) -> dict:
    """The tokenizer settings, without the vocabulary arrays Ollama leaves empty."""
    return {
        key: value
        for key, value in model_info.items()
        if key.startswith("tokenizer.") and value != []
    }
