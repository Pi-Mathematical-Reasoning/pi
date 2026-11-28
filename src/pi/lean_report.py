"""The report of a run on a Lean benchmark."""


def build_lean_report(run: dict, results: list[dict]) -> str:
    """A Markdown report: for now its title, and the notice an interrupted run carries."""
    benchmark = run["benchmark"]
    total = len(benchmark["ids"])
    proved = sum(result["verdict"] == "proved" for result in results)
    if run["complete"]:
        return f"# {benchmark['name']}: {proved} of {total} proved ({proved / total:.1%})\n"
    attempted = len(results)
    return (
        f"# {benchmark['name']}: incomplete, {attempted} of {total} theorems attempted\n"
        "\n"
        f"The run was interrupted. {proved} of the {attempted} theorems attempted so far "
        "are proved, which is not a score for the benchmark.\n"
    )
