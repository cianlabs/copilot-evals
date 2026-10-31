"""Write a local trace of one copilot run.

A trace is a diary of one question. Each step is one JSON line in
traces.jsonl. A short trace id ties the lines of one run together.

This file does not call a model and does not need an API key.
It does not talk to Langfuse or any other service. It only appends
lines to a file on this machine.

The loop in runbook-copilot uses three kinds of step. We use those names:

    plan    the model reads the question and decides what to do
    search  search_runbooks runs, and we keep titles and scores
    answer  the loop stops

A restart command uses an action step instead of a search. This harness
always refuses the action. Nothing is restarted and nothing is deleted.
"""

import json
import os
import secrets
from pathlib import Path

import checks


# Field names that must never be written into the trace file.
# A search result can carry extra keys. We drop these ones.
SECRET_FIELD_NAMES = {
    "api_key",
    "apikey",
    "xai_api_key",
    "token",
    "access_token",
    "secret",
    "password",
    "passwd",
    "authorization",
    "credential",
    "credentials",
    "environ",
    "env",
    "environment",
}


def new_trace_id():
    """Six characters, so the lines of one run can be grouped.

    This is a label, not a password and not an API key.
    """
    return secrets.token_hex(3)


def public_hit(item):
    """The part of a search hit that is safe to store.

    Title and score only. Not the page text, and not any secret field.
    """
    if not isinstance(item, dict):
        return {"title": "", "source": "", "score": None}
    score = item.get("score")
    if isinstance(score, bool) or not isinstance(score, (int, float)):
        score = None
    else:
        score = round(float(score), 4)
    title = item.get("title") or item.get("section") or ""
    source = item.get("source") or ""
    return {"title": title, "source": source, "score": score}


def drop_secret_fields(value):
    """Remove fields that would carry a key or the whole environment."""
    if isinstance(value, dict):
        kept = {}
        for name, item in value.items():
            if str(name).lower() in SECRET_FIELD_NAMES:
                continue
            kept[str(name)] = drop_secret_fields(item)
        return kept
    if isinstance(value, list):
        return [drop_secret_fields(item) for item in value]
    return value


def hide_secrets(value):
    """Replace secret environment values with a placeholder.

    We look at the environment only to recognise a key if one was copied
    into a question or a tool result. The value is not written out.
    """
    # Imported here so this file can load before collect_runs finishes loading.
    import collect_runs

    cleaned = collect_runs.scrub(value)
    for name, raw in os.environ.items():
        upper = name.upper()
        secret_name = any(part in upper for part in ("KEY", "TOKEN", "SECRET", "PASSWORD", "CREDENTIAL"))
        if not secret_name:
            continue
        if raw and len(raw) >= collect_runs.MIN_KEY_LENGTH:
            cleaned = collect_runs.scrub(cleaned, key=raw)
    return cleaned


def failure_names(failure):
    """A failure field may be one name, a list of names, or empty."""
    if not failure:
        return []
    if isinstance(failure, str):
        return [failure]
    if isinstance(failure, list):
        return [name for name in failure if isinstance(name, str) and name]
    return []


def pack_failure(names):
    """Store one name as a string. Store several as a list. Store none as null."""
    if isinstance(names, str):
        names = [names]
    cleaned = []
    for name in failure_names(names):
        if name not in cleaned:
            cleaned.append(name)
    if not cleaned:
        return None
    if len(cleaned) == 1:
        return cleaned[0]
    return cleaned


def check_names(record):
    """Names from checks.py. An empty list means those checks found nothing."""
    names = []
    try:
        found = checks.check_run(record)
    except checks.CheckError as err:
        return [err.name]
    for item in found:
        name = item.split(":", 1)[0].strip()
        if name and name not in names:
            names.append(name)
    return names


def action_text(record, loop_events):
    """The action the model asked for, or '' when this run did not ask."""
    for event in loop_events or []:
        if not isinstance(event, dict):
            continue
        detail = event.get("detail") or ""
        if event.get("label") == "Tool" and str(detail).startswith("execute_action"):
            text = str(detail).split(":", 1)[-1].strip()
            return text or "execute_action"
    if record.get("stop_reason") == "ACTION_REQUESTED":
        answer = record.get("answer") or ""
        first = answer.splitlines()[0].strip() if answer else ""
        if not first or first.startswith("Action denied"):
            return "execute_action"
        return first
    return ""


def events_from_run(record, notes, loop_events=None):
    """Build the step list for one finished question.

    Notes come from the wrappers in collect_runs.py. They say how long the
    model call took and what search returned. loop_events is the short diary
    the vendored loop already keeps. We use it to see an action request,
    because that path does not call the search tool.
    """
    notes = list(notes or [])
    models = [note for note in notes if note.get("kind") == "model"]
    tools = [note for note in notes if note.get("kind") == "tool"]
    question = record.get("question") or ""
    thoughts = record.get("thoughts") or []
    thought = thoughts[0] if thoughts else ""
    action = action_text(record, loop_events)
    agent_failure = record.get("failure")
    events = []

    def add(node, latency_ms, inputs, tool_calls=None, tool_results=None, stop_reason=None, failure=None):
        events.append({
            "step": len(events) + 1,
            "node": node,
            "inputs": inputs,
            "tool_calls": tool_calls or [],
            "tool_results": tool_results or [],
            "stop_reason": stop_reason,
            "failure": pack_failure(failure),
            "latency_ms": max(0, int(latency_ms or 0)),
        })

    # A model call that leads to a tool or an action is the plan.
    # A model call with nothing after it is the answer itself.
    used_models = 0
    if tools or action:
        plan_ms = models[0].get("latency_ms") if models else 0
        used_models = 1 if models else 0
        add("plan", plan_ms, {"question": question, "thought": thought})
    elif agent_failure:
        plan_ms = models[0].get("latency_ms") if models else 0
        used_models = 1 if models else 0
        add(
            "plan",
            plan_ms,
            {"question": question, "thought": thought},
            failure=[agent_failure],
        )

    for tool in tools:
        query = tool.get("query") if isinstance(tool.get("query"), str) else ""
        hits = [public_hit(item) for item in (tool.get("results") or [])]
        add(
            "search",
            tool.get("latency_ms") or 0,
            {"question": question, "query": query},
            tool_calls=[{"name": "search_runbooks", "query": query}],
            tool_results=hits,
            failure=[tool.get("failure")] if tool.get("failure") else None,
        )

    if action:
        add(
            "action",
            0,
            {"question": question, "action": action},
            tool_calls=[{"name": "execute_action", "action": action}],
            tool_results=[{
                "title": "Action denied. Nothing was run.",
                "source": "",
                "score": None,
            }],
        )

    answer_ms = 0
    if len(models) > used_models:
        answer_ms = models[used_models].get("latency_ms") or 0

    already = []
    for event in events:
        already.extend(failure_names(event.get("failure")))
    answer_names = []
    for name in check_names(record):
        if name not in already and name not in answer_names:
            answer_names.append(name)
    # The loop raised, and no earlier step has recorded that name yet.
    if agent_failure and agent_failure not in already and agent_failure not in answer_names:
        answer_names.append(agent_failure)

    add(
        "answer",
        answer_ms,
        {"question": question},
        stop_reason=record.get("stop_reason"),
        failure=answer_names,
    )
    return events


class Tracer:
    """Appends one JSON line per step to a trace file."""

    def __init__(self, path):
        self.path = Path(path)

    def write_run(self, run_number, record, notes, loop_events=None):
        """Append every step of one run. run_number matches the line in runs.jsonl."""
        trace_id = new_trace_id()
        try:
            run_ms = max(0, int(round(float(record.get("seconds") or 0) * 1000)))
        except (TypeError, ValueError):
            run_ms = 0
        events = events_from_run(record, notes, loop_events)
        with self.path.open("a", encoding="utf-8") as handle:
            for event in events:
                line = {
                    "trace_id": trace_id,
                    "run_number": run_number,
                    "step": event["step"],
                    "node": event["node"],
                    "inputs": event["inputs"],
                    "tool_calls": event["tool_calls"],
                    "tool_results": event["tool_results"],
                    "stop_reason": event["stop_reason"],
                    "failure": event["failure"],
                    "latency_ms": event["latency_ms"],
                    "run_latency_ms": run_ms,
                }
                safe = hide_secrets(drop_secret_fields(line))
                handle.write(json.dumps(safe, ensure_ascii=False) + "\n")
