import pytest

from tests.ollama_stub import OllamaStub


@pytest.fixture
def ollama():
    """A running stand-in for the Ollama server."""
    stub = OllamaStub().start()
    yield stub
    stub.stop()
