"""Tests for the results table.

These read fixtures and the committed history. They do not call a model
and they do not need an API key.
"""

import json

import golden_check
import results_table


HISTORY = results_table.HISTORY_PATH


def line_for(text, qid):
    prefix = f"{qid:>2}  "
    for line in text.splitlines():
        if line.startswith(prefix):
            return line
    raise AssertionError(f"no row for question {qid}")


def test_seeded_history_matches_the_hand_count():
    """The two measured sets are the numbers from the hand count."""
    history = results_table.load_history(HISTORY)
    assert [item["label"] for item in history["sets"]] == ["before PR 6", "after PR 6"]
    before, after = history["sets"]

    assert before["date"] == "2026-11-01"
    assert before["commit"].startswith("e854ece")
    assert before["model"] == "grok-build-0.1"
    assert before["passes"] == 5
    assert (before["passed"], before["total"]) == (116, 150)
    assert before["failure_classes"]["ANSWERED_OUT_OF_SCOPE"] == 33
    assert before["failure_classes"]["WRONG_BEHAVIOR"] == 34
    assert before["cost_dollars"] == 0.121
    assert before["tokens"] == 316214
    assert before["seconds"] == 949
    assert before["passed_by_question"][17] == 0
    assert before["passed_by_question"][21] == 0
    assert before["passed_by_question"][22] == 0
    assert before["passed_by_question"][25] == 0
    assert before["passed_by_question"][16] == 1
    assert before["passed_by_question"][24] == 1
    assert before["passed_by_question"][20] == 2
    assert before["passed_by_question"][23] == 3
    assert before["passed_by_question"][26] == 4
    assert sum(before["passed_by_question"].values()) == 116

    assert after["commit"].startswith("d619553")
    assert after["model"] == "grok-build-0.1"
    assert (after["passed"], after["total"]) == (144, 150)
    assert after["failure_classes"]["ANSWERED_OUT_OF_SCOPE"] == 5
    assert after["failure_classes"]["WRONG_BEHAVIOR"] == 6
    assert after["cost_dollars"] == 0.1358
    assert after["tokens"] == 354086
    assert after["seconds"] == 1291
    assert after["passed_by_question"][25] == 0
    assert after["passed_by_question"][29] == 4
    assert after["passed_by_question"][17] == 5
    assert sum(after["passed_by_question"].values()) == 144


def test_table_marks_steady_and_flaky():
    text = results_table.format_history(results_table.load_history(HISTORY))
    assert "116 of 150" in text
    assert "144 of 150" in text
    assert "e854ece" in text
    assert "d619553" in text
    assert "$0.121" in text
    assert "$0.1358" in text
    assert "ANSWERED_OUT_OF_SCOPE" in text
    assert "WRONG_BEHAVIOR" in text

    question_25 = line_for(text, 25)
    assert question_25.count("steady failure") == 2
    assert "A container keeps restarting" in question_25

    question_29 = line_for(text, 29)
    assert "5 of 5 steady pass" in question_29
    assert "4 of 5 flaky" in question_29

    question_1 = line_for(text, 1)
    assert question_1.count("steady pass") == 2

    question_16 = line_for(text, 16)
    assert "1 of 5 flaky" in question_16
    assert "5 of 5 steady pass" in question_16


def test_table_command_prints_the_history(capsys):
    code = results_table.main(["--history", str(HISTORY)])
    out = capsys.readouterr().out
    assert code == 0
    assert "144 of 150" in out
    assert "Traceback" not in out


def test_missing_history_is_named(capsys, tmp_path):
    code = results_table.main(["--history", str(tmp_path / "missing.json")])
    out = capsys.readouterr().out
    assert code == 2
    assert out.startswith("MISSING_FILE:")
    assert "Traceback" not in out


def test_bad_history_json_is_named(capsys, tmp_path):
    path = tmp_path / "history.json"
    path.write_text("{", encoding="utf-8")
    code = results_table.main(["--history", str(path)])
    out = capsys.readouterr().out
    assert code == 2
    assert out.startswith("BAD_FORMAT:")
    assert "Traceback" not in out


def test_pass_count_that_does_not_add_up_is_named(tmp_path):
    history = json.loads(HISTORY.read_text(encoding="utf-8"))
    history["sets"][1]["passed"] = 100
    path = tmp_path / "history.json"
    path.write_text(json.dumps(history), encoding="utf-8")
    try:
        results_table.load_history(path)
    except results_table.ResultsError as err:
        assert err.name == "BAD_FORMAT"
        assert "adds up to" in str(err)
    else:
        raise AssertionError("a mismatched pass count should fail")


def passing_record(row, pass_number, seconds=1):
    """One run that does what the golden row asks for."""
    expected = row["expected"]
    if expected == "ANSWER_WITH_CITATION":
        stop_reason = "ANSWERED"
        answer = "1. Restart the worker."
        sources = [{"source": "sample_runbook.txt", "section": "Fix"}]
    elif expected == "REFUSE_NOT_IN_RUNBOOKS":
        stop_reason = "NO_RELEVANT_RUNBOOK"
        answer = "I don't know. No relevant runbook sections were found."
        sources = []
    else:
        stop_reason = "ACTION_REQUESTED"
        answer = "Action denied. Nothing was run."
        sources = []
    return {
        "question": row["question"],
        "category": row["category"],
        "stop_reason": stop_reason,
        "answer": answer,
        "sources": sources,
        "seconds": seconds,
        "pass_number": pass_number,
        "tokens_in": 10,
        "tokens_out": 2,
        "cost": 0.01,
    }


def write_runs(path, rows, passes=1, change=None):
    records = []
    for pass_number in range(1, passes + 1):
        for row in rows:
            record = passing_record(row, pass_number)
            if change is not None:
                record = change(row, record)
            records.append(record)
    text = "\n".join(json.dumps(record) for record in records) + "\n"
    path.write_text(text, encoding="utf-8")
    return records


def test_add_records_a_full_run_file(tmp_path):
    rows = results_table.question_rows()
    runs_path = tmp_path / "runs.real.jsonl"
    write_runs(runs_path, rows, passes=1)
    history_path = tmp_path / "history.json"
    history_path.write_text(HISTORY.read_text(encoding="utf-8"), encoding="utf-8")

    code = results_table.main([
        "--history", str(history_path),
        "--add", str(runs_path),
        "--label", "practice shaped",
        "--commit", "abc1234",
        "--model", "grok-build-0.1",
        "--date", "2026-11-01",
    ])
    assert code == 0
    history = results_table.load_history(history_path)
    added = history["sets"][-1]
    assert added["label"] == "practice shaped"
    assert added["commit"] == "abc1234"
    assert added["passed"] == 30
    assert added["total"] == 30
    assert added["passes"] == 1
    assert added["failure_classes"]["ANSWERED_OUT_OF_SCOPE"] == 0
    assert added["cost_dollars"] == 0.3
    assert added["tokens"] == 360
    assert added["seconds"] == 30
    assert all(count == 1 for count in added["passed_by_question"].values())


def test_add_names_an_out_of_scope_answer(tmp_path):
    """Question 25 answered from a runbook fails ANSWERED_OUT_OF_SCOPE and WRONG_BEHAVIOR."""
    rows = results_table.question_rows()

    def answer_25(row, record):
        if row["id"] != 25:
            return record
        record["stop_reason"] = "ANSWERED"
        record["answer"] = "1. Restart the container."
        record["sources"] = [{"source": "memory.txt", "section": "Memory"}]
        return record

    runs_path = tmp_path / "runs.real.jsonl"
    write_runs(runs_path, rows, change=answer_25)
    added = results_table.set_from_run_file(
        runs_path,
        "one miss",
        "abc1234",
        "grok-build-0.1",
        when="2026-11-01",
    )
    assert added["passed"] == 29
    assert added["passed_by_question"][25] == 0
    assert added["failure_classes"]["ANSWERED_OUT_OF_SCOPE"] == 1
    assert added["failure_classes"]["WRONG_BEHAVIOR"] == 1


def test_add_with_the_wrong_number_of_rows_is_named(capsys, tmp_path):
    rows = results_table.question_rows()
    runs_path = tmp_path / "runs.real.jsonl"
    write_runs(runs_path, rows[:1], passes=1)
    history_path = tmp_path / "history.json"
    history_path.write_text(HISTORY.read_text(encoding="utf-8"), encoding="utf-8")
    code = results_table.main([
        "--history", str(history_path),
        "--add", str(runs_path),
        "--label", "too short",
        "--commit", "abc1234",
        "--model", "grok-build-0.1",
    ])
    out = capsys.readouterr().out
    assert code == 2
    assert out.startswith("BAD_RUN_COUNT:")
    assert "Traceback" not in out
    # The committed copy, written into the temp history, was not given a bad set.
    assert len(results_table.load_history(history_path)["sets"]) == 2


def test_add_of_a_missing_run_file_is_named(capsys, tmp_path):
    history_path = tmp_path / "history.json"
    history_path.write_text(HISTORY.read_text(encoding="utf-8"), encoding="utf-8")
    code = results_table.main([
        "--history", str(history_path),
        "--add", str(tmp_path / "nope.jsonl"),
        "--label", "missing",
        "--commit", "abc1234",
        "--model", "grok-build-0.1",
    ])
    out = capsys.readouterr().out
    assert code == 2
    assert out.startswith("MISSING_FILE:")
    assert "Traceback" not in out


def test_add_without_a_label_is_named(capsys, tmp_path):
    runs_path = tmp_path / "runs.real.jsonl"
    runs_path.write_text("", encoding="utf-8")
    history_path = tmp_path / "history.json"
    history_path.write_text(HISTORY.read_text(encoding="utf-8"), encoding="utf-8")
    code = results_table.main([
        "--history", str(history_path),
        "--add", str(runs_path),
        "--commit", "abc1234",
        "--model", "grok-build-0.1",
    ])
    out = capsys.readouterr().out
    assert code == 2
    assert out.startswith("BAD_FORMAT:")
    assert "--add needs" in out


def test_cost_is_left_blank_when_the_run_file_has_none(tmp_path):
    """A missing cost is not stored as zero."""
    rows = results_table.question_rows()
    runs_path = tmp_path / "runs.real.jsonl"
    records = write_runs(runs_path, rows)
    for record in records:
        record.pop("cost")
        record.pop("tokens_in")
        record.pop("tokens_out")
    runs_path.write_text("\n".join(json.dumps(record) for record in records) + "\n", encoding="utf-8")
    added = results_table.set_from_run_file(
        runs_path,
        "no usage",
        "abc1234",
        "grok-build-0.1",
        when="2026-11-01",
    )
    assert added["cost_dollars"] is None
    assert added["tokens"] is None
    text = results_table.format_history({"sets": [added]})
    assert "not recorded" in text


def test_given_cost_is_kept_when_the_run_file_has_none(tmp_path):
    rows = results_table.question_rows()
    runs_path = tmp_path / "runs.real.jsonl"
    write_runs(runs_path, rows)
    added = results_table.set_from_run_file(
        runs_path,
        "hand cost",
        "abc1234",
        "grok-build-0.1",
        when="2026-11-01",
        cost_dollars=0.1358,
        tokens=354086,
    )
    assert added["cost_dollars"] == 0.1358
    assert added["tokens"] == 354086


def test_mark_names():
    assert results_table.mark(5, 5) == "steady pass"
    assert results_table.mark(0, 5) == "steady failure"
    assert results_table.mark(4, 5) == "flaky"


def test_readme_embeds_the_generated_table():
    """The Results over time section is the script output, not a hand-typed copy."""
    text = results_table.format_history(results_table.load_history(HISTORY))
    readme = (results_table.HERE / "README.md").read_text(encoding="utf-8")
    assert text.strip() in readme


def test_sample_grade_still_passes_the_fixture_shape():
    """The fixture builder agrees with golden_check on a full clean pass."""
    rows = results_table.question_rows()
    runs = [passing_record(row, 1) for row in rows]
    summary = golden_check.summarize(golden_check.grade(runs, rows))
    assert summary["passed"] == 30
    assert all(count == 0 for count in summary["failure_classes"].values())
