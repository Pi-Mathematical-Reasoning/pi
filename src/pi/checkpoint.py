"""Which checkpoint is installed, and whether it is the pinned one."""

import hashlib
import os
import re
from pathlib import Path

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


def verify_weights(name: str | None, models_dir: Path | None = None) -> bool | None:
    """Whether Ollama's weights file holds what its name promises.

    Ollama names each file after the SHA-256 of its content, `sha256-<hex>`.
    True if the content matches, False if it does not, None if the file is not
    there or the name promises no checksum. Hashing 9 GB takes about 15 seconds.
    """
    if not name or not name.startswith("sha256-"):
        return None
    directory = models_dir or Path(os.environ.get("OLLAMA_MODELS", "~/.ollama/models"))
    path = Path(directory).expanduser() / "blobs" / name
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as weights:
        while chunk := weights.read(1 << 24):
            digest.update(chunk)
    return f"sha256-{digest.hexdigest()}" == name
