"""Loading a run configuration: the model pin and the generation settings."""

from pathlib import Path

import pytest

from pi.config import ConfigError, load_config

DIGEST = "bdbd181c33f2ed1b31c972991882db3cf4d192569092138a7d29e973cd9debe8"

VALID = f"""
[model]
name = "qwen3:14b"
digest = "{DIGEST}"

[runtime]
host = "http://127.0.0.1:11434"

[generation]
think = true
context_length = 16384
max_output_tokens = 8192
temperature = 0.6
top_p = 0.95
top_k = 20
seed = 1
time_limit_seconds = 600
num_batch = 1024
use_mmap = true

[probe]
problem = "What is 2 + 2?"
"""


def write(tmp_path, text):
    path = tmp_path / "config.toml"
    path.write_text(text)
    return path


def test_loads_the_model_pin_and_the_generation_settings(tmp_path):
    config = load_config(write(tmp_path, VALID))

    assert config.model.name == "qwen3:14b"
    assert config.model.digest == DIGEST
    assert config.runtime.host == "http://127.0.0.1:11434"
    assert config.generation.think is True
    assert config.generation.context_length == 16384
    assert config.generation.max_output_tokens == 8192
    assert config.generation.temperature == 0.6
    assert config.generation.top_p == 0.95
    assert config.generation.top_k == 20
    assert config.generation.seed == 1
    assert config.generation.time_limit_seconds == 600
    assert config.generation.num_batch == 1024
    assert config.generation.use_mmap is True
    assert config.probe.problem == "What is 2 + 2?"


def test_refuses_a_config_that_leaves_the_batch_size_to_ollama(tmp_path):
    # Ollama picks a batch size and memory mapping from free memory when the
    # request names none, and both change the numbers.
    unpinned = VALID.replace("num_batch = 1024\n", "")

    with pytest.raises(ConfigError, match=r"generation\.num_batch"):
        load_config(write(tmp_path, unpinned))


def test_rejects_a_config_without_the_model_digest(tmp_path):
    without_pin = VALID.replace(f'digest = "{DIGEST}"\n', "")

    with pytest.raises(ConfigError, match=r"model\.digest"):
        load_config(write(tmp_path, without_pin))


def test_rejects_a_setting_of_the_wrong_type(tmp_path):
    wrong_type = VALID.replace("context_length = 16384", 'context_length = "large"')

    with pytest.raises(ConfigError, match=r"generation\.context_length"):
        load_config(write(tmp_path, wrong_type))


def test_rejects_true_where_a_number_is_expected(tmp_path):
    wrong_type = VALID.replace("top_k = 20", "top_k = true")

    with pytest.raises(ConfigError, match=r"generation\.top_k"):
        load_config(write(tmp_path, wrong_type))


def test_rejects_a_setting_it_does_not_know(tmp_path):
    # A misspelt setting must not be dropped silently: the run would use a
    # default while its record claimed otherwise.
    misspelt = VALID.replace(
        "max_output_tokens = 8192", "max_output_tokens = 8192\nmax_tokens = 64"
    )

    with pytest.raises(ConfigError, match=r"generation\.max_tokens"):
        load_config(write(tmp_path, misspelt))


def test_accepts_a_whole_number_for_a_decimal_setting(tmp_path):
    whole = VALID.replace("temperature = 0.6", "temperature = 1")

    assert load_config(write(tmp_path, whole)).generation.temperature == 1.0


def test_reports_a_missing_file_as_a_config_error(tmp_path):
    with pytest.raises(ConfigError, match="no-such-file.toml"):
        load_config(tmp_path / "no-such-file.toml")


def test_refuses_an_output_limit_that_leaves_no_room_for_the_problem(tmp_path):
    # The problem and the whole reply share the context, so a reply as long
    # as the context could never be finished.
    no_room = VALID.replace("max_output_tokens = 8192", "max_output_tokens = 16384")

    with pytest.raises(ConfigError, match=r"generation\.max_output_tokens"):
        load_config(write(tmp_path, no_room))


def test_every_committed_configuration_loads():
    configs = sorted((Path(__file__).parent.parent / "configs").glob("*.toml"))

    assert configs, "no committed configuration to check"
    for path in configs:
        load_config(path)


ROOT = Path(__file__).resolve().parents[1]

LEAN = """
[lean]
instruction = "Complete the theorem."
compile_time_limit_seconds = 300
judge_time_limit_seconds = 60
"""


def test_a_configuration_without_a_lean_section_has_none():
    assert load_config(ROOT / "configs" / "qwen3-14b.toml").lean is None


def test_a_lean_section_is_loaded_with_its_three_settings(tmp_path):
    lean = load_config(write(tmp_path, VALID + LEAN)).lean

    assert lean.instruction == "Complete the theorem."
    assert lean.compile_time_limit_seconds == 300
    assert lean.judge_time_limit_seconds == 60


def test_a_lean_section_must_state_every_setting(tmp_path):
    without_instruction = LEAN.replace('instruction = "Complete the theorem."\n', "")

    with pytest.raises(ConfigError, match=r"missing setting lean\.instruction"):
        load_config(write(tmp_path, VALID + without_instruction))


def test_refuses_an_unknown_lean_setting(tmp_path):
    with pytest.raises(ConfigError, match=r"unknown setting lean\.retries"):
        load_config(write(tmp_path, VALID + LEAN + "retries = 3\n"))


def test_refuses_a_blank_lean_instruction(tmp_path):
    blank = LEAN.replace('"Complete the theorem."', '"  "')

    with pytest.raises(ConfigError, match=r"lean\.instruction"):
        load_config(write(tmp_path, VALID + blank))


@pytest.mark.parametrize("setting", ["compile_time_limit_seconds", "judge_time_limit_seconds"])
@pytest.mark.parametrize("value", ["0", "-5"])
def test_refuses_a_lean_time_limit_that_is_not_positive(tmp_path, setting, value):
    text = LEAN.replace(
        f"{setting} = {300 if 'compile' in setting else 60}", f"{setting} = {value}"
    )

    with pytest.raises(ConfigError, match=rf"lean\.{setting}"):
        load_config(write(tmp_path, VALID + text))


def test_the_lean_configuration_differs_from_the_baseline_only_in_its_lean_section():
    lean = load_config(ROOT / "configs" / "qwen3-14b-lean.toml")
    base = load_config(ROOT / "configs" / "qwen3-14b.toml")

    assert (lean.model, lean.runtime, lean.generation, lean.probe) == (
        base.model,
        base.runtime,
        base.generation,
        base.probe,
    )
    assert (lean.lean.compile_time_limit_seconds, lean.lean.judge_time_limit_seconds) == (300, 300)
