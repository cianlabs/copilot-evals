#!/usr/bin/env python3
"""Fail when the latest recorded real-model set gets worse.

No real model is called and no API key is read. The check uses two
committed files:

- results/history.json, the measured run sets
- results/floor.json, the minimum the latest set must still meet

It also scores the practice model against baseline.json, the same way
tests/test_golden.py does. The practice model stays on this machine.

The check fails when:

- the latest set passes fewer runs than the floor
- out-of-scope answers go over the floor
- a question that passed every time in the previous set fails every
  time in the latest set, unless that question is a known failure
- a failure class that was at 0 in the previous set is now above 0
- the practice model scores worse than baseline.json

A question that fails some passes and passes others is flaky. That is
not a failure of this check by itself. The total still has to meet the
floor.

Question numbers listed in known_failures are allowed to fail every
pass. Question 25 starts there.

    python3 regression_check.py

Exit 0 when the recorded runs and the practice baseline held.
Exit 1 when a regression is named.
Exit 2 when a file is missing or the wrong shape.
"""

import argparse
import contextlib
import io
import sys
import tempfile
from pathlib import Path

import check_runs
import checks
import collect_runs
import golden_check
import results_table


HERE = Path(__file__).resolve().parent
FLOOR_PATH = HERE / "results" / "floor.json"


class RegressionError(Exception):
    """The copilot got worse in a way this check is meant to catch.

    The first word of the message is the name.
    """

    def __init__(self, name, message):
        self.name = name
        super().__init__(f"{name}: {message}")


def load_floor(path=None):
    """Read floor.json. The numbers in that file are the line CI holds."""
    path = FLOOR_PATH if path is None else Path(path)
    data = results_table.read_json(path)
    passed = results_table.require_whole_number(data.get("passed"), "floor passed")
    total = results_table.require_whole_number(data.get("total"), "floor total")
    limit = results_table.require_whole_number(
        data.get("max_answered_out_of_scope"),
        "floor max_answered_out_of_scope",
    )
    if total < 1 or passed < 0 or passed > total:
        raise results_table.ResultsError(
            "BAD_FORMAT",
            "the floor passed count must sit between 0 and total.",
        )
    if limit < 0:
        raise results_table.ResultsError(
            "BAD_FORMAT",
            "max_answered_out_of_scope cannot be negative.",
        )
    known = data.get("known_failures")
    if not isinstance(known, list):
        raise results_table.ResultsError(
            "BAD_FORMAT",
            "known_failures must be a list of question numbers.",
        )
    ids = set(results_table.question_ids())
    numbers = []
    for item in known:
        number = results_table.require_whole_number(item, "a known failure")
        if number not in ids:
            raise results_table.ResultsError(
                "BAD_FORMAT",
                f"known failure {number} is not a question in golden.jsonl.",
            )
        if number in numbers:
            raise results_table.ResultsError("BAD_FORMAT", f"known failure {number} is listed twice.")
        numbers.append(number)
    note = data.get("note", "")
    if not isinstance(note, str):
        raise results_table.ResultsError("BAD_FORMAT", "the floor note must be text.")
    return {
        "passed": passed,
        "total": total,
        "max_answered_out_of_scope": limit,
        "known_failures": numbers,
        "note": note,
    }


def floor_problems(latest, floor):
    """Regressions against the committed floor. Empty when the set still meets it."""
    if latest["total"] != floor["total"]:
        raise results_table.ResultsError(
            "BAD_RUN_COUNT",
            f"the latest run set {latest['label']} has {latest['total']} runs. "
            f"The floor expects {floor['total']}.",
        )
    problems = []
    if latest["passed"] < floor["passed"]:
        problems.append(RegressionError(
            "BELOW_FLOOR",
            f"The latest run set {latest['label']} passed {latest['passed']} of {latest['total']}. "
            f"The floor is {floor['passed']} of {floor['total']}.",
        ))
    out_of_scope = latest["failure_classes"].get("ANSWERED_OUT_OF_SCOPE", 0)
    allowed = floor["max_answered_out_of_scope"]
    if out_of_scope > allowed:
        problems.append(RegressionError(
            "TOO_MANY_OUT_OF_SCOPE",
            f"The latest run set {latest['label']} has {out_of_scope} ANSWERED_OUT_OF_SCOPE. "
            f"The floor allows at most {allowed}.",
        ))
    return problems


def compare_with_previous(latest, previous, known_failures):
    """Regressions against the previous recorded set.

    A steady pass that becomes a steady failure is a regression, unless
    that question is on the known-failure list. A single miss, with the
    other passes still succeeding, is flaky and is not this regression.

    A failure class counts as new when the previous set had 0 and this
    set has more than 0. A class that was already present can go up or
    down without this check firing. The floor covers the score and the
    out-of-scope count.
    """
    problems = []
    known = set(known_failures)
    question_ids = sorted(set(latest["passed_by_question"]) | set(previous["passed_by_question"]))
    started = []
    for qid in question_ids:
        if qid in known:
            continue
        if qid not in latest["passed_by_question"] or qid not in previous["passed_by_question"]:
            raise results_table.ResultsError(
                "BAD_FORMAT",
                f"question {qid} is missing from a run set.",
            )
        before = previous["passed_by_question"][qid]
        after = latest["passed_by_question"][qid]
        was_steady_pass = before == previous["passes"]
        now_steady_failure = after == 0
        if was_steady_pass and now_steady_failure:
            started.append(qid)
    if started:
        if len(started) == 1:
            which = f"Question {started[0]}"
        else:
            which = "Questions " + ", ".join(str(qid) for qid in started)
        problems.append(RegressionError(
            "STEADY_PASS_NOW_FAILS",
            f"{which} passed every time in {previous['label']} "
            f"and failed every time in {latest['label']}.",
        ))

    names = list(golden_check.FAILURE_CLASSES)
    for name in list(previous["failure_classes"]) + list(latest["failure_classes"]):
        if name not in names:
            names.append(name)
    fresh = []
    for name in names:
        old = previous["failure_classes"].get(name, 0)
        now = latest["failure_classes"].get(name, 0)
        if old == 0 and now > 0:
            fresh.append(f"{name} ({now})")
    if fresh:
        shown = ", ".join(fresh)
        problems.append(RegressionError(
            "NEW_FAILURE_CLASS",
            f"The latest run set {latest['label']} has a failure class "
            f"the previous set {previous['label']} did not have: {shown}.",
        ))
    return problems


def find_regressions(history, floor):
    """Named regressions for the latest set. An empty list means it held.

    This does not call a model. It only reads the history and the floor.
    """
    sets = history["sets"]
    if len(sets) < 2:
        raise results_table.ResultsError(
            "BAD_FORMAT",
            "history needs at least two run sets so the latest can be compared with the previous one.",
        )
    latest = sets[-1]
    previous = sets[-2]
    problems = floor_problems(latest, floor)
    problems.extend(compare_with_previous(latest, previous, floor["known_failures"]))
    return problems


def check_practice_baseline():
    """Score the sample file and one practice pass against baseline.json.

    The practice model is DemoClient. This does not read XAI_API_KEY and
    it does not call a model on the internet. The question lines from the
    practice pass are not printed.
    """
    baseline = results_table.read_json(HERE / "baseline.json")
    for key in ("passed", "total", "failure_classes", "sample"):
        if key not in baseline:
            raise results_table.ResultsError("BAD_FORMAT", f"baseline.json is missing {key}.")
    golden = golden_check.read_golden(golden_check.DEFAULT_GOLDEN)
    sample_runs = check_runs.read_runs(check_runs.locate("runs.sample.jsonl"))
    sample_summary = golden_check.summarize(golden_check.grade(sample_runs, golden))
    problems = []
    sample_message = golden_check.regression_message(sample_summary, baseline["sample"])
    if sample_message:
        problems.append(RegressionError("PRACTICE_BASELINE", sample_message))

    try:
        agent_mod, app_mod, _folder = collect_runs.load_copilot()
    except collect_runs.HarnessError as err:
        detail = str(err).split(": ", 1)[-1]
        raise results_table.ResultsError(err.name, detail) from err

    questions = collect_runs.read_questions(collect_runs.QUESTIONS_FILE)
    with tempfile.TemporaryDirectory() as tmp:
        output = Path(tmp) / "runs.jsonl"
        with contextlib.redirect_stdout(io.StringIO()):
            collect_runs.collect(questions, output, app_mod.DemoClient(), agent_mod)
        runs = check_runs.read_runs(output)
    summary = golden_check.summarize(golden_check.grade(runs, golden))
    message = golden_check.regression_message(summary, baseline)
    if message:
        problems.append(RegressionError("PRACTICE_BASELINE", message))
    return {
        "problems": problems,
        "passed": summary["passed"],
        "total": summary["total"],
        "sample_passed": sample_summary["passed"],
        "sample_total": sample_summary["total"],
    }


def success_text(history, floor, practice):
    latest = history["sets"][-1]
    previous = history["sets"][-2]
    out_of_scope = latest["failure_classes"].get("ANSWERED_OUT_OF_SCOPE", 0)
    lines = [
        "Recorded runs held.",
        (
            f"Latest set: {latest['label']}, {latest['passed']} of {latest['total']} pass. "
            f"Floor: {floor['passed']} of {floor['total']}."
        ),
        (
            f"Out-of-scope answers: {out_of_scope}. "
            f"Floor allows at most {floor['max_answered_out_of_scope']}."
        ),
        f"Compared with the previous set: {previous['label']}.",
        (
            f"Practice baseline held: {practice['passed']} of {practice['total']} pass. "
            f"Sample file: {practice['sample_passed']} of {practice['sample_total']} pass."
        ),
    ]
    return "\n".join(lines)


def parse_args(argv):
    parser = argparse.ArgumentParser(
        description="Compare the latest recorded real-model set with the floor. No model key is used.",
    )
    parser.add_argument(
        "--history",
        type=Path,
        default=results_table.HISTORY_PATH,
        help="History file. Default: results/history.json.",
    )
    parser.add_argument(
        "--floor",
        type=Path,
        default=FLOOR_PATH,
        help="Floor file. Default: results/floor.json.",
    )
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(sys.argv[1:] if argv is None else argv)
    try:
        history = results_table.load_history(args.history)
        floor = load_floor(args.floor)
        problems = find_regressions(history, floor)
        practice = check_practice_baseline()
    except results_table.ResultsError as err:
        print(str(err))
        return 2
    except checks.CheckError as err:
        print(str(err))
        return 2
    problems.extend(practice["problems"])
    if problems:
        for problem in problems:
            print(str(problem))
        return 1
    print(success_text(history, floor, practice))
    return 0


if __name__ == "__main__":
    sys.exit(main())
