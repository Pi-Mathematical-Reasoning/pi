"""The Ollama client, driven over real HTTP against a local stand-in server."""

import socket

import pytest

from pi.config import Generation
from pi.ollama import ChatResult, OllamaClient, OllamaError, OllamaTimeout, OllamaUnavailable
from tests.ollama_stub import DIGEST

GENERATION = Generation(
    think=True,
    context_length=16384,
    max_output_tokens=8192,
    temperature=0.6,
    top_p=0.95,
    top_k=20,
    seed=1,
    time_limit_seconds=30,
)


def test_reports_the_server_version(ollama):
    assert OllamaClient(ollama.host).version() == "0.40.13"


def test_finds_the_digest_of_an_installed_model(ollama):
    assert OllamaClient(ollama.host).installed_digest("qwen3:14b") == DIGEST


def test_reports_no_digest_for_a_model_that_is_not_installed(ollama):
    assert OllamaClient(ollama.host).installed_digest("qwen3:32b") is None


def test_reports_the_memory_ollama_says_the_loaded_model_takes(ollama):
    assert OllamaClient(ollama.host).loaded_bytes("qwen3:14b") == 9_952_024_329


def test_reports_no_memory_for_a_model_that_is_not_loaded(ollama):
    ollama.loaded = False

    assert OllamaClient(ollama.host).loaded_bytes("qwen3:14b") is None


def test_unload_asks_ollama_to_drop_the_model(ollama):
    OllamaClient(ollama.host).unload("qwen3:14b")

    assert ollama.requests_to("/api/generate") == [
        ("POST", "/api/generate", {"model": "qwen3:14b", "keep_alive": 0})
    ]


def test_unload_waits_until_the_model_has_gone(ollama):
    ollama.unload_lag = 2

    OllamaClient(ollama.host).unload("qwen3:14b", poll_interval=0.01)

    # Two answers that still listed the model, then one that did not.
    assert len(ollama.requests_to("/api/ps")) == 3


def test_unload_fails_if_the_model_stays_loaded(ollama):
    ollama.unload_lag = 10**9

    with pytest.raises(OllamaError, match="still loaded"):
        OllamaClient(ollama.host).unload("qwen3:14b", poll_interval=0.01, timeout=0.1)


def test_describes_a_model(ollama):
    description = OllamaClient(ollama.host).describe("qwen3:14b")

    assert description["details"]["quantization_level"] == "Q4_K_M"
    assert ollama.requests_to("/api/show") == [("POST", "/api/show", {"model": "qwen3:14b"})]


def test_sends_only_the_problem_with_the_generation_settings(ollama):
    OllamaClient(ollama.host).chat("qwen3:14b", "What is 2 + 2?", GENERATION)

    assert ollama.requests_to("/api/chat") == [
        (
            "POST",
            "/api/chat",
            {
                "model": "qwen3:14b",
                "stream": False,
                "think": True,
                "messages": [{"role": "user", "content": "What is 2 + 2?"}],
                "options": {
                    "num_ctx": 16384,
                    "num_predict": 8192,
                    "temperature": 0.6,
                    "top_p": 0.95,
                    "top_k": 20,
                    "seed": 1,
                },
            },
        )
    ]


def test_returns_the_answer_the_reasoning_and_the_timings(ollama):
    result = OllamaClient(ollama.host).chat("qwen3:14b", "What is 2 + 2?", GENERATION)

    assert result == ChatResult(
        content="The sum is 12.",
        thinking="Two cases.",
        done_reason="stop",
        prompt_tokens=26,
        cached_prompt_tokens=0,
        output_tokens=256,
        load_seconds=9.0,
        prompt_seconds=0.25,
        output_seconds=12.8,
        total_seconds=22.1,
    )


def test_reports_how_much_of_the_prompt_was_already_in_the_cache(ollama):
    ollama.chat["prompt_eval_cached_count"] = 31

    result = OllamaClient(ollama.host).chat("qwen3:14b", "What is 2 + 2?", GENERATION)

    assert result.cached_prompt_tokens == 31


def test_does_not_guess_the_cache_count_when_the_server_omits_it(ollama):
    del ollama.chat["prompt_eval_cached_count"]

    result = OllamaClient(ollama.host).chat("qwen3:14b", "What is 2 + 2?", GENERATION)

    assert result.cached_prompt_tokens is None


def test_reads_a_reply_that_has_no_reasoning(ollama):
    del ollama.chat["message"]["thinking"]

    result = OllamaClient(ollama.host).chat("qwen3:14b", "What is 2 + 2?", GENERATION)

    assert result.thinking == ""


def test_gives_up_when_the_model_runs_past_the_time_limit(ollama):
    ollama.chat_delay = 5
    hurried = Generation(**{**vars(GENERATION), "time_limit_seconds": 0.2})

    with pytest.raises(OllamaTimeout, match="0.2"):
        OllamaClient(ollama.host).chat("qwen3:14b", "What is 2 + 2?", hurried)


def test_says_so_when_the_server_cannot_be_reached():
    with socket.socket() as placeholder:
        placeholder.bind(("127.0.0.1", 0))
        closed_port = placeholder.getsockname()[1]
    host = f"http://127.0.0.1:{closed_port}"

    with pytest.raises(OllamaUnavailable, match=host):
        OllamaClient(host).version()


def test_passes_on_the_reason_the_server_gives_for_an_error(ollama):
    ollama.chat_error = (404, "model 'qwen3:14b' not found")

    with pytest.raises(OllamaError, match="model 'qwen3:14b' not found"):
        OllamaClient(ollama.host).chat("qwen3:14b", "What is 2 + 2?", GENERATION)
