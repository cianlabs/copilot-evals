"""Tests for the loop-versus-graph comparison.

Stand-ins replace the model and the agent. No API key is required and no
network call is made. One test at the bottom runs two practice questions
through the real graph download, and only when that folder is already here.
"""

import os
import subprocess
import sys
from types import SimpleNamespace

import pytest

import collect_runs
import compare_agents


SECRET = "xai-test-key-do-not-leak-9f3a2c"


def fields(stop, sources=None, failure=None, answer="an answer"):
    return {
        "stop_reason": stop,
        "sources": [] if sources is None else sources,
        "failure": failure,
        "answer": answer,
    }


def sample_row(number=1, category="answerable", question="web server CPU is high",
               loop_stop="ANSWERED", graph_stop="ANSWERED",
               loop_sources=None, graph_sources=None,
               node_path=None, loop_failure=None, graph_failure=None):
    """Build one comparison row the same way the script does."""
    cpu = [{"source": "sample_runbook.txt", "section": "High CPU on web servers"}]
    return compare_agents.make_row(
        number,
        category,
        question,
        fields(loop_stop, cpu if loop_sources is None else loop_sources, loop_failure),
        fields(graph_stop, cpu if graph_sources is None else graph_sources, graph_failure),
        ["PLAN", "SEARCH", "CHECK", "ANSWER"] if node_path is None else node_path,
    )


class FakeAgent:
    """Enough of agent.py for collect_runs.run_one. No real model."""

    def __init__(self):
        self.LOG_FILE = "put-this-back"
        self.last_trace = None
        self.seen_log = []
        self.seen_ask = []
        self.calls = 0

    class AgentError(Exception):
        def __init__(self, name, message=""):
            self.name = name
            super().__init__(f"{name}: {message}")

    def run_agent(self, question, client=None, ask=input, defer_approval=False):
        self.seen_log.append(self.LOG_FILE)
        self.seen_ask.append(ask)
        self.calls += 1
        self.last_trace = SimpleNamespace(
            stop_reason="ANSWERED",
            answer="1. Find the worker.",
            sources=[{"source": "sample_runbook.txt", "section": "High CPU on web servers"}],
            steps=2,
            thoughts=["search"],
        )
        return "1. Find the worker."

    @staticmethod
    def strip_model_sources(text):
        return text or ""


class FakeGraph:
    def __init__(self, agent):
        self.agent = agent
        self.last_trace = None
        self.seen_log = []
        self.seen_ask = []

    def run_graph(self, question, client=None, ask=input, defer_approval=False):
        self.seen_log.append(self.agent.LOG_FILE)
        self.seen_ask.append(ask)
        if question == "this call will fail":
            self.last_trace = None
            raise self.agent.AgentError("BAD_TOOL_ARGS", "not json")
        self.last_trace = SimpleNamespace(
            stop_reason="NO_RELEVANT_RUNBOOK" if question == "bake bread" else "ANSWERED",
            answer="I don't know." if question == "bake bread" else "1. Find the worker.",
            sources=[] if question == "bake bread" else [
                {"source": "sample_runbook.txt", "section": "High CPU on web servers"},
            ],
            steps=1,
            thoughts=[],
            node_path=["PLAN", "SEARCH", "CHECK", "IDK"] if question == "bake bread" else [
                "PLAN", "SEARCH", "CHECK", "ANSWER", "CHECK", "ANSWER",
            ],
        )
        return self.last_trace.answer


def test_sources_match_only_when_the_sections_are_the_same():
    cpu = [{"source": "sample_runbook.txt", "section": "High CPU on web servers"}]
    disk = [{"source": "sample_runbook.txt", "section": "Disk space almost full"}]
    assert compare_agents.sources_match([], [])
    assert compare_agents.sources_match(cpu, [dict(cpu[0])])
    assert not compare_agents.sources_match(cpu, disk)
    assert not compare_agents.sources_match(cpu, [])
    # Same sections in a different order are not treated as a match.
    swapped = list(reversed(cpu + disk))
    assert not compare_agents.sources_match(cpu + disk, swapped)


def test_summary_counts_same_and_different_stop_reasons():
    rows = [
        sample_row(1, loop_stop="ANSWERED", graph_stop="ANSWERED"),
        sample_row(2, category="not_in_runbooks", question="bake bread",
                   loop_stop="NO_RELEVANT_RUNBOOK", graph_stop="ANSWERED",
                   loop_sources=[], graph_sources=[]),
        sample_row(3, loop_stop="ANSWERED", graph_stop="ANSWERED",
                   graph_sources=[{"source": "other.txt", "section": "Other"}]),
    ]
    counts = compare_agents.summary_counts(rows)
    assert counts == {
        "total": 3,
        "same": 2,
        "different": 1,
        "sources_same": 2,
        "sources_different": 1,
    }
    assert not compare_agents.behaved_identically(rows)


def test_report_has_the_table_and_says_when_they_match():
    row = sample_row(question="restart | the worker")
    text = compare_agents.render_report([row], {"branch": "cursor/graph-agent-loop-86f9", "commit": "abc123"})
    assert "## Summary" in text
    assert "Questions asked: 1" in text
    assert "Same stop reason: 1" in text
    assert "Different stop reason: 0" in text
    assert compare_agents.IDENTICAL_SENTENCE in text
    header = "| Number | Category | Question | Loop stop reason | Graph stop reason | Same or different | Graph node path | Cited sources matched |"
    assert header in text
    assert r"restart \| the worker" in text
    assert "PLAN → SEARCH → CHECK → ANSWER" in text
    assert "| same |" in text
    assert "| yes |" in text
    assert "None. The stop reasons matched" in text
    assert "abc123" in text


def test_report_explains_a_difference_in_plain_words():
    rows = [
        sample_row(4, category="near_miss", question="My laptop fan is loud",
                   loop_stop="ANSWERED", graph_stop="WEAK_MATCH_ONLY",
                   graph_sources=[]),
    ]
    text = compare_agents.render_report(rows, {"branch": "b", "commit": "c"})
    assert "Different stop reason: 1" in text
    assert compare_agents.NOT_IDENTICAL_SENTENCE in text
    assert "Question 4 is in the near_miss group." in text
    assert "The question was: My laptop fan is loud." in text
    assert "WEAK_MATCH_ONLY" in text
    assert "weak matches" in text
    assert "The cited sections did not match." in text
    assert "no sections" in text
    assert compare_agents.NOT_IDENTICAL_SENTENCE in text
    assert compare_agents.IDENTICAL_SENTENCE not in text


def test_a_failure_name_is_explained_when_only_one_side_has_it():
    row = sample_row(loop_failure=None, graph_failure="BAD_TOOL_ARGS")
    notes = compare_agents.explain_row(row)
    assert any("BAD_TOOL_ARGS" in note for note in notes)
    assert not compare_agents.behaved_identically([row])


def test_ask_both_reuses_the_collector_and_declines_actions():
    """The practice rules live in collect_runs.run_one. This checks we call it."""
    agent = FakeAgent()
    graph = FakeGraph(agent)
    questions = [
        ("answerable", "web server CPU is high"),
        ("not_in_runbooks", "bake bread"),
    ]
    loop_client = object()
    graph_client = object()
    rows = compare_agents.ask_both(agent, graph, questions, loop_client, graph_client)
    assert agent.LOG_FILE == "put-this-back"
    # One loop call and one graph call per question, both with logging off.
    assert agent.seen_log == [None, None]
    assert graph.seen_log == [None, None]
    assert agent.calls == 2
    for ask in agent.seen_ask + graph.seen_ask:
        assert ask is collect_runs.decline_action
        assert ask("Approve this action? (y/n) ") == "n"
    assert len(rows) == 2
    assert rows[0]["verdict"] == "same"
    assert rows[0]["sources_matched"] is True
    assert rows[0]["node_path"][0] == "PLAN"
    assert rows[1]["verdict"] == "different"
    assert rows[1]["graph_stop"] == "NO_RELEVANT_RUNBOOK"
    assert rows[1]["node_path"][-1] == "IDK"
    assert rows[1]["sources_matched"] is False
    assert loop_client is not graph_client


def test_a_named_error_is_recorded_and_the_next_question_still_runs():
    agent = FakeAgent()
    graph = FakeGraph(agent)
    questions = [
        ("answerable", "this call will fail"),
        ("answerable", "web server CPU is high"),
    ]
    rows = compare_agents.ask_both(agent, graph, questions, object(), object())
    assert rows[0]["graph_failure"] == "BAD_TOOL_ARGS"
    assert rows[0]["graph_stop"] is None
    assert rows[0]["node_path"] == []
    assert rows[1]["graph_failure"] is None
    assert rows[1]["verdict"] == "same"
    assert agent.LOG_FILE == "put-this-back"


def test_logging_stays_off_and_is_restored_if_building_a_row_fails(tmp_path, monkeypatch):
    agent = FakeAgent()
    log_path = tmp_path / "agent.log"
    agent.LOG_FILE = log_path
    graph = FakeGraph(agent)

    def boom(*args, **kwargs):
        # The question already ran. Logging must still be off here.
        assert agent.LOG_FILE is None
        raise RuntimeError("surprise")

    monkeypatch.setattr(compare_agents, "make_row", boom)
    with pytest.raises(RuntimeError):
        compare_agents.ask_both(agent, graph, [("action", "restart sshd")], object(), object())
    assert agent.LOG_FILE == log_path
    assert agent.seen_log == [None]
    assert graph.seen_log == [None]
    assert not log_path.exists()


def test_practice_clients_never_ask_for_the_real_model(monkeypatch):
    seen = []

    def fake_make_client(agent_mod, app_mod, real):
        seen.append(real)
        return {"n": len(seen)}

    monkeypatch.setattr(collect_runs, "make_client", fake_make_client)
    left, right = compare_agents.practice_clients(object(), object())
    assert seen == [False, False]
    assert left != right


def test_default_paths_are_the_question_file_and_compare_md():
    args = compare_agents.parse_args([])
    assert args.questions == collect_runs.QUESTIONS_FILE
    assert args.output == compare_agents.HERE / "compare.md"
    assert args.graph_path is None


def test_a_missing_graph_folder_does_not_download(tmp_path, monkeypatch, capsys):
    def git_must_not_run(*args, **kwargs):
        raise AssertionError("git was called")

    monkeypatch.setattr(collect_runs, "_git", git_must_not_run)
    code = compare_agents.main([
        "--questions", str(collect_runs.QUESTIONS_FILE),
        "--output", str(tmp_path / "compare.md"),
        "--graph-path", str(tmp_path / "no-such-folder"),
    ])
    captured = capsys.readouterr()
    assert code == 2
    assert "CHECKOUT_MISSING" in captured.out
    assert "Cloning" not in captured.out
    assert not (tmp_path / "compare.md").exists()


def test_a_bad_question_file_stops_before_any_download(tmp_path, monkeypatch, capsys):
    def git_must_not_run(*args, **kwargs):
        raise AssertionError("git was called")

    monkeypatch.setattr(collect_runs, "_git", git_must_not_run)
    questions = tmp_path / "questions.txt"
    questions.write_text("this line has no pipe\n", encoding="utf-8")
    code = compare_agents.main([
        "--questions", str(questions),
        "--output", str(tmp_path / "compare.md"),
        "--graph-path", str(tmp_path / "no-such-folder"),
    ])
    captured = capsys.readouterr()
    assert code == 2
    assert "BAD_QUESTIONS" in captured.out
    assert "Cloning" not in captured.out


def test_the_download_folder_is_gitignored_and_pytest_skips_it():
    ignore = (compare_agents.HERE / ".gitignore").read_text(encoding="utf-8")
    pytest_ini = (compare_agents.HERE / "pytest.ini").read_text(encoding="utf-8")
    assert ".vendor-graph/" in ignore
    assert ".vendor-graph" in pytest_ini


def test_committed_report_agrees_with_the_question_list_and_its_table():
    """compare.md is the real run. The counts in the summary must match the table."""
    text = (compare_agents.HERE / "compare.md").read_text(encoding="utf-8")
    questions = collect_runs.read_questions(collect_runs.QUESTIONS_FILE)
    body = []
    for line in text.splitlines():
        if not line.startswith("| "):
            continue
        if line.startswith("| Number") or line.startswith("| ---"):
            continue
        body.append(line)
    assert len(body) == len(questions) == 30
    same = sum("| same |" in line for line in body)
    different = sum("| different |" in line for line in body)
    cited_yes = sum(line.rstrip().endswith("| yes |") for line in body)
    cited_no = sum(line.rstrip().endswith("| no |") for line in body)
    assert f"Questions asked: {len(body)}" in text
    assert f"Same stop reason: {same}" in text
    assert f"Different stop reason: {different}" in text
    assert f"Cited the same sections: {cited_yes}" in text
    assert f"Cited different sections: {cited_no}" in text
    for number, (category, question) in enumerate(questions, start=1):
        assert f"| {number} | {category} | {question} |" in text
    if different == 0 and cited_no == 0:
        assert compare_agents.IDENTICAL_SENTENCE in text
    else:
        assert compare_agents.NOT_IDENTICAL_SENTENCE in text


def test_write_report_replaces_the_old_file(tmp_path):
    path = tmp_path / "compare.md"
    path.write_text("old words that must go\n", encoding="utf-8")
    compare_agents.write_report(path, "new report\n")
    assert path.read_text(encoding="utf-8") == "new report\n"


def test_two_practice_questions_compare_without_a_key(tmp_path):
    """The real practice model, on two questions, in a fresh process.

    A fresh process keeps this import away from the pinned checkout the
    other tests already loaded. Nothing here is allowed to use the network.
    """
    folder = compare_agents.find_graph_checkout()
    if folder is None:
        pytest.fail(
            "The graph download is missing. Run: .venv/bin/python compare_agents.py "
            "That downloads it into .vendor-graph/. The tests do not download it."
        )
    questions = tmp_path / "questions.txt"
    questions.write_text(
        "not_in_runbooks | How do I bake sourdough bread at home\n"
        "action | Restart the runaway worker\n",
        encoding="utf-8",
    )
    output = tmp_path / "compare.md"
    log_path = folder / "agent.log"
    before = log_path.read_text(encoding="utf-8") if log_path.exists() else None
    env = os.environ.copy()
    env["XAI_API_KEY"] = SECRET
    env["PYTHONIOENCODING"] = "utf-8"
    # A missing credential should fail the command, not sit at a prompt.
    env["GIT_TERMINAL_PROMPT"] = "0"
    completed = subprocess.run(
        [
            sys.executable,
            str(compare_agents.HERE / "compare_agents.py"),
            "--questions", str(questions),
            "--output", str(output),
            "--graph-path", str(folder),
        ],
        cwd=tmp_path,
        env=env,
        text=True,
        capture_output=True,
        check=False,
        timeout=120,
    )
    blob = (completed.stdout or "") + (completed.stderr or "")
    assert completed.returncode == 0, blob
    report = output.read_text(encoding="utf-8")
    assert SECRET not in report + blob
    assert "Cloning" not in blob
    assert "practice model" in blob
    assert "Questions asked: 2" in report
    assert "NO_RELEVANT_RUNBOOK" in report
    assert "ACTION_REQUESTED" in report
    assert "PLAN" in report
    assert "Same stop reason:" in report
    assert "Different stop reason:" in report
    assert "Replacement started" not in report + blob
    assert "[simulated]" not in report + blob
    if before is None:
        assert not log_path.exists()
    else:
        assert log_path.read_text(encoding="utf-8") == before
