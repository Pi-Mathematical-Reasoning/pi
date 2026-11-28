"""Compare the reproduction run's replies with the scored run's recorded ones.

Usage: python3 compare-reproduce.py [scored_dir] [reproduce_dir]

The defaults are the git-ignored run directories it was run against; for the
committed copies, pass experiments/2026-11-21-math-500 and
experiments/2026-11-21-math-500/reproduction.

Writes <reproduce_dir>/comparison.json and exits 0 only if every reply matches
exactly (thinking and final content), along with answer, verdict and token count.
"""

import hashlib
import json
import sys
from pathlib import Path

scored = Path(sys.argv[1] if len(sys.argv) > 1 else "runs/2026-11-21-math-500")
repro = Path(sys.argv[2] if len(sys.argv) > 2 else "runs/2026-11-21-math-500-reproduce")

EXPECTED = [
    "test/algebra/305.json",
    "test/counting_and_probability/25149.json",
    "test/geometry/456.json",
    "test/intermediate_algebra/232.json",
    "test/precalculus/675.json",
]


def load(path: Path) -> dict:
    return {r["id"]: r for r in map(json.loads, (path / "results.jsonl").read_text().splitlines())}


def sha(text: str) -> str:
    return hashlib.sha256((text or "").encode()).hexdigest()


def first_difference(a: str, b: str) -> int | None:
    a, b = a or "", b or ""
    for i, (x, y) in enumerate(zip(a, b, strict=False)):
        if x != y:
            return i
    return None if len(a) == len(b) else min(len(a), len(b))


recorded, rerun = load(scored), load(repro)
missing = [i for i in EXPECTED if i not in rerun]
if missing:
    sys.exit(f"the reproduction run has no result for: {', '.join(missing)}")

rows, all_match = [], True
for pid in EXPECTED:
    old, new = recorded[pid], rerun[pid]
    row = {"id": pid}
    for field in ("thinking", "content"):
        a, b = old["response"].get(field), new["response"].get(field)
        row[field] = {
            "match": a == b,
            "recorded_sha256": sha(a),
            "reproduced_sha256": sha(b),
            "first_difference_at_char": first_difference(a, b),
        }
    for field in ("answer", "verdict", "output_tokens"):
        row[field] = {
            "match": old[field] == new[field],
            "recorded": old[field],
            "reproduced": new[field],
        }
    row["match"] = all(
        row[f]["match"] for f in ("thinking", "content", "answer", "verdict", "output_tokens")
    )
    all_match &= row["match"]
    rows.append(row)
    status = "MATCH" if row["match"] else "DIFFERS"
    note = ""
    if not row["match"]:
        diffs = [
            f
            for f in ("thinking", "content", "answer", "verdict", "output_tokens")
            if not row[f]["match"]
        ]
        at = row["thinking"]["first_difference_at_char"]
        note = (
            f"  ({', '.join(diffs)} differ"
            + (f"; thinking diverges at char {at}" if at is not None else "")
            + ")"
        )
    print(f"{status:8} {pid}  {old['output_tokens']} -> {new['output_tokens']} tokens{note}")

(repro / "comparison.json").write_text(
    json.dumps(
        {
            "scored_run": str(scored),
            "reproduction_run": str(repro),
            "all_match": all_match,
            "problems": rows,
        },
        indent=2,
    )
    + "\n"
)
summary = "all 5 replies reproduced exactly" if all_match else "NOT all replies reproduced"
print(f"\n{summary}; written to {repro / 'comparison.json'}")
sys.exit(0 if all_match else 1)
