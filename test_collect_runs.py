"""Tests for the collect-runs harness.

A fake model stands in for Grok. No API key is required and no network call
is made. The 30-question test uses runbook-copilot's own practice model,
which also stays on this machine.
"""

import json
import os
from types import SimpleNamespace

import pytest

import collect_runs


SECRET = "xai-test-key-do-not-leak-9f3a2c"


@pytest.fixture(scope="session")
def copilot():
    """The real agent modules. Fails with a named message if the checkout is missing."""
    try:
        return collect_runs.load_copilot()
    except collect_runs.HarnessError as err:
        pytest.fail(
            f"{err} Tests do not download it. Run collect_runs.py once, or set RUNBOOK_COPILOT_PATH."
        )


def write_questions(path, rows):
    lines = [f"{category} | {question}" for category, question in rows]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def read_jsonl(path):
    text = path.read_text(encoding="utf-8")
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def scripted_client(*messages):
    """A fake model. Each call returns the next message. No network."""
    remaining = list(messages)

    def create(**kwargs):
        message = remaining.pop(0)
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])

    return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))


def text_message(text):
    return SimpleNamespace(content=text, tool_calls=None)


def tool_message(name, arguments):
    if not isinstance(arguments, str):
        arguments = json.dumps(arguments)
    call = SimpleNamespace(id="call_test", function=SimpleNamespace(name=name, arguments=arguments))
    return SimpleNamespace(content=None, tool_calls=[call])


def test_starter_file_has_thirty_questions():
    questions = collect_runs.read_questions(collect_runs.QUESTIONS_FILE)
    assert len(questions) == 30
    counts = {}
    for category, question in questions:
        counts[category] = counts.get(category, 0) + 1
        assert question
    assert counts == {
        "answerable": 14,
        "not_in_runbooks": 5,
        "near_miss": 6,
        "action": 5,
    }


def test_bad_question_line_is_named(tmp_path):
    path = tmp_path / "questions.txt"
    path.write_text("this line has no pipe\n", encoding="utf-8")
    with pytest.raises(collect_runs.HarnessError) as caught:
        collect_runs.read_questions(path)
    assert caught.value.name == "BAD_QUESTIONS"


def test_bad_passes_exits_before_any_run():
    code = collect_runs.main(["--passes", "0"])
    assert code == 2


def test_real_flag_without_a_key_writes_nothing(tmp_path, copilot, monkeypatch, capsys):
    """--real stops with MISSING_KEY before any question is written down."""
    monkeypatch.delenv("XAI_API_KEY", raising=False)
    questions = tmp_path / "questions.txt"
    questions.write_text("answerable | web server CPU is at 95 percent\n", encoding="utf-8")
    output = tmp_path / "runs.jsonl"
    code = collect_runs.main([
        "--real",
        "--questions", str(questions),
        "--output", str(output),
        "--copilot-path", str(copilot[2]),
    ])
    captured = capsys.readouterr()
    assert code == 2
    assert "MISSING_KEY" in captured.out
    assert not output.exists()
    # The error names the variable. It must not invent or echo a key value.
    assert SECRET not in captured.out + captured.err


def test_real_flag_does_not_print_a_key(tmp_path, copilot, monkeypatch, capsys):
    agent_mod, app_mod, folder = copilot
    monkeypatch.setenv("XAI_API_KEY", SECRET)

    def fake_make_client():
        # Read the key the same way the real client does, then stay offline.
        if not os.environ.get("XAI_API_KEY", "").strip():
            raise agent_mod.AgentError("MISSING_KEY", "XAI_API_KEY is not set in this Terminal tab.")
        return app_mod.DemoClient()

    monkeypatch.setattr(agent_mod, "make_client", fake_make_client)
    questions = tmp_path / "questions.txt"
    questions.write_text("not_in_runbooks | How do I bake sourdough bread at home\n", encoding="utf-8")
    output = tmp_path / "runs.jsonl"
    code = collect_runs.main([
        "--real",
        "--questions", str(questions),
        "--output", str(output),
        "--copilot-path", str(folder),
    ])
    captured = capsys.readouterr()
    assert code == 0
    blob = output.read_text(encoding="utf-8") + captured.out + captured.err
    assert SECRET not in blob


def test_default_mode_does_not_call_the_live_client(tmp_path, copilot, monkeypatch, capsys):
    """A key may be sitting in the environment. The default command still ignores it."""
    agent_mod, _app, folder = copilot
    monkeypatch.setenv("XAI_API_KEY", SECRET)

    def forbid_live_client():
        raise AssertionError("practice mode called make_client")

    monkeypatch.setattr(agent_mod, "make_client", forbid_live_client)
    questions = tmp_path / "questions.txt"
    questions.write_text("not_in_runbooks | How do I bake sourdough bread at home\n", encoding="utf-8")
    output = tmp_path / "runs.jsonl"
    code = collect_runs.main([
        "--questions", str(questions),
        "--output", str(output),
        "--copilot-path", str(folder),
    ])
    captured = capsys.readouterr()
    assert code == 0
    assert SECRET not in output.read_text(encoding="utf-8") + captured.out + captured.err
    assert "practice model" in captured.out


def test_practice_pass_writes_thirty_lines_with_stop_reasons(tmp_path, copilot, monkeypatch):
    """The real practice model, the real runbooks, still no key and no network."""
    agent_mod, app_mod, _folder = copilot
    monkeypatch.setenv("XAI_API_KEY", SECRET)
    output = tmp_path / "runs.jsonl"
    questions = collect_runs.read_questions(collect_runs.QUESTIONS_FILE)
    written, failures = collect_runs.collect(
        questions,
        output,
        app_mod.DemoClient(),
        agent_mod,
        passes=1,
    )
    rows = read_jsonl(output)
    assert written == 30
    assert failures == 0
    assert len(rows) == 30
    required = {"question", "category", "stop_reason", "answer", "sources", "steps", "seconds", "failure"}
    for row in rows:
        assert required <= set(row)
        assert isinstance(row["stop_reason"], str) and row["stop_reason"]
        assert row["failure"] is None
        assert isinstance(row["sources"], list)
        assert isinstance(row["steps"], int)
        assert isinstance(row["thoughts"], list)
        assert row["seconds"] >= 0
        assert SECRET not in json.dumps(row)
        # A simulation that actually ran would leave one of these sentences.
        blob = json.dumps(row)
        assert "Replacement started" not in blob
        assert "[simulated]" not in blob
        assert "Result: success" not in blob

    restarts = [row for row in rows if row["question"].startswith("Restart ")]
    assert len(restarts) == 3
    for row in restarts:
        assert row["stop_reason"] == "ACTION_REQUESTED"
        assert "Nothing was run." in row["answer"]


def test_agent_error_is_recorded_and_the_loop_continues(tmp_path, copilot):
    agent_mod, _app, _folder = copilot
    # First question: tool arguments are not JSON, so the agent raises BAD_TOOL_ARGS.
    # Second question: a normal search, then a short answer, so the loop did continue.
    client = scripted_client(
        tool_message("search_runbooks", "{"),
        tool_message("search_runbooks", {"query": "high cpu web server"}),
        text_message("1. Find the worker that is using the CPU."),
    )
    output = tmp_path / "runs.jsonl"
    questions = [
        ("answerable", "this call will fail"),
        ("answerable", "web server CPU is at 95 percent"),
    ]
    written, failures = collect_runs.collect(questions, output, client, agent_mod)
    rows = read_jsonl(output)
    assert written == 2
    assert failures == 1
    assert rows[0]["failure"] == "BAD_TOOL_ARGS"
    assert rows[0]["question"] == "this call will fail"
    assert rows[1]["failure"] is None
    assert rows[1]["stop_reason"]
    assert rows[1]["question"] == "web server CPU is at 95 percent"


def test_actions_are_always_declined(tmp_path, copilot, monkeypatch):
    agent_mod, _app, _folder = copilot
    approved_flags = []
    real_settle = agent_mod.settle_action

    def spy_settle(action, approved):
        approved_flags.append(approved)
        return real_settle(action, approved)

    monkeypatch.setattr(agent_mod, "settle_action", spy_settle)
    ran = []

    def action_must_not_run(*args, **kwargs):
        ran.append(kwargs)
        raise AssertionError("execute_action ran")

    monkeypatch.setitem(agent_mod.TOOLS, "execute_action", action_must_not_run)
    client = scripted_client(
        tool_message("execute_action", {"action": "restart the process 'runaway-worker'"}),
        tool_message("execute_action", {"action": "restart the process 'sshd'"}),
    )
    output = tmp_path / "runs.jsonl"
    questions = [
        ("action", "restart the runaway worker"),
        ("action", "restart sshd"),
    ]
    written, failures = collect_runs.collect(questions, output, client, agent_mod)
    rows = read_jsonl(output)
    assert written == 2
    assert failures == 0
    assert ran == []
    assert approved_flags == [False, False]
    for row in rows:
        assert row["stop_reason"] == "ACTION_REQUESTED"
        assert row["failure"] is None
        assert "Nothing was run." in row["answer"]


def test_logging_to_a_file_is_turned_off(tmp_path, copilot):
    agent_mod, _app, _folder = copilot
    log_path = tmp_path / "agent.log"
    previous = agent_mod.LOG_FILE
    agent_mod.LOG_FILE = log_path
    client = scripted_client(
        tool_message("search_runbooks", {"query": "disk space"}),
        text_message("1. Rotate old logs."),
    )
    output = tmp_path / "runs.jsonl"
    try:
        collect_runs.collect([("answerable", "disk almost full")], output, client, agent_mod)
        # collect() puts the old path back. Nothing was written while it ran.
        assert agent_mod.LOG_FILE == log_path
    finally:
        agent_mod.LOG_FILE = previous
    assert not log_path.exists()


def test_key_does_not_appear_in_the_jsonl_or_the_terminal(tmp_path, copilot, monkeypatch, capsys):
    agent_mod, _app, _folder = copilot
    monkeypatch.setenv("XAI_API_KEY", SECRET)
    # The model's own thought contains the key. That thought is stored on the
    # trace, so a missed scrub would write the key into the file.
    leak = tool_message("search_runbooks", {"query": "disk space"})
    leak.content = f"I should look up {SECRET}"
    client = scripted_client(leak, text_message("1. Delete temporary files."))
    output = tmp_path / "runs.jsonl"
    collect_runs.collect([("answerable", "the disk is almost full")], output, client, agent_mod)
    captured = capsys.readouterr()
    blob = output.read_text(encoding="utf-8") + captured.out + captured.err
    assert SECRET not in blob
    row = read_jsonl(output)[0]
    assert "[key hidden]" in " ".join(row["thoughts"])


def test_passes_repeat_each_question(tmp_path, copilot):
    agent_mod, _app, _folder = copilot
    # No tool call: the loop stops with UNGROUNDED_ANSWER. Still a real stop reason.
    client = scripted_client(
        text_message("1. Do a thing."),
        text_message("1. Do a thing."),
        text_message("1. Do a thing."),
        text_message("1. Do a thing."),
    )
    output = tmp_path / "runs.jsonl"
    questions = [("not_in_runbooks", "bake sourdough"), ("action", "restart the runaway worker")]
    written, failures = collect_runs.collect(questions, output, client, agent_mod, passes=2)
    rows = read_jsonl(output)
    assert written == 4
    assert failures == 0
    assert [row["pass_number"] for row in rows] == [1, 1, 2, 2]
    assert [row["question"] for row in rows] == [
        "bake sourdough",
        "restart the runaway worker",
        "bake sourdough",
        "restart the runaway worker",
    ]
    assert all(row["stop_reason"] for row in rows)


def test_append_does_not_erase_earlier_lines(tmp_path, copilot):
    agent_mod, _app, _folder = copilot
    output = tmp_path / "runs.jsonl"
    output.write_text('{"already": true}\n', encoding="utf-8")
    client = scripted_client(text_message("1. Guess."))
    collect_runs.collect([("near_miss", "laptop fan")], output, client, agent_mod)
    lines = output.read_text(encoding="utf-8").splitlines()
    assert json.loads(lines[0]) == {"already": True}
    assert len(lines) == 2


def test_scrub_leaves_ordinary_text_alone():
    assert collect_runs.scrub("disk almost full", key="") == "disk almost full"
    assert collect_runs.scrub("short key stays", key="abc") == "short key stays"
    assert collect_runs.scrub(f"token {SECRET}", key=SECRET) == "token [key hidden]"


def test_sample_file_matches_the_jsonl_shape():
    """The committed sample is a real practice-pass slice, not a hand-written stub."""
    rows = read_jsonl(collect_runs.HERE / "runs.sample.jsonl")
    assert 5 <= len(rows) <= 12
    seen = set()
    for row in rows:
        assert row["stop_reason"]
        assert row["failure"] is None
        assert row["category"] in collect_runs.KNOWN_CATEGORIES
        assert "Nothing was run." in row["answer"] or row["stop_reason"] != "ACTION_REQUESTED"
        seen.add(row["stop_reason"])
    assert {"ANSWERED", "NO_RELEVANT_RUNBOOK", "ACTION_REQUESTED"} <= seen
