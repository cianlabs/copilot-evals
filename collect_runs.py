#!/usr/bin/env python3
"""Collect runs of runbook-copilot so a person can label them later.

Each line in questions.txt is sent through the real agent loop. The result
is appended as one JSON line in runs.jsonl. This file does not score the
answers. It only writes down what happened.

Safety rules, the same ones evals.py in runbook-copilot uses:

- If the agent proposes an action, we always answer "n". Nothing is restarted
  and nothing is deleted.
- Tool-call logging is turned off for the duration of the run (LOG_FILE = None)
  so we do not write an agent.log full of questions.

The default model is the built-in practice model (DemoClient in
runbook-copilot's app.py). It reads the local runbooks and does not call the
network, so it needs no API key.

    python3 -m venv .venv && .venv/bin/pip install -r requirements.txt && .venv/bin/python collect_runs.py

Add --real to use the live model. That reads XAI_API_KEY from the environment.
The key is never printed, never logged, and never written into a run file.
A real pass writes runs.real.jsonl (and traces.real.jsonl with --trace)
so it is not mixed with the practice files.

Before any real call, the command prints the model, the question count,
the passes, and an upper bound on calls, then waits until you type yes.
--yes skips that question. --limit 3 runs only the first 3 questions.

Add --passes 3 to ask every question three times.
Add --fresh to empty the runs file and the trace file before this pass.

Add --trace to also write a trace file next to the runs file, one JSON
line per step. Without --trace, this file does the same work as before.
"""

import argparse
import contextlib
import io
import json
import os
import subprocess
import sys
import time
from pathlib import Path

# trace.py is the step logger in this folder. It is not Python's standard
# library module of the same name. Running this script from this folder
# makes this import pick up the local file.
import trace

# This commit is main of cianlabs/runbook-copilot when this harness was written
# (the week-4 UI and stop-reason work). A fresh clone checks out this commit
# so a later upstream change does not silently change the collected runs.
PINNED_COMMIT = "f4f6cf6216fddc212b187a76e04fc9a51c7b7100"
REPO_URL = "https://github.com/cianlabs/runbook-copilot.git"

HERE = Path(__file__).resolve().parent
QUESTIONS_FILE = HERE / "questions.txt"
# Downloaded agent code lives here. It is gitignored. It is not a copy we commit.
VENDOR_DIR = HERE / ".vendor" / "runbook-copilot"

# The four starter categories. A typo in questions.txt fails with BAD_QUESTIONS
# instead of quietly filing a run under a new name.
KNOWN_CATEGORIES = ("answerable", "not_in_runbooks", "near_miss", "action")

# Hide the key only when it is long enough that replacing it cannot chew up
# ordinary words. Real xAI keys are much longer than this.
MIN_KEY_LENGTH = 12

# One real model call waits this long, then stops. Same idea as the
# 60 second judge timeout in judge.py. The practice model does not use it.
CALL_TIMEOUT = 60

# Published price for grok-build-0.1, in dollars per token.
# Under 200,000 input tokens: $1 per 1M in, $0.20 per 1M cached, $2 per 1M out.
# At 200,000 input tokens or more, the whole request uses the higher price:
# $2 per 1M in, $0.40 per 1M cached, $4 per 1M out.
# https://docs.x.ai/developers/models/grok-build-0.1
# These are the global API prices. If a response has no usage, we do not guess.
GROK_BUILD_MODELS = (
    "grok-build-0.1",
    "grok-code-fast-1",
    "grok-code-fast",
    "grok-code-fast-1-0825",
)
PRICE_LONG_AT = 200_000
PRICES = {
    "short": {"in": 1.00 / 1_000_000, "cached": 0.20 / 1_000_000, "out": 2.00 / 1_000_000},
    "long": {"in": 2.00 / 1_000_000, "cached": 0.40 / 1_000_000, "out": 4.00 / 1_000_000},
}

# Shown when the key is missing. The example is a command shape, not a key.
MISSING_KEY_MESSAGE = (
    "XAI_API_KEY is not set. Set it for this one command only. "
    "Do not put the key in a file. Example:\n"
    "XAI_API_KEY=\"$(op read 'op://Personal/xAI API Key/credential')\" "
    "python collect_runs.py --real --trace --limit 3"
)


class HarnessError(Exception):
    """A named failure in this harness. The first word of the message is the name."""

    def __init__(self, name, message):
        self.name = name
        super().__init__(f"{name}: {message}")


class MissingKey(HarnessError):
    """XAI_API_KEY is not set. Same name as in judge.py. The message has no key."""

    def __init__(self, message):
        super().__init__("MissingKey", message)


class ModelTimeout(Exception):
    """One model call took too long. The message has no key. Same style as JudgeTimeout."""

    def __init__(self, message):
        self.name = "ModelTimeout"
        super().__init__(f"ModelTimeout: {message}")


class ModelHttpError(Exception):
    """One model call failed on the network. The message has no key. Same style as JudgeHttpError."""

    def __init__(self, message):
        self.name = "ModelHttpError"
        super().__init__(f"ModelHttpError: {message}")


# ---- Finding runbook-copilot ------------------------------------------------
# runbook-copilot is a folder of Python files, not an installable package, so
# pip cannot import it. We put that folder on sys.path and import agent.py.
#
# Where we look, first match wins:
#   1. --copilot-path
#   2. the RUNBOOK_COPILOT_PATH environment variable
#   3. .vendor/runbook-copilot (created by cloning the pinned commit)
#   4. ../runbook-copilot (a checkout sitting next to this repo)


def find_checkout(explicit=None):
    """Return a folder that contains agent.py, or None if we cannot see one."""
    candidates = []
    if explicit:
        candidates.append(Path(explicit))
    env_path = os.environ.get("RUNBOOK_COPILOT_PATH", "").strip()
    if env_path:
        candidates.append(Path(env_path))
    candidates.append(VENDOR_DIR)
    candidates.append(HERE.parent / "runbook-copilot")
    for candidate in candidates:
        folder = candidate.expanduser()
        if (folder / "agent.py").is_file() and (folder / "app.py").is_file() and (folder / "runbooks").is_dir():
            return folder.resolve()
    return None


def _git(args, cwd=None):
    """Run one git command. Raise GIT_CLONE_FAILED with the git message on error."""
    env = os.environ.copy()
    # A missing credential should fail the command, not sit forever at a prompt.
    env["GIT_TERMINAL_PROMPT"] = "0"
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=cwd,
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )
    except FileNotFoundError:
        raise HarnessError("GIT_NOT_INSTALLED", "git is not installed, so the harness cannot download runbook-copilot.")
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "git failed").strip()
        raise HarnessError("GIT_CLONE_FAILED", detail)
    return (completed.stdout or "").strip()


def checkout_commit(folder):
    """The commit of a checkout, or 'unknown' if it is not a git repo."""
    try:
        return _git(["rev-parse", "HEAD"], cwd=folder)
    except HarnessError:
        return "unknown"


def ensure_checkout(explicit=None):
    """Find a checkout, or clone the pinned commit into .vendor/runbook-copilot.

    An explicit path or RUNBOOK_COPILOT_PATH that does not exist is an error.
    We do not quietly clone somewhere else in that case.
    """
    found = find_checkout(explicit)
    if found is not None:
        return found
    if explicit or os.environ.get("RUNBOOK_COPILOT_PATH", "").strip():
        where = explicit or os.environ.get("RUNBOOK_COPILOT_PATH", "").strip()
        raise HarnessError(
            "CHECKOUT_MISSING",
            f"no runbook-copilot checkout at {where}. Expected agent.py, app.py, and a runbooks folder.",
        )
    print(f"Cloning {REPO_URL}")
    print(f"Pinned commit: {PINNED_COMMIT}")
    print(f"Into: {VENDOR_DIR}")
    VENDOR_DIR.parent.mkdir(parents=True, exist_ok=True)
    if VENDOR_DIR.exists():
        raise HarnessError(
            "CHECKOUT_BROKEN",
            f"{VENDOR_DIR} exists but has no agent.py. Delete that folder and run this again.",
        )
    _git(["clone", "--depth", "1", REPO_URL, str(VENDOR_DIR)])
    _git(["fetch", "--depth", "1", "origin", PINNED_COMMIT], cwd=VENDOR_DIR)
    _git(["checkout", "--detach", "FETCH_HEAD"], cwd=VENDOR_DIR)
    found = find_checkout(VENDOR_DIR)
    if found is None:
        raise HarnessError("CHECKOUT_BROKEN", f"clone finished but {VENDOR_DIR} has no agent.py.")
    return found


_LOADED_FROM = None


def load_copilot(path=None):
    """Import agent.py and app.py from the checkout. Returns (agent, app, folder)."""
    global _LOADED_FROM
    checkout = find_checkout(path)
    if checkout is None:
        raise HarnessError(
            "CHECKOUT_MISSING",
            "could not find runbook-copilot. Run collect_runs.py once to clone it, "
            "or set RUNBOOK_COPILOT_PATH to a checkout that contains agent.py.",
        )
    if _LOADED_FROM is not None and _LOADED_FROM != checkout:
        raise HarnessError(
            "CHECKOUT_ALREADY_LOADED",
            f"this process already loaded runbook-copilot from {_LOADED_FROM}. "
            f"Start a new process to use {checkout}.",
        )
    checkout_str = str(checkout)
    if checkout_str not in sys.path:
        sys.path.insert(0, checkout_str)
    import agent  # the copilot, not a module in this repo
    import app  # holds DemoClient, the practice model

    _LOADED_FROM = checkout
    return agent, app, checkout


# ---- Questions --------------------------------------------------------------

def read_questions(path):
    """Read 'category | question' lines. Blank lines and # comments are skipped."""
    path = Path(path)
    if not path.is_file():
        raise HarnessError("BAD_QUESTIONS", f"cannot find {path}.")
    questions = []
    for line_number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "|" not in line:
            raise HarnessError("BAD_QUESTIONS", f"line {line_number} in {path} needs the form: category | question")
        category, question = [part.strip() for part in line.split("|", 1)]
        if not category or not question:
            raise HarnessError("BAD_QUESTIONS", f"line {line_number} in {path} has an empty category or question.")
        if category not in KNOWN_CATEGORIES:
            known = ", ".join(KNOWN_CATEGORIES)
            raise HarnessError(
                "BAD_QUESTIONS",
                f"line {line_number} has category {category!r}. Known categories: {known}.",
            )
        questions.append((category, question))
    if not questions:
        raise HarnessError("BAD_QUESTIONS", f"{path} has no questions.")
    return questions


# ---- Secrets ----------------------------------------------------------------

def api_key():
    """The live-model key, or '' when it is unset. Never log this return value."""
    return os.environ.get("XAI_API_KEY", "").strip()


def scrub(value, key=None):
    """Replace the API key with a placeholder anywhere in a string, list, or dict."""
    secret = api_key() if key is None else key
    if not secret or len(secret) < MIN_KEY_LENGTH:
        return value
    if isinstance(value, str):
        return value.replace(secret, "[key hidden]")
    if isinstance(value, list):
        return [scrub(item, secret) for item in value]
    if isinstance(value, dict):
        return {scrub(str(name), secret): scrub(item, secret) for name, item in value.items()}
    return value


# ---- One run ----------------------------------------------------------------

def decline_action(prompt=""):
    """Always refuse. A proposed action must never run from this harness."""
    return "n"


def run_one(agent_mod, client, question):
    """Ask one question. Return the trace fields, plus a failure name if it raised.

    AgentError and any other named error are caught. The caller keeps going.
    Stdout from the agent is thrown away here so a surprise print cannot land
    the API key in the terminal. The JSON line is the record that matters.
    """
    started = time.perf_counter()
    failure = None
    error_text = ""
    result = None
    try:
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            result = agent_mod.run_agent(question, client=client, ask=decline_action)
    except agent_mod.AgentError as err:
        failure = err.name
        error_text = str(err)
    except Exception as err:
        # RetrieveError uses the same .name pattern. Anything else gets a
        # harness name so one surprise does not kill the whole file.
        failure = getattr(err, "name", None) or "UNEXPECTED_ERROR"
        error_text = str(err)
    seconds = round(time.perf_counter() - started, 3)

    trace = agent_mod.last_trace
    stop_reason = None
    answer = ""
    sources = []
    steps = None
    thoughts = []
    if trace is not None:
        stop_reason = trace.stop_reason
        # The trace answer repeats a Sources block at the bottom. That list is
        # already stored in `sources`, so the answer field stays just the reply.
        answer = agent_mod.strip_model_sources(trace.answer or "")
        sources = [dict(item) for item in trace.sources]
        steps = trace.steps
        thoughts = list(trace.thoughts)

    # run_agent returns the word "denied" after the approval gate says no.
    # The trace answer is the proposed action. Add a plain sentence so a
    # reader of the JSON line can see that nothing ran.
    if result == "denied":
        denial = "Action denied. Nothing was run."
        if denial not in answer:
            answer = (answer.rstrip() + "\n\n" + denial).strip()

    # Belt and braces: the gate should have refused before any simulation.
    # If a result object comes back, name it so the line is obvious.
    if result is not None and hasattr(result, "status"):
        failure = failure or "ACTION_WAS_RUN"
        if not answer:
            answer = f"An action returned status {result.status}. This harness should have refused it."

    if failure and not answer:
        answer = error_text

    return {
        "question": question,
        "stop_reason": stop_reason,
        "answer": answer,
        "sources": sources,
        "steps": steps,
        "thoughts": thoughts,
        "seconds": seconds,
        "failure": failure,
    }


def append_record(path, record):
    """Add one JSON object as a single line. The API key is scrubbed first."""
    line = json.dumps(scrub(record), ensure_ascii=False)
    with Path(path).open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")


def existing_line_count(path):
    """How many lines are already in the runs file. A missing file counts as 0.

    The next run number is this count plus one, so it matches that line
    in runs.jsonl.
    """
    path = Path(path)
    if not path.is_file():
        return 0
    text = path.read_text(encoding="utf-8")
    if not text:
        return 0
    return len(text.splitlines())


def _get(obj, *names):
    """The first present field, from a dict or an object. Missing stays None."""
    if obj is None:
        return None
    for name in names:
        if isinstance(obj, dict):
            if name in obj and obj[name] is not None:
                return obj[name]
        else:
            value = getattr(obj, name, None)
            if value is not None:
                return value
    return None


def _whole_number(value):
    """An int from the API, or None. A bool is not a token count."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return None


def _money(value):
    """A dollar amount from the API, or None. We do not turn text into a price."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def parse_usage(usage):
    """Token counts and a cost from one usage object. Missing fields stay None."""
    empty = {"tokens_in": None, "tokens_out": None, "cached": None, "cost": None}
    if usage is None:
        return empty
    cached = _whole_number(_get(usage, "cached_tokens", "cache_read_input_tokens"))
    details = _get(usage, "prompt_tokens_details", "input_tokens_details")
    if cached is None and details is not None:
        cached = _whole_number(_get(details, "cached_tokens", "cache_read_input_tokens"))
    return {
        "tokens_in": _whole_number(_get(usage, "prompt_tokens", "input_tokens")),
        "tokens_out": _whole_number(_get(usage, "completion_tokens", "output_tokens")),
        "cached": cached,
        "cost": _money(_get(usage, "cost", "cost_in_usd")),
    }


def estimate_cost(model, tokens_in, tokens_out, cached):
    """Dollars for grok-build-0.1, or None when we should not guess.

    Both token counts must be present. A missing count is not treated as zero.
    If the response did not report cached tokens, the estimate uses the normal
    input price and does not invent a cache discount.
    """
    if model not in GROK_BUILD_MODELS:
        return None
    if tokens_in is None or tokens_out is None:
        return None
    if cached is None:
        cached = 0
    if cached < 0 or tokens_in < 0 or tokens_out < 0 or cached > tokens_in:
        return None
    fresh = tokens_in - cached
    band = "long" if tokens_in >= PRICE_LONG_AT else "short"
    rates = PRICES[band]
    amount = fresh * rates["in"] + cached * rates["cached"] + tokens_out * rates["out"]
    return round(amount, 8)


def describe_model_call(model_name, response):
    """Name, token counts, and cost for one real response.

    Cost stays empty when the response has no usage. A cost number that
    the response already included is kept. Otherwise we estimate only for
    grok-build-0.1, from the published price above.
    """
    reported = _get(response, "model")
    name = reported if isinstance(reported, str) and reported else (model_name or "")
    parsed = parse_usage(_get(response, "usage"))
    if parsed["cost"] is not None:
        cost = round(parsed["cost"], 8)
    else:
        cost = estimate_cost(name, parsed["tokens_in"], parsed["tokens_out"], parsed["cached"])
    return {
        "model": name,
        "tokens_in": parsed["tokens_in"],
        "tokens_out": parsed["tokens_out"],
        "cost": cost,
    }


def short_detail(err):
    """A short scrubbed error line. The key is replaced before we keep any text."""
    text = scrub("" if err is None else str(err))
    text = " ".join(text.split())
    if len(text) > 200:
        text = text[:200] + "..."
    return text


def is_http_error(err):
    """True for a network or HTTP failure. A timeout is handled separately."""
    name = type(err).__name__
    known = {
        "APIConnectionError",
        "APIStatusError",
        "APIError",
        "RateLimitError",
        "InternalServerError",
        "HTTPError",
        "HTTPStatusError",
        "ConnectError",
        "ReadError",
        "WriteError",
        "NetworkError",
        "RemoteProtocolError",
        "CloseError",
        "ProxyError",
    }
    if name in known or "HTTP" in name or "Connection" in name or "Network" in name:
        return True
    status = getattr(err, "status_code", None)
    return isinstance(status, int) and not isinstance(status, bool)


def classified_model_error(agent_mod, err):
    """Turn one client failure into a named error. The text never keeps the key."""
    if isinstance(err, (ModelTimeout, ModelHttpError, agent_mod.AgentError)):
        return err
    name = type(err).__name__
    if name == "AuthenticationError":
        return agent_mod.AgentError("BAD_KEY", "xAI rejected the key. Check XAI_API_KEY.")
    if "Timeout" in name:
        return ModelTimeout(f"the model call timed out after {CALL_TIMEOUT} seconds.")
    if is_http_error(err):
        detail = short_detail(err)
        if detail:
            return ModelHttpError(f"the model call failed ({name}). {detail}")
        return ModelHttpError(f"the model call failed ({name}).")
    return agent_mod.AgentError("MODEL_ERROR", f"the model call failed ({name}).")


def call_upper_bound(question_count, passes, max_steps):
    """The most model calls this pass can make. Each question stops at max_steps."""
    return question_count * passes * max_steps


def format_real_summary(model, question_count, passes, max_steps):
    """The plain summary printed before a real call."""
    calls = call_upper_bound(question_count, passes, max_steps)
    return (
        "This will call the real model.\n"
        f"Model: {model}\n"
        f"Questions: {question_count}\n"
        f"Passes: {passes}\n"
        f"Upper bound on calls: {calls} "
        f"({question_count} questions times {passes} passes times {max_steps} steps).\n"
        f"Each model call waits at most {CALL_TIMEOUT} seconds.\n"
        "The API key is not printed and is not written into the run files."
    )


def confirm_real_run(model, question_count, passes, max_steps, assume_yes):
    """Print the summary. True only for a yes, or when --yes was set."""
    print(scrub(format_real_summary(model, question_count, passes, max_steps)))
    if assume_yes:
        print("Continuing because --yes was set.")
        return True
    print("Type yes to continue. Anything else stops before any model call.")
    try:
        answer = input("Type yes to continue: ")
    except EOFError:
        print("Stopped. No answer, so no model call was made.")
        return False
    if answer.strip().lower() != "yes":
        print("Stopped. No model call was made.")
        return False
    return True


def trace_file_for(output_path, real):
    """The trace file that belongs with this runs file.

    A real pass uses traces.real.jsonl so it is not mixed with the practice trace.
    """
    name = "traces.real.jsonl" if real else "traces.jsonl"
    return Path(output_path).resolve().parent / name


def report_output_files(runs_path, trace_path, fresh):
    """Warn when the files already have lines. --fresh empties both first."""
    found = []
    for path in (Path(runs_path), Path(trace_path)):
        count = existing_line_count(path)
        if count:
            found.append((path, count))
    if fresh:
        for path, count in found:
            path.write_text("", encoding="utf-8")
            print(f"Emptied {path.name} ({count} lines) because --fresh was set.")
        if not found:
            print("--fresh is set. Those files were already empty.")
        return
    if found:
        for path, count in found:
            word = "line" if count == 1 else "lines"
            print(f"{path.name} already has {count} {word}. This command will add more after them.")
        print("If that was an accident, stop and run again with --fresh to empty both files first.")
        return
    print("This file is not emptied first. Use --fresh if you want a fresh pass.")


def install_real_guard(agent_mod):
    """Use our own model call for a real pass.

    The vendored ask_model turns every failure into MODEL_ERROR, so a timeout
    would lose its name. This wrapper calls the client, waits at most
    CALL_TIMEOUT seconds, and raises ModelTimeout or ModelHttpError.
    The practice model does not install this. Call the returned function
    to put ask_model back.
    """

    def guarded(client, messages, tools=None):
        model_name = getattr(agent_mod, "MODEL", "") or ""
        kwargs = {"model": model_name, "messages": messages, "timeout": CALL_TIMEOUT}
        if tools:
            kwargs["tools"] = tools
        try:
            response = client.chat.completions.create(**kwargs)
        except Exception as err:
            # from None drops the original error. Its text can hold the key.
            named = classified_model_error(agent_mod, err)
            try:
                # No usage on a failed call, so the token counts and the cost stay empty.
                setattr(named, "_harness_call", {
                    "model": model_name,
                    "tokens_in": None,
                    "tokens_out": None,
                    "cost": None,
                })
            except Exception:
                pass
            raise named from None
        try:
            message = response.choices[0].message
        except (AttributeError, IndexError, TypeError):
            raise agent_mod.AgentError("MODEL_ERROR", "the model call returned no message.")
        info = describe_model_call(model_name, response)
        try:
            # The trace wrapper reads this. It is not written on its own.
            setattr(message, "_harness_call", info)
        except Exception:
            pass
        return message

    previous = agent_mod.ask_model
    agent_mod.ask_model = guarded

    def restore():
        agent_mod.ask_model = previous

    return restore


def _elapsed_ms(started):
    """Milliseconds since `started`, from the same kind of clock as the run timer."""
    return max(0, int(round((time.perf_counter() - started) * 1000)))


def watch_for_trace(agent_mod, notes):
    """Remember each model call and each search while one question runs.

    The vendored loop does not time each step. The events it saves only
    mention the top score, not every title. We wrap the functions here,
    in this file, and we do not edit runbook-copilot.

    Each wrapper calls the real function and returns the same value.
    Call the function this returns to put the originals back.
    Only collect() with a tracer installs these wrappers.
    """
    original_search = agent_mod.TOOLS["search_runbooks"]
    original_ask = agent_mod.ask_model

    def watched_search(query):
        started = time.perf_counter()
        failure = None
        results = None
        try:
            results = original_search(query)
            return results
        except Exception as err:
            # Keep the name the agent already uses, such as EMPTY_QUERY.
            failure = getattr(err, "name", None) or "UNEXPECTED_ERROR"
            raise
        finally:
            # A query that is not text is not stored. That avoids dumping
            # some other object into the trace.
            saved_query = query if isinstance(query, str) else ""
            hits = []
            if results:
                hits = [trace.public_hit(item) for item in results]
            notes.append({
                "kind": "tool",
                "name": "search_runbooks",
                "query": saved_query,
                "results": hits,
                "latency_ms": _elapsed_ms(started),
                "failure": failure,
            })

    def watched_ask(client, messages, tools=None):
        started = time.perf_counter()
        message = None
        error = None
        try:
            message = original_ask(client, messages, tools=tools)
            return message
        except Exception as err:
            error = err
            raise
        finally:
            # Only the time, plus token counts when a real call left them.
            # A practice call has no counts, so the note stays the same as
            # before. Do not copy the messages. A failed real call still
            # names the model, and leaves the token counts empty.
            note = {"kind": "model", "latency_ms": _elapsed_ms(started)}
            info = None
            if message is not None:
                info = getattr(message, "_harness_call", None)
            elif error is not None:
                info = getattr(error, "_harness_call", None)
            if isinstance(info, dict):
                for field_name in ("model", "tokens_in", "tokens_out", "cost"):
                    if field_name in info:
                        note[field_name] = info[field_name]
            notes.append(note)

    agent_mod.TOOLS["search_runbooks"] = watched_search
    agent_mod.ask_model = watched_ask

    def restore():
        agent_mod.TOOLS["search_runbooks"] = original_search
        agent_mod.ask_model = original_ask

    return restore


def collect(questions, output_path, client, agent_mod, passes=1, tracer=None, real=False):
    """Run every question `passes` times. Append one JSON line each time.

    Logging to agent.log is off for the whole call, then restored.
    When tracer is set, also append one JSON line per step. Leave tracer
    empty and this function does the same work as before.
    real=True installs the timeout and the named network errors. The
    practice path leaves real at False and does not install that wrapper.
    """
    saved_log = agent_mod.LOG_FILE
    agent_mod.LOG_FILE = None
    # Notes for the current question. Cleared before each question.
    # Only filled when the wrappers are installed, which is when tracer is set.
    notes = []
    restore_guard = None
    restore_watch = None
    if real:
        restore_guard = install_real_guard(agent_mod)
    if tracer is not None:
        restore_watch = watch_for_trace(agent_mod, notes)
    written = 0
    failures = 0
    # The first new line keeps the next number after whatever is already there.
    run_number = existing_line_count(output_path)
    try:
        for pass_number in range(1, passes + 1):
            for index, (category, question) in enumerate(questions, start=1):
                notes.clear()
                fields = run_one(agent_mod, client, question)
                record = {
                    "question": question,
                    "category": category,
                    "stop_reason": fields["stop_reason"],
                    "answer": fields["answer"],
                    "sources": fields["sources"],
                    "steps": fields["steps"],
                    "thoughts": fields["thoughts"],
                    "seconds": fields["seconds"],
                    "failure": fields["failure"],
                    # Which repeat this line is. 1 when --passes is left at the default.
                    "pass_number": pass_number,
                }
                append_record(output_path, record)
                written += 1
                run_number += 1
                if tracer is not None:
                    # The loop's own short diary. It tells us about an action
                    # request, which does not go through the search wrapper.
                    loop_events = []
                    live = getattr(agent_mod, "last_trace", None)
                    if live is not None:
                        loop_events = list(getattr(live, "events", None) or [])
                    tracer.write_run(run_number, record, list(notes), loop_events)
                if record["failure"]:
                    failures += 1
                    status = f"FAILURE {record['failure']}"
                else:
                    status = record["stop_reason"] or "NO_STOP_REASON"
                prefix = f"[{index}/{len(questions)}]"
                if passes > 1:
                    prefix = f"[pass {pass_number} {index}/{len(questions)}]"
                print(scrub(f"{prefix} {category}  {status}  {record['seconds']:.3f}s  {question}"))
    finally:
        agent_mod.LOG_FILE = saved_log
        # Put the trace wrapper back first, then the real-call wrapper.
        if restore_watch is not None:
            restore_watch()
        if restore_guard is not None:
            restore_guard()
    return written, failures


# ---- Command line -----------------------------------------------------------

def parse_args(argv):
    parser = argparse.ArgumentParser(
        description="Run each question through runbook-copilot and append one JSON line per run.",
    )
    parser.add_argument(
        "--real",
        action="store_true",
        help="Use the real model. Reads XAI_API_KEY from the environment and never prints it.",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Skip the yes/no question before a real run. For scripts.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Run only the first N questions. Useful for a short try.",
    )
    parser.add_argument(
        "--fresh",
        action="store_true",
        help="Empty the runs file and the trace file before this pass.",
    )
    parser.add_argument(
        "--passes",
        type=int,
        default=1,
        help="How many times to ask every question. Default: 1.",
    )
    parser.add_argument(
        "--questions",
        type=Path,
        default=QUESTIONS_FILE,
        help="Question file. Default: questions.txt next to this script.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help=(
            "File to append JSON lines to. "
            "Default: runs.jsonl, or runs.real.jsonl when --real is set."
        ),
    )
    parser.add_argument(
        "--trace",
        action="store_true",
        help="Also write traces.jsonl next to the runs file, one JSON line per step.",
    )
    parser.add_argument(
        "--copilot-path",
        type=Path,
        default=None,
        help="Folder with runbook-copilot's agent.py. Overrides RUNBOOK_COPILOT_PATH.",
    )
    return parser.parse_args(argv)


def make_client(agent_mod, app_mod, real):
    """Practice model by default. --real uses agent.make_client, which reads the key."""
    if not real:
        return app_mod.DemoClient()
    if not api_key():
        # Stop before any question so we do not write thirty identical failures.
        raise MissingKey(MISSING_KEY_MESSAGE)
    try:
        return agent_mod.make_client()
    except agent_mod.AgentError as err:
        if err.name == "MISSING_KEY":
            raise MissingKey(MISSING_KEY_MESSAGE)
        # The message does not contain the key.
        detail = str(err).split(": ", 1)[-1]
        raise HarnessError(err.name, detail)


def main(argv=None):
    args = parse_args(sys.argv[1:] if argv is None else argv)
    if args.passes < 1:
        print("BAD_PASSES: --passes must be 1 or more.")
        return 2
    if args.limit is not None and args.limit < 1:
        print("BAD_LIMIT: --limit must be 1 or more.")
        return 2
    # A real pass has its own files unless you pass --output yourself.
    if args.output is None:
        args.output = Path("runs.real.jsonl") if args.real else Path("runs.jsonl")
    try:
        questions = read_questions(args.questions)
        if args.limit is not None:
            questions = questions[:args.limit]
        checkout = ensure_checkout(args.copilot_path)
        agent_mod, app_mod, checkout = load_copilot(checkout)
        if args.real and not api_key():
            raise MissingKey(MISSING_KEY_MESSAGE)
    except HarnessError as err:
        print(scrub(str(err)))
        return 2

    commit = checkout_commit(checkout)
    mode = "real model" if args.real else "practice model (no API key, no model network call)"
    print(f"Using runbook-copilot at {checkout}")
    print(f"Commit: {commit}")
    if commit not in (PINNED_COMMIT, "unknown"):
        print(f"Note: this harness was written against {PINNED_COMMIT}.")
    print(f"Mode: {mode}")
    print(f"Questions: {len(questions)}  Passes: {args.passes}")
    if args.real:
        model_name = getattr(agent_mod, "MODEL", "") or "unknown"
        max_steps = getattr(agent_mod, "MAX_STEPS", None)
        if not isinstance(max_steps, int) or isinstance(max_steps, bool) or max_steps < 1:
            print("BAD_COPILOT: this checkout has no MAX_STEPS, so the call bound cannot be shown.")
            return 2
        # Ask before make_client, so a "no" never starts a model call.
        if not confirm_real_run(model_name, len(questions), args.passes, max_steps, args.yes):
            return 2
    try:
        client = make_client(agent_mod, app_mod, args.real)
    except HarnessError as err:
        print(scrub(str(err)))
        return 2

    trace_path = trace_file_for(args.output, args.real)
    tracer = trace.Tracer(trace_path) if args.trace else None
    print(f"Appending to {args.output.resolve()}")
    if tracer is not None:
        print(f"Writing a trace to {tracer.path}")
        print("The trace lists steps, runbook titles, and scores. It does not store keys.")
    report_output_files(args.output, trace_path, args.fresh)
    print("Proposed actions are declined. Nothing will be run.")
    print()

    written, failures = collect(
        questions,
        args.output,
        client,
        agent_mod,
        passes=args.passes,
        tracer=tracer,
        real=args.real,
    )
    print()
    print(f"Wrote {written} lines to {args.output}. Agent failures recorded: {failures}.")
    # Collecting a failure is the point of this file, so a named AgentError
    # still exits 0. A broken setup exits 2 above.
    return 0


if __name__ == "__main__":
    sys.exit(main())
