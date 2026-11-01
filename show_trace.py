#!/usr/bin/env python3
"""Print a trace file as a short story.

    python show_trace.py traces.jsonl 13
    python show_trace.py traces.jsonl --slowest 5
    python show_trace.py traces.jsonl --failures
    python show_trace.py traces.jsonl --summary

Run numbers match runs.jsonl. Run 13 is the 13th line of that file
when both files were written by the same pass.

This file only reads the trace. It does not call a model.
A stop reason of MAX_STEPS_REACHED is the failure class
GAVE_UP_AT_STEP_LIMIT. The failing step is the last answer step.
"""

import argparse
import json
import sys
from pathlib import Path

import checks
import trace


def question_of(events):
    """The question this run was asked, from the first step that has one."""
    for event in events:
        inputs = event.get("inputs") or {}
        if isinstance(inputs, dict) and inputs.get("question"):
            return inputs["question"]
    return ""


def last_answer_event(events):
    """The last answer step, or None when this run has no answer step."""
    last = None
    for event in events:
        if event.get("node") == "answer":
            last = event
    return last


def step_limit_event(events):
    """The step to blame when the run stopped at the step limit.

    The stop reason MAX_STEPS_REACHED means the copilot never reached a
    final answer. Older traces store that stop reason and leave failure
    empty. The class still belongs on the last answer step. If the trace
    has no answer step, the step that carries the stop reason is used.
    """
    hit = None
    for event in events:
        if event.get("stop_reason") == checks.STEP_LIMIT_STOP:
            hit = event
    if hit is None:
        return None
    answer = last_answer_event(events)
    if answer is not None:
        return answer
    return hit


def failing_pairs(events):
    """(failure name, step) for every named failure on this run.

    A run that hit the step limit is GAVE_UP_AT_STEP_LIMIT even when the
    trace left the failure field empty. The pair uses the last answer step.
    """
    pairs = []
    for event in events:
        for name in trace.failure_names(event.get("failure")):
            pairs.append((name, event))
    limit = step_limit_event(events)
    already = any(name == checks.GAVE_UP_AT_STEP_LIMIT for name, _event in pairs)
    if limit is not None and not already:
        pairs.append((checks.GAVE_UP_AT_STEP_LIMIT, limit))
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
    model_line = format_model_line(event)
    if model_line:
        lines.append(model_line)
    lines.append(f"  Time: {event.get('latency_ms', 0)} ms")
    return lines


def format_model_line(event):
    """One line for a real model call. A practice step has no model name.

    Token counts are printed only when the trace stored them. A missing
    count is not shown as zero.
    """
    name = event.get("model")
    if not isinstance(name, str) or not name:
        return None
    ms = event.get("latency_ms")
    if not isinstance(ms, (int, float)) or isinstance(ms, bool):
        ms = 0
    line = f"  Model: {name}, {ms / 1000:.1f} s"
    tokens_in = event.get("tokens_in")
    tokens_out = event.get("tokens_out")
    has_in = isinstance(tokens_in, int) and not isinstance(tokens_in, bool)
    has_out = isinstance(tokens_out, int) and not isinstance(tokens_out, bool)
    if has_in or has_out:
        shown_in = str(tokens_in) if has_in else "not recorded"
        shown_out = str(tokens_out) if has_out else "not recorded"
        line += f", {shown_in} in, {shown_out} out"
    cost = event.get("cost")
    if isinstance(cost, (int, float)) and not isinstance(cost, bool):
        line += f", about ${cost:.6f}"
    return line


def _number(value):
    """A real number, or None. True and False are not counts."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return value


def format_summary(runs):
    """Total time, total tokens, and how many runs fell in each failure class.

    Time is the whole-run time, counted once per run. Tokens are summed
    from the steps that recorded them. A run with no failure counts as none.
    A run with two classes is counted in both. We do not invent a token
    total when no step recorded usage.
    """
    total_ms = 0
    tokens_in = 0
    tokens_out = 0
    saw_tokens = False
    cost = 0.0
    saw_cost = False
    class_counts = {}
    for events in runs:
        if not events:
            continue
        ms = _number(events[-1].get("run_latency_ms"))
        if ms is not None:
            total_ms += ms
        for event in events:
            inn = _number(event.get("tokens_in"))
            out = _number(event.get("tokens_out"))
            if inn is not None:
                tokens_in += inn
                saw_tokens = True
            if out is not None:
                tokens_out += out
                saw_tokens = True
            step_cost = _number(event.get("cost"))
            if step_cost is not None:
                cost += step_cost
                saw_cost = True
        # Same names as --failures, including a step-limit run whose
        # failure field was left empty. A run is counted once per class.
        seen = []
        for name, _event in failing_pairs(events):
            if name not in seen:
                seen.append(name)
        if not seen:
            class_counts["none"] = class_counts.get("none", 0) + 1
        else:
            for name in seen:
                class_counts[name] = class_counts.get(name, 0) + 1
    lines = [
        "Summary",
        f"Total time: {total_ms / 1000:.1f} s ({int(total_ms)} ms)",
    ]
    if saw_tokens:
        total_tokens = int(tokens_in) + int(tokens_out)
        lines.append(
            f"Total tokens: {total_tokens} ({int(tokens_in)} in, {int(tokens_out)} out)"
        )
    else:
        lines.append("Total tokens: not recorded")
    if saw_cost:
        lines.append(f"Total estimated cost: ${cost:.6f}")
    else:
        lines.append("Total estimated cost: not recorded")
    lines.append("Runs by failure class:")
    if not class_counts:
        lines.append("  (no runs)")
    else:
        for name in sorted(class_counts):
            lines.append(f"  {name}  {class_counts[name]}")
    return "\n".join(lines)


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
    parser.add_argument(
        "--summary",
        action="store_true",
        help="Print total time, total tokens, and the count of runs per failure class.",
    )
    args = parser.parse_args(argv)
    if args.slowest is not None and args.slowest < 1:
        print("--slowest needs a number 1 or more.")
        return 2
    if args.run_number is None and args.slowest is None and not args.failures and not args.summary:
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
        showed = True
    if args.summary:
        if showed:
            print()
        print(format_summary(runs))
    return 0


if __name__ == "__main__":
    sys.exit(main())
