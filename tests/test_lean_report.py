"""The first line of a Lean run's report."""

import json

from pi.report import build_report


def saved_run(tmp_path, verdicts, ids, complete):
    run = {
        "kind": "evaluation",
        "complete": complete,
        "benchmark": {"name": "sample", "kind": "lean", "ids": ids},
    }
    (tmp_path / "run.json").write_text(json.dumps(run))
    results = [{"id": f"t{i}", "verdict": v} for i, v in enumerate(verdicts)]
    (tmp_path / "results.jsonl").write_text("".join(json.dumps(r) + "\n" for r in results))


def test_a_finished_run_is_titled_with_its_score(tmp_path):
    saved_run(tmp_path, ["proved", "failed", "missing"], ["t0", "t1", "t2"], True)

    assert build_report(tmp_path) == "# sample: 1 of 3 proved (33.3%)\n"


def test_an_interrupted_run_says_it_is_not_a_score(tmp_path):
    saved_run(tmp_path, ["proved", "cut_off"], ["t0", "t1", "t2", "t3"], False)

    assert build_report(tmp_path) == (
        "# sample: incomplete, 2 of 4 theorems attempted\n"
        "\n"
        "The run was interrupted. 1 of the 2 theorems attempted so far are proved, "
        "which is not a score for the benchmark.\n"
    )
