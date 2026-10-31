"""Tests for the LLM judge.

Every test uses FakeJudge, or a stand-in that never touches the network.
No real model is called. No real API key is read.
"""

import json
from pathlib import Path

import httpx
import pytest

import golden_check
import judge
import judge_agreement


ROOT = Path(__file__).resolve().parent.parent
SAMPLE = ROOT / "runs.sample.jsonl"

FAKE_KEY = "fake-key-for-tests-only"


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """Block the real API for every test in this file."""
    monkeypatch.delenv("XAI_API_KEY", raising=False)

    def boom(*args, **kwargs):
        raise AssertionError("this test tried to call the network")

    monkeypatch.setattr(judge.httpx, "post", boom)


def load():
    golden = golden_check.index_golden(golden_check.read_golden(ROOT / "golden.jsonl"))
    labels = judge.read_hand_labels(ROOT / "labels.md")
    return golden, labels


def bread_run():
    """A refusal the code checks do not flag. Hand label in labels.md is pass."""
    return {
        "question": "How do I bake sourdough bread at home",
        "category": "not_in_runbooks",
        "stop_reason": "NO_RELEVANT_RUNBOOK",
        "answer": "I don't know. No relevant runbook sections were found, so I will not guess.",
        "sources": [],
    }


def cpu_run():
    """A symptom-only answer. The code checks flag it as PARTIAL_ANSWER."""
    return {
        "question": "The web server CPU is at 95 percent and pages are slow",
        "category": "answerable",
        "stop_reason": "ANSWERED",
        "answer": "1. Symptom: web servers show CPU above ninety percent and response times climb.",
        "sources": [{"source": "sample_runbook.txt", "section": "High CPU on web servers"}],
    }


def coredns_run():
    """An answer with a fix step and a source. The code checks leave it alone."""
    return {
        "question": "CoreDNS logs show read udp i/o timeout and pods fail name lookups",
        "category": "answerable",
        "stop_reason": "ANSWERED",
        "answer": "1. Restart CoreDNS.\n2. Check the upstream DNS server.",
        "sources": [{"source": "incident_coredns.txt", "section": "Read timeout"}],
    }


def write_runs(path, records):
    lines = [json.dumps(record) for record in records]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_labels_file_has_the_practice_rows():
    labels = judge.read_hand_labels(ROOT / "labels.md")
    assert len(labels) == 30
    assert labels[15]["label"] == "pass"
    assert labels[10]["label"] == "unreviewed"
    assert labels[22]["label"] == "WRONG_RUNBOOK_CITED"
    assert labels[30]["label"] == "WRONGLY_REFUSED"


def test_parse_keeps_a_good_label():
    got = judge.parse_verdict(
        '{"label": "PASS", "reason": "The copilot said it does not know."}'
    )
    assert got["label"] == "PASS"
    assert got["reason"] == "The copilot said it does not know."
    assert got["raw"] is None


def test_parse_peels_a_fence_and_extra_words():
    fenced = '```json\n{"label": "ANSWERED_WRONGLY", "reason": "The steps are not in the runbook."}\n```'
    extra = 'Sure.\n{"label": "RAMBLING_OR_PASTED_TEXT", "reason": "It pasted the page."}\nThanks.'
    assert judge.parse_verdict(fenced)["label"] == "ANSWERED_WRONGLY"
    assert judge.parse_verdict(extra)["label"] == "RAMBLING_OR_PASTED_TEXT"


def test_bad_json_is_named_and_keeps_the_raw_text():
    raw = "I think this is a pass"
    got = judge.parse_verdict(raw)
    assert got["label"] == "JUDGE_BAD_JSON"
    assert got["raw"] == raw
    assert got["label"] != "PASS"


def test_a_label_outside_the_rubric_is_bad_json():
    """PARTIAL_ANSWER is a code check. The judge is not allowed to return it."""
    got = judge.parse_verdict('{"label": "PARTIAL_ANSWER", "reason": "Missing a step."}')
    assert got["label"] == "JUDGE_BAD_JSON"
    assert "PARTIAL_ANSWER" in got["raw"]


def test_lowercase_pass_from_the_model_is_bad_json():
    """The model must say PASS. The word pass in labels.md is a hand label, not this."""
    got = judge.parse_verdict('{"label": "pass", "reason": "It fits."}')
    assert got["label"] == "JUDGE_BAD_JSON"


def test_json_without_a_reason_is_bad_json():
    got = judge.parse_verdict('{"label": "PASS"}')
    assert got["label"] == "JUDGE_BAD_JSON"
    empty = judge.parse_verdict('{"label": "PASS", "reason": "  "}')
    assert empty["label"] == "JUDGE_BAD_JSON"


def test_prompt_has_the_case_and_the_rubric_but_not_the_hand_label():
    golden, _labels = load()
    record = coredns_run()
    prompt = judge.build_prompt(record, golden[record["question"]])
    assert record["question"] in prompt
    assert record["answer"] in prompt
    assert "ANSWERED" in prompt
    assert "incident_coredns.txt" in prompt
    assert "Read timeout" in prompt
    assert "ANSWER_WITH_CITATION" in prompt
    assert "answer and cite a runbook" in prompt
    assert "CoreDNS read timeouts" in prompt
    for name in judge.JUDGE_LABELS:
        assert name in prompt
        assert judge.RUBRIC[name] in prompt
    # The hand label for this run is unreviewed. The model must not see it.
    assert "unreviewed" not in prompt
    assert "Likely pass" not in prompt


def test_prompt_for_a_refusal_names_the_stop_reason_and_no_sources():
    golden, _labels = load()
    record = bread_run()
    prompt = judge.build_prompt(record, golden[record["question"]])
    assert record["question"] in prompt
    assert record["answer"] in prompt
    assert "NO_RELEVANT_RUNBOOK" in prompt
    assert "REFUSE_NOT_IN_RUNBOOKS" in prompt
    assert "(none)" in prompt
    assert "Said it does not know." not in prompt


def test_code_flagged_runs_are_skipped_and_the_judge_is_not_called():
    golden, labels = load()
    client = judge.FakeJudge('{"label": "PASS", "reason": "Looks fine."}')
    results = judge.judge_runs(
        [cpu_run(), bread_run()],
        client,
        golden,
        labels,
        only_unflagged=True,
    )
    assert results[0]["skipped"] is True
    assert results[0]["code_flags"] == ["PARTIAL_ANSWER"]
    assert results[0]["label"] is None
    assert results[1]["skipped"] is False
    assert results[1]["label"] == "PASS"
    assert len(client.prompts) == 1
    assert "sourdough" in client.prompts[0]


def test_no_only_unflagged_grades_a_flagged_run():
    golden, labels = load()
    client = judge.FakeJudge('{"label": "PASS", "reason": "Looks fine."}')
    results = judge.judge_runs(
        [cpu_run()],
        client,
        golden,
        labels,
        only_unflagged=False,
    )
    assert results[0]["skipped"] is False
    assert results[0]["code_flags"] == ["PARTIAL_ANSWER"]
    assert len(client.prompts) == 1


def test_bad_json_from_the_client_does_not_crash():
    golden, labels = load()
    raw = "this is not json"
    client = judge.FakeJudge(raw)
    results = judge.judge_runs([bread_run()], client, golden, labels)
    assert results[0]["label"] == "JUDGE_BAD_JSON"
    assert results[0]["raw"] == raw
    assert results[0]["flaky"] is False


def test_passes_flag_reports_when_the_judge_disagrees_with_itself(tmp_path, capsys):
    path = tmp_path / "runs.jsonl"
    out = tmp_path / "judge_results.jsonl"
    write_runs(path, [bread_run()])
    client = judge.FakeJudge([
        '{"label": "PASS", "reason": "It refused."}',
        '{"label": "WRONGLY_REFUSED", "reason": "A runbook covers this."}',
    ])
    code = judge.main(
        [str(path), "--passes", "2", "--output", str(out)],
        client=client,
    )
    assert code == 0
    text = capsys.readouterr().out
    assert "disagreed with itself" in text
    assert "PASS" in text
    assert "WRONGLY_REFUSED" in text
    saved = json.loads(out.read_text(encoding="utf-8").splitlines()[0])
    assert saved["flaky"] is True
    assert [item["label"] for item in saved["passes"]] == ["PASS", "WRONGLY_REFUSED"]
    assert client.prompts[0] == client.prompts[1]
    assert FAKE_KEY not in text
    assert FAKE_KEY not in out.read_text(encoding="utf-8")


def test_stable_passes_are_not_flaky(tmp_path, capsys):
    path = tmp_path / "runs.jsonl"
    out = tmp_path / "judge_results.jsonl"
    write_runs(path, [bread_run()])
    reply = '{"label": "PASS", "reason": "It refused."}'
    code = judge.main(
        [str(path), "--passes", "2", "--output", str(out)],
        client=judge.FakeJudge([reply, reply]),
    )
    assert code == 0
    assert "agreed with itself" in capsys.readouterr().out
    saved = json.loads(out.read_text(encoding="utf-8").splitlines()[0])
    assert saved["flaky"] is False


def test_fake_flag_needs_no_key_and_is_not_a_grade(tmp_path, capsys):
    path = tmp_path / "runs.jsonl"
    out = tmp_path / "judge_results.jsonl"
    write_runs(path, [bread_run()])
    code = judge.main([str(path), "--fake", "--output", str(out)])
    assert code == 0
    saved = json.loads(out.read_text(encoding="utf-8").splitlines()[0])
    assert saved["label"] == "PASS"
    assert "not a real grade" in saved["reason"]
    assert "Fake judge" in capsys.readouterr().out


def test_sample_file_skips_flagged_runs_and_writes_a_table(tmp_path, capsys):
    out = tmp_path / "judge_results.jsonl"
    code = judge.main([str(SAMPLE), "--fake", "--output", str(out)])
    assert code == 0
    text = capsys.readouterr().out
    rows = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 9
    skipped = [row for row in rows if row["skipped"]]
    graded = [row for row in rows if not row["skipped"]]
    assert len(skipped) == 5
    assert len(graded) == 4
    assert {row["id"] for row in graded} == {15, 26, 27, 30}
    assert all(row["label"] == "PASS" for row in graded)
    assert "skipped" in text
    assert "PASS" in text
    assert f"Wrote {out}" in text


def test_missing_key_is_named_and_does_not_call_the_network():
    with pytest.raises(judge.MissingKey) as caught:
        judge.XaiJudge().complete("hello")
    message = str(caught.value)
    assert message.startswith("MissingKey:")
    assert "XAI_API_KEY" in message
    assert FAKE_KEY not in message


def test_a_blank_key_is_still_missing(monkeypatch):
    monkeypatch.setenv("XAI_API_KEY", "   ")
    with pytest.raises(judge.MissingKey):
        judge.XaiJudge().complete("hello")


def test_cli_missing_key_exits_and_writes_nothing(tmp_path, capsys):
    path = tmp_path / "runs.jsonl"
    out = tmp_path / "judge_results.jsonl"
    write_runs(path, [bread_run()])
    code = judge.main([str(path), "--output", str(out)])
    assert code == 2
    assert capsys.readouterr().out.startswith("MissingKey:")
    assert not out.exists()


def test_model_name_defaults_to_grok_4_and_can_be_changed(monkeypatch):
    monkeypatch.delenv("JUDGE_MODEL", raising=False)
    assert judge.XaiJudge().model == "grok-4"
    monkeypatch.setenv("JUDGE_MODEL", "grok-4-mini")
    assert judge.XaiJudge().model == "grok-4-mini"


def test_request_body_uses_temperature_zero_and_has_no_key():
    body = judge.request_body("grade this", "grok-4")
    assert body["temperature"] == 0
    assert body["model"] == "grok-4"
    assert body["messages"][1]["content"] == "grade this"
    assert FAKE_KEY not in json.dumps(body)


def test_http_error_hides_the_key(monkeypatch):
    monkeypatch.setenv("XAI_API_KEY", FAKE_KEY)
    seen = {}

    def fake_post(*args, **kwargs):
        seen["url"] = args[0]
        seen["body"] = kwargs["json"]
        seen["timeout"] = kwargs["timeout"]
        seen["follow_redirects"] = kwargs["follow_redirects"]
        seen["auth"] = kwargs["headers"]["Authorization"]

        class Response:
            status_code = 401
            text = "unauthorized " + FAKE_KEY

        return Response()

    monkeypatch.setattr(judge.httpx, "post", fake_post)
    with pytest.raises(judge.JudgeHttpError) as caught:
        judge.XaiJudge().complete("grade this")
    message = str(caught.value)
    assert message.startswith("JudgeHttpError:")
    assert "401" in message
    assert FAKE_KEY not in message
    assert seen["url"] == judge.API_URL
    assert seen["body"]["temperature"] == 0
    assert seen["timeout"] == judge.DEFAULT_TIMEOUT
    assert seen["follow_redirects"] is False
    assert FAKE_KEY not in json.dumps(seen["body"])
    assert seen["auth"] == "Bearer " + FAKE_KEY


def test_timeout_is_named_and_hides_the_key(monkeypatch):
    monkeypatch.setenv("XAI_API_KEY", FAKE_KEY)

    def fake_post(*args, **kwargs):
        raise httpx.TimeoutException("timed out calling " + FAKE_KEY)

    monkeypatch.setattr(judge.httpx, "post", fake_post)
    with pytest.raises(judge.JudgeTimeout) as caught:
        judge.XaiJudge().complete("grade this")
    message = str(caught.value)
    assert message.startswith("JudgeTimeout:")
    assert "timed out" in message
    assert FAKE_KEY not in message


def test_a_reply_that_contains_the_key_is_scrubbed(monkeypatch):
    monkeypatch.setenv("XAI_API_KEY", FAKE_KEY)

    def fake_post(*args, **kwargs):
        class Response:
            status_code = 200
            text = ""

            def json(self):
                return {"choices": [{"message": {"content": "leaked " + FAKE_KEY}}]}

        return Response()

    monkeypatch.setattr(judge.httpx, "post", fake_post)
    text = judge.XaiJudge().complete("hi")
    assert FAKE_KEY not in text
    assert "[key hidden]" in text


def verdict(run_id, label, reason, skipped=False, hand_label="should-be-ignored", flaky=False):
    golden, _labels = load()
    question = next(row["question"] for row in golden.values() if row["id"] == run_id)
    return {
        "line": 1,
        "id": run_id,
        "question": question,
        "hand_label": hand_label,
        "skipped": skipped,
        "label": label,
        "reason": reason,
        "flaky": flaky,
    }


def test_agreement_counts_matches_and_lists_disagreements(tmp_path, capsys):
    path = tmp_path / "judge_results.jsonl"
    rows = [
        verdict(18, "PASS", "It refused."),
        verdict(30, "WRONGLY_REFUSED", "A runbook covers the rollback."),
        verdict(15, "WRONGLY_REFUSED", "It should have answered."),
        verdict(10, "PASS", "Looks fine."),
        verdict(1, None, "Skipped.", skipped=True),
    ]
    write_runs(path, rows)
    code = judge_agreement.main([str(path)])
    assert code == 0
    text = capsys.readouterr().out
    assert "2 of 3 agree." in text
    assert "run 15:" in text
    assert "hand label pass" in text
    assert "Judge said WRONGLY_REFUSED" in text
    assert "1 run was skipped" in text
    assert "1 run is still unreviewed" in text
    assert judge_agreement.NOTE in text
    assert "labels.md" in text


def test_hand_labels_in_the_file_do_not_override_labels_md(tmp_path, capsys):
    """The saved hand_label is wrong on purpose. labels.md still wins."""
    path = tmp_path / "judge_results.jsonl"
    write_runs(path, [
        verdict(15, "PASS", "It refused.", hand_label="WRONG_RUNBOOK_CITED"),
    ])
    code = judge_agreement.main([str(path)])
    assert code == 0
    text = capsys.readouterr().out
    assert "1 of 1 agree." in text
    assert "No disagreements." in text
    assert judge_agreement.NOTE in text


def test_bad_json_is_a_disagreement_not_a_pass(tmp_path, capsys):
    path = tmp_path / "judge_results.jsonl"
    write_runs(path, [
        verdict(15, "JUDGE_BAD_JSON", "The judge did not return JSON with a label and a reason."),
    ])
    code = judge_agreement.main([str(path)])
    assert code == 0
    text = capsys.readouterr().out
    assert "0 of 1 agree." in text
    assert "JUDGE_BAD_JSON" in text
    assert "No disagreements." not in text


def test_sample_fake_judge_agreement(tmp_path, capsys):
    """The fake judge says PASS. The hand label on run 30 does not."""
    out = tmp_path / "judge_results.jsonl"
    code = judge.main([str(SAMPLE), "--fake", "--output", str(out)])
    assert code == 0
    capsys.readouterr()
    code = judge_agreement.main([str(out)])
    assert code == 0
    text = capsys.readouterr().out
    assert "3 of 4 agree." in text
    assert "run 30:" in text
    assert "WRONGLY_REFUSED" in text
    assert "5 runs were skipped" in text
    assert judge_agreement.NOTE in text
