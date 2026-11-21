#!/usr/bin/env python3
"""Chooses the development problems and prints them as a list of ids.

The development problems are a frozen sample of MATH training problems, for
tuning limits and debugging the grader without touching MATH-500. The sample
mirrors the mix of levels in MATH-500, so its timings carry over.

    uv run python scripts/select_dev_problems.py

The output is the `ids` list in benchmarks/math-dev.toml. The choice depends
only on the two pinned files and the seed below, so running this again prints
the same list.
"""

import random
from collections import Counter
from pathlib import Path

from pi.benchmarks import load_benchmark, load_problems, read_rows

ROOT = Path(__file__).resolve().parent.parent
SEED = 20261120
# 30 problems in the proportions of MATH-500's levels (43, 90, 105, 128, 134).
PER_LEVEL = {1: 3, 2: 5, 3: 6, 4: 8, 5: 8}


def main() -> None:
    data = ROOT / "data"
    evaluation = load_problems(load_benchmark(ROOT / "benchmarks" / "math-500.toml"), data)
    held_out = {problem.problem.strip() for problem in evaluation}

    source = load_benchmark(ROOT / "benchmarks" / "math-dev.toml")
    rows = read_rows(source, data)
    seen = Counter(row["unique_id"] for row in rows)
    candidates = [
        row
        for row in rows
        if row["unique_id"].startswith("train/")  # MATH's own training split
        and seen[row["unique_id"]] == 1
        and (row["answer"] or "").strip()
        and row["problem"].strip() not in held_out
    ]

    chooser = random.Random(SEED)
    print("ids = [")
    for level, count in PER_LEVEL.items():
        pool = sorted(row["unique_id"] for row in candidates if row["level"] == level)
        for chosen in sorted(chooser.sample(pool, count)):
            print(f'    "{chosen}",')
    print("]")


if __name__ == "__main__":
    main()
