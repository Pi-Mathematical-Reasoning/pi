"""The checkpoint probe: run one problem and record what it took.

The record answers the first question of the baseline: which exact checkpoint
and runtime ran, and whether a problem finishes at a practical speed on this
machine. Nothing is graded here.
"""

import time
from dataclasses import asdict
from datetime import UTC, datetime

from pi.checkpoint import inspect_checkpoint
from pi.config import Config
from pi.ollama import OllamaClient, OllamaTimeout
from pi.resources import ResourceSampler, without_home


def run_probe(
    config: Config,
    client: OllamaClient,
    sampler: ResourceSampler,
    *,
    command: list[str],
    code: dict | None,
    clock=time.monotonic,
) -> dict:
    name = config.model.name
    checkpoint = inspect_checkpoint(config, client)

    # Start from a fresh load: the same seed gives different text when the
    # prompt is already in the model's cache.
    client.unload(name)

    started_at = datetime.now(UTC)
    with sampler:
        started = clock()
        try:
            reply = client.chat(name, config.probe.problem, config.generation)
        except OllamaTimeout:
            reply = None
        elapsed = clock() - started
        reported = client.loaded_bytes(name)

    speed = None
    if reply is not None and reply.output_seconds > 0:
        speed = reply.output_tokens / reply.output_seconds

    return {
        "kind": "probe",
        "started_at": started_at.isoformat(timespec="seconds"),
        "command": command,
        "code": code,
        "config": asdict(config),
        "runtime": {
            **checkpoint["runtime"],
            "runner_commands": [without_home(c) for c in sampler.runner_commands],
        },
        "model": checkpoint["model"],
        "response": None
        if reply is None
        else {
            "content": reply.content,
            "thinking": reply.thinking,
            "done_reason": reply.done_reason,
        },
        "measurements": {
            "finished": reply is not None and reply.done_reason == "stop",
            "timed_out": reply is None,
            "elapsed_seconds": elapsed,
            "load_seconds": None if reply is None else reply.load_seconds,
            "prompt_tokens": None if reply is None else reply.prompt_tokens,
            "cached_prompt_tokens": None if reply is None else reply.cached_prompt_tokens,
            "output_tokens": None if reply is None else reply.output_tokens,
            "output_tokens_per_second": speed,
            "peak_memory_bytes": sampler.peak_resident_bytes,
            "ollama_reported_bytes": reported,
            "swap_before_bytes": sampler.swap_before_bytes,
            "swap_peak_bytes": sampler.swap_peak_bytes,
            "swap_growth_bytes": sampler.swap_growth_bytes,
        },
    }


def summarize(record: dict) -> str:
    """The measurements of a probe record, for a person to read."""
    model, measured = record["model"], record["measurements"]
    limit = record["config"]["generation"]["time_limit_seconds"]

    if measured["finished"]:
        finished = "yes"
    elif measured["timed_out"]:
        finished = f"no, timed out after {limit:g} s"
    else:
        finished = f"no, stopped early ({record['response']['done_reason']})"

    elapsed = f"{measured['elapsed_seconds']:.1f} s"
    if measured["load_seconds"] is not None:
        elapsed += f", of which {measured['load_seconds']:.1f} s loading the model"

    speed = measured["output_tokens_per_second"]
    rows = [
        ("finished", finished),
        ("output tokens", _or_missing(measured["output_tokens"], "not reported")),
        ("speed", "not reported" if speed is None else f"{speed:.1f} tokens/s"),
        ("elapsed", elapsed),
        ("peak memory", _gib(measured["peak_memory_bytes"], 1)),
        ("swap growth", _gib(measured["swap_growth_bytes"], 2)),
    ]
    heading = (
        f"{model['name']} ({model['quantization']}, {model['parameter_size']}) "
        f"on Ollama {record['runtime']['version']}"
    )
    return "\n".join([heading, *(f"  {label:<14} {value}" for label, value in rows)])


def _or_missing(value, missing: str) -> str:
    return missing if value is None else str(value)


def _gib(size: int | None, places: int) -> str:
    return "not measured" if size is None else f"{size / 2**30:.{places}f} GiB"
