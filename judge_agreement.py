#!/usr/bin/env python3
"""Compare judge results to the hand labels in labels.md.

The hand labels are the truth. When the judge disagrees, the hand label
wins. This command does not call a model.

    python3 judge_agreement.py judge_results.jsonl

It prints how many graded runs agree, the list of disagreements, and a
short note. Runs the judge skipped are not part of the count. Rows still
marked unreviewed in labels.md are not part of the count either.
"""

import argparse
import sys

import check_runs
import checks
import golden_check
import judge


# Printed at the end of every report. Hand labels win.
NOTE = (
    "The judge can be wrong. When the judge and the hand label disagree, "
    "the hand label in labels.md is the truth. Check this report before you trust the judge."
)


def labels_agree(hand, judged):
    """True when the judge label matches the hand label.

    labels.md writes a pass as "pass". The judge writes "PASS".
    Those two mean the same thing. Every other name must match exactly.
    """
    if not isinstance(hand, str) or not isinstance(judged, str):
        return False
    left = hand.strip()
    right = judged.strip()
    if left.casefold() == "pass" and right == "PASS":
        return True
    return left == right


def is_unreviewed(hand):
    return isinstance(hand, str) and hand.strip().casefold() == "unreviewed"


def resolve_id(result, golden_by_question):
    """The labels.md run number for this result, or None."""
    if isinstance(result.get("id"), int):
        return result["id"]
    question = result.get("question")
    row = golden_by_question.get(question)
    if not isinstance(row, dict):
        return None
    run_id = row.get("id")
    if isinstance(run_id, int):
        return run_id
    return None


def summarize(results, labels_by_id, golden_by_question):
    """Count agreements. Hand labels come from labels.md, not from the file.

    A copy of the hand label inside judge_results.jsonl is ignored.
    Skipped runs and unreviewed rows are not in the agree count.
    """
    agree = 0
    disagreements = []
    skipped = 0
    unreviewed = 0
    missing_hand = 0
    for result in results:
        if result.get("skipped"):
            skipped += 1
            continue
        run_id = resolve_id(result, golden_by_question)
        hand_row = labels_by_id.get(run_id) if run_id is not None else None
        if not isinstance(hand_row, dict):
            missing_hand += 1
            continue
        hand = hand_row.get("label")
        if is_unreviewed(hand):
            unreviewed += 1
            continue
        judged = result.get("label")
        if labels_agree(hand, judged):
            agree += 1
            continue
        disagreements.append({
            "id": run_id,
            "question": result.get("question"),
            "hand_label": hand,
            "hand_reason": hand_row.get("reason") or "",
            "judge_label": judged,
            "judge_reason": result.get("reason") or "",
            "flaky": bool(result.get("flaky")),
        })
    compared = agree + len(disagreements)
    return {
        "agree": agree,
        "compared": compared,
        "disagreements": disagreements,
        "skipped": skipped,
        "unreviewed": unreviewed,
        "missing_hand": missing_hand,
    }


def format_disagreement(item):
    where = f"run {item['id']}" if isinstance(item["id"], int) else "a run"
    hand_bit = f"hand label {item['hand_label']}"
    if item["hand_reason"]:
        hand_bit += f" ({item['hand_reason']})"
    judge_label = item["judge_label"] or "(none)"
    judge_bit = f"Judge said {judge_label} ({item['judge_reason']})."
    flaky = " The judge also disagreed with itself." if item["flaky"] else ""
    return f"{where}: {hand_bit}. {judge_bit}{flaky}"


def skipped_sentence(count):
    if count == 1:
        return (
            "1 run was skipped because code checks already flagged it, "
            "so the judge did not grade it."
        )
    return (
        f"{count} runs were skipped because code checks already flagged them, "
        "so the judge did not grade them."
    )


def unreviewed_sentence(count):
    if count == 1:
        return "1 run is still unreviewed in labels.md, so it was not scored."
    return f"{count} runs are still unreviewed in labels.md, so they were not scored."


def missing_sentence(count):
    if count == 1:
        return "1 run has no hand label in labels.md, so it was not scored."
    return f"{count} runs have no hand label in labels.md, so they were not scored."


def format_report(summary):
    """Agreement count, disagreements, then the note. Hand labels win."""
    lines = [f"{summary['agree']} of {summary['compared']} agree."]
    lines.append("")
    disagreements = summary["disagreements"]
    if disagreements:
        lines.append("Disagreements (the hand label is the truth):")
        for item in disagreements:
            lines.append(format_disagreement(item))
    else:
        lines.append("No disagreements.")
    if summary["skipped"]:
        lines.append(skipped_sentence(summary["skipped"]))
    if summary["unreviewed"]:
        lines.append(unreviewed_sentence(summary["unreviewed"]))
    if summary["missing_hand"]:
        lines.append(missing_sentence(summary["missing_hand"]))
    lines.append("")
    lines.append(NOTE)
    return "\n".join(lines)


def parse_args(argv):
    parser = argparse.ArgumentParser(
        description="Compare judge_results.jsonl to the hand labels in labels.md.",
    )
    parser.add_argument("path", help="JSONL file written by judge.py.")
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(sys.argv[1:] if argv is None else argv)
    try:
        results = check_runs.read_runs(check_runs.locate(args.path))
        labels_by_id = judge.read_hand_labels(judge.DEFAULT_LABELS)
        golden_rows = golden_check.read_golden(judge.DEFAULT_GOLDEN)
        golden_by_question = golden_check.index_golden(golden_rows)
        summary = summarize(results, labels_by_id, golden_by_question)
    except (checks.CheckError, judge.JudgeError) as err:
        print(str(err))
        return 2
    print(format_report(summary))
    return 0


if __name__ == "__main__":
    sys.exit(main())
