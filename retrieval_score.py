#!/usr/bin/env python3
"""Score whether search finds the right runbook.

This is a separate step from the trace. The trace writes down what search
returned on a real run. This file asks a smaller question: for a few known
questions, was the right runbook in the top 5?

retrieval_gold.jsonl is a tiny starter set. It is not a full measure.
The questions there are ones whose practice-model answer cites a runbook
that obviously matches. There are at most 8 of them.

Recall at 5: the share of those questions where the right runbook is in
the first 5 search hits.

MRR (mean reciprocal rank): first place scores 1, second place scores 1/2,
third place scores 1/3, and a miss scores 0. MRR is the average.

This uses the same local search as the copilot. It does not call a model
and it does not need an API key.

    python retrieval_score.py
"""

import argparse
import json
import sys
from pathlib import Path


HERE = Path(__file__).resolve().parent
GOLD_FILE = HERE / "retrieval_gold.jsonl"
# The syllabus asks for the first 5 hits. The copilot's own search keeps 3
# unless we ask for more.
TOP_N = 5
# Keep this list small on purpose. It is a starter set, not a full grade.
MAX_ROWS = 8


def hit_matches(hit, expected_runbook, expected_section=None):
    """True when this search hit is the runbook we hoped to find.

    expected_runbook is the file name. When expected_section is set, the
    section title must match too. sample_runbook.txt holds more than one
    topic, so the section keeps those topics apart.
    The names have to match exactly, including capital letters.
    """
    if not isinstance(hit, dict):
        return False
    source = (hit.get("source") or "").strip()
    section = (hit.get("section") or hit.get("title") or "").strip()
    expected_runbook = (expected_runbook or "").strip()
    if not expected_runbook:
        return False
    if expected_section:
        return source == expected_runbook and section == expected_section.strip()
    return source == expected_runbook or section == expected_runbook


def rank_of(results, expected_runbook, expected_section=None):
    """1-based place of the expected runbook, or None if it is not in the list.

    The list is best-first. Pass at most 5 hits when scoring recall at 5.
    A longer list is fine for a made-up example.
    """
    for place, hit in enumerate(results or [], start=1):
        if hit_matches(hit, expected_runbook, expected_section):
            return place
    return None


def recall_at_5(ranks):
    """Fraction of questions whose right runbook is in the first 5 hits.

    `ranks` is a list of 1-based places. None means the runbook was missing.
    A place of 6 or worse counts as a miss here.
    """
    if not ranks:
        return 0.0
    found = 0
    for rank in ranks:
        if rank is not None and 1 <= rank <= TOP_N:
            found += 1
    return found / len(ranks)


def mean_reciprocal_rank(ranks):
    """Average of 1/rank. A missing runbook scores 0.

    This uses the full place, even past 5. Recall at 5 is the cutoff.
    """
    if not ranks:
        return 0.0
    total = 0.0
    for rank in ranks:
        if rank is not None and rank >= 1:
            total += 1.0 / rank
    return total / len(ranks)


def read_gold(path):
    """Read retrieval_gold.jsonl. Each line needs a question and a runbook."""
    path = Path(path)
    if not path.is_file():
        raise ValueError(f"BAD_GOLD: cannot find {path}.")
    rows = []
    for line_number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not raw.strip():
            continue
        try:
            row = json.loads(raw)
        except json.JSONDecodeError as err:
            raise ValueError(f"BAD_GOLD: line {line_number} is not JSON ({err.msg}).") from err
        if not isinstance(row, dict):
            raise ValueError(f"BAD_GOLD: line {line_number} is not a row.")
        if not row.get("question") or not row.get("expected_runbook"):
            raise ValueError(
                f"BAD_GOLD: line {line_number} needs question and expected_runbook."
            )
        rows.append(row)
    if not rows:
        raise ValueError(f"BAD_GOLD: {path} has no rows.")
    if len(rows) > MAX_ROWS:
        raise ValueError(
            f"BAD_GOLD: this starter set is limited to {MAX_ROWS} rows. "
            f"{path} has {len(rows)}."
        )
    return rows


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Print recall at 5 and MRR for the small retrieval starter set.",
    )
    parser.add_argument(
        "--gold",
        type=Path,
        default=GOLD_FILE,
        help="The starter file. Default: retrieval_gold.jsonl next to this script.",
    )
    args = parser.parse_args(argv)
    try:
        rows = read_gold(args.gold)
    except ValueError as err:
        print(err)
        return 2

    # The search lives in the vendored copilot. Loading it does not call a model.
    import collect_runs

    try:
        checkout = collect_runs.ensure_checkout()
        collect_runs.load_copilot(checkout)
        import retrieve
    except collect_runs.HarnessError as err:
        print(err)
        return 2

    print("Retrieval score")
    print(f"{len(rows)} questions. This is a tiny starter set, not a full measure.")
    print()
    ranks = []
    for row in rows:
        hits = retrieve.search(row["question"], top_k=TOP_N)
        rank = rank_of(hits, row["expected_runbook"], row.get("expected_section"))
        ranks.append(rank)
        label = row.get("id", "?")
        if rank is None:
            place = "not in the top 5"
        else:
            place = f"rank {rank}"
        section = row.get("expected_section") or ""
        extra = f"  {section}" if section else ""
        print(f"Run {label}  {place}  {row['expected_runbook']}{extra}")

    found = sum(1 for rank in ranks if rank is not None and rank <= TOP_N)
    print()
    print(f"Recall at 5: {recall_at_5(ranks):.3f} ({found} of {len(ranks)})")
    print(f"MRR: {mean_reciprocal_rank(ranks):.3f}")
    print()
    print("A perfect score here only means search found these obvious runbooks.")
    print("It does not grade the other questions.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
