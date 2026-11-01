#!/usr/bin/env python3
"""Print measured real-model run sets, and record a new one.

No model is called. The numbers live in results/history.json.

    python3 results_table.py
    python3 results_table.py --add runs.real.jsonl --label "after the next change" --commit abc1234 --model grok-build-0.1

A steady pass passed every time in that set. A steady failure failed
every time. Flaky means it passed some times and failed others.

A missing file, a file that is not the shape we expect, or a run file
with the wrong number of rows is a named error. The program prints that
name and stops. It does not show a traceback.
"""

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path

import check_runs
import checks
import golden_check


HERE = Path(__file__).resolve().parent
HISTORY_PATH = HERE / "results" / "history.json"

DATE_TEXT = re.compile(r"^\d{4}-\d{2}-\d{2}$")

DEFAULT_NOTE = (
    "Measured real-model run sets for the 30 questions. "
    "regression_check.py reads this file and does not call a model. "
    "Add a later set with results_table.py --add."
)


class ResultsError(Exception):
    """A named failure while reading or recording results.

    The first word of the message is the name.
    """

    def __init__(self, name, message):
        self.name = name
        super().__init__(f"{name}: {message}")


def require_whole_number(value, label):
    """An int that is not a bool. Bool is a subclass of int, so it is rejected."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise ResultsError("BAD_FORMAT", f"{label} must be a whole number.")
    return value


def require_number(value, label):
    """An int or a float. A bool is rejected. None is not a number."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ResultsError("BAD_FORMAT", f"{label} must be a number.")
    return value


def question_rows():
    """Golden rows in question order. The id is the question number."""
    return golden_check.read_golden(golden_check.DEFAULT_GOLDEN)


def question_ids():
    ids = []
    for row in question_rows():
        qid = row.get("id")
        if isinstance(qid, bool) or not isinstance(qid, int):
            raise ResultsError("BAD_FORMAT", "a golden row needs a numeric id.")
        ids.append(qid)
    return ids


def read_json(path):
    """Read one JSON object. A missing file or bad JSON is a named error."""
    path = Path(path)
    if not path.is_file():
        raise ResultsError("MISSING_FILE", f"no file at {path}.")
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as err:
        raise ResultsError("BAD_FORMAT", f"{path} is not UTF-8.") from err
    try:
        data = json.loads(text)
    except json.JSONDecodeError as err:
        raise ResultsError("BAD_FORMAT", f"{path} is not JSON ({err.msg}).") from err
    if not isinstance(data, dict):
        raise ResultsError("BAD_FORMAT", f"{path} must be a JSON object.")
    return data


def parse_classes(raw, total):
    """Every failure class from golden_check, including the zeros."""
    if not isinstance(raw, dict):
        raise ResultsError("BAD_FORMAT", "failure_classes must be an object of class name to count.")
    parsed = {}
    for name in golden_check.FAILURE_CLASSES:
        if name not in raw:
            raise ResultsError("BAD_FORMAT", f"failure_classes is missing {name}.")
        count = require_whole_number(raw[name], name)
        if count < 0:
            raise ResultsError("BAD_FORMAT", f"{name} cannot be negative.")
        if count > total:
            raise ResultsError(
                "BAD_FORMAT",
                f"{name} count {count} is higher than {total} runs.",
            )
        parsed[name] = count
    extra = [name for name in raw if name not in parsed]
    if extra:
        shown = ", ".join(str(name) for name in extra)
        raise ResultsError("BAD_FORMAT", f"unknown failure class: {shown}.")
    return parsed


def parse_question_counts(raw, passes, ids):
    """Question number -> how many passes it passed. Every question is required."""
    if not isinstance(raw, dict):
        raise ResultsError(
            "BAD_FORMAT",
            "passed_by_question must be an object of question number to pass count.",
        )
    parsed = {}
    for key, value in raw.items():
        if isinstance(key, bool) or not isinstance(key, str) or not key.isdigit():
            raise ResultsError(
                "BAD_FORMAT",
                f"passed_by_question key {key!r} must be a question number.",
            )
        qid = int(key)
        count = require_whole_number(value, f"question {qid} pass count")
        if count < 0 or count > passes:
            raise ResultsError(
                "BAD_FORMAT",
                f"question {qid} passed {count} times, and this set has {passes} passes.",
            )
        if qid in parsed:
            raise ResultsError("BAD_FORMAT", f"question {qid} is listed twice.")
        parsed[qid] = count
    if set(parsed) != set(ids):
        raise ResultsError(
            "BAD_FORMAT",
            "passed_by_question must have one count for every question in golden.jsonl.",
        )
    return parsed


def parse_day(value, label):
    if not isinstance(value, str) or DATE_TEXT.fullmatch(value) is None:
        raise ResultsError("BAD_FORMAT", f"{label} must be a day written like 2026-11-01.")
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError as err:
        raise ResultsError(
            "BAD_FORMAT",
            f"{label} must be a real day, written like 2026-11-01.",
        ) from err
    return value


def parse_line(value, label):
    """A required one-line string. Blank and multi-line text are rejected."""
    if not isinstance(value, str) or not value.strip() or "\n" in value or "\r" in value:
        raise ResultsError("BAD_FORMAT", f"{label} must be one line of text.")
    return value.strip()


def parse_set(raw, ids):
    """One measured run set. The returned question counts use int keys."""
    if not isinstance(raw, dict):
        raise ResultsError("BAD_FORMAT", "each run set must be a JSON object.")
    passes = require_whole_number(raw.get("passes"), "passes")
    if passes < 1:
        raise ResultsError("BAD_FORMAT", "passes must be 1 or more.")
    total = require_whole_number(raw.get("total"), "total")
    question_count = len(ids)
    expected = passes * question_count
    if total != expected:
        raise ResultsError(
            "BAD_RUN_COUNT",
            f"total is {total}. {passes} passes of {question_count} questions is {expected} runs.",
        )
    passed = require_whole_number(raw.get("passed"), "passed")
    if passed < 0 or passed > total:
        raise ResultsError("BAD_FORMAT", f"passed must be between 0 and {total}.")
    counts = parse_question_counts(raw.get("passed_by_question"), passes, ids)
    added = sum(counts.values())
    if added != passed:
        raise ResultsError(
            "BAD_FORMAT",
            f"passed_by_question adds up to {added}, but passed is {passed}.",
        )
    cost = raw.get("cost_dollars")
    if cost is not None:
        cost = require_number(cost, "cost_dollars")
        if cost < 0:
            raise ResultsError("BAD_FORMAT", "cost_dollars cannot be negative.")
    tokens = raw.get("tokens")
    if tokens is not None:
        tokens = require_whole_number(tokens, "tokens")
        if tokens < 0:
            raise ResultsError("BAD_FORMAT", "tokens cannot be negative.")
    seconds = require_number(raw.get("seconds"), "seconds")
    if seconds < 0:
        raise ResultsError("BAD_FORMAT", "seconds cannot be negative.")
    note = raw.get("note", "")
    if not isinstance(note, str):
        raise ResultsError("BAD_FORMAT", "note must be text.")
    return {
        "label": parse_line(raw.get("label"), "label"),
        "date": parse_day(raw.get("date"), "date"),
        "commit": parse_line(raw.get("commit"), "commit"),
        "model": parse_line(raw.get("model"), "model"),
        "passes": passes,
        "passed": passed,
        "total": total,
        "failure_classes": parse_classes(raw.get("failure_classes"), total),
        "passed_by_question": counts,
        "cost_dollars": cost,
        "tokens": tokens,
        "seconds": seconds,
        "note": note,
    }


def load_history(path=None):
    """Read history.json. Question counts use int keys after this returns."""
    path = HISTORY_PATH if path is None else Path(path)
    data = read_json(path)
    sets = data.get("sets")
    if not isinstance(sets, list):
        raise ResultsError("BAD_FORMAT", f"{path} must contain a list called sets.")
    ids = question_ids()
    parsed = [parse_set(item, ids) for item in sets]
    labels = [item["label"] for item in parsed]
    if len(labels) != len(set(labels)):
        raise ResultsError("BAD_FORMAT", "two run sets use the same label.")
    note = data.get("note", "")
    if not isinstance(note, str):
        raise ResultsError("BAD_FORMAT", "the history note must be text.")
    return {"note": note, "sets": parsed}


def set_for_json(item):
    """The on-disk shape. Question numbers are strings because JSON object keys are strings."""
    counts = {str(qid): item["passed_by_question"][qid] for qid in sorted(item["passed_by_question"])}
    classes = {name: item["failure_classes"][name] for name in golden_check.FAILURE_CLASSES}
    stored = {
        "label": item["label"],
        "date": item["date"],
        "commit": item["commit"],
        "model": item["model"],
        "passes": item["passes"],
        "passed": item["passed"],
        "total": item["total"],
        "failure_classes": classes,
        "passed_by_question": counts,
        "cost_dollars": item["cost_dollars"],
        "tokens": item["tokens"],
        "seconds": item["seconds"],
    }
    if item.get("note"):
        stored["note"] = item["note"]
    return stored


def save_history(history, path=None):
    path = HISTORY_PATH if path is None else Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "note": history.get("note") or DEFAULT_NOTE,
        "sets": [set_for_json(item) for item in history["sets"]],
    }
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def mark(passed, passes):
    """steady pass, steady failure, or flaky."""
    if passed == passes:
        return "steady pass"
    if passed == 0:
        return "steady failure"
    return "flaky"


def short_commit(commit):
    """The first 7 characters of a long git hash. A short label is left as it is."""
    text = commit.strip()
    if len(text) >= 12 and all(ch in "0123456789abcdef" for ch in text.lower()):
        return text[:7]
    return text


def format_cost(value):
    if value is None:
        return "not recorded"
    text = f"{value:.4f}".rstrip("0").rstrip(".")
    return "$" + text


def format_tokens(value):
    if value is None:
        return "not recorded"
    return str(int(value))


def format_seconds(value):
    if isinstance(value, float) and not value.is_integer():
        return f"{value:.3f}"
    return str(int(value))


def _widths(sets, cells_per_set):
    """How wide each run-set column needs to be."""
    widths = [len(item["label"]) for item in sets]
    for cells in cells_per_set:
        for index, text in enumerate(cells):
            widths[index] = max(widths[index], len(text))
    return widths


def _header(corner, corner_width, sets, widths):
    labels = "  ".join(item["label"].ljust(widths[index]) for index, item in enumerate(sets))
    return f"{corner.ljust(corner_width)}  {labels}".rstrip()


def format_run_sets(sets):
    rows = [
        ("date", lambda item: item["date"]),
        ("commit", lambda item: short_commit(item["commit"])),
        ("model", lambda item: item["model"]),
        ("passes", lambda item: str(item["passes"])),
        ("score", lambda item: f"{item['passed']} of {item['total']}"),
        ("cost", lambda item: format_cost(item["cost_dollars"])),
        ("tokens", lambda item: format_tokens(item["tokens"])),
        ("seconds", lambda item: format_seconds(item["seconds"])),
    ]
    rendered = [(name, [fn(item) for item in sets]) for name, fn in rows]
    widths = _widths(sets, [cells for _name, cells in rendered])
    corner = "run set"
    corner_width = max(len(corner), max(len(name) for name, _cells in rendered))
    lines = ["Run sets", _header(corner, corner_width, sets, widths)]
    for name, cells in rendered:
        body = "  ".join(cells[index].ljust(widths[index]) for index in range(len(sets)))
        lines.append(f"{name.ljust(corner_width)}  {body}".rstrip())
    return lines


def format_failure_classes(sets):
    names = list(golden_check.FAILURE_CLASSES)
    rendered = [[str(item["failure_classes"][name]) for item in sets] for name in names]
    widths = _widths(sets, rendered)
    corner = "failure class"
    corner_width = max(len(corner), max(len(name) for name in names))
    lines = ["Failure classes", _header(corner, corner_width, sets, widths)]
    for name, cells in zip(names, rendered):
        body = "  ".join(cells[index].ljust(widths[index]) for index in range(len(sets)))
        lines.append(f"{name.ljust(corner_width)}  {body}".rstrip())
    return lines


def format_questions(sets):
    rows = question_rows()
    rendered = []
    for row in rows:
        cells = []
        for item in sets:
            passed = item["passed_by_question"][row["id"]]
            cells.append(f"{passed} of {item['passes']} {mark(passed, item['passes'])}")
        rendered.append(cells)
    widths = _widths(sets, rendered)
    q_width = max(len("question"), max(len(row["question"]) for row in rows))
    lines = [
        "Questions",
        "steady pass: passed every time. steady failure: failed every time. "
        "flaky: passed some times and failed others.",
    ]
    labels = "  ".join(item["label"].ljust(widths[index]) for index, item in enumerate(sets))
    lines.append(f"{'#':>2}  {'question'.ljust(q_width)}  {labels}".rstrip())
    for row, cells in zip(rows, rendered):
        body = "  ".join(cells[index].ljust(widths[index]) for index in range(len(sets)))
        lines.append(f"{row['id']:>2}  {row['question'].ljust(q_width)}  {body}".rstrip())
    return lines


def format_history(history):
    """The side-by-side run sets, the failure classes, and one row per question."""
    sets = history["sets"]
    if not sets:
        return "No run sets recorded.\n"
    lines = []
    lines.extend(format_run_sets(sets))
    lines.append("")
    lines.extend(format_failure_classes(sets))
    lines.append("")
    lines.extend(format_questions(sets))
    return "\n".join(lines) + "\n"


def read_run_file(path):
    """Read a jsonl run file. Map the collector's file errors onto our names."""
    path = Path(path)
    try:
        return check_runs.read_runs(path)
    except checks.CheckError as err:
        if err.name == "BAD_FILE" and "no run file" in str(err):
            raise ResultsError("MISSING_FILE", f"no run file at {path}.") from err
        detail = str(err).split(": ", 1)[-1]
        raise ResultsError("BAD_FORMAT", detail) from err


def _whole_or_none(value):
    """A non-negative int, or None when the field was left out. Bool is not a count."""
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def _cost_or_none(value):
    if value is None or isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if value < 0:
        return None
    return float(value)


def usage_totals(runs):
    """Sum cost and tokens. If any run left them out, return None for that total.

    A missing cost is not zero. Adding zero would pretend we measured a number
    the file does not have.
    """
    cost = 0.0
    tokens = 0
    cost_complete = True
    tokens_complete = True
    for record in runs:
        run_cost = _cost_or_none(record.get("cost"))
        tokens_in = _whole_or_none(record.get("tokens_in"))
        tokens_out = _whole_or_none(record.get("tokens_out"))
        if run_cost is None:
            cost_complete = False
        else:
            cost += run_cost
        if tokens_in is None or tokens_out is None:
            tokens_complete = False
        else:
            tokens += tokens_in + tokens_out
    return (round(cost, 4) if cost_complete else None, tokens if tokens_complete else None)


def set_from_runs(runs, label, commit, model, when=None, cost_dollars=None, tokens=None, note=""):
    """Score a full run file with golden_check and build one history set.

    `runs` must be one row per question per pass. Anything else is
    BAD_RUN_COUNT. Scoring uses the same checks as golden_check.py.
    An out-of-scope answer is also WRONG_BEHAVIOR, because the golden
    row said to refuse.
    """
    rows = question_rows()
    if not rows:
        raise ResultsError("BAD_FORMAT", "golden.jsonl has no questions.")
    by_question = {}
    for row in rows:
        by_question[row["question"]] = row["id"]
    by_id = {qid: [] for qid in question_ids()}
    if not runs:
        raise ResultsError(
            "BAD_RUN_COUNT",
            "the run file has no runs. Expected one row for every question, once per pass.",
        )
    for index, record in enumerate(runs, start=1):
        try:
            checks.require_run(record)
        except checks.CheckError as err:
            detail = str(err).split(": ", 1)[-1]
            raise ResultsError("BAD_FORMAT", f"run {index}: {detail}") from err
        qid = by_question.get(record["question"])
        if qid is None:
            raise ResultsError(
                "BAD_FORMAT",
                f"run {index} has a question that is not in golden.jsonl.",
            )
        pass_number = record.get("pass_number")
        if isinstance(pass_number, bool) or not isinstance(pass_number, int) or pass_number < 1:
            raise ResultsError("BAD_FORMAT", f"run {index} needs a pass_number of 1 or more.")
        seconds = record.get("seconds")
        if isinstance(seconds, bool) or not isinstance(seconds, (int, float)) or seconds < 0:
            raise ResultsError("BAD_FORMAT", f"run {index} needs a seconds number that is 0 or more.")
        by_id[qid].append(record)

    passes = len(by_id[rows[0]["id"]])
    mismatched = [
        f"question {qid} appears {len(items)} times"
        for qid, items in by_id.items()
        if len(items) != passes
    ]
    if mismatched:
        shown = ", ".join(mismatched[:3])
        if len(mismatched) > 3:
            shown += f", and {len(mismatched) - 3} more"
        raise ResultsError(
            "BAD_RUN_COUNT",
            f"the run file does not have the same number of passes for every question. {shown}.",
        )
    expected_rows = passes * len(rows)
    if len(runs) != expected_rows:
        raise ResultsError(
            "BAD_RUN_COUNT",
            f"the run file has {len(runs)} runs. "
            f"Expected {expected_rows} runs ({passes} passes of {len(rows)} questions).",
        )
    expected_numbers = list(range(1, passes + 1))
    for qid, items in by_id.items():
        numbers = sorted(item["pass_number"] for item in items)
        if numbers != expected_numbers:
            raise ResultsError(
                "BAD_RUN_COUNT",
                f"question {qid} has pass numbers {numbers}. Expected {expected_numbers}, one run each.",
            )

    results = golden_check.grade(runs, rows)
    summary = golden_check.summarize(results)
    passed_by_question = {qid: 0 for qid in by_id}
    for result in results:
        if result["result"] == "pass":
            passed_by_question[result["id"]] += 1
    classes = {name: summary["failure_classes"].get(name, 0) for name in golden_check.FAILURE_CLASSES}
    summed_cost, summed_tokens = usage_totals(runs)
    if cost_dollars is None:
        cost_dollars = summed_cost
    else:
        cost_dollars = require_number(cost_dollars, "cost")
        if cost_dollars < 0:
            raise ResultsError("BAD_FORMAT", "cost cannot be negative.")
        cost_dollars = round(float(cost_dollars), 4)
    if tokens is None:
        tokens = summed_tokens
    else:
        tokens = require_whole_number(tokens, "tokens")
        if tokens < 0:
            raise ResultsError("BAD_FORMAT", "tokens cannot be negative.")
    total_seconds = round(sum(record["seconds"] for record in runs), 3)
    if total_seconds == int(total_seconds):
        total_seconds = int(total_seconds)
    if when is None:
        when = datetime.now().strftime("%Y-%m-%d")
    return parse_set(
        {
            "label": label,
            "date": when,
            "commit": commit,
            "model": model,
            "passes": passes,
            "passed": summary["passed"],
            "total": summary["total"],
            "failure_classes": classes,
            "passed_by_question": {str(qid): passed_by_question[qid] for qid in passed_by_question},
            "cost_dollars": cost_dollars,
            "tokens": tokens,
            "seconds": total_seconds,
            "note": note,
        },
        question_ids(),
    )


def set_from_run_file(path, label, commit, model, when=None, cost_dollars=None, tokens=None, note=""):
    return set_from_runs(
        read_run_file(path),
        label,
        commit,
        model,
        when=when,
        cost_dollars=cost_dollars,
        tokens=tokens,
        note=note,
    )


def parse_args(argv):
    parser = argparse.ArgumentParser(
        description="Print measured real-model run sets. No model is called.",
    )
    parser.add_argument(
        "--history",
        type=Path,
        default=HISTORY_PATH,
        help="History file. Default: results/history.json.",
    )
    parser.add_argument(
        "--add",
        type=Path,
        default=None,
        help="Record a finished run file, such as runs.real.jsonl, as a new set.",
    )
    parser.add_argument("--label", default=None, help="Short name for the new set. Required with --add.")
    parser.add_argument("--commit", default=None, help="runbook-copilot commit that was measured. Required with --add.")
    parser.add_argument("--model", default=None, help="Model name, such as grok-build-0.1. Required with --add.")
    parser.add_argument("--date", default=None, help="Day the set was measured, written like 2026-11-01. Default: today.")
    parser.add_argument(
        "--cost",
        type=float,
        default=None,
        help="Total cost in dollars. Used when the run file has no cost. The script does not invent one.",
    )
    parser.add_argument(
        "--tokens",
        type=int,
        default=None,
        help="Total tokens. Used when the run file has no token counts.",
    )
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(sys.argv[1:] if argv is None else argv)
    try:
        history = load_history(args.history)
        if args.add is not None:
            if not args.label or not args.commit or not args.model:
                raise ResultsError("BAD_FORMAT", "--add needs --label, --commit, and --model.")
            if any(item["label"] == args.label.strip() for item in history["sets"]):
                raise ResultsError(
                    "BAD_FORMAT",
                    f"a run set is already labeled {args.label.strip()!r}. Pick a new label.",
                )
            new_set = set_from_run_file(
                args.add,
                args.label,
                args.commit,
                args.model,
                when=args.date,
                cost_dollars=args.cost,
                tokens=args.tokens,
            )
            history["sets"].append(new_set)
            save_history(history, args.history)
            print(f"Added {new_set['label']} to {args.history}.")
            print()
        print(format_history(history), end="")
    except ResultsError as err:
        print(str(err))
        return 2
    except checks.CheckError as err:
        print(str(err))
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
