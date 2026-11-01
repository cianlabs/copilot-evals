"""Tests for the regression check.

The failure cases use small copies of the history. They do not call a
model. One test runs the practice model, the same way the golden
baseline test does. That model stays on this machine and needs no key.
"""

import json

import pytest

import golden_check
import regression_check
import results_table


def history_and_floor():
    history = results_table.load_history(results_table.HISTORY_PATH)
    floor = regression_check.load_floor(regression_check.FLOOR_PATH)
    return history, floor


def test_seeded_history_meets_the_floor():
    """Question 29 fails 1 of 5. That is flaky, so the seeded sets pass.

    Question 25 fails every pass and is on the known-failure list.
    """
    history, floor = history_and_floor()
    assert floor["passed"] == 144
    assert floor["total"] == 150
    assert floor["max_answered_out_of_scope"] == 5
    assert floor["known_failures"] == [25]
    assert regression_check.find_regressions(history, floor) == []


def names(problems):
    return [problem.name for problem in problems]


def test_pass_count_below_the_floor_is_named():
    history, floor = history_and_floor()
    history["sets"][-1]["passed"] = 143
    problems = regression_check.find_regressions(history, floor)
    assert names(problems) == ["BELOW_FLOOR"]
    message = str(problems[0])
    assert message.startswith("BELOW_FLOOR:")
    assert "143 of 150" in message
    assert "144 of 150" in message
    assert "Traceback" not in message


def test_too_many_out_of_scope_answers_is_named():
    history, floor = history_and_floor()
    history["sets"][-1]["failure_classes"]["ANSWERED_OUT_OF_SCOPE"] = 6
    problems = regression_check.find_regressions(history, floor)
    assert names(problems) == ["TOO_MANY_OUT_OF_SCOPE"]
    message = str(problems[0])
    assert message.startswith("TOO_MANY_OUT_OF_SCOPE:")
    assert "ANSWERED_OUT_OF_SCOPE" in message
    assert "6" in message
    assert "at most 5" in message


def test_a_steady_pass_that_fails_every_time_is_named():
    history, floor = history_and_floor()
    latest = history["sets"][-1]
    latest["passed_by_question"][1] = 0
    # Keep the floor from also firing, so this case is only the steady-pass rule.
    floor["passed"] = 0
    floor["max_answered_out_of_scope"] = 100
    problems = regression_check.find_regressions(history, floor)
    assert names(problems) == ["STEADY_PASS_NOW_FAILS"]
    message = str(problems[0])
    assert message.startswith("STEADY_PASS_NOW_FAILS:")
    assert "Question 1" in message
    assert "before PR 6" in message
    assert "after PR 6" in message


def test_a_single_miss_on_a_steady_pass_is_flaky_and_allowed():
    """4 of 5 is flaky. The floor still has to be met, but this rule stays quiet."""
    history, floor = history_and_floor()
    latest = history["sets"][-1]
    latest["passed_by_question"][1] = 4
    floor["passed"] = 0
    floor["max_answered_out_of_scope"] = 100
    assert regression_check.find_regressions(history, floor) == []


def test_a_known_failure_may_fail_every_pass():
    previous = {qid: 5 for qid in range(1, 31)}
    latest = {qid: 5 for qid in range(1, 31)}
    latest[25] = 0
    classes = {name: 0 for name in golden_check.FAILURE_CLASSES}
    before = {
        "label": "earlier",
        "passes": 5,
        "passed_by_question": previous,
        "failure_classes": dict(classes),
    }
    after = {
        "label": "later",
        "passes": 5,
        "passed_by_question": latest,
        "failure_classes": dict(classes),
    }
    allowed = regression_check.compare_with_previous(after, before, [25])
    assert allowed == []
    blocked = regression_check.compare_with_previous(after, before, [])
    assert names(blocked) == ["STEADY_PASS_NOW_FAILS"]
    assert "Question 25" in str(blocked[0])


def test_a_new_failure_class_is_named():
    history, floor = history_and_floor()
    history["sets"][-1]["failure_classes"]["GAVE_UP_AT_STEP_LIMIT"] = 2
    problems = regression_check.find_regressions(history, floor)
    assert names(problems) == ["NEW_FAILURE_CLASS"]
    message = str(problems[0])
    assert message.startswith("NEW_FAILURE_CLASS:")
    assert "GAVE_UP_AT_STEP_LIMIT" in message
    assert "Traceback" not in message


def test_a_class_that_was_already_present_can_change_count():
    """WRONG_BEHAVIOR is in both seeded sets. A higher count is not a new class."""
    history, floor = history_and_floor()
    history["sets"][-1]["failure_classes"]["WRONG_BEHAVIOR"] = 20
    floor["passed"] = 0
    assert regression_check.find_regressions(history, floor) == []


def test_raising_the_floor_above_the_latest_set_fails():
    """The floor file is what the check reads. A higher number is a harder line."""
    history, floor = history_and_floor()
    floor["passed"] = 145
    problems = regression_check.find_regressions(history, floor)
    assert names(problems) == ["BELOW_FLOOR"]
    assert "145 of 150" in str(problems[0])


def test_missing_floor_file_is_named(capsys, tmp_path):
    code = regression_check.main([
        "--history", str(results_table.HISTORY_PATH),
        "--floor", str(tmp_path / "missing.json"),
    ])
    out = capsys.readouterr().out
    assert code == 2
    assert out.startswith("MISSING_FILE:")
    assert "Traceback" not in out


def test_bad_floor_file_is_named(capsys, tmp_path):
    path = tmp_path / "floor.json"
    path.write_text("[]", encoding="utf-8")
    code = regression_check.main([
        "--history", str(results_table.HISTORY_PATH),
        "--floor", str(path),
    ])
    out = capsys.readouterr().out
    assert code == 2
    assert out.startswith("BAD_FORMAT:")
    assert "Traceback" not in out


def test_a_run_set_with_the_wrong_size_is_named():
    history, floor = history_and_floor()
    history["sets"][-1]["total"] = 90
    with pytest.raises(results_table.ResultsError) as caught:
        regression_check.find_regressions(history, floor)
    assert caught.value.name == "BAD_RUN_COUNT"
    assert "90" in str(caught.value)
    assert "150" in str(caught.value)


def test_practice_baseline_holds_and_does_not_call_the_real_client(monkeypatch):
    """The practice check uses DemoClient. A real client call would fail this test."""

    def boom(*_args, **_kwargs):
        raise AssertionError("the regression check tried to call the real model")

    monkeypatch.setenv("XAI_API_KEY", "this-is-not-a-real-key")
    monkeypatch.setattr("collect_runs.make_client", boom)
    practice = regression_check.check_practice_baseline()
    assert practice["problems"] == []
    assert practice["passed"] == 8
    assert practice["total"] == 30
    assert practice["sample_passed"] == 3
    assert practice["sample_total"] == 9


def test_command_passes_on_the_seeded_files(capsys):
    code = regression_check.main([])
    out = capsys.readouterr().out
    assert code == 0, out
    assert "Recorded runs held." in out
    assert "144 of 150" in out
    assert "8 of 30" in out
    assert "Traceback" not in out


def test_command_prints_a_named_regression(capsys, tmp_path):
    history = json.loads(results_table.HISTORY_PATH.read_text(encoding="utf-8"))
    # 4 fewer passes on question 1, which is then flaky (1 of 5), not a steady failure.
    history["sets"][-1]["passed"] = 140
    history["sets"][-1]["passed_by_question"]["1"] = 1
    history_path = tmp_path / "history.json"
    history_path.write_text(json.dumps(history), encoding="utf-8")
    code = regression_check.main([
        "--history", str(history_path),
        "--floor", str(regression_check.FLOOR_PATH),
    ])
    out = capsys.readouterr().out
    assert code == 1
    assert out.startswith("BELOW_FLOOR:")
    assert "Traceback" not in out
