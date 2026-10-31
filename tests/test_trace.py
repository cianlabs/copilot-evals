"""Tests for the local tracer, the story printer, and the retrieval math.

No API key is required. The practice-model test stays on this machine.
A made-up example covers the retrieval math, so that test does not search.
"""

import json
from types import SimpleNamespace

import pytest

import collect_runs
import retrieval_score
import show_trace
import trace


SECRET = "xai-test-key-do-not-leak-9f3a2c"
# A second secret, so the test can see that environment values are not copied.
TOKEN = "zebra-marker-token-99"

REQUIRED = {
    "trace_id",
    "run_number",
    "step",
    "node",
    "inputs",
    "tool_calls",
    "tool_results",
    "stop_reason",
    "failure",
    "latency_ms",
    "run_latency_ms",
}


@pytest.fixture(scope="session")
def copilot():
    """The real agent modules. Fails with a named message if the checkout is missing."""
    try:
        return collect_runs.load_copilot()
    except collect_runs.HarnessError as err:
        pytest.fail(
            f"{err} Tests do not download it. Run collect_runs.py once, or set RUNBOOK_COPILOT_PATH."
        )


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


def partial_record(secret=""):
    """An answerable run the partial-answer check flags. The secret is planted on purpose."""
    return {
        "question": "The web server CPU is at 95 percent and pages are slow",
        "category": "answerable",
        "stop_reason": "ANSWERED",
        "answer": "1. Symptom: web servers show CPU above ninety percent and response times climb.",
        "sources": [{"source": "sample_runbook.txt", "section": "High CPU on web servers"}],
        "steps": 2,
        "thoughts": [f"I should search for {secret}".rstrip()],
        "seconds": 0.012,
        "failure": None,
    }


def write_partial_trace(path, secret=""):
    """One traced run, as collect_runs would write it after a search."""
    tracer = trace.Tracer(path)
    notes = [
        {"kind": "model", "latency_ms": 2},
        {
            "kind": "tool",
            "name": "search_runbooks",
            "query": f"high cpu {secret}".rstrip(),
            "results": [{
                "title": f"High CPU on web servers {secret}".rstrip(),
                "source": "sample_runbook.txt",
                "score": 0.471,
                "text": "full chunk that must not be stored",
                "environ": {"XAI_API_KEY": secret or "nope"},
            }],
            "latency_ms": 4,
        },
        {"kind": "model", "latency_ms": 1},
    ]
    tracer.write_run(13, partial_record(secret), notes, [])
    return tracer


def test_tracer_writes_valid_lines_and_hides_keys(tmp_path, monkeypatch):
    """Each step is one JSON line. A planted key and a chunk of page text stay out."""
    monkeypatch.setenv("XAI_API_KEY", SECRET)
    monkeypatch.setenv("TRACE_TEST_TOKEN", TOKEN)
    path = tmp_path / "traces.jsonl"
    write_partial_trace(path, secret=SECRET)
    # A second run, so two trace ids can be compared. This one also plants the token.
    trace.Tracer(path).write_run(
        14,
        {
            "question": f"where is {TOKEN}",
            "category": "not_in_runbooks",
            "stop_reason": "NO_RELEVANT_RUNBOOK",
            "answer": "I don't know. No relevant runbook sections were found, so I will not guess.",
            "sources": [],
            "steps": 1,
            "thoughts": [],
            "seconds": 0.004,
            "failure": None,
        },
        [
            {"kind": "model", "latency_ms": 1},
            {
                "kind": "tool",
                "name": "search_runbooks",
                "query": "bread",
                "results": [],
                "latency_ms": 1,
            },
        ],
        [],
    )
    lines = path.read_text(encoding="utf-8").splitlines()
    assert lines
    events = [json.loads(line) for line in lines]
    blob = path.read_text(encoding="utf-8")
    assert SECRET not in blob
    assert TOKEN not in blob
    assert "full chunk that must not be stored" not in blob
    assert "[key hidden]" in blob
    ids = {event["trace_id"] for event in events}
    assert len(ids) == 2
    for event in events:
        assert REQUIRED <= set(event)
        assert isinstance(event["trace_id"], str) and len(event["trace_id"]) == 6
        assert isinstance(event["step"], int) and event["step"] >= 1
        assert isinstance(event["latency_ms"], int)
        assert isinstance(event["run_latency_ms"], int)
        assert isinstance(event["tool_calls"], list)
        assert isinstance(event["tool_results"], list)
        for hit in event["tool_results"]:
            assert "text" not in hit
            assert "environ" not in hit
    run_13 = [event for event in events if event["run_number"] == 13]
    assert [event["node"] for event in run_13] == ["plan", "search", "answer"]
    assert [event["step"] for event in run_13] == [1, 2, 3]
    assert len({event["trace_id"] for event in run_13}) == 1
    assert run_13[-1]["stop_reason"] == "ANSWERED"
    assert run_13[-1]["failure"] == "PARTIAL_ANSWER"
    assert run_13[-1]["run_latency_ms"] == 12
    assert run_13[1]["tool_results"][0]["score"] == 0.471
    assert run_13[1]["inputs"]["query"]


def test_show_trace_prints_each_step_and_the_failing_step(tmp_path, capsys):
    path = tmp_path / "traces.jsonl"
    write_partial_trace(path)
    code = show_trace.main([str(path), "13"])
    captured = capsys.readouterr()
    assert code == 0
    text = captured.out
    assert "Run 13" in text
    assert "Step 1 plan" in text
    assert "Step 2 search" in text
    assert "Found 1 runbook with a score:" in text
    assert "0.471" in text
    assert "High CPU on web servers" in text
    assert "Step 3 answer" in text
    assert "Stop reason: ANSWERED" in text
    assert "Failure class: PARTIAL_ANSWER" in text
    assert "Went wrong at step 3 (answer)" in text
    assert "Whole run: 12 ms" in text
    assert "Time:" in text


def test_show_trace_groups_failures_and_lists_the_slowest(tmp_path, capsys):
    path = tmp_path / "traces.jsonl"
    # Two hand-written runs. Times are fixed so the slow one is obvious.
    rows = [
        {
            "trace_id": "aaaaaa",
            "run_number": 1,
            "step": 1,
            "node": "answer",
            "inputs": {"question": "How do I bake sourdough bread at home"},
            "tool_calls": [],
            "tool_results": [],
            "stop_reason": "NO_RELEVANT_RUNBOOK",
            "failure": None,
            "latency_ms": 1,
            "run_latency_ms": 5,
        },
        {
            "trace_id": "bbbbbb",
            "run_number": 2,
            "step": 1,
            "node": "search",
            "inputs": {"question": "How do I reset a user's Okta MFA", "query": "okta"},
            "tool_calls": [{"name": "search_runbooks", "query": "okta"}],
            "tool_results": [],
            "stop_reason": None,
            "failure": None,
            "latency_ms": 4,
            "run_latency_ms": 40,
        },
        {
            "trace_id": "bbbbbb",
            "run_number": 2,
            "step": 2,
            "node": "answer",
            "inputs": {"question": "How do I reset a user's Okta MFA"},
            "tool_calls": [],
            "tool_results": [],
            "stop_reason": "ANSWERED",
            "failure": "ANSWERED_OUT_OF_SCOPE",
            "latency_ms": 2,
            "run_latency_ms": 40,
        },
    ]
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    code = show_trace.main([str(path), "--failures"])
    failures = capsys.readouterr().out
    assert code == 0
    assert "ANSWERED_OUT_OF_SCOPE" in failures
    assert "Run 2 went wrong at step 2 (answer)" in failures
    assert "Run 1 went wrong" not in failures

    code = show_trace.main([str(path), "--slowest", "1"])
    slow = capsys.readouterr().out
    assert code == 0
    assert "Slowest 1" in slow
    assert "Run 2  40 ms" in slow
    assert "Run 1" not in slow


def test_show_trace_rejects_a_bad_line(tmp_path, capsys):
    path = tmp_path / "traces.jsonl"
    path.write_text("this is not json\n", encoding="utf-8")
    code = show_trace.main([str(path), "1"])
    captured = capsys.readouterr()
    assert code == 1
    assert "BAD_TRACE" in captured.out


def test_trace_flag_leaves_run_results_unchanged(tmp_path, copilot, monkeypatch, capsys):
    """--trace adds a trace file. The runs file matches a pass that did not trace."""
    agent_mod, app_mod, folder = copilot
    monkeypatch.setenv("XAI_API_KEY", SECRET)
    original_search = agent_mod.TOOLS["search_runbooks"]
    original_ask = agent_mod.ask_model
    questions = tmp_path / "questions.txt"
    questions.write_text(
        "answerable | The web server CPU is at 95 percent and pages are slow\n"
        "not_in_runbooks | How do I bake sourdough bread at home\n"
        "action | Restart the runaway worker\n",
        encoding="utf-8",
    )
    plain_dir = tmp_path / "plain"
    traced_dir = tmp_path / "traced"
    plain_dir.mkdir()
    traced_dir.mkdir()
    plain = plain_dir / "runs.jsonl"
    traced = traced_dir / "runs.jsonl"
    code = collect_runs.main([
        "--questions", str(questions),
        "--output", str(plain),
        "--copilot-path", str(folder),
    ])
    assert code == 0
    assert not (plain_dir / "traces.jsonl").exists()
    code = collect_runs.main([
        "--questions", str(questions),
        "--output", str(traced),
        "--copilot-path", str(folder),
        "--trace",
    ])
    captured = capsys.readouterr()
    assert code == 0
    # The wrappers must not stay installed after the command finishes.
    assert agent_mod.TOOLS["search_runbooks"] is original_search
    assert agent_mod.ask_model is original_ask

    rows_plain = read_jsonl(plain)
    rows_traced = read_jsonl(traced)
    assert len(rows_plain) == len(rows_traced) == 3
    for left, right in zip(rows_plain, rows_traced):
        # The clock is the only field allowed to differ.
        left = dict(left)
        right = dict(right)
        left.pop("seconds")
        right.pop("seconds")
        assert left == right

    trace_path = traced_dir / "traces.jsonl"
    blob = trace_path.read_text(encoding="utf-8") + captured.out + captured.err
    assert SECRET not in blob
    events = read_jsonl(trace_path)
    for event in events:
        assert REQUIRED <= set(event)
        json.dumps(event)
    by_run = {}
    for event in events:
        by_run.setdefault(event["run_number"], []).append(event["node"])
    assert by_run[1] == ["plan", "search", "answer"]
    assert by_run[2] == ["plan", "search", "answer"]
    assert by_run[3] == ["plan", "action", "answer"]
    answer = [event for event in events if event["run_number"] == 1 and event["node"] == "answer"][0]
    assert answer["stop_reason"] == "ANSWERED"
    assert answer["failure"] == "PARTIAL_ANSWER"
    search = [event for event in events if event["run_number"] == 1 and event["node"] == "search"][0]
    assert search["tool_results"]
    assert "score" in search["tool_results"][0]
    assert "title" in search["tool_results"][0]
    assert "text" not in search["tool_results"][0]


def test_trace_records_the_step_where_bad_tool_args_broke(tmp_path, copilot):
    agent_mod, _app, _folder = copilot
    client = scripted_client(tool_message("search_runbooks", "{"))
    output = tmp_path / "runs.jsonl"
    tracer = trace.Tracer(tmp_path / "traces.jsonl")
    written, failures = collect_runs.collect(
        [("answerable", "this call will fail")],
        output,
        client,
        agent_mod,
        tracer=tracer,
    )
    assert written == 1
    assert failures == 1
    assert read_jsonl(output)[0]["failure"] == "BAD_TOOL_ARGS"
    events = read_jsonl(tmp_path / "traces.jsonl")
    broken = [event for event in events if event.get("failure") == "BAD_TOOL_ARGS"]
    assert broken
    assert broken[0]["node"] == "plan"
    assert broken[0]["step"] == 1
    story = show_trace.format_run(events)
    assert "Went wrong at step 1 (plan)" in story
    assert "BAD_TOOL_ARGS" in story


def test_show_trace_prints_the_model_line_and_the_summary(tmp_path, capsys):
    """Token totals add the recorded counts. A missing cost is not turned into zero."""
    path = tmp_path / "traces.real.jsonl"
    rows = [
        {
            "trace_id": "aaaaaa",
            "run_number": 1,
            "step": 1,
            "node": "plan",
            "inputs": {"question": "cpu"},
            "tool_calls": [],
            "tool_results": [],
            "stop_reason": None,
            "failure": "PARTIAL_ANSWER",
            "latency_ms": 1200,
            "run_latency_ms": 1500,
            "model": "grok-build-0.1",
            "tokens_in": 100,
            "tokens_out": 20,
            "cost": 0.00014,
        },
        {
            "trace_id": "aaaaaa",
            "run_number": 1,
            "step": 2,
            "node": "answer",
            "inputs": {"question": "cpu"},
            "tool_calls": [],
            "tool_results": [],
            "stop_reason": "ANSWERED",
            "failure": "PARTIAL_ANSWER",
            "latency_ms": 300,
            "run_latency_ms": 1500,
            "model": "grok-build-0.1",
            "tokens_in": 10,
            "tokens_out": 5,
            "cost": 0.00002,
        },
        {
            "trace_id": "bbbbbb",
            "run_number": 2,
            "step": 1,
            "node": "answer",
            "inputs": {"question": "bread"},
            "tool_calls": [],
            "tool_results": [],
            "stop_reason": "NO_RELEVANT_RUNBOOK",
            "failure": None,
            "latency_ms": 500,
            "run_latency_ms": 500,
        },
        {
            "trace_id": "cccccc",
            "run_number": 3,
            "step": 1,
            "node": "answer",
            "inputs": {"question": "timeout"},
            "tool_calls": [],
            "tool_results": [],
            "stop_reason": None,
            "failure": "ModelTimeout",
            "latency_ms": 2500,
            "run_latency_ms": 2500,
            "model": "grok-build-0.1",
            "tokens_in": None,
            "tokens_out": None,
            "cost": None,
        },
    ]
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    code = show_trace.main([str(path), "1"])
    story = capsys.readouterr().out
    assert code == 0
    assert "Model: grok-build-0.1, 1.2 s, 100 in, 20 out, about $0.000140" in story
    assert "Model: grok-build-0.1, 0.3 s, 10 in, 5 out, about $0.000020" in story

    code = show_trace.main([str(path), "--summary"])
    summary = capsys.readouterr().out
    assert code == 0
    assert "Total time: 4.5 s (4500 ms)" in summary
    assert "Total tokens: 135 (110 in, 25 out)" in summary
    assert "Total estimated cost: $0.000160" in summary
    # One run, even though two steps name the same class.
    assert "PARTIAL_ANSWER  1" in summary
    assert "ModelTimeout  1" in summary
    assert "none  1" in summary


def test_retrieval_math_on_a_made_up_example():
    """Three questions. The right runbook is 1st, 6th, and missing.

    Recall at 5 only counts a hit in the first 5, so 6th is a miss.
    MRR still gives the 6th place a score of 1/6. A miss scores 0.
    """
    ranks = [1, 6, None]
    assert retrieval_score.recall_at_5(ranks) == pytest.approx(1 / 3)
    assert retrieval_score.mean_reciprocal_rank(ranks) == pytest.approx((1 + 1 / 6 + 0) / 3)

    results = [
        {"source": "other.txt", "section": "Not it"},
        {"source": "sample_runbook.txt", "section": "Disk space almost full"},
        {"source": "sample_runbook.txt", "section": "High CPU on web servers"},
    ]
    assert retrieval_score.rank_of(
        results, "sample_runbook.txt", "High CPU on web servers",
    ) == 3
    # The file is present earlier, but the section is the one we asked for.
    assert retrieval_score.rank_of(results, "sample_runbook.txt") == 2
    assert retrieval_score.rank_of(results, "missing.txt") is None
    assert retrieval_score.recall_at_5([]) == 0.0
    assert retrieval_score.mean_reciprocal_rank([]) == 0.0


def test_retrieval_gold_is_a_small_starter_set():
    """At most 8 rows, and each question really is that answerable golden question."""
    rows = retrieval_score.read_gold(retrieval_score.GOLD_FILE)
    golden = {}
    for line in (collect_runs.HERE / "golden.jsonl").read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            golden[row["id"]] = row

    assert 1 <= len(rows) <= 8
    seen = set()
    for row in rows:
        assert row["id"] not in seen
        seen.add(row["id"])
        match = golden[row["id"]]
        assert match["question"] == row["question"]
        assert match["category"] == "answerable"
        assert row["expected_runbook"].endswith(".txt")
        assert " " not in row["expected_runbook"]
