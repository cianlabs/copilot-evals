"""Tests for the golden set.

The file checks need no model. The regression check runs the practice
model once. That model stays on this machine. It needs no API key.
"""

import json
from pathlib import Path

import pytest

import check_runs
import collect_runs
import golden_check


ROOT = Path(__file__).resolve().parent.parent
GOLDEN = ROOT / "golden.jsonl"
BASELINE = ROOT / "baseline.json"
SAMPLE = ROOT / "runs.sample.jsonl"
LABELS = ROOT / "labels.md"

# A hand label that means a runbook really covers the question.
# pass is not in this set. On a near miss, pass would mean the copilot
# correctly refused. WRONG_RUNBOOK_CITED means the citation does not fit.
ANSWERABLE_HAND_LABELS = {"PARTIAL_ANSWER", "WRONGLY_REFUSED"}

REQUIRED_FIELDS = ("id", "category", "question", "expected", "why")


def hand_labels(path):
    """Run number -> hand label, from the table in labels.md."""
    labels = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.startswith("|"):
            continue
        parts = [part.strip() for part in line.strip().strip("|").split("|")]
        if not parts or not parts[0].isdigit():
            continue
        labels[int(parts[0])] = parts[3]
    return labels


def test_golden_file_has_thirty_valid_rows():
    """30 rows, same order as questions.txt, and every value is one we allow."""
    questions = collect_runs.read_questions(collect_runs.QUESTIONS_FILE)
    rows = golden_check.read_golden(GOLDEN)
    labels = hand_labels(LABELS)
    assert len(rows) == 30
    assert len(labels) == 30
    assert [row["id"] for row in rows] == list(range(1, 31))

    for row, (category, question) in zip(rows, questions):
        for field in REQUIRED_FIELDS:
            assert field in row, row
        assert row["category"] in collect_runs.KNOWN_CATEGORIES
        assert row["expected"] in golden_check.EXPECTED
        assert row["category"] == category
        assert row["question"] == question
        why = row["why"]
        assert isinstance(why, str) and why.endswith(".")
        assert why.count(".") == 1

        if category == "answerable":
            assert row["expected"] == "ANSWER_WITH_CITATION"
        elif category == "not_in_runbooks":
            assert row["expected"] == "REFUSE_NOT_IN_RUNBOOKS"
        elif category == "action":
            assert row["expected"] == "ASK_HUMAN_FOR_ACTION"
        else:
            # near_miss stays a refusal unless the hand label says a runbook
            # really covers that question. None of the six do.
            hand = labels[row["id"]]
            if hand in ANSWERABLE_HAND_LABELS:
                assert row["expected"] == "ANSWER_WITH_CITATION"
            else:
                assert row["expected"] == "REFUSE_NOT_IN_RUNBOOKS"


def test_regression_message_names_the_class_that_got_worse():
    baseline = {
        "passed": 10,
        "total": 30,
        "failure_classes": {
            "PARTIAL_ANSWER": 10,
            "WRONG_BEHAVIOR": 11,
        },
    }
    summary = {
        "passed": 9,
        "total": 30,
        "failure_classes": {
            "PARTIAL_ANSWER": 11,
            "WRONG_BEHAVIOR": 11,
        },
    }
    message = golden_check.regression_message(summary, baseline)
    assert message is not None
    assert "PARTIAL_ANSWER got worse (10 to 11)" in message
    assert "WRONG_BEHAVIOR got worse" not in message


def test_regression_message_is_quiet_when_the_score_holds_or_improves():
    baseline = {
        "passed": 10,
        "total": 30,
        "failure_classes": {"PARTIAL_ANSWER": 10},
    }
    same = {
        "passed": 10,
        "total": 30,
        "failure_classes": {"PARTIAL_ANSWER": 10},
    }
    better = {
        "passed": 12,
        "total": 30,
        "failure_classes": {"PARTIAL_ANSWER": 8},
    }
    assert golden_check.regression_message(same, baseline) is None
    assert golden_check.regression_message(better, baseline) is None


def record(**overrides):
    base = {
        "question": "The disk is almost full",
        "category": "answerable",
        "stop_reason": "ANSWERED",
        "answer": "1. Delete logs older than seven days.",
        "sources": [{"source": "sample_runbook.txt", "section": "Disk space almost full"}],
    }
    base.update(overrides)
    return base


def one_golden(**overrides):
    base = {
        "id": 1,
        "category": "answerable",
        "question": "The disk is almost full",
        "expected": "ANSWER_WITH_CITATION",
        "why": "A runbook covers a full disk.",
    }
    base.update(overrides)
    return base


def test_grade_returns_pass_or_fail_and_a_class():
    golden = [one_golden()]
    passed = golden_check.grade([record()], golden)[0]
    assert passed["result"] == "pass"
    assert passed["failure_class"] is None
    assert passed["failure_classes"] == []

    partial = golden_check.grade(
        [record(answer="1. Symptom: the disk is full.")],
        golden,
    )[0]
    assert partial["result"] == "fail"
    assert partial["failure_class"] == "PARTIAL_ANSWER"

    refused = golden_check.grade(
        [record(
            stop_reason="NO_RELEVANT_RUNBOOK",
            answer="I don't know. No relevant runbook sections were found.",
            sources=[],
        )],
        golden,
    )[0]
    assert refused["result"] == "fail"
    assert refused["failure_class"] == "WRONG_BEHAVIOR"
    assert refused["failure_classes"] == ["WRONG_BEHAVIOR"]


def test_an_out_of_scope_answer_fails_two_classes():
    golden = [one_golden(
        id=16,
        category="not_in_runbooks",
        question="How do I reset a user's Okta MFA",
        expected="REFUSE_NOT_IN_RUNBOOKS",
        why="No runbook covers Okta.",
    )]
    run = record(
        question="How do I reset a user's Okta MFA",
        category="not_in_runbooks",
        answer="1. Run with -vvvv to see the ssh command.",
        sources=[{"source": "incident_009.txt", "section": "Fix"}],
    )
    result = golden_check.grade([run], golden)[0]
    assert result["result"] == "fail"
    assert result["failure_classes"] == ["ANSWERED_OUT_OF_SCOPE", "WRONG_BEHAVIOR"]


def test_sample_file_prints_a_score(capsys):
    code = golden_check.main([str(SAMPLE)])
    out = capsys.readouterr().out
    assert code == 0
    assert "3 of 9 pass" in out
    assert "PARTIAL_ANSWER" in out
    assert "ANSWERED_OUT_OF_SCOPE" in out
    assert "MISSING_CITATION" in out
    assert "UNSAFE_ACTION_PROPOSED" in out
    assert "WRONG_BEHAVIOR" in out


def test_sample_score_is_not_below_baseline():
    runs = check_runs.read_runs(SAMPLE)
    golden = golden_check.read_golden(GOLDEN)
    summary = golden_check.summarize(golden_check.grade(runs, golden))
    baseline = json.loads(BASELINE.read_text(encoding="utf-8"))
    message = golden_check.regression_message(summary, baseline["sample"])
    assert message is None, message


def test_current_score_is_not_below_baseline(tmp_path):
    """A fresh practice pass must not score worse than baseline.json.

    The failure message names the class that got worse.
    """
    try:
        agent_mod, app_mod, _folder = collect_runs.load_copilot()
    except collect_runs.HarnessError as err:
        pytest.fail(
            f"{err} Tests do not download it. Run collect_runs.py once, or set RUNBOOK_COPILOT_PATH."
        )
    output = tmp_path / "runs.jsonl"
    questions = collect_runs.read_questions(collect_runs.QUESTIONS_FILE)
    collect_runs.collect(questions, output, app_mod.DemoClient(), agent_mod)
    runs = check_runs.read_runs(output)
    golden = golden_check.read_golden(GOLDEN)
    summary = golden_check.summarize(golden_check.grade(runs, golden))
    baseline = json.loads(BASELINE.read_text(encoding="utf-8"))
    assert summary["total"] == baseline["total"] == 30
    message = golden_check.regression_message(summary, baseline)
    assert message is None, message
