"""The `pi` command, run in-process against a local stand-in for Ollama."""

import json
import socket
import subprocess
import sys

from pi.cli import main
from tests.ollama_stub import DIGEST

CONFIG = """
[model]
name = "qwen3:14b"
digest = "{digest}"

[runtime]
host = "{host}"

[generation]
think = true
context_length = 16384
max_output_tokens = 8192
temperature = 0.6
top_p = 0.95
top_k = 20
seed = 1
time_limit_seconds = {time_limit}

[probe]
problem = "What is 2 + 2?"
"""


def write_config(tmp_path, host, digest=DIGEST, time_limit=30):
    path = tmp_path / "baseline.toml"
    path.write_text(CONFIG.format(host=host, digest=digest, time_limit=time_limit))
    return str(path)


def test_probe_writes_the_record_and_prints_the_measurements(ollama, tmp_path, capsys):
    out = tmp_path / "records" / "probe.json"

    status = main(["probe", "--config", write_config(tmp_path, ollama.host), "--out", str(out)])

    assert status == 0
    record = json.loads(out.read_text())
    assert record["kind"] == "probe"
    assert record["measurements"]["output_tokens"] == 256
    assert record["command"][:2] == ["pi", "probe"]
    printed = capsys.readouterr().out
    assert "qwen3:14b" in printed
    assert "20.0 tokens/s" in printed
    assert str(out) in printed


def test_probe_writes_to_the_runs_directory_by_default(ollama, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    status = main(["probe", "--config", write_config(tmp_path, ollama.host)])

    assert status == 0
    assert len(list((tmp_path / "runs").glob("probe-*.json"))) == 1


def test_probe_stops_on_the_wrong_checkpoint_and_writes_nothing(ollama, tmp_path, capsys):
    out = tmp_path / "probe.json"
    config = write_config(tmp_path, ollama.host, digest="0" * 64)

    status = main(["probe", "--config", config, "--out", str(out)])

    assert status == 1
    assert "pins" in capsys.readouterr().err
    assert not out.exists()


def test_probe_explains_an_unreachable_server(tmp_path, capsys):
    with socket.socket() as placeholder:
        placeholder.bind(("127.0.0.1", 0))
        closed_port = placeholder.getsockname()[1]
    config = write_config(tmp_path, f"http://127.0.0.1:{closed_port}")

    status = main(["probe", "--config", config, "--out", str(tmp_path / "probe.json")])

    assert status == 1
    assert "ollama serve" in capsys.readouterr().err


def test_probe_explains_a_missing_configuration(tmp_path, capsys):
    status = main(["probe", "--config", str(tmp_path / "absent.toml")])

    assert status == 1
    assert "absent.toml" in capsys.readouterr().err


def test_a_reply_that_was_cut_off_is_reported_as_unfinished(ollama, tmp_path, capsys):
    ollama.chat["done_reason"] = "length"
    config = write_config(tmp_path, ollama.host)

    main(["probe", "--config", config, "--out", str(tmp_path / "probe.json")])

    assert "no, stopped early (length)" in capsys.readouterr().out


def test_a_run_past_the_time_limit_is_reported_as_timed_out(ollama, tmp_path, capsys):
    ollama.chat_delay = 5
    config = write_config(tmp_path, ollama.host, time_limit=0.2)

    status = main(["probe", "--config", config, "--out", str(tmp_path / "probe.json")])

    assert status == 0
    assert "no, timed out after 0.2 s" in capsys.readouterr().out


def test_the_package_runs_as_a_module():
    done = subprocess.run([sys.executable, "-m", "pi", "--help"], capture_output=True, text=True)

    assert done.returncode == 0
    assert "probe" in done.stdout
