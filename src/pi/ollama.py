"""A small client for the Ollama HTTP API, using only the standard library."""

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass

from pi.config import Generation


class OllamaError(Exception):
    """Ollama answered with an error."""


class OllamaUnavailable(OllamaError):
    """No Ollama server answered at the configured host."""


class OllamaTimeout(OllamaError):
    """The model did not finish within the time limit."""


@dataclass(frozen=True)
class ChatResult:
    content: str
    thinking: str
    done_reason: str
    prompt_tokens: int
    cached_prompt_tokens: int | None
    output_tokens: int
    load_seconds: float
    prompt_seconds: float
    output_seconds: float
    total_seconds: float


class OllamaClient:
    def __init__(self, host: str, timeout: float = 10):
        self.host = host.rstrip("/")
        self._timeout = timeout

    def version(self) -> str:
        return self._request("/api/version")["version"]

    def installed_digest(self, model: str) -> str | None:
        """The manifest digest of an installed model, or None if it is not installed."""
        for entry in self._request("/api/tags")["models"]:
            if entry["name"] == model:
                return entry["digest"]
        return None

    def describe(self, model: str) -> dict:
        return self._request("/api/show", {"model": model})

    def loaded_bytes(self, model: str) -> int | None:
        """The memory Ollama reports for a loaded model, or None if it is not loaded."""
        for entry in self._request("/api/ps")["models"]:
            if entry["name"] == model:
                return entry["size"]
        return None

    def unload(self, model: str, poll_interval: float = 0.2, timeout: float = 30) -> None:
        """Drop a model from memory and wait until it has gone.

        The next request then starts from a fresh load. That matters because a
        model that still holds a prompt in its cache generates different text
        from the same seed.
        """
        self._request("/api/generate", {"model": model, "keep_alive": 0}, timeout=timeout)
        deadline = time.monotonic() + timeout
        while self.loaded_bytes(model) is not None:
            if time.monotonic() >= deadline:
                raise OllamaError(f"{model} is still loaded {timeout:g} seconds after unloading")
            time.sleep(poll_interval)

    def chat(self, model: str, problem: str, generation: Generation) -> ChatResult:
        """One attempt at one problem. The model is sent the problem text and nothing else."""
        payload = {
            "model": model,
            "stream": False,
            "think": generation.think,
            "messages": [{"role": "user", "content": problem}],
            "options": {
                "num_ctx": generation.context_length,
                "num_predict": generation.max_output_tokens,
                "temperature": generation.temperature,
                "top_p": generation.top_p,
                "top_k": generation.top_k,
                "seed": generation.seed,
            },
        }
        limit = generation.time_limit_seconds
        try:
            reply = self._request("/api/chat", payload, timeout=limit)
        except TimeoutError:
            raise OllamaTimeout(f"{model} did not finish within {limit:g} seconds") from None

        message = reply["message"]
        return ChatResult(
            content=message.get("content", ""),
            thinking=message.get("thinking", ""),
            done_reason=reply.get("done_reason", ""),
            prompt_tokens=reply.get("prompt_eval_count", 0),
            cached_prompt_tokens=reply.get("prompt_eval_cached_count"),
            output_tokens=reply.get("eval_count", 0),
            load_seconds=_seconds(reply.get("load_duration", 0)),
            prompt_seconds=_seconds(reply.get("prompt_eval_duration", 0)),
            output_seconds=_seconds(reply.get("eval_duration", 0)),
            total_seconds=_seconds(reply.get("total_duration", 0)),
        )

    def _request(self, path: str, payload: dict | None = None, timeout: float | None = None):
        request = urllib.request.Request(
            self.host + path,
            data=None if payload is None else json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout or self._timeout) as response:
                return json.load(response)
        except urllib.error.HTTPError as error:
            raise OllamaError(f"Ollama at {self.host}: {_reason(error)}") from None
        except urllib.error.URLError as error:
            if isinstance(error.reason, TimeoutError):
                raise TimeoutError from None
            raise OllamaUnavailable(
                f"no Ollama server at {self.host} ({error.reason}); is `ollama serve` running?"
            ) from None


def _seconds(nanoseconds: int) -> float:
    return nanoseconds / 1e9


def _reason(error: urllib.error.HTTPError) -> str:
    body = error.read().decode(errors="replace")
    try:
        return json.loads(body)["error"]
    except (ValueError, KeyError, TypeError):
        return f"HTTP {error.code} {body}".strip()
