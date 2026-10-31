#!/usr/bin/env python3
"""Score a jsonl file of runs with the plain checks.

No model is called. One line of the file is one run. The table lists each
check, how many runs it flagged, and those run numbers. Run numbers follow
the order of lines in the file, starting at 1.

    python3 check_runs.py
    python3 check_runs.py runs.sample.jsonl
    python3 check_runs.py --strict

Exit 0 when the file was read, even if a check flagged a run.
--strict exits 1 when any check flagged a run.
A broken file exits 2.
"""

import argparse
import json
import sys
from pathlib import Path

import checks


HERE = Path(__file__).resolve().parent
DEFAULT_PATH = "runs.sample.jsonl"


def parse_args(argv):
    parser = argparse.ArgumentParser(
        description="Score a jsonl file of runs with plain checks. No model is called.",
    )
    parser.add_argument(
        "path",
        nargs="?",
        default=DEFAULT_PATH,
        help="JSONL file of runs. Default: runs.sample.jsonl.",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit 1 if any check flags a run. Without this flag the exit code is 0.",
    )
    return parser.parse_args(argv)


def locate(path):
    """Prefer the path as given. If it is missing, look next to this script."""
    candidate = Path(path)
    if candidate.is_file():
        return candidate
    if not candidate.is_absolute():
        beside = HERE / candidate
        if beside.is_file():
            return beside
    return candidate


def read_runs(path):
    """Read one run dict per non-blank line. A bad line is a named error."""
    path = Path(path)
    if not path.is_file():
        raise checks.CheckError("BAD_FILE", f"no run file at {path}.")
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as err:
        raise checks.CheckError("BAD_FILE", f"{path} is not UTF-8.") from err
    runs = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as err:
            raise checks.CheckError(
                "BAD_JSON",
                f"line {line_number} in {path} is not JSON ({err.msg}).",
            ) from err
        if not isinstance(record, dict):
            raise checks.CheckError(
                "BAD_RUN",
                f"line {line_number} in {path} is not a run record.",
            )
        runs.append(record)
    return runs


def score_runs(runs):
    """Return check name -> run numbers, and the failure strings in run order."""
    by_check = {name: [] for name in checks.CHECK_NAMES}
    failures = []
    for number, record in enumerate(runs, start=1):
        for message in checks.check_run(record):
            if not isinstance(message, str) or ": " not in message:
                raise checks.CheckError("BAD_CHECK", f"run {number} returned {message!r}.")
            name = message.split(": ", 1)[0]
            if name not in by_check:
                raise checks.CheckError("BAD_CHECK", f"run {number} returned {message!r}.")
            by_check[name].append(number)
            failures.append((number, message))
    return by_check, failures


def format_table(by_check, run_count):
    """One row per check, then a total of flags and of runs that had any flag."""
    lines = [f"{'check':<24} {'flagged':>7}  runs"]
    total = 0
    flagged_runs = set()
    for name in checks.CHECK_NAMES:
        numbers = by_check[name]
        total += len(numbers)
        flagged_runs.update(numbers)
        shown = ", ".join(str(number) for number in numbers) if numbers else "-"
        lines.append(f"{name:<24} {len(numbers):>7}  {shown}")
    lines.append(f"{'total':<24} {total:>7}  {len(flagged_runs)} of {run_count} runs")
    return "\n".join(lines)


def main(argv=None):
    args = parse_args(sys.argv[1:] if argv is None else argv)
    path = locate(args.path)
    try:
        runs = read_runs(path)
        by_check, failures = score_runs(runs)
    except checks.CheckError as err:
        print(str(err))
        return 2
    print(format_table(by_check, len(runs)))
    if failures:
        print()
        for number, message in failures:
            print(f"run {number}: {message}")
    if args.strict and failures:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
