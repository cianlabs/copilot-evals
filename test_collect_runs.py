"""Tests for the collect-runs harness.

A fake model stands in for Grok. No API key is required and no network call
is made. The 30-question test uses runbook-copilot's own practice model,
which also stays on this machine.
"""

import json
import os
from types import SimpleNamespace

import pytest

import check_runs
import collect_runs
import golden_check
import judge
import show_trace


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
    """--real stops with MissingKey before any question is written down."""
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
    assert "MissingKey" in captured.out
    assert "op read" in captured.out
    assert "op://Personal/xAI API Key/credential" in captured.out
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
        "--yes",
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


def test_bad_limit_exits_before_any_run():
    code = collect_runs.main(["--limit", "0"])
    assert code == 2


def test_upper_bound_and_cost_do_not_invent_numbers():
    """The call bound is questions times passes times steps. Cost comes from usage."""
    assert collect_runs.call_upper_bound(30, 1, 4) == 120
    assert collect_runs.call_upper_bound(3, 2, 4) == 24
    assert collect_runs.call_upper_bound(0, 2, 4) == 0

    usage = SimpleNamespace(prompt_tokens=1000, completion_tokens=500)
    info = collect_runs.describe_model_call(
        "grok-build-0.1",
        SimpleNamespace(model="grok-build-0.1", usage=usage),
    )
    assert info["tokens_in"] == 1000
    assert info["tokens_out"] == 500
    # 1000 in at $1 / 1M, plus 500 out at $2 / 1M.
    assert info["cost"] == pytest.approx(0.002)

    cached = SimpleNamespace(
        prompt_tokens=1000,
        completion_tokens=0,
        prompt_tokens_details=SimpleNamespace(cached_tokens=400),
    )
    info = collect_runs.describe_model_call("grok-build-0.1", SimpleNamespace(usage=cached))
    # 600 fresh in at $1 / 1M, 400 cached at $0.20 / 1M, no output.
    assert info["cost"] == pytest.approx(0.00068)

    long_usage = SimpleNamespace(prompt_tokens=200_000, completion_tokens=0)
    info = collect_runs.describe_model_call("grok-build-0.1", SimpleNamespace(usage=long_usage))
    # The whole request uses the higher price: $2 / 1M in.
    assert info["cost"] == pytest.approx(0.4)

    priced = SimpleNamespace(prompt_tokens=10, completion_tokens=10, cost=1.25)
    info = collect_runs.describe_model_call("grok-build-0.1", SimpleNamespace(usage=priced))
    assert info["cost"] == pytest.approx(1.25)

    other = SimpleNamespace(prompt_tokens=1000, completion_tokens=500)
    info = collect_runs.describe_model_call(
        "some-other-model",
        SimpleNamespace(model="some-other-model", usage=other),
    )
    assert info["tokens_in"] == 1000
    assert info["tokens_out"] == 500
    assert info["cost"] is None

    info = collect_runs.describe_model_call("grok-build-0.1", SimpleNamespace(usage=None))
    assert info["model"] == "grok-build-0.1"
    assert info["tokens_in"] is None
    assert info["tokens_out"] is None
    assert info["cost"] is None


def test_real_prompt_stops_without_yes(tmp_path, copilot, monkeypatch, capsys):
    """A real run prints the bound and stops unless the answer is yes."""
    agent_mod, _app, folder = copilot
    monkeypatch.setenv("XAI_API_KEY", SECRET)

    def forbid_client():
        raise AssertionError("make_client was called")

    monkeypatch.setattr(agent_mod, "make_client", forbid_client)
    answers = iter(["no", "y"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    questions = tmp_path / "questions.txt"
    questions.write_text(
        "not_in_runbooks | How do I bake sourdough bread at home\n"
        "not_in_runbooks | How do I reset a user's Okta MFA\n"
        "action | Restart the runaway worker\n",
        encoding="utf-8",
    )
    output = tmp_path / "runs.real.jsonl"
    args = [
        "--real",
        "--limit", "2",
        "--passes", "2",
        "--questions", str(questions),
        "--output", str(output),
        "--copilot-path", str(folder),
    ]
    code = collect_runs.main(args)
    captured = capsys.readouterr()
    bound = collect_runs.call_upper_bound(2, 2, agent_mod.MAX_STEPS)
    assert code == 2
    assert "Stopped" in captured.out
    assert "Questions: 2" in captured.out
    assert "Passes: 2" in captured.out
    assert f"Upper bound on calls: {bound}" in captured.out
    assert agent_mod.MODEL in captured.out
    assert not output.exists()
    assert SECRET not in captured.out + captured.err

    # A single letter is not a yes. Still no model call.
    code = collect_runs.main(args)
    captured = capsys.readouterr()
    assert code == 2
    assert "Stopped" in captured.out
    assert not output.exists()
    assert SECRET not in captured.out + captured.err


def test_yes_skips_the_prompt_and_limit_keeps_the_first_questions(tmp_path, copilot, monkeypatch, capsys):
    agent_mod, app_mod, folder = copilot
    monkeypatch.setenv("XAI_API_KEY", SECRET)

    def forbid_input(prompt=""):
        raise AssertionError("input was called")

    monkeypatch.setattr("builtins.input", forbid_input)
    monkeypatch.setattr(agent_mod, "make_client", lambda: app_mod.DemoClient())
    questions = tmp_path / "questions.txt"
    questions.write_text(
        "not_in_runbooks | How do I bake sourdough bread at home\n"
        "not_in_runbooks | How do I reset a user's Okta MFA\n"
        "action | Restart the runaway worker\n",
        encoding="utf-8",
    )
    output = tmp_path / "runs.jsonl"
    code = collect_runs.main([
        "--real",
        "--yes",
        "--limit", "1",
        "--passes", "2",
        "--questions", str(questions),
        "--output", str(output),
        "--copilot-path", str(folder),
    ])
    captured = capsys.readouterr()
    assert code == 0
    rows = read_jsonl(output)
    assert len(rows) == 2
    assert [row["question"] for row in rows] == [
        "How do I bake sourdough bread at home",
        "How do I bake sourdough bread at home",
    ]
    bound = collect_runs.call_upper_bound(1, 2, agent_mod.MAX_STEPS)
    assert f"Upper bound on calls: {bound}" in captured.out
    assert "Continuing because --yes was set." in captured.out
    blob = output.read_text(encoding="utf-8") + captured.out + captured.err
    assert SECRET not in blob


def test_named_errors_are_recorded_and_the_run_continues(tmp_path, copilot, monkeypatch, capsys):
    """A timeout and an HTTP error are saved, and the next question still runs."""
    agent_mod, _app, folder = copilot
    monkeypatch.setenv("XAI_API_KEY", SECRET)
    original_ask = agent_mod.ask_model

    class APITimeoutError(Exception):
        pass

    class APIStatusError(Exception):
        def __init__(self):
            self.status_code = 500
            super().__init__("down " + SECRET)

    calls = {"n": 0, "timeouts": []}

    def create(**kwargs):
        calls["timeouts"].append(kwargs.get("timeout"))
        calls["n"] += 1
        if calls["n"] == 1:
            raise APITimeoutError("slow " + SECRET)
        if calls["n"] == 2:
            raise APIStatusError()
        message = text_message("1. Do a thing.")
        return SimpleNamespace(
            model="grok-build-0.1",
            usage=None,
            choices=[SimpleNamespace(message=message)],
        )

    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    monkeypatch.setattr(agent_mod, "make_client", lambda: client)

    def forbid_input(prompt=""):
        raise AssertionError("input was called")

    monkeypatch.setattr("builtins.input", forbid_input)
    questions = tmp_path / "questions.txt"
    questions.write_text(
        "answerable | this call will time out\n"
        "answerable | this call will fail on http\n"
        "not_in_runbooks | How do I bake sourdough bread at home\n",
        encoding="utf-8",
    )
    output = tmp_path / "runs.real.jsonl"
    code = collect_runs.main([
        "--real",
        "--yes",
        "--trace",
        "--questions", str(questions),
        "--output", str(output),
        "--copilot-path", str(folder),
    ])
    captured = capsys.readouterr()
    assert code == 0
    assert agent_mod.ask_model is original_ask
    rows = read_jsonl(output)
    assert [row["failure"] for row in rows] == ["ModelTimeout", "ModelHttpError", None]
    assert calls["timeouts"] == [60, 60, 60]
    trace_path = tmp_path / "traces.real.jsonl"
    blob = output.read_text(encoding="utf-8") + trace_path.read_text(encoding="utf-8")
    blob += captured.out + captured.err
    assert SECRET not in blob
    assert "[key hidden]" in output.read_text(encoding="utf-8")
    events = read_jsonl(trace_path)
    timed = [event for event in events if event.get("failure") == "ModelTimeout"]
    assert timed
    assert timed[0]["model"] == "grok-build-0.1"
    assert timed[0]["tokens_in"] is None
    assert timed[0]["cost"] is None


def test_fresh_empties_both_files_and_warns_when_lines_exist(tmp_path, copilot, capsys):
    """Old lines stay unless --fresh is set. The warning names that flag."""
    _agent, _app, folder = copilot
    questions = tmp_path / "questions.txt"
    questions.write_text(
        "not_in_runbooks | How do I bake sourdough bread at home\n",
        encoding="utf-8",
    )
    runs = tmp_path / "runs.jsonl"
    traces = tmp_path / "traces.jsonl"
    runs.write_text('{"old": 1}\n{"old": 2}\n', encoding="utf-8")
    traces.write_text('{"old": true}\n', encoding="utf-8")
    code = collect_runs.main([
        "--questions", str(questions),
        "--output", str(runs),
        "--copilot-path", str(folder),
        "--trace",
    ])
    captured = capsys.readouterr()
    assert code == 0
    assert "already has 2 lines" in captured.out
    assert "traces.jsonl already has 1 line" in captured.out
    assert "--fresh" in captured.out
    lines = runs.read_text(encoding="utf-8").splitlines()
    assert json.loads(lines[0]) == {"old": 1}
    assert len(lines) == 3
    assert traces.read_text(encoding="utf-8").splitlines()[0] == '{"old": true}'

    code = collect_runs.main([
        "--questions", str(questions),
        "--output", str(runs),
        "--copilot-path", str(folder),
        "--trace",
        "--fresh",
    ])
    captured = capsys.readouterr()
    assert code == 0
    assert "Emptied runs.jsonl (3 lines)" in captured.out
    assert "Emptied traces.jsonl" in captured.out
    rows = read_jsonl(runs)
    assert len(rows) == 1
    assert "old" not in runs.read_text(encoding="utf-8")
    assert '{"old": true}' not in traces.read_text(encoding="utf-8")
    assert rows[0]["question"] == "How do I bake sourdough bread at home"


def test_real_pass_keeps_practice_files_separate(tmp_path, copilot, monkeypatch, capsys):
    """--real writes runs.real.jsonl and traces.real.jsonl, and leaves the practice files."""
    agent_mod, app_mod, folder = copilot
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("XAI_API_KEY", SECRET)
    (tmp_path / "runs.jsonl").write_text('{"practice": true}\n', encoding="utf-8")
    (tmp_path / "traces.jsonl").write_text('{"practice": true}\n', encoding="utf-8")
    questions = tmp_path / "questions.txt"
    questions.write_text(
        "not_in_runbooks | How do I bake sourdough bread at home\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(agent_mod, "make_client", lambda: app_mod.DemoClient())
    code = collect_runs.main([
        "--real",
        "--yes",
        "--trace",
        "--questions", str(questions),
        "--copilot-path", str(folder),
    ])
    captured = capsys.readouterr()
    assert code == 0
    assert (tmp_path / "runs.jsonl").read_text(encoding="utf-8") == '{"practice": true}\n'
    assert (tmp_path / "traces.jsonl").read_text(encoding="utf-8") == '{"practice": true}\n'
    runs = tmp_path / "runs.real.jsonl"
    traces = tmp_path / "traces.real.jsonl"
    blob = runs.read_text(encoding="utf-8") + traces.read_text(encoding="utf-8")
    blob += captured.out + captured.err
    assert SECRET not in blob
    events = read_jsonl(traces)
    model_events = [event for event in events if "model" in event]
    assert model_events
    for event in model_events:
        assert event["model"] == agent_mod.MODEL
        assert event["tokens_in"] is None
        assert event["tokens_out"] is None
        assert event["cost"] is None


def test_checkers_accept_the_real_file_names(tmp_path, capsys):
    """check_runs, golden_check, judge, and show_trace already take a file name."""
    sample = (collect_runs.HERE / "runs.sample.jsonl").read_text(encoding="utf-8")
    runs = tmp_path / "runs.real.jsonl"
    runs.write_text(sample, encoding="utf-8")
    assert check_runs.main([str(runs)]) == 0
    assert golden_check.main([str(runs)]) == 0
    judge_out = tmp_path / "judge_results.jsonl"
    assert judge.main([str(runs), "--fake", "--output", str(judge_out)]) == 0
    assert judge_out.is_file()
    traces = tmp_path / "traces.real.jsonl"
    traces.write_text(
        json.dumps({
            "trace_id": "abc123",
            "run_number": 1,
            "step": 1,
            "node": "answer",
            "inputs": {"question": "How do I bake sourdough bread at home"},
            "tool_calls": [],
            "tool_results": [],
            "stop_reason": "NO_RELEVANT_RUNBOOK",
            "failure": None,
            "latency_ms": 1000,
            "run_latency_ms": 1000,
        }) + "\n",
        encoding="utf-8",
    )
    assert show_trace.main([str(traces), "--summary"]) == 0
    assert "Total time: 1.0 s" in capsys.readouterr().out
    assert SECRET not in judge_out.read_text(encoding="utf-8")
