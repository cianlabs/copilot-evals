#!/usr/bin/env python3
"""Print a trace file as a short story.

    python show_trace.py traces.jsonl 13
    python show_trace.py traces.jsonl --slowest 5
    python show_trace.py traces.jsonl --failures

Run numbers match runs.jsonl. Run 13 is the 13th line of that file
when both files were written by the same pass.

This file only reads the trace. It does not call a model.
"""

import argparse
import json
import sys
from pathlib import Path

import trace


def question_of(events):
    """The question this run was asked, from the first step that has one."""
    for event in events:
        inputs = event.get("inputs") or {}
        if isinstance(inputs, dict) and inputs.get("question"):
            return inputs["question"]
    return ""


def failing_pairs(events):
    """(failure name, step) for every named failure on this run."""
    pairs = []
    for event in events:
        for name in trace.failure_names(event.get("failure")):
            pairs.append((name, event))
    return pairs


def format_hit(hit):
    """One search hit: score, title, and the file it came from."""
    if not isinstance(hit, dict):
        return "    (no hit)"
    score = hit.get("score")
    if isinstance(score, (int, float)) and not isinstance(score, bool):
        score_text = f"{float(score):.3f}"
    else:
        score_text = "n/a"
    title = hit.get("title") or "(no title)"
    source = hit.get("source") or ""
    if source:
        return f"    {score_text}  {title} ({source})"
    return f"    {score_text}  {title}"


def format_event(event):
    """A few lines for one step."""
    lines = [f"Step {event.get('step')} {event.get('node')}"]
    node = event.get("node")
    inputs = event.get("inputs") or {}
    if not isinstance(inputs, dict):
        inputs = {}
    if node == "plan":
        thought = inputs.get("thought") or ""
        if thought:
            lines.append(f"  Thought: {thought}")
        else:
            lines.append("  The model read the question and chose the next step.")
    elif node == "search":
        lines.append(f"  Search for: {inputs.get('query') or ''}")
        results = event.get("tool_results") or []
        count = len(results)
        if count == 0:
            lines.append("  Found no runbooks.")
        elif count == 1:
            lines.append("  Found 1 runbook with a score:")
        else:
            lines.append(f"  Found {count} runbooks with scores:")
        for hit in results:
            lines.append(format_hit(hit))
    elif node == "action":
        lines.append(f"  Asked to run: {inputs.get('action') or ''}")
        lines.append("  Came back: Action denied. Nothing was run.")
    elif node == "answer":
        lines.append(f"  Stop reason: {event.get('stop_reason') or 'none'}")
    lines.append(f"  Time: {event.get('latency_ms', 0)} ms")
    return lines


def format_run(events):
    """The whole story for one run."""
    number = events[0].get("run_number")
    trace_id = events[0].get("trace_id") or ""
    run_ms = events[-1].get("run_latency_ms")
    if run_ms is None:
        run_ms = 0
    stop = None
    for event in events:
        if event.get("stop_reason"):
            stop = event["stop_reason"]
    lines = [
        f"Run {number}",
        f"Trace id: {trace_id}",
        f"Question: {question_of(events)}",
        "",
    ]
    for event in events:
        lines.extend(format_event(event))
        lines.append("")
    lines.append(f"Whole run: {run_ms} ms")
    lines.append(f"Stop reason: {stop or 'none'}")
    pairs = failing_pairs(events)
    if not pairs:
        lines.append("Failure class: none")
    else:
        lines.append("Failure class: " + ", ".join(name for name, _event in pairs))
        for _name, event in pairs:
            lines.append(f"Went wrong at step {event.get('step')} ({event.get('node')})")
    return "\n".join(lines)


def format_failures(runs):
    """Failing runs, grouped by failure class, with the step that went wrong."""
    groups = {}
    for events in runs:
        for name, event in failing_pairs(events):
            groups.setdefault(name, []).append((events, event))
    if not groups:
        return "No failing runs."
    lines = ["Failures by class", ""]
    for name in sorted(groups):
        lines.append(name)
        ordered = sorted(groups[name], key=lambda item: item[0][0].get("run_number") or 0)
        for events, event in ordered:
            number = events[0].get("run_number")
            question = question_of(events)
            step = event.get("step")
            node = event.get("node")
            lines.append(f"  Run {number} went wrong at step {step} ({node}): {question}")
        lines.append("")
    return "\n".join(lines).rstrip()


def format_slowest(runs, limit):
    """The runs that took the longest, whole run time, up to `limit` of them."""
    def sort_key(events):
        ms = events[-1].get("run_latency_ms")
        if not isinstance(ms, (int, float)):
            ms = 0
        number = events[0].get("run_number") or 0
        return (-ms, number)

    chosen = sorted(runs, key=sort_key)[:limit]
    lines = [f"Slowest {limit}"]
    if not chosen:
        lines.append("No runs in this file.")
        return "\n".join(lines)
    for events in chosen:
        number = events[0].get("run_number")
        ms = events[-1].get("run_latency_ms")
        if not isinstance(ms, (int, float)):
            ms = 0
        lines.append(f"Run {number}  {int(ms)} ms  {question_of(events)}")
    return "\n".join(lines)


def load_runs(path):
    """Read the file and group lines that share a trace id.

    Returns the list of runs, or None when the file cannot be used.
    A message is already printed in that case.
    """
    path = Path(path)
    if not path.is_file():
        print(f"Cannot find {path}.")
        return None
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        print(f"BAD_TRACE: {path} is not a text file.")
        return None
    groups = []
    by_id = {}
    for line_number, raw in enumerate(text.splitlines(), start=1):
        if not raw.strip():
            continue
        try:
            event = json.loads(raw)
        except json.JSONDecodeError:
            print(f"BAD_TRACE: line {line_number} is not JSON.")
            return None
        if not isinstance(event, dict) or "trace_id" not in event:
            print(f"BAD_TRACE: line {line_number} needs a trace_id.")
            return None
        trace_id = event["trace_id"]
        if trace_id not in by_id:
            by_id[trace_id] = []
            groups.append(by_id[trace_id])
        by_id[trace_id].append(event)
    return groups


def print_one(runs, number, path):
    """Print the story for one run number. 0 when it was found."""
    matches = [events for events in runs if events and events[0].get("run_number") == number]
    if not matches:
        print(f"No run {number} in {path}.")
        return 1
    if len(matches) > 1:
        print(f"This file has {len(matches)} runs numbered {number}. Showing the last one.")
        print()
    print(format_run(matches[-1]))
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Print a trace file as a short story. Run numbers match runs.jsonl.",
    )
    parser.add_argument("path", help="The traces.jsonl file.")
    parser.add_argument(
        "run_number",
        nargs="?",
        type=int,
        help="Which run to print. Same number as that line in runs.jsonl.",
    )
    parser.add_argument(
        "--slowest",
        type=int,
        help="Print the N slowest runs, using the whole-run time.",
    )
    parser.add_argument(
        "--failures",
        action="store_true",
        help="Group failing runs by failure class and show the step that went wrong.",
    )
    args = parser.parse_args(argv)
    if args.slowest is not None and args.slowest < 1:
        print("--slowest needs a number 1 or more.")
        return 2
    if args.run_number is None and args.slowest is None and not args.failures:
        parser.print_help()
        return 2
    runs = load_runs(args.path)
    if runs is None:
        return 1
    showed = False
    if args.run_number is not None:
        code = print_one(runs, args.run_number, args.path)
        if code != 0:
            return code
        showed = True
    if args.failures:
        if showed:
            print()
        print(format_failures(runs))
        showed = True
    if args.slowest is not None:
        if showed:
            print()
        print(format_slowest(runs, args.slowest))
    return 0


if __name__ == "__main__":
    sys.exit(main())
