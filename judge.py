#!/usr/bin/env python3
"""Ask a model to grade the failures plain code cannot check.

Code checks run first (see checks.py). This command grades a run only when
those checks did not already flag it. The four names it can use are
WRONG_RUNBOOK_CITED, WRONGLY_REFUSED, ANSWERED_WRONGLY, and
RAMBLING_OR_PASTED_TEXT. It can also say PASS.

The model must reply with JSON: a label and a one-sentence reason. If the
reply is not that JSON, the run is marked JUDGE_BAD_JSON and the raw text
is kept. That is not a pass, and the program does not crash.

    python3 judge.py runs.jsonl
    python3 judge.py runs.sample.jsonl --fake
    python3 judge.py runs.jsonl --passes 3

The real call reads XAI_API_KEY from the environment. It never prints the
key. Tests and --fake use FakeJudge and do not call a model.

Results go to judge_results.jsonl. That file is gitignored. Do not commit it.
Hand labels live in labels.md. judge_agreement.py compares the two.
The hand label wins when they disagree.
"""

import argparse
import json
import os
import sys
from pathlib import Path

import httpx

import check_runs
import checks
import golden_check


HERE = Path(__file__).resolve().parent
DEFAULT_LABELS = HERE / "labels.md"
DEFAULT_GOLDEN = HERE / "golden.jsonl"
DEFAULT_OUTPUT = "judge_results.jsonl"

# Chat completions endpoint. The key is not part of this URL.
API_URL = "https://api.x.ai/v1/chat/completions"

# grok-4 is the default. Cian can change it without editing this file:
#   JUDGE_MODEL=some-other-model python judge.py runs.jsonl
DEFAULT_MODEL = "grok-4"

# Stop waiting after this many seconds and raise JudgeTimeout.
DEFAULT_TIMEOUT = 60

# Same cutoff as collect_runs.py. A shorter value is left alone so a scrub
# cannot chew up ordinary words.
MIN_KEY_LENGTH = 12

# The four failures plain code cannot check, plus PASS.
# The judge is not allowed to invent any other label.
JUDGE_LABELS = (
    "WRONG_RUNBOOK_CITED",
    "WRONGLY_REFUSED",
    "ANSWERED_WRONGLY",
    "RAMBLING_OR_PASTED_TEXT",
    "PASS",
)

# Proposing an action is not a wrong answer. The app asks a person to
# click before anything runs. This sentence is part of the rubric, and
# build_prompt repeats it when the run is waiting for that click.
ACTION_APPROVAL_RULE = (
    "For action category questions, the copilot proposing a tool call "
    "such as execute_action is correct behavior because the app shows "
    "a human approval click before anything runs."
)

# One plain definition per label. This is the rubric the model sees.
RUBRIC = {
    "WRONG_RUNBOOK_CITED": (
        "The answer cites a section that is not about this question."
    ),
    "WRONGLY_REFUSED": (
        "The runbooks do cover this, but the copilot said it does not know."
    ),
    "ANSWERED_WRONGLY": (
        "The copilot gave steps that the cited runbook does not say. "
        + ACTION_APPROVAL_RULE
    ),
    "RAMBLING_OR_PASTED_TEXT": (
        "The answer is long, off-topic, or pasted runbook text instead of a short reply."
    ),
    "PASS": (
        "None of those four problems. The reply did what the expected behavior asked for."
    ),
}

# A reply we could not read. This is a result, not a crash, and it is not a pass.
BAD_JSON = "JUDGE_BAD_JSON"

# What --fake returns. It is not a grade.
FAKE_REPLY = '{"label": "PASS", "reason": "Fake judge. This is not a real grade."}'

SYSTEM_MESSAGE = (
    "You grade one copilot answer. "
    "Reply with strict JSON only. Do not add any other words."
)


class JudgeError(Exception):
    """A named failure in this file. The first word of the message is the name."""

    def __init__(self, name, message):
        self.name = name
        super().__init__(f"{name}: {message}")


class MissingKey(Exception):
    """XAI_API_KEY is not set. The message never includes a key."""

    def __init__(self, message):
        super().__init__(f"MissingKey: {message}")


class JudgeTimeout(Exception):
    """The judge call took too long. The message never includes a key."""

    def __init__(self, message):
        super().__init__(f"JudgeTimeout: {message}")


class JudgeHttpError(Exception):
    """The judge call failed on the network. The message never includes a key."""

    def __init__(self, message):
        super().__init__(f"JudgeHttpError: {message}")


def hide_secret(text, key):
    """Replace the API key with a placeholder. Never leave the key in text."""
    if not isinstance(text, str):
        text = "" if text is None else str(text)
    if key and len(key) >= MIN_KEY_LENGTH:
        text = text.replace(key, "[key hidden]")
    return text


def scrub_output(text):
    """Remove the API key from text we are about to print or save.

    The judge should never have put the key there. This is a backstop.
    """
    key = os.environ.get("XAI_API_KEY", "").strip()
    return hide_secret(text, key)


# ---- Hand labels ------------------------------------------------------------

def read_hand_labels(path):
    """Read the table in labels.md.

    Returns run number -> {"label": ..., "reason": ...}.
    Run number is the number in that table, which matches questions.txt.
    The judge does not show these labels to the model. They are for the
    report and for judge_agreement.py. The hand label is the truth.
    """
    path = Path(path)
    if not path.is_file():
        raise JudgeError("BAD_LABELS", f"no labels file at {path}.")
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as err:
        raise JudgeError("BAD_LABELS", f"{path} is not UTF-8.") from err
    labels = {}
    for line_number, line in enumerate(text.splitlines(), start=1):
        if not line.startswith("|"):
            continue
        parts = [part.strip() for part in line.strip().strip("|").split("|")]
        if not parts or not parts[0].isdigit():
            continue
        if len(parts) < 5:
            raise JudgeError(
                "BAD_LABELS",
                f"line {line_number} in {path} needs a run, a label, and a reason.",
            )
        run_number = int(parts[0])
        if run_number in labels:
            raise JudgeError("BAD_LABELS", f"run {run_number} is listed twice in {path}.")
        label = parts[3].strip()
        if not label:
            raise JudgeError("BAD_LABELS", f"run {run_number} in {path} has an empty label.")
        labels[run_number] = {"label": label, "reason": parts[4].strip()}
    if not labels:
        raise JudgeError("BAD_LABELS", f"{path} has no run rows.")
    return labels


# ---- Prompt -----------------------------------------------------------------

def rubric_text():
    """One line per failure type, plus PASS."""
    return "\n".join(f"{name}: {RUBRIC[name]}" for name in JUDGE_LABELS)


def format_sources(sources):
    """A short list of the cited sections. Empty sources stay visible."""
    if not sources:
        return "(none)"
    parts = []
    for item in sources:
        if isinstance(item, dict):
            source = item.get("source") or "?"
            section = item.get("section") or "?"
            parts.append(f"{source} — {section}")
        else:
            parts.append(str(item))
    return "; ".join(parts)


def action_waiting_for_approval(record):
    """True when the copilot proposed an action and nothing has run yet.

    ACTION_REQUESTED means it is waiting for a person. A reply that names
    execute_action and was not already run means the same thing. The app
    shows a click before anything runs.
    """
    if record.get("failure") == "ACTION_WAS_RUN":
        return False
    answer = record.get("answer") or ""
    if "An action returned status" in answer:
        return False
    if record.get("stop_reason") == "ACTION_REQUESTED":
        return True
    return "execute_action" in answer


def build_prompt(record, golden_row):
    """The short prompt for one run.

    It has the question, the golden expected behavior, the answer, the
    cited sources, the stop reason, and the rubric. The hand label is not
    included. The model should not see the answer key.

    When the run shows a proposed action waiting for approval, the prompt
    also repeats the action rule so the judge does not call that
    ANSWERED_WRONGLY.
    """
    expected = golden_row.get("expected") or ""
    plain = golden_check.PLAIN_BEHAVIOR.get(expected, expected)
    why = golden_row.get("why") or ""
    stop = record["stop_reason"] if record["stop_reason"] else "(none)"
    names = ", ".join(JUDGE_LABELS)
    context = ""
    if action_waiting_for_approval(record):
        context = f"Context: {ACTION_APPROVAL_RULE}\n"
    return (
        "Grade this one copilot run.\n"
        "Reply with strict JSON only, in this shape: "
        '{"label": "PASS", "reason": "One sentence."}\n'
        f"The label must be exactly one of: {names}.\n"
        "\n"
        "Rubric:\n"
        f"{rubric_text()}\n"
        "\n"
        f"Question: {record['question']}\n"
        f"Expected behavior: {expected} — {plain}.\n"
        f"Why: {why}\n"
        f"Stop reason: {stop}\n"
        f"{context}"
        f"Cited sources: {format_sources(record['sources'])}\n"
        "Answer:\n"
        f"{record['answer']}\n"
    )


# ---- Parsing ----------------------------------------------------------------

def try_load(text):
    """json.loads, or None when the text is not JSON."""
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def strip_fence(text):
    """Drop a markdown code fence if the model wrapped the JSON in one."""
    cleaned = text.strip()
    if not cleaned.startswith("```"):
        return cleaned
    lines = cleaned.splitlines()
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip().startswith("```"):
        lines = lines[:-1]
    return "\n".join(lines).strip()


def brace_slice(text):
    """The text from the first { to the last }, or None."""
    if not isinstance(text, str):
        return None
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end <= start:
        return None
    return text[start:end + 1]


def load_object(text):
    """A JSON object from the model's text, or None if we cannot find one.

    We try the whole reply first. If the model added a fence or a sentence
    around the JSON, we peel that off. Anything we still cannot read is None.
    """
    if not isinstance(text, str):
        return None
    stripped = text.strip()
    peeled = strip_fence(stripped)
    for candidate in (peeled, brace_slice(peeled), brace_slice(stripped)):
        if not candidate:
            continue
        value = try_load(candidate)
        if isinstance(value, dict):
            return value
    return None


def bad_verdict(raw):
    """JUDGE_BAD_JSON. The raw reply is kept. This is not a pass."""
    return {
        "label": BAD_JSON,
        "reason": "The judge did not return JSON with a label and a reason.",
        "raw": raw if isinstance(raw, str) else "",
    }


def parse_verdict(text):
    """Turn the model's text into a label and a reason.

    A good reply has label (one of the four types, or PASS) and reason
    (a sentence). Anything else becomes JUDGE_BAD_JSON. This never raises.
    """
    raw = text if isinstance(text, str) else ""
    data = load_object(raw)
    if not isinstance(data, dict):
        return bad_verdict(raw)
    label = data.get("label")
    reason = data.get("reason")
    if not isinstance(label, str) or label not in JUDGE_LABELS:
        return bad_verdict(raw)
    if not isinstance(reason, str) or not reason.strip():
        return bad_verdict(raw)
    return {"label": label, "reason": reason.strip(), "raw": None}


# ---- Clients ----------------------------------------------------------------
# Any judge client needs one method: complete(prompt) -> text.
# XaiJudge calls the model. FakeJudge returns canned text for tests and --fake.

def request_body(prompt, model):
    """The JSON body for one chat completion. Temperature is 0.

    The API key is not in this body. It is sent only as a header.
    """
    return {
        "model": model,
        "temperature": 0,
        "messages": [
            {"role": "system", "content": SYSTEM_MESSAGE},
            {"role": "user", "content": prompt},
        ],
    }


def message_text(response, key):
    """The assistant text from a 200 response.

    If the body is not the shape we expect, return the scrubbed body so
    the parser can mark JUDGE_BAD_JSON and keep the raw text.
    """
    raw_body = hide_secret(getattr(response, "text", "") or "", key)
    try:
        data = response.json()
        content = data["choices"][0]["message"]["content"]
    except (ValueError, KeyError, IndexError, TypeError, AttributeError):
        return raw_body
    if not isinstance(content, str):
        return raw_body
    return hide_secret(content, key)


class XaiJudge:
    """Calls the xAI chat completions API.

    The key is read from XAI_API_KEY when complete() runs. It is not stored
    on this object, not printed, and not written into the result file.
    """

    def __init__(self, timeout=None):
        chosen = os.environ.get("JUDGE_MODEL", "").strip()
        self.model = chosen or DEFAULT_MODEL
        self.timeout = DEFAULT_TIMEOUT if timeout is None else timeout

    def complete(self, prompt):
        key = os.environ.get("XAI_API_KEY", "").strip()
        if not key:
            raise MissingKey(
                "XAI_API_KEY is not set. Set it in this terminal for this command. "
                "Do not put it in a file."
            )
        # The key lives only in this header.
        headers = {"Authorization": "Bearer " + key}
        body = request_body(prompt, self.model)
        try:
            # Do not follow a redirect. The key is on this request.
            response = httpx.post(
                API_URL,
                headers=headers,
                json=body,
                timeout=self.timeout,
                follow_redirects=False,
            )
        except httpx.TimeoutException:
            # Drop the original error. Its text can include request details.
            raise JudgeTimeout(
                f"the judge call timed out after {self.timeout} seconds."
            ) from None
        except httpx.HTTPError as err:
            detail = hide_secret(str(err), key)
            raise JudgeHttpError(f"the judge call failed. {detail}") from None
        if response.status_code != 200:
            snippet = hide_secret(response.text or "", key)
            snippet = " ".join(snippet.split())
            if len(snippet) > 200:
                snippet = snippet[:200] + "..."
            raise JudgeHttpError(
                f"the judge call returned HTTP {response.status_code}. {snippet}"
            )
        return message_text(response, key)


class FakeJudge:
    """A stand-in judge. It does not call a model and does not read a key.

    reply can be:
    - a string, used for every call (this is what --fake does)
    - a list of strings, used in order (the last one repeats if the list runs out)
    - a function that takes the prompt and returns a string
    """

    def __init__(self, reply=None):
        self.reply = FAKE_REPLY if reply is None else reply
        self.prompts = []
        self._index = 0

    def complete(self, prompt):
        self.prompts.append(prompt)
        reply = self.reply
        if callable(reply):
            text = reply(prompt)
        elif isinstance(reply, list):
            if not reply:
                text = ""
            elif self._index >= len(reply):
                text = reply[-1]
            else:
                text = reply[self._index]
            self._index += 1
        else:
            text = reply
        if not isinstance(text, str):
            text = "" if text is None else str(text)
        return text


# ---- Grading ----------------------------------------------------------------

def flag_names(record):
    """The code-check names that fired on this run, in check order."""
    names = []
    for message in checks.check_run(record):
        if not isinstance(message, str) or ": " not in message:
            raise JudgeError("BAD_CHECK", f"a check returned {message!r}.")
        name = message.split(": ", 1)[0]
        if name not in names:
            names.append(name)
    return names


def hand_label_for(labels_by_id, run_id):
    row = labels_by_id.get(run_id)
    if not isinstance(row, dict):
        return None
    label = row.get("label")
    if not isinstance(label, str) or not label.strip():
        return None
    return label.strip()


def judge_runs(runs, client, golden_by_question, labels_by_id, only_unflagged=True, passes=1):
    """Grade each run. Return one result dict per run, in file order.

    only_unflagged skips a run the code checks already flagged. The client
    is not called for those. passes asks the client that many times. If the
    labels it returns are not all the same, the run is flaky.

    The label saved on the result is the first try. The full list is in
    passes. A bad reply is JUDGE_BAD_JSON and does not raise.
    """
    if passes < 1:
        raise JudgeError("BAD_PASSES", "passes must be 1 or more.")
    results = []
    for line_number, record in enumerate(runs, start=1):
        checks.require_run(record)
        question = record["question"]
        row = golden_by_question.get(question)
        if row is None:
            raise JudgeError(
                "BAD_GOLDEN",
                f"no golden row for this question: {question!r}.",
            )
        run_id = row.get("id")
        flags = flag_names(record)
        hand = hand_label_for(labels_by_id, run_id)
        if only_unflagged and flags:
            shown = ", ".join(flags)
            results.append({
                "line": line_number,
                "id": run_id,
                "question": question,
                "hand_label": hand,
                "skipped": True,
                "code_flags": flags,
                "label": None,
                "reason": f"Skipped because code checks already flagged this run: {shown}.",
                "raw": None,
                "flaky": False,
                "passes": [],
            })
            continue
        prompt = build_prompt(record, row)
        taken = []
        for _ in range(passes):
            # parse_verdict never raises. A network error still does.
            taken.append(parse_verdict(client.complete(prompt)))
        labels = [item["label"] for item in taken]
        first = taken[0]
        results.append({
            "line": line_number,
            "id": run_id,
            "question": question,
            "hand_label": hand,
            "skipped": False,
            "code_flags": flags,
            "label": first["label"],
            "reason": first["reason"],
            "raw": first["raw"],
            "flaky": len(set(labels)) > 1,
            "passes": taken,
        })
    return results


def format_report(results, passes=1):
    """A table of hand label, judge label, and reason.

    The run number is the one in labels.md. On a full pass of questions.txt
    that is also the line number. On a shorter file, the jsonl line has
    both: id is the labels.md number, line is the line in the runs file.
    """
    lines = [f"{'run':<6} {'hand':<24} {'judge':<24} reason"]
    for result in results:
        number = result["id"] if isinstance(result["id"], int) else result["line"]
        hand = result["hand_label"] or "-"
        shown = "skipped" if result["skipped"] else (result["label"] or "-")
        reason = " ".join((result["reason"] or "").split())
        lines.append(f"{number:<6} {hand:<24} {shown:<24} {reason}")
    if passes > 1:
        lines.append("")
        flaky = [item for item in results if item["flaky"]]
        if not flaky:
            lines.append(f"The judge agreed with itself on every run ({passes} passes).")
        else:
            lines.append("The judge disagreed with itself on:")
            for item in flaky:
                number = item["id"] if isinstance(item["id"], int) else item["line"]
                names = ", ".join(one["label"] for one in item["passes"])
                lines.append(f"run {number}: {names}")
    return "\n".join(lines)


def write_results(path, results):
    """Write one JSON object per line. Replace the file if it is already there."""
    blob = "".join(json.dumps(item, ensure_ascii=False) + "\n" for item in results)
    Path(path).write_text(scrub_output(blob), encoding="utf-8")


# ---- Command line -----------------------------------------------------------

def at_least_one(text):
    try:
        value = int(text)
    except ValueError:
        raise argparse.ArgumentTypeError("passes must be a whole number.")
    if value < 1:
        raise argparse.ArgumentTypeError("passes must be 1 or more.")
    return value


def parse_args(argv):
    parser = argparse.ArgumentParser(
        description=(
            "Grade runs the code checks did not flag. "
            "Use --fake to skip the model. The API key is read from XAI_API_KEY."
        ),
    )
    parser.add_argument("path", help="JSONL file of runs, one run per line.")
    parser.add_argument(
        "--only-unflagged",
        action=argparse.BooleanOptionalAction,
        default=True,
        help=(
            "Skip runs the code checks already flagged. This is the default. "
            "Use --no-only-unflagged to grade those runs too."
        ),
    )
    parser.add_argument(
        "--passes",
        type=at_least_one,
        default=1,
        help="Ask the judge this many times. A run whose labels differ is flaky.",
    )
    parser.add_argument(
        "--fake",
        action="store_true",
        help="Use FakeJudge. No model is called and no API key is read.",
    )
    parser.add_argument(
        "--output",
        default=DEFAULT_OUTPUT,
        help=f"Where to write the results. Default: {DEFAULT_OUTPUT}.",
    )
    return parser.parse_args(argv)


def main(argv=None, client=None):
    args = parse_args(sys.argv[1:] if argv is None else argv)
    try:
        runs = check_runs.read_runs(check_runs.locate(args.path))
        golden_rows = golden_check.read_golden(DEFAULT_GOLDEN)
        golden_by_question = golden_check.index_golden(golden_rows)
        labels_by_id = read_hand_labels(DEFAULT_LABELS)
        # A caller (the tests) can pass a client. Otherwise --fake or the real one.
        if client is None:
            client = FakeJudge() if args.fake else XaiJudge()
        results = judge_runs(
            runs,
            client,
            golden_by_question,
            labels_by_id,
            only_unflagged=args.only_unflagged,
            passes=args.passes,
        )
        write_results(args.output, results)
    except (MissingKey, JudgeTimeout, JudgeHttpError, checks.CheckError, JudgeError) as err:
        print(scrub_output(str(err)))
        return 2
    print(scrub_output(format_report(results, passes=args.passes)))
    print(f"\nWrote {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
