"""The checkpoint probe: one problem, with the checkpoint and the machine recorded."""

from pathlib import Path

import pytest

from pi.checkpoint import CheckpointError
from pi.config import Config, Generation, ModelPin, Probe, Runtime
from pi.ollama import OllamaClient
from pi.probe import run_probe
from pi.resources import OllamaTree, ResourceSampler
from tests.ollama_stub import DIGEST


def config_for(ollama, **changes):
    settings = {
        "model": ModelPin(name="qwen3:14b", digest=DIGEST),
        "runtime": Runtime(host=ollama.host),
        "generation": Generation(
            think=True,
            context_length=16384,
            max_output_tokens=8192,
            temperature=0.6,
            top_p=0.95,
            top_k=20,
            seed=1,
            time_limit_seconds=30,
        ),
        "probe": Probe(problem="What is 2 + 2?"),
    }
    return Config(**{**settings, **changes})


def sampler_reading(trees=(None,), swap=(None,)):
    def reader(values):
        remaining = list(values)
        return lambda: remaining.pop(0) if len(remaining) > 1 else remaining[0]

    return ResourceSampler(reader(trees), reader(swap), interval=60)


def probe(ollama, config=None, sampler=None, **options):
    return run_probe(
        config or config_for(ollama),
        OllamaClient(ollama.host),
        sampler or sampler_reading(),
        command=["pi", "probe", "--config", "configs/baseline.toml"],
        code={"revision": "abc123", "dirty": False},
        **options,
    )


def test_refuses_to_run_a_checkpoint_other_than_the_pinned_one(ollama):
    other = "0" * 64
    config = config_for(ollama, model=ModelPin(name="qwen3:14b", digest=other))

    with pytest.raises(CheckpointError, match=f"{DIGEST}.*{other}"):
        probe(ollama, config)

    assert ollama.requests_to("/api/chat") == []
    # A refused probe leaves the machine as it found it.
    assert ollama.requests_to("/api/generate") == []


def test_starts_from_a_freshly_loaded_model(ollama):
    # With the same seed, a model that already holds the prompt in its cache
    # writes different text from one that was just loaded.
    probe(ollama)

    paths = [path for _, path, _ in ollama.requests]
    assert ollama.requests_to("/api/generate") == [
        ("POST", "/api/generate", {"model": "qwen3:14b", "keep_alive": 0})
    ]
    assert paths.index("/api/generate") < paths.index("/api/chat")


def test_says_how_to_install_a_model_that_is_missing(ollama):
    config = config_for(ollama, model=ModelPin(name="qwen3:32b", digest=DIGEST))

    with pytest.raises(CheckpointError, match="ollama pull qwen3:32b"):
        probe(ollama, config)


def test_records_the_exact_checkpoint(ollama):
    record = probe(ollama)

    assert record["model"] == {
        "name": "qwen3:14b",
        "digest": DIGEST,
        "weights": "sha256-a8cc1361f3145dc01f6d77c6c82c9116b9ffe3c97b34716fe20418455876c40e",
        "format": "gguf",
        "parameter_size": "14.8B",
        "quantization": "Q4_K_M",
        "default_parameters": ollama.show["parameters"],
        "tokenizer": {
            "tokenizer.ggml.add_bos_token": False,
            "tokenizer.ggml.bos_token_id": 151643,
            "tokenizer.ggml.eos_token_id": 151645,
            "tokenizer.ggml.model": "gpt2",
            "tokenizer.ggml.padding_token_id": 151643,
            "tokenizer.ggml.pre": "qwen2",
        },
    }


def test_records_the_runtime_and_how_it_launched_the_model(ollama):
    launched = OllamaTree(resident_bytes=1, runner_commands=("llama-server -c 16384",))

    record = probe(ollama, sampler=sampler_reading(trees=[launched]))

    assert record["runtime"] == {
        "name": "ollama",
        "version": "0.40.13",
        "runner_commands": ["llama-server -c 16384"],
    }


def test_writes_the_runner_command_without_the_home_directory(ollama):
    command = f"llama-server --model {Path.home()}/.ollama/models/blobs/sha256-a8cc"
    launched = OllamaTree(resident_bytes=1, runner_commands=(command,))

    record = probe(ollama, sampler=sampler_reading(trees=[launched]))

    assert record["runtime"]["runner_commands"] == [
        "llama-server --model ~/.ollama/models/blobs/sha256-a8cc"
    ]


def test_measures_speed_from_the_tokens_the_model_generated(ollama):
    measurements = probe(ollama)["measurements"]

    # The stand-in server reports 256 tokens generated in 12.8 seconds.
    assert measurements["output_tokens"] == 256
    assert measurements["output_tokens_per_second"] == 20.0
    assert measurements["prompt_tokens"] == 26
    assert measurements["load_seconds"] == 9.0
    assert measurements["finished"] is True
    assert measurements["timed_out"] is False


def test_records_how_much_of_the_prompt_was_already_in_the_cache(ollama):
    # A run that reuses a cached prompt is not in the same state as a fresh one.
    ollama.chat["prompt_eval_cached_count"] = 31

    assert probe(ollama)["measurements"]["cached_prompt_tokens"] == 31


def test_measures_elapsed_time_on_its_own_clock(ollama):
    ticks = iter([100.0, 112.5])

    measurements = probe(ollama, clock=lambda: next(ticks))["measurements"]

    assert measurements["elapsed_seconds"] == 12.5


def test_records_peak_memory_and_swap_growth(ollama):
    loading = OllamaTree(resident_bytes=100, runner_commands=())
    loaded = OllamaTree(resident_bytes=900, runner_commands=("llama-server",))

    measurements = probe(ollama, sampler=sampler_reading([loading, loaded], [10, 50]))[
        "measurements"
    ]

    assert measurements["peak_memory_bytes"] == 900
    assert measurements["swap_before_bytes"] == 10
    assert measurements["swap_peak_bytes"] == 50
    assert measurements["swap_growth_bytes"] == 40
    assert measurements["ollama_reported_bytes"] == 9_952_024_329


def test_a_reply_cut_off_at_the_output_limit_did_not_finish(ollama):
    ollama.chat["done_reason"] = "length"

    measurements = probe(ollama)["measurements"]

    assert measurements["finished"] is False
    assert measurements["timed_out"] is False


def test_a_model_that_runs_out_of_time_is_recorded_rather_than_raised(ollama):
    ollama.chat_delay = 5
    generation = Generation(**{**vars(config_for(ollama).generation), "time_limit_seconds": 0.2})

    record = probe(ollama, config_for(ollama, generation=generation))

    assert record["response"] is None
    assert record["measurements"]["timed_out"] is True
    assert record["measurements"]["finished"] is False
    assert record["measurements"]["output_tokens"] is None
    assert record["measurements"]["output_tokens_per_second"] is None


def test_keeps_the_reply_and_the_reasoning(ollama):
    assert probe(ollama)["response"] == {
        "content": "The sum is 12.",
        "thinking": "Two cases.",
        "done_reason": "stop",
    }


def test_quotes_the_command_the_code_revision_and_the_configuration(ollama):
    record = probe(ollama)

    assert record["kind"] == "probe"
    assert record["command"] == ["pi", "probe", "--config", "configs/baseline.toml"]
    assert record["code"] == {"revision": "abc123", "dirty": False}
    assert record["config"]["model"] == {"name": "qwen3:14b", "digest": DIGEST}
    assert record["config"]["generation"]["context_length"] == 16384
    assert record["config"]["probe"]["problem"] == "What is 2 + 2?"
