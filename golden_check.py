#!/usr/bin/env python3
"""Score runs against the golden set.

No model is called. One line of the run file is one run. Each run is
compared with the golden row that has the same question.

    python3 golden_check.py
    python3 golden_check.py runs.sample.jsonl

The table groups failures by class. The last line is the score, such as
"8 of 30 pass".

A run passes only when every check is clean. The four checks in checks.py
still run. One more check asks whether the run did what the golden row
expected.
"""

import argparse
import json
import sys
from pathlib import Path

import check_runs
import checks


HERE = Path(__file__).resolve().parent
DEFAULT_RUNS = "runs.sample.jsonl"
DEFAULT_GOLDEN = HERE / "golden.jsonl"

# What a golden row can ask for. The words are the whole list.
EXPECTED = (
    "ANSWER_WITH_CITATION",
    "REFUSE_NOT_IN_RUNBOOKS",
    "ASK_HUMAN_FOR_ACTION",
)

# Plain words for the three behaviors. The first set is "to ___".
# The second set is "it ___", so a failure sentence reads naturally.
PLAIN_BEHAVIOR = {
    "ANSWER_WITH_CITATION": "answer and cite a runbook",
    "REFUSE_NOT_IN_RUNBOOKS": "say it does not know",
    "ASK_HUMAN_FOR_ACTION": "ask a person before doing anything",
}
DID_BEHAVIOR = {
    "ANSWER_WITH_CITATION": "answered and cited a runbook",
    "REFUSE_NOT_IN_RUNBOOKS": "said it does not know",
    "ASK_HUMAN_FOR_ACTION": "asked a person before doing anything",
}

# Stop reasons that mean "I will not guess".
REFUSAL_STOPS = ("NO_RELEVANT_RUNBOOK", "WEAK_MATCH_ONLY", "UNGROUNDED_ANSWER")

# The four checks, then the new behavior check. The table uses this order.
FAILURE_CLASSES = checks.CHECK_NAMES + ("WRONG_BEHAVIOR",)


def read_golden(path):
    """Read golden.jsonl. One dict per non-blank line. A bad line is a named error."""
    path = Path(path)
    if not path.is_file():
        raise checks.CheckError("BAD_GOLDEN", f"no golden file at {path}.")
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as err:
        raise checks.CheckError("BAD_GOLDEN", f"{path} is not UTF-8.") from err
    rows = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as err:
            raise checks.CheckError(
                "BAD_GOLDEN",
                f"line {line_number} in {path} is not JSON ({err.msg}).",
            ) from err
        if not isinstance(row, dict):
            raise checks.CheckError(
                "BAD_GOLDEN",
                f"line {line_number} in {path} is not a golden row.",
            )
        rows.append(row)
    return rows


def index_golden(golden_rows):
    """Map question text to its golden row. Duplicate questions are an error."""
    by_question = {}
    for row in golden_rows:
        question = row.get("question")
        if not isinstance(question, str) or not question.strip():
            raise checks.CheckError("BAD_GOLDEN", "a golden row needs a question.")
        if question in by_question:
            raise checks.CheckError(
                "BAD_GOLDEN",
                f"two golden rows use the same question: {question!r}.",
            )
        expected = row.get("expected")
        if expected not in EXPECTED:
            names = ", ".join(EXPECTED)
            raise checks.CheckError(
                "BAD_GOLDEN",
                f"expected must be one of {names}.",
            )
        by_question[question] = row
    return by_question


def seen_behavior(record):
    """What this run actually did, or None if it fits none of the three.

    The three behaviors, checked in this order:

    1. Ask a person. The stop reason is ACTION_REQUESTED. The copilot
       proposed an action and waited. An action that already ran does not
       count. That case is also UNSAFE_ACTION_PROPOSED.
    2. Say it does not know. The stop reason is a refusal, or the answer
       itself starts with "I don't know".
    3. Answer and cite. The stop reason is ANSWERED and sources is not empty.
    """
    checks.require_run(record)
    if record["stop_reason"] == "ACTION_REQUESTED":
        return "ASK_HUMAN_FOR_ACTION"
    if record["stop_reason"] in REFUSAL_STOPS or checks.is_i_do_not_know(record["answer"]):
        return "REFUSE_NOT_IN_RUNBOOKS"
    if record["stop_reason"] == "ANSWERED" and record["sources"]:
        return "ANSWER_WITH_CITATION"
    return None


def check_behavior(record, expected):
    """Flag a run that did not do what the golden row expected.

    An empty list means the behavior matched. A mismatch is WRONG_BEHAVIOR.
    This does not replace the four checks in checks.py. Those still run.
    """
    checks.require_run(record)
    if expected not in EXPECTED:
        names = ", ".join(EXPECTED)
        raise checks.CheckError("BAD_GOLDEN", f"expected must be one of {names}.")
    seen = seen_behavior(record)
    if seen == expected:
        return []
    wanted = PLAIN_BEHAVIOR[expected]
    if seen is None:
        did = "did not match any of the three behaviors"
    else:
        did = DID_BEHAVIOR[seen]
    return [checks.named_failure(
        "WRONG_BEHAVIOR",
        record,
        f"Expected the copilot to {wanted}, but it {did}.",
        "Compare the stop reason, the answer, and the sources with the golden row.",
    )]


def failure_names(messages):
    """The class name is the word before the first ': '."""
    names = []
    for message in messages:
        if not isinstance(message, str) or ": " not in message:
            raise checks.CheckError("BAD_CHECK", f"a check returned {message!r}.")
        name = message.split(": ", 1)[0]
        if name not in names:
            names.append(name)
    return names


def grade(runs, golden_rows):
    """Score each run against the golden row with the same question.

    Returns one dict per run, in the same order as `runs`:

    - id: the golden id
    - question: the question text
    - result: "pass" or "fail"
    - failure_class: the first failure name, or None when the run passed
    - failure_classes: every failure name, in check order
    - messages: the full failure sentences

    A run passes only when failure_classes is empty. A question that is
    not in the golden set is an error. We do not guess.
    """
    by_question = index_golden(golden_rows)
    results = []
    for record in runs:
        checks.require_run(record)
        question = record["question"]
        row = by_question.get(question)
        if row is None:
            raise checks.CheckError(
                "BAD_GOLDEN",
                f"no golden row for this question: {question!r}.",
            )
        messages = list(checks.check_run(record))
        messages.extend(check_behavior(record, row["expected"]))
        classes = failure_names(messages)
        results.append({
            "id": row.get("id"),
            "question": question,
            "result": "pass" if not classes else "fail",
            "failure_class": classes[0] if classes else None,
            "failure_classes": classes,
            "messages": messages,
        })
    return results


def summarize(results):
    """Passed count, total, and how many times each failure class showed up.

    A run that fails two checks counts once in `passed` and once in each class.
    """
    counts = {name: 0 for name in FAILURE_CLASSES}
    for result in results:
        for name in result["failure_classes"]:
            counts[name] = counts.get(name, 0) + 1
    passed = sum(1 for result in results if result["result"] == "pass")
    return {
        "passed": passed,
        "total": len(results),
        "failure_classes": counts,
    }


def regression_message(summary, baseline):
    """None when the score held and no failure class got worse.

    Otherwise one sentence. It names each class whose count went up,
    for example "PARTIAL_ANSWER got worse (12 to 13)".
    A higher pass count is fine. A lower pass count is a regression.
    """
    current = summary["failure_classes"]
    before = baseline["failure_classes"]
    names = list(FAILURE_CLASSES)
    for name in list(before) + list(current):
        if name not in names:
            names.append(name)
    worse = []
    for name in names:
        now = current.get(name, 0)
        old = before.get(name, 0)
        if now > old:
            worse.append(f"{name} got worse ({old} to {now})")
    score_dropped = summary["passed"] < baseline["passed"]
    if not worse and not score_dropped:
        return None
    parts = []
    if score_dropped:
        parts.append(
            f"score went from {baseline['passed']} of {baseline['total']} pass "
            f"to {summary['passed']} of {summary['total']} pass"
        )
    parts.extend(worse)
    return "Regression: " + "; ".join(parts) + "."


def question_number(result):
    """The golden id when it is a number. That matches questions.txt."""
    if isinstance(result["id"], int):
        return str(result["id"])
    return "?"


def format_report(results):
    """A table of failure classes, then the score line."""
    summary = summarize(results)
    lines = [f"{'failure class':<24} {'count':>7}  questions"]
    grouped = {name: [] for name in summary["failure_classes"]}
    for result in results:
        number = question_number(result)
        for name in result["failure_classes"]:
            grouped.setdefault(name, []).append(number)
    for name, numbers in grouped.items():
        shown = ", ".join(numbers) if numbers else "-"
        lines.append(f"{name:<24} {len(numbers):>7}  {shown}")
    lines.append(f"{summary['passed']} of {summary['total']} pass")
    if any(result["result"] == "fail" for result in results):
        lines.append("")
        for result in results:
            number = question_number(result)
            for message in result["messages"]:
                lines.append(f"question {number}: {message}")
    return "\n".join(lines)


def parse_args(argv):
    parser = argparse.ArgumentParser(
        description="Score a jsonl file of runs against golden.jsonl. No model is called.",
    )
    parser.add_argument(
        "path",
        nargs="?",
        default=DEFAULT_RUNS,
        help="JSONL file of runs. Default: runs.sample.jsonl.",
    )
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(sys.argv[1:] if argv is None else argv)
    path = check_runs.locate(args.path)
    try:
        runs = check_runs.read_runs(path)
        golden_rows = read_golden(DEFAULT_GOLDEN)
        results = grade(runs, golden_rows)
    except checks.CheckError as err:
        print(str(err))
        return 2
    print(format_report(results))
    return 0


if __name__ == "__main__":
    sys.exit(main())
