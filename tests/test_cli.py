"""The `pi` command, run in-process against a local stand-in for Ollama."""

import hashlib
import io
import json
import socket
import subprocess
import sys
from pathlib import Path

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
num_batch = 1024
use_mmap = true

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


def test_grade_accepts_an_equivalent_form_of_the_reference(capsys):
    status = main(["grade", "--reference", r"\frac{1}{2}", "--reply", r"So it is $\boxed{0.5}$."])

    printed = capsys.readouterr().out
    assert status == 0
    assert printed.splitlines()[0] == "correct"
    assert "math-verify" in printed


def test_grade_reports_a_wrong_answer(capsys):
    main(["grade", "--reference", "12", "--reply", r"So it is $\boxed{13}$."])

    assert capsys.readouterr().out.splitlines()[0] == "incorrect"


def test_grade_reports_a_reply_with_no_final_answer(capsys):
    main(["grade", "--reference", "12", "--reply", "I could not work this out."])

    assert capsys.readouterr().out.splitlines()[0] == "missing"


def write_record(tmp_path, response):
    path = tmp_path / "record.json"
    path.write_text(json.dumps({"kind": "probe", "response": response}))
    return str(path)


def test_grade_reads_the_reply_from_a_record_and_ignores_the_reasoning(tmp_path, capsys):
    record = write_record(
        tmp_path,
        {
            "content": r"The sum is $\boxed{12}$.",
            "thinking": r"Maybe \boxed{99}?",
            "done_reason": "stop",
        },
    )

    main(["grade", "--reference", "12", "--record", record])
    assert capsys.readouterr().out.splitlines()[0] == "correct"

    main(["grade", "--reference", "99", "--record", record])
    assert capsys.readouterr().out.splitlines()[0] == "incorrect"


def test_grade_treats_a_record_with_no_reply_as_missing(tmp_path, capsys):
    main(["grade", "--reference", "12", "--record", write_record(tmp_path, None)])

    assert capsys.readouterr().out.splitlines()[0] == "missing"


def test_grade_explains_a_reference_it_cannot_read(capsys):
    status = main(["grade", "--reference", "", "--reply", r"$\boxed{12}$"])

    assert status == 1
    assert "reference" in capsys.readouterr().err


def test_grade_explains_a_record_it_cannot_read(tmp_path, capsys):
    status = main(["grade", "--reference", "12", "--record", str(tmp_path / "absent.json")])

    assert status == 1
    assert "absent.json" in capsys.readouterr().err


PROBLEM_ROWS = [
    {
        "unique_id": "dev/1",
        "problem": "What is $1+1$?",
        "answer": "2",
        "subject": "Algebra",
        "level": 1,
    },
    {
        "unique_id": "dev/2",
        "problem": "How many sides has a triangle?",
        "answer": "3",
        "subject": "Geometry",
        "level": 2,
    },
    {
        "unique_id": "dev/3",
        "problem": "Solve $2x=1$.",
        "answer": "\\frac{1}{2}",
        "subject": "Algebra",
        "level": 3,
    },
]


def write_benchmark(tmp_path):
    """A benchmark definition pinned to a problem file on disk."""
    source = tmp_path / "problems.jsonl"
    source.write_text("".join(json.dumps(row) + "\n" for row in PROBLEM_ROWS))
    definition = tmp_path / "sample.toml"
    definition.write_text(
        'name = "sample"\n'
        f'url = "{source.as_uri()}"\n'
        f'sha256 = "{hashlib.sha256(source.read_bytes()).hexdigest()}"\n'
        'format = "jsonl"\n'
    )
    return str(definition)


def eval_arguments(tmp_path, ollama):
    return [
        "eval",
        "--config",
        write_config(tmp_path, ollama.host),
        "--benchmark",
        write_benchmark(tmp_path),
        "--out",
        str(tmp_path / "run"),
        "--data-dir",
        str(tmp_path / "data"),
    ]


def answer_one_of_three(ollama):
    ollama.replies = {
        "What is $1+1$?": {"content": r"It is $\boxed{2}$."},
        "How many sides has a triangle?": {"content": r"It has $\boxed{4}$."},
        "Solve $2x=1$.": {"content": "I cannot tell."},
    }


def test_eval_runs_every_problem_and_prints_the_score(ollama, tmp_path, capsys):
    answer_one_of_three(ollama)

    status = main(eval_arguments(tmp_path, ollama))

    printed = capsys.readouterr().out
    assert status == 0
    assert "[1/3] dev/1  correct" in printed
    assert "[3/3] dev/3  missing" in printed
    assert "sample: 1 of 3 correct (33.3%)" in printed
    assert len((tmp_path / "run" / "results.jsonl").read_text().splitlines()) == 3
    assert json.loads((tmp_path / "run" / "run.json").read_text())["complete"] is True


def test_eval_that_fails_part_way_says_how_to_resume(ollama, tmp_path, capsys):
    answer_one_of_three(ollama)
    ollama.replies["How many sides has a triangle?"] = {"error": (500, "the runner crashed")}

    status = main(eval_arguments(tmp_path, ollama))

    errors = capsys.readouterr().err
    assert status == 1
    assert "the runner crashed" in errors
    assert "run the same command again to resume" in errors
    assert json.loads((tmp_path / "run" / "run.json").read_text())["complete"] is False


def test_eval_stopped_from_the_keyboard_says_how_to_resume(ollama, tmp_path, capsys, monkeypatch):
    def interrupted(*arguments, **options):
        raise KeyboardInterrupt

    monkeypatch.setattr("pi.cli.run_evaluation", interrupted)

    status = main(eval_arguments(tmp_path, ollama))

    assert status == 130
    assert "run the same command again to resume" in capsys.readouterr().err


def test_eval_explains_a_missing_benchmark_definition(ollama, tmp_path, capsys):
    arguments = eval_arguments(tmp_path, ollama)
    arguments[arguments.index("--benchmark") + 1] = str(tmp_path / "absent.toml")

    status = main(arguments)

    assert status == 1
    assert "absent.toml" in capsys.readouterr().err


def test_report_prints_the_report_of_a_saved_run(ollama, tmp_path, capsys):
    answer_one_of_three(ollama)
    main(eval_arguments(tmp_path, ollama))
    capsys.readouterr()

    status = main(["report", str(tmp_path / "run")])

    printed = capsys.readouterr().out
    assert status == 0
    assert printed.startswith("# sample: 1 of 3 correct (33.3%)\n")
    assert "| dev/2 | incorrect | `4` |" in printed


def test_report_does_not_contact_the_model(ollama, tmp_path):
    answer_one_of_three(ollama)
    main(eval_arguments(tmp_path, ollama))
    before = len(ollama.requests)

    main(["report", str(tmp_path / "run")])

    assert len(ollama.requests) == before


def test_report_writes_to_a_file_when_asked(ollama, tmp_path, capsys):
    answer_one_of_three(ollama)
    main(eval_arguments(tmp_path, ollama))
    capsys.readouterr()

    main(["report", str(tmp_path / "run"), "--out", str(tmp_path / "report.md")])

    assert (tmp_path / "report.md").read_text().startswith("# sample: 1 of 3 correct (33.3%)\n")
    assert str(tmp_path / "report.md") in capsys.readouterr().out


def test_report_explains_a_directory_that_holds_no_run(tmp_path, capsys):
    status = main(["report", str(tmp_path / "nothing-here")])

    assert status == 1
    assert "nothing-here" in capsys.readouterr().err


def test_eval_shows_each_result_as_it_finishes_when_its_output_is_piped(
    ollama, tmp_path, monkeypatch
):
    # A pipe is block-buffered, so an unflushed line stays hidden until the run ends.
    answer_one_of_three(ollama)
    events = []

    class Pipe(io.StringIO):
        def write(self, text):
            events.append(("write", text))
            return super().write(text)

        def flush(self):
            events.append(("flush", ""))

    monkeypatch.setattr(sys, "stdout", Pipe())

    main(eval_arguments(tmp_path, ollama))

    for marker, following in (("[1/3]", "[2/3]"), ("[2/3]", "[3/3]")):
        written = next(i for i, (kind, text) in enumerate(events) if marker in text)
        next_line = next(i for i, (kind, text) in enumerate(events) if following in text)
        assert ("flush", "") in events[written:next_line]


def test_eval_records_where_the_problem_file_came_from(ollama, tmp_path):
    answer_one_of_three(ollama)

    main(eval_arguments(tmp_path, ollama))

    session = json.loads((tmp_path / "run" / "run.json").read_text())["sessions"][0]
    assert session["problem_file"] == (tmp_path / "problems.jsonl").as_uri()


def test_eval_warns_when_the_mirror_fails_and_the_upstream_serves(ollama, tmp_path, capsys, aws):
    answer_one_of_three(ollama)
    arguments = eval_arguments(tmp_path, ollama)
    definition = Path(arguments[arguments.index("--benchmark") + 1])
    mirror = "s3://jaws-pi-benchmarks-problems/data/sample/abc/problems.jsonl"
    definition.write_text(definition.read_text() + f'mirror = "{mirror}"\n')

    status = main(arguments)

    captured = capsys.readouterr()
    assert status == 0
    assert "warning:" in captured.err and "NoSuchKey" in captured.err
    assert f"problem file from {(tmp_path / 'problems.jsonl').as_uri()}" in captured.out


def finished_run(ollama, tmp_path):
    answer_one_of_three(ollama)
    arguments = eval_arguments(tmp_path, ollama)
    main(arguments)
    definition = arguments[arguments.index("--benchmark") + 1]
    return tmp_path / "run", definition


def test_audit_writes_the_report_and_the_audit_and_passes_a_sound_run(ollama, tmp_path, capsys):
    out, definition = finished_run(ollama, tmp_path)
    capsys.readouterr()

    status = main(
        ["audit", str(out), "--benchmark", definition, "--data-dir", str(tmp_path / "data")]
    )

    printed = capsys.readouterr().out
    assert status == 0
    assert (out / "report.md").exists()
    assert json.loads((out / "audit.json").read_text())["passed"] is True
    assert "passed: verdicts" in printed
    assert "audit passed" in printed


def test_audit_fails_a_run_whose_records_were_altered(ollama, tmp_path, capsys):
    out, definition = finished_run(ollama, tmp_path)
    rows = (out / "results.jsonl").read_text().splitlines()
    altered = json.loads(rows[1])
    altered["verdict"] = "correct"
    rows[1] = json.dumps(altered)
    (out / "results.jsonl").write_text("\n".join(rows) + "\n")
    capsys.readouterr()

    status = main(
        ["audit", str(out), "--benchmark", definition, "--data-dir", str(tmp_path / "data")]
    )

    printed = capsys.readouterr().out
    assert status == 1
    assert "FAILED: verdicts" in printed and "dev/2" in printed


def test_publish_uploads_an_audited_run(ollama, tmp_path, capsys, aws):
    out, definition = finished_run(ollama, tmp_path)
    main(["audit", str(out), "--benchmark", definition, "--data-dir", str(tmp_path / "data")])
    capsys.readouterr()

    status = main(["publish", str(out)])

    printed = capsys.readouterr().out
    assert status == 0
    assert "_manifest.json: uploaded" in printed
    manifest = aws / "jaws-pi-prover-artifacts" / "data" / "runs" / "run" / "_manifest.json"
    assert json.loads(manifest.read_text())["run"] == "run"


def test_publish_refuses_a_run_that_was_not_audited(ollama, tmp_path, capsys, aws):
    out, _ = finished_run(ollama, tmp_path)
    capsys.readouterr()

    status = main(["publish", str(out)])

    assert status == 1
    assert "pi audit" in capsys.readouterr().err
