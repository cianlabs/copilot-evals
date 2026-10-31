#!/usr/bin/env python3
"""Ask every question to the old loop and the new graph, then write compare.md.

The old version is run_agent in agent.py. It still walks in a circle.
The new version is run_graph in graph_agent.py. It walks a picture of boxes.
That new file exists only on an unmerged branch of runbook-copilot.

Both versions are asked the same way collect_runs.py asks:

- the practice model (no API key, no call to a model on the internet)
- if the copilot wants to do something, the answer is always no
- logging is turned off, so no agent.log is written

The asking itself is collect_runs.run_one. This file does not copy that.
It only loads the graph, calls that helper twice, and writes the report.

    python3 -m venv .venv && .venv/bin/pip install -r requirements.txt && .venv/bin/python compare_agents.py
"""

import argparse
import importlib.util
import sys
from pathlib import Path

import collect_runs


# The open pull request that adds graph_agent.py. Not merged.
GRAPH_BRANCH = "cursor/graph-agent-loop-86f9"
# The commit on that branch when this comparison was written.
# A later push to the branch does not silently change the report.
GRAPH_COMMIT = "b3358854f835761fc7a74de607b5ba2aeb11e673"

HERE = Path(__file__).resolve().parent
GRAPH_DIR = HERE / ".vendor-graph" / "runbook-copilot"
DEFAULT_OUTPUT = HERE / "compare.md"

# Short meanings for the stop-reason names. The full table is taxonomy.md.
STOP_PLAIN = {
    "ANSWERED": "it wrote an answer from runbook sections it had read",
    "NO_RELEVANT_RUNBOOK": "search found nothing useful, so it said it does not know",
    "WEAK_MATCH_ONLY": "search found only weak matches, so it said it does not know",
    "UNGROUNDED_ANSWER": "it wrote steps before reading a section, so those words were dropped",
    "MAX_STEPS_REACHED": "it used every step it is allowed and then stopped",
    "ACTION_REQUESTED": "it asked to do something, and this script said no",
}

IDENTICAL_SENTENCE = (
    "The two versions behaved identically. "
    "For every question, they stopped for the same reason and cited the same runbook sections."
)
NOT_IDENTICAL_SENTENCE = (
    "The two versions did not behave identically. "
    "The notes under Differences say what changed."
)


class GraphRunner:
    """A thin stand-in so collect_runs.run_one can call the graph.

    run_one expects a module with run_agent, last_trace, AgentError, and
    strip_model_sources. The graph uses different names for the first two.
    This object translates, and leaves the safety rules in collect_runs.
    """

    def __init__(self, agent_mod, graph_mod):
        self._agent = agent_mod
        self._graph = graph_mod

    def run_agent(self, request, client=None, ask=input, defer_approval=False):
        return self._graph.run_graph(
            request,
            client=client,
            ask=ask,
            defer_approval=defer_approval,
        )

    @property
    def last_trace(self):
        return self._graph.last_trace

    @property
    def AgentError(self):
        return self._agent.AgentError

    def strip_model_sources(self, text):
        return self._agent.strip_model_sources(text)


# ---- Finding the graph branch ----------------------------------------------

def is_graph_checkout(folder):
    """True when this folder has the graph, the loop, and the runbooks."""
    folder = Path(folder)
    return (
        (folder / "graph_agent.py").is_file()
        and (folder / "agent.py").is_file()
        and (folder / "app.py").is_file()
        and (folder / "runbooks").is_dir()
    )


def find_graph_checkout(explicit=None):
    """Return a folder that contains graph_agent.py, or None.

    A path you passed in is the only place we look. We do not quietly
    switch to the default folder when that path is wrong.
    """
    if explicit:
        folder = Path(explicit).expanduser()
        if is_graph_checkout(folder):
            return folder.resolve()
        return None
    if is_graph_checkout(GRAPH_DIR):
        return GRAPH_DIR.resolve()
    return None


def ensure_graph_checkout(explicit=None):
    """Find the graph branch, or clone the pinned commit into .vendor-graph.

    A path you passed in that does not exist is an error. We do not quietly
    download a different folder in that case.
    """
    found = find_graph_checkout(explicit)
    if found is not None:
        return found
    if explicit:
        raise collect_runs.HarnessError(
            "CHECKOUT_MISSING",
            f"no graph checkout at {explicit}. "
            "Expected graph_agent.py, agent.py, app.py, and a runbooks folder.",
        )
    print(f"Cloning {collect_runs.REPO_URL}")
    print(f"Branch: {GRAPH_BRANCH}")
    print(f"Pinned commit: {GRAPH_COMMIT}")
    print(f"Into: {GRAPH_DIR}")
    GRAPH_DIR.parent.mkdir(parents=True, exist_ok=True)
    if GRAPH_DIR.exists():
        raise collect_runs.HarnessError(
            "CHECKOUT_BROKEN",
            f"{GRAPH_DIR} exists but has no graph_agent.py. Delete that folder and run this again.",
        )
    # The git helper already lives in collect_runs. Call it instead of copying it.
    collect_runs._git([
        "clone", "--depth", "1", "--branch", GRAPH_BRANCH,
        collect_runs.REPO_URL, str(GRAPH_DIR),
    ])
    collect_runs._git(["fetch", "--depth", "1", "origin", GRAPH_COMMIT], cwd=GRAPH_DIR)
    collect_runs._git(["checkout", "--detach", "FETCH_HEAD"], cwd=GRAPH_DIR)
    found = find_graph_checkout(GRAPH_DIR)
    if found is None:
        raise collect_runs.HarnessError(
            "CHECKOUT_BROKEN",
            f"clone finished but {GRAPH_DIR} has no graph_agent.py.",
        )
    return found


def load_graph_module(checkout):
    """Load graph_agent.py from this folder, not from some other copy."""
    path = Path(checkout) / "graph_agent.py"
    if not path.is_file():
        raise collect_runs.HarnessError(
            "GRAPH_MISSING",
            f"{checkout} has no graph_agent.py. Expected branch {GRAPH_BRANCH}.",
        )
    existing = sys.modules.get("graph_agent")
    if existing is not None:
        existing_file = getattr(existing, "__file__", None)
        if existing_file and Path(existing_file).resolve() == path.resolve():
            return existing
        raise collect_runs.HarnessError(
            "CHECKOUT_ALREADY_LOADED",
            "this process already loaded a different graph_agent.py. Start a new process.",
        )
    spec = importlib.util.spec_from_file_location("graph_agent", path)
    if spec is None or spec.loader is None:
        raise collect_runs.HarnessError("GRAPH_MISSING", f"could not load {path}.")
    module = importlib.util.module_from_spec(spec)
    sys.modules["graph_agent"] = module
    spec.loader.exec_module(module)
    return module


def load_both(folder):
    """Import the loop and the graph from the same download.

    The branch keeps agent.py and adds graph_agent.py beside it. Loading
    both from that one folder means they share the same runbooks and tools.
    """
    agent_mod, app_mod, checkout = collect_runs.load_copilot(folder)
    graph_mod = load_graph_module(checkout)
    if not hasattr(graph_mod, "run_graph"):
        raise collect_runs.HarnessError(
            "GRAPH_MISSING",
            f"{checkout / 'graph_agent.py'} has no run_graph function.",
        )
    return agent_mod, graph_mod, app_mod, checkout


def practice_clients(agent_mod, app_mod):
    """Two practice models. real=False means no API key and no live client."""
    return (
        collect_runs.make_client(agent_mod, app_mod, False),
        collect_runs.make_client(agent_mod, app_mod, False),
    )


# ---- One question, both versions -------------------------------------------

def node_path_of(graph_mod):
    """The boxes the graph walked, or an empty list if the run failed first."""
    trace = graph_mod.last_trace
    if trace is None:
        return []
    path = getattr(trace, "node_path", None) or []
    return [str(name) for name in path]


def ask_both(agent_mod, graph_mod, questions, loop_client, graph_client, echo=None):
    """Ask each question once to the loop and once to the graph.

    Logging is off for the whole call, then put back. Proposed actions are
    declined inside collect_runs.run_one.
    """
    saved_log = agent_mod.LOG_FILE
    agent_mod.LOG_FILE = None
    runner = GraphRunner(agent_mod, graph_mod)
    rows = []
    total = len(questions)
    try:
        for number, (category, question) in enumerate(questions, start=1):
            loop_fields = collect_runs.run_one(agent_mod, loop_client, question)
            graph_fields = collect_runs.run_one(runner, graph_client, question)
            row = make_row(
                number,
                category,
                question,
                loop_fields,
                graph_fields,
                node_path_of(graph_mod),
            )
            rows.append(row)
            if echo is not None:
                line = (
                    f"[{number}/{total}] {category}  "
                    f"loop {show_stop(row['loop_stop'])}  "
                    f"graph {show_stop(row['graph_stop'])}  "
                    f"{row['verdict']}"
                )
                echo(collect_runs.scrub(line))
    finally:
        agent_mod.LOG_FILE = saved_log
    return rows


# ---- Comparing the two results ---------------------------------------------

def source_pairs(sources):
    """File name and section title, in the order they were cited."""
    pairs = []
    for item in sources or []:
        pairs.append((str(item.get("source") or ""), str(item.get("section") or "")))
    return pairs


def sources_match(left, right):
    """True when both answers cite the same sections in the same order."""
    return source_pairs(left) == source_pairs(right)


def make_row(number, category, question, loop_fields, graph_fields, node_path):
    """One question, side by side. verdict is only about the stop reason."""
    loop_stop = loop_fields.get("stop_reason")
    graph_stop = graph_fields.get("stop_reason")
    return {
        "number": number,
        "category": category,
        "question": question,
        "loop_stop": loop_stop,
        "graph_stop": graph_stop,
        "verdict": "same" if loop_stop == graph_stop else "different",
        "node_path": list(node_path),
        "sources_matched": sources_match(loop_fields.get("sources"), graph_fields.get("sources")),
        "loop_sources": list(loop_fields.get("sources") or []),
        "graph_sources": list(graph_fields.get("sources") or []),
        "loop_failure": loop_fields.get("failure"),
        "graph_failure": graph_fields.get("failure"),
    }


def summary_counts(rows):
    """How many stop reasons matched, and how many source lists matched."""
    total = len(rows)
    same = sum(1 for row in rows if row["verdict"] == "same")
    sources_same = sum(1 for row in rows if row["sources_matched"])
    return {
        "total": total,
        "same": same,
        "different": total - same,
        "sources_same": sources_same,
        "sources_different": total - sources_same,
    }


def show_stop(stop):
    if stop:
        return str(stop)
    return "(none)"


def plain_stop(stop):
    """The code name plus a short meaning, for the notes at the bottom."""
    if not stop:
        return "it did not record a stop reason"
    meaning = STOP_PLAIN.get(stop)
    if meaning:
        return f"{stop}, which means {meaning}"
    return str(stop)


def show_path(node_path):
    if not node_path:
        return "(none)"
    return " → ".join(str(name) for name in node_path)


def show_sources(sources):
    pairs = source_pairs(sources)
    if not pairs:
        return "no sections"
    parts = []
    for source, section in pairs:
        title = section or "(no section name)"
        filename = source or "(no file name)"
        parts.append(f"{title} ({filename})")
    return "; ".join(parts)


def explain_row(row):
    """Plain sentences for one question, only when something did not match."""
    notes = []
    lead = (
        f"Question {row['number']} is in the {row['category']} group. "
        f"The question was: {row['question']}."
    )
    if row["verdict"] == "different":
        notes.append(
            f"{lead} The loop stopped because {plain_stop(row['loop_stop'])}. "
            f"The graph stopped because {plain_stop(row['graph_stop'])}. "
            f"The graph walked these boxes: {show_path(row['node_path'])}."
        )
    if row["loop_failure"] != row["graph_failure"]:
        loop_failure = row["loop_failure"] or "none"
        graph_failure = row["graph_failure"] or "none"
        notes.append(
            f"{lead} A failure name was recorded. "
            f"The loop failure was {loop_failure}. "
            f"The graph failure was {graph_failure}."
        )
    if not row["sources_matched"]:
        notes.append(
            f"{lead} The cited sections did not match. "
            f"The loop cited {show_sources(row['loop_sources'])}. "
            f"The graph cited {show_sources(row['graph_sources'])}."
        )
    return notes


def difference_notes(rows):
    notes = []
    for row in rows:
        notes.extend(explain_row(row))
    return notes


def behaved_identically(rows):
    """Same stop reason, same failure name, and the same cited sections."""
    return bool(rows) and not difference_notes(rows)


def cell(value):
    """One table cell. Pipes and line breaks would break the markdown row."""
    text = " ".join(str(value).split())
    return text.replace("|", "\\|")


def render_report(rows, details):
    """The whole compare.md file, in plain words."""
    counts = summary_counts(rows)
    notes = difference_notes(rows)
    if not rows:
        ending = "No questions were run."
    elif behaved_identically(rows):
        ending = IDENTICAL_SENTENCE
    else:
        ending = NOT_IDENTICAL_SENTENCE

    branch = details.get("branch") or GRAPH_BRANCH
    commit = details.get("commit") or "unknown"
    lines = [
        "# Old loop compared with the new graph",
        "",
        "Each question in `questions.txt` was asked once to two versions of runbook-copilot.",
        "",
        "- The old version is the loop. Its function is `run_agent` in `agent.py`.",
        "- The new version is the graph. Its function is `run_graph` in `graph_agent.py`.",
        "",
        f"The graph code is on the branch `{branch}` (commit `{commit}`). "
        "That branch is not merged. Both versions in this report came from that download, "
        "because the branch keeps the old loop and adds the graph next to it. "
        "The download sits in `.vendor-graph/` and is not part of this repo.",
        "",
        "How they were asked:",
        "",
        "- Practice model only. That is the built-in stand-in. It reads the local runbooks.",
        "- No API key.",
        "- No call to a model on the internet.",
        "- If either version asked to do something, the answer was no. Nothing was restarted or deleted.",
        "- Logging was turned off, so no `agent.log` was written.",
        "",
        "Stop-reason names are explained in [taxonomy.md](taxonomy.md).",
        "",
        "## Summary",
        "",
        f"- Questions asked: {counts['total']}",
        f"- Same stop reason: {counts['same']}",
        f"- Different stop reason: {counts['different']}",
        f"- Cited the same sections: {counts['sources_same']}",
        f"- Cited different sections: {counts['sources_different']}",
        "",
        ending,
        "",
        "## Results",
        "",
        "Number is the order in `questions.txt`, skipping blank lines and comments. "
        "Category is the label on that line. "
        "Same or different is only about the stop reason. "
        "Graph node path is the list of boxes the new version walked. "
        "The old loop does not have boxes, so that column is only for the graph. "
        "Cited sources matched is yes when both versions named the same runbook sections, in the same order.",
        "",
        "| Number | Category | Question | Loop stop reason | Graph stop reason | Same or different | Graph node path | Cited sources matched |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in rows:
        sources_word = "yes" if row["sources_matched"] else "no"
        lines.append("| " + " | ".join([
            cell(row["number"]),
            cell(row["category"]),
            cell(row["question"]),
            cell(show_stop(row["loop_stop"])),
            cell(show_stop(row["graph_stop"])),
            cell(row["verdict"]),
            cell(show_path(row["node_path"])),
            cell(sources_word),
        ]) + " |")
    lines.extend([
        "",
        "A question in the action group can still stop with something other than ACTION_REQUESTED. "
        "The practice model only treats a restart as something to do. "
        "Other commands are searched like a normal question. "
        "Both versions use that same practice model, so this is not a difference between them.",
        "",
        "## Differences",
        "",
    ])
    if notes:
        for index, note in enumerate(notes):
            if index:
                lines.append("")
            lines.append(note)
    else:
        lines.append(
            "None. The stop reasons matched, and the cited sections matched, on every question."
        )
    lines.append("")
    return "\n".join(lines)


def write_report(path, text):
    """Replace compare.md. This report is a fresh write, not a growing log."""
    Path(path).write_text(text, encoding="utf-8")


# ---- Command line -----------------------------------------------------------

def parse_args(argv):
    parser = argparse.ArgumentParser(
        description="Ask every question to the loop and the graph, then write compare.md.",
    )
    parser.add_argument(
        "--questions",
        type=Path,
        default=collect_runs.QUESTIONS_FILE,
        help="Question file. Default: questions.txt next to this script.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="Markdown file to write. Default: compare.md next to this script. Replaced each run.",
    )
    parser.add_argument(
        "--graph-path",
        type=Path,
        default=None,
        help="Folder with graph_agent.py. Default: .vendor-graph/runbook-copilot.",
    )
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(sys.argv[1:] if argv is None else argv)
    try:
        questions = collect_runs.read_questions(args.questions)
        folder = ensure_graph_checkout(args.graph_path)
        agent_mod, graph_mod, app_mod, folder = load_both(folder)
        loop_client, graph_client = practice_clients(agent_mod, app_mod)
    except collect_runs.HarnessError as err:
        print(collect_runs.scrub(str(err)))
        return 2

    commit = collect_runs.checkout_commit(folder)
    print(f"Using the graph branch at {folder}")
    print(f"Branch: {GRAPH_BRANCH}")
    print(f"Commit: {commit}")
    if commit not in (GRAPH_COMMIT, "unknown"):
        print(f"Note: this comparison was written against {GRAPH_COMMIT}.")
    print("Mode: practice model (no API key, no model network call)")
    print(f"Questions: {len(questions)}")
    print("Proposed actions are declined. Nothing will be run.")
    print("Logging is off.")
    print()

    rows = ask_both(
        agent_mod,
        graph_mod,
        questions,
        loop_client,
        graph_client,
        echo=print,
    )
    text = collect_runs.scrub(render_report(rows, {"branch": GRAPH_BRANCH, "commit": commit}))
    write_report(args.output, text)
    counts = summary_counts(rows)
    print()
    print(f"Same stop reason: {counts['same']}")
    print(f"Different stop reason: {counts['different']}")
    print(f"Wrote {args.output.resolve()}")
    if behaved_identically(rows):
        print(IDENTICAL_SENTENCE)
    else:
        print(NOT_IDENTICAL_SENTENCE)
    return 0


if __name__ == "__main__":
    sys.exit(main())
