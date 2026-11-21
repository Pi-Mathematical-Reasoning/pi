"""Measurements a result keeps that can only be taken while the problem runs."""

from pi.evaluation import read_results
from pi.resources import OllamaTree, parse_thermal
from tests.test_integrity import ONE, evaluate, ollama, quiet_sampler, sequence  # noqa: F401

THERMAL = ["Note: No thermal warning level has been recorded"]


def only_result(tmp_path):
    (result,) = read_results(tmp_path / "run")
    return result


def test_keeps_ollamas_breakdown_of_where_the_time_went(ollama, tmp_path):  # noqa: F811
    evaluate(ollama, tmp_path / "run", problems=[ONE])

    result = only_result(tmp_path)
    assert (result["prompt_seconds"], result["output_seconds"], result["total_seconds"]) == (
        0.25,
        12.8,
        22.1,
    )
    assert result["metrics"]["eval_duration"] == 12_800_000_000
    assert result["metrics"]["done_reason"] == "stop"


def test_keeps_how_far_the_reply_had_got_over_time(ollama, tmp_path):  # noqa: F811
    evaluate(ollama, tmp_path / "run", problems=[ONE])

    progress = only_result(tmp_path)["progress"]
    assert progress[0][0] == 1  # the first token: time to first token
    assert progress[-1][0] >= progress[0][0]


def test_keeps_when_the_attempt_ended_and_how_long_unloading_took(ollama, tmp_path):  # noqa: F811
    evaluate(ollama, tmp_path / "run", problems=[ONE])

    result = only_result(tmp_path)
    assert result["ended_at"] >= result["started_at"]
    assert result["unload_seconds"] >= 0


def test_keeps_the_attempts_own_peak_memory_and_the_swap_in_use_after_it(ollama, tmp_path):  # noqa: F811
    # Read on entering the session, then right after the attempt, then later on.
    trees = [OllamaTree(500, ()), OllamaTree(900, ()), OllamaTree(700, ())]
    sampler = quiet_sampler(trees, swap=[0, 4096])

    evaluate(ollama, tmp_path / "run", problems=[ONE], sampler=sampler)

    result = only_result(tmp_path)
    assert result["peak_memory_bytes"] == 900
    assert result["swap_used_bytes"] == 4096


def test_keeps_the_thermal_state_after_each_attempt(ollama, tmp_path):  # noqa: F811
    evaluate(ollama, tmp_path / "run", problems=[ONE], read_thermal=lambda: THERMAL)

    assert only_result(tmp_path)["thermal"] == THERMAL


def test_keeps_the_attempts_thrown_away_because_the_machine_slept(ollama, tmp_path):  # noqa: F811
    wakes = sequence(["06:00", "07:00", "07:00", "07:00"])

    evaluate(ollama, tmp_path / "run", problems=[ONE], read_wake=wakes)

    (discarded,) = only_result(tmp_path)["discarded_attempts"]
    assert discarded["reason"] == "the machine slept"
    assert discarded["ended_at"] >= discarded["started_at"]


def test_an_attempt_nothing_interrupted_lists_no_discarded_attempts(ollama, tmp_path):  # noqa: F811
    evaluate(ollama, tmp_path / "run", problems=[ONE])

    assert only_result(tmp_path)["discarded_attempts"] == []


def test_reads_the_thermal_notes_pmset_prints():
    text = (
        "Note: No thermal warning level has been recorded\n"
        "Note: No performance warning level has been recorded\n\n"
    )

    assert parse_thermal(text) == [
        "Note: No thermal warning level has been recorded",
        "Note: No performance warning level has been recorded",
    ]
