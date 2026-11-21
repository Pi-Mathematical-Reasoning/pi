"""A run configuration: which checkpoint to load and how to generate with it.

The file is TOML. Every setting is required and none is defaulted, so the
record of a run can quote its configuration and be complete.
"""

import tomllib
from dataclasses import dataclass, fields
from pathlib import Path


class ConfigError(Exception):
    """The configuration file is missing, malformed or incomplete."""


@dataclass(frozen=True)
class ModelPin:
    name: str
    digest: str


@dataclass(frozen=True)
class Runtime:
    host: str


@dataclass(frozen=True)
class Generation:
    think: bool
    context_length: int
    max_output_tokens: int
    temperature: float
    top_p: float
    top_k: int
    seed: int
    time_limit_seconds: float
    # Ollama picks these from free memory when a request names none, and both
    # change the numbers, so a run names them. Defaults serve code, not files:
    # a configuration file must state every setting.
    num_batch: int = 1024
    use_mmap: bool = True


@dataclass(frozen=True)
class Probe:
    problem: str


@dataclass(frozen=True)
class Config:
    model: ModelPin
    runtime: Runtime
    generation: Generation
    probe: Probe


def load_config(path: Path) -> Config:
    path = Path(path)
    try:
        data = tomllib.loads(path.read_text())
    except FileNotFoundError:
        raise ConfigError(f"no configuration file at {path}") from None
    except tomllib.TOMLDecodeError as error:
        raise ConfigError(f"{path} is not valid TOML: {error}") from None

    sections = {field.name: field.type for field in fields(Config)}
    unknown = sorted(set(data) - set(sections))
    if unknown:
        raise ConfigError(f"{path}: unknown section [{unknown[0]}]")
    config = Config(**{name: _section(path, data, name, cls) for name, cls in sections.items()})

    generation = config.generation
    if generation.max_output_tokens >= generation.context_length:
        raise ConfigError(
            f"{path}: generation.max_output_tokens ({generation.max_output_tokens}) must be "
            f"smaller than generation.context_length ({generation.context_length}), "
            "because the problem and the reply share the context"
        )
    return config


def _section(path: Path, data: dict, name: str, cls: type):
    table = data.get(name)
    if not isinstance(table, dict):
        raise ConfigError(f"{path}: missing section [{name}]")

    expected = {field.name: field.type for field in fields(cls)}
    unknown = sorted(set(table) - set(expected))
    if unknown:
        raise ConfigError(f"{path}: unknown setting {name}.{unknown[0]}")

    values = {}
    for key, kind in expected.items():
        if key not in table:
            raise ConfigError(f"{path}: missing setting {name}.{key}")
        values[key] = _typed(path, f"{name}.{key}", table[key], kind)
    return cls(**values)


def _typed(path: Path, setting: str, value, kind: type):
    # bool is a subclass of int, so `true` would otherwise pass as a number.
    is_bool = isinstance(value, bool)
    if kind is float and isinstance(value, (int, float)) and not is_bool:
        return float(value)
    if isinstance(value, kind) and (kind is bool or not is_bool):
        return value
    raise ConfigError(
        f"{path}: {setting} must be {_NAMES[kind]}, not {type(value).__name__} {value!r}"
    )


_NAMES = {bool: "true or false", int: "a whole number", float: "a number", str: "a string"}
