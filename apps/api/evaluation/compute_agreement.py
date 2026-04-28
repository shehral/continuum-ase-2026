"""Inter-annotator agreement for the two-reviewer evaluation reported in the paper.

Computes:
  - Cohen's kappa on the 30-mention entity-annotation overlap
  - Cohen's kappa on the 10-decision decision-review overlap
  - Percent agreement for both
  - Merged precision stats (entity CORRECT rate, decision CORRECT/PARTIAL/WRONG/NOT_A_DECISION)
  - GraphRAG relevance mean across the 10 non-overlapping query judgments

Run from apps/api/:
    .venv/bin/python -m evaluation.compute_agreement

Outputs JSON to evaluation/data/v5/agreement_results.json.
"""

from __future__ import annotations

import csv
import json
import re
from collections import Counter
from pathlib import Path
from statistics import mean

DATA_DIR = Path(__file__).parent / "data" / "v5"
F1_DIR = DATA_DIR / "annotator_a"
F2_DIR = DATA_DIR / "annotator_b"


def _normalize_entity(j: str) -> str:
    """Collapse entity judgment to 4 classes: CORRECT, WRONG, NOT_ENTITY, AMBIGUOUS.

    Accepts the full rubric (y / n:Name / WRONG: Name / s / a / etc.).
    """
    if not j:
        return ""
    s = j.strip().upper()
    if s in {"Y", "CORRECT"}:
        return "CORRECT"
    if s in {"S", "NOT_ENTITY"}:
        return "NOT_ENTITY"
    if s in {"A", "AMBIGUOUS"}:
        return "AMBIGUOUS"
    if s.startswith("N:") or s.startswith("WRONG") or s.startswith("N "):
        return "WRONG"
    return s  # leave unexpected labels visible


def _normalize_decision(j: str) -> str:
    if not j:
        return ""
    return j.strip().upper()


def _load_csv(path: Path) -> list[dict]:
    with path.open() as f:
        return list(csv.DictReader(f))


def cohens_kappa(pairs: list[tuple[str, str]]) -> tuple[float, float]:
    """Return (kappa, percent_agreement) for a list of (a, b) label pairs."""
    if not pairs:
        return float("nan"), float("nan")
    n = len(pairs)
    po = sum(1 for a, b in pairs if a == b) / n
    a_counts = Counter(a for a, _ in pairs)
    b_counts = Counter(b for _, b in pairs)
    pe = sum((a_counts[k] / n) * (b_counts[k] / n) for k in set(a_counts) | set(b_counts))
    kappa = (po - pe) / (1 - pe) if pe < 1 else float("nan")
    return kappa, po


def entity_agreement() -> dict:
    f1 = _load_csv(F1_DIR / "entity-annotation-sheet.csv")
    f2 = _load_csv(F2_DIR / "entity-annotation-sheet.csv")

    f1_by_id = {r["mention_id"]: r for r in f1}
    f2_by_id = {r["mention_id"]: r for r in f2}
    overlap = sorted(set(f1_by_id) & set(f2_by_id))

    pairs = [
        (_normalize_entity(f1_by_id[mid]["annotator_judgment"]),
         _normalize_entity(f2_by_id[mid]["annotator_judgment"]))
        for mid in overlap
    ]
    kappa, agree = cohens_kappa(pairs)

    # Per-annotator distribution (full set)
    def dist(rows: list[dict]) -> dict[str, int]:
        c = Counter(_normalize_entity(r["annotator_judgment"]) for r in rows)
        return dict(c)

    # "Entity resolution accuracy" = CORRECT / (CORRECT + WRONG). NOT_ENTITY and
    # AMBIGUOUS are excluded because they are not entity-resolution decisions.
    def accuracy(rows: list[dict]) -> tuple[int, int, float]:
        labels = [_normalize_entity(r["annotator_judgment"]) for r in rows]
        correct = sum(1 for l in labels if l == "CORRECT")
        wrong = sum(1 for l in labels if l == "WRONG")
        denom = correct + wrong
        return correct, denom, (correct / denom if denom else float("nan"))

    f1_c, f1_d, f1_acc = accuracy(f1)
    f2_c, f2_d, f2_acc = accuracy(f2)

    return {
        "overlap_n": len(overlap),
        "cohens_kappa": round(kappa, 3),
        "percent_agreement": round(agree, 3),
        "confusion": [
            {"annotator_a": a, "annotator_b": b} for a, b in pairs
        ],
        "annotator_a_distribution": dist(f1),
        "annotator_b_distribution": dist(f2),
        "annotator_a_accuracy": {
            "correct": f1_c,
            "denom": f1_d,
            "accuracy": round(f1_acc, 4),
        },
        "annotator_b_accuracy": {
            "correct": f2_c,
            "denom": f2_d,
            "accuracy": round(f2_acc, 4),
        },
        "combined_accuracy_range_pct": [
            round(min(f1_acc, f2_acc) * 100, 1),
            round(max(f1_acc, f2_acc) * 100, 1),
        ],
    }


def decision_agreement() -> dict:
    f1 = _load_csv(F1_DIR / "decision-review-sheet.csv")
    f2 = _load_csv(F2_DIR / "decision-review-sheet.csv")

    f1_by_id = {r["decision_id"]: r for r in f1}
    f2_by_id = {r["decision_id"]: r for r in f2}
    overlap = sorted(set(f1_by_id) & set(f2_by_id))

    pairs = [
        (_normalize_decision(f1_by_id[did]["judgment"]),
         _normalize_decision(f2_by_id[did]["judgment"]))
        for did in overlap
    ]
    kappa, agree = cohens_kappa(pairs)

    def dist(rows: list[dict]) -> dict[str, int]:
        return dict(Counter(_normalize_decision(r["judgment"]) for r in rows))

    # Strict precision = CORRECT / total reviewed
    # Lenient precision = (CORRECT + PARTIAL) / total reviewed
    def precision(rows: list[dict]) -> dict:
        labels = [_normalize_decision(r["judgment"]) for r in rows]
        n = len(labels)
        c = labels.count("CORRECT")
        p = labels.count("PARTIAL")
        w = labels.count("WRONG")
        nd = labels.count("NOT_A_DECISION")
        return {
            "n": n,
            "correct": c,
            "partial": p,
            "wrong": w,
            "not_a_decision": nd,
            "strict_precision": round(c / n, 4) if n else float("nan"),
            "lenient_precision": round((c + p) / n, 4) if n else float("nan"),
            "extraction_precision_excl_not_decision": round(
                (c + p) / (n - nd), 4
            ) if (n - nd) else float("nan"),
        }

    # Merge annotator A + annotator B non-overlapping rows + majority-vote on overlap
    merged_rows: list[str] = []
    for did, r in f1_by_id.items():
        if did in f2_by_id:
            # resolution: if annotators agree, take it; if disagree, keep both
            j1 = _normalize_decision(r["judgment"])
            j2 = _normalize_decision(f2_by_id[did]["judgment"])
            if j1 == j2:
                merged_rows.append(j1)
            else:
                # count both as separate observations for a conservative view
                merged_rows.append(j1)
                merged_rows.append(j2)
        else:
            merged_rows.append(_normalize_decision(r["judgment"]))
    for did, r in f2_by_id.items():
        if did not in f1_by_id:
            merged_rows.append(_normalize_decision(r["judgment"]))

    merged_counts = dict(Counter(merged_rows))
    merged_n = len(merged_rows)
    merged_stats = {
        "n_observations": merged_n,
        "distribution": merged_counts,
        "correct_pct": round(100 * merged_counts.get("CORRECT", 0) / merged_n, 1),
        "partial_pct": round(100 * merged_counts.get("PARTIAL", 0) / merged_n, 1),
        "wrong_pct": round(100 * merged_counts.get("WRONG", 0) / merged_n, 1),
        "not_a_decision_pct": round(
            100 * merged_counts.get("NOT_A_DECISION", 0) / merged_n, 1
        ),
        "extraction_precision_pct": round(
            100
            * (merged_counts.get("CORRECT", 0) + merged_counts.get("PARTIAL", 0))
            / (merged_n - merged_counts.get("NOT_A_DECISION", 0)),
            1,
        )
        if (merged_n - merged_counts.get("NOT_A_DECISION", 0)) > 0
        else None,
    }

    return {
        "overlap_n": len(overlap),
        "cohens_kappa": round(kappa, 3),
        "percent_agreement": round(agree, 3),
        "confusion": [
            {"decision_id": did, "annotator_a": a, "annotator_b": b}
            for did, (a, b) in zip(overlap, pairs)
        ],
        "annotator_a_distribution": dist(f1),
        "annotator_b_distribution": dist(f2),
        "annotator_a_precision": precision(f1),
        "annotator_b_precision": precision(f2),
        "merged": merged_stats,
    }


_RATING_RE = re.compile(r"YOUR RATING.*?:\s*([123])")


def graphrag_mean() -> dict:
    def parse(path: Path) -> list[int]:
        return [int(m) for m in _RATING_RE.findall(path.read_text())]

    f1 = parse(F1_DIR / "graphrag-ratings.txt")
    f2 = parse(F2_DIR / "graphrag-ratings.txt")
    all_ratings = f1 + f2
    return {
        "annotator_a_ratings": f1,
        "annotator_b_ratings": f2,
        "annotator_a_mean": round(mean(f1), 2) if f1 else None,
        "annotator_b_mean": round(mean(f2), 2) if f2 else None,
        "combined_mean": round(mean(all_ratings), 2) if all_ratings else None,
        "n_total": len(all_ratings),
    }


def main() -> None:
    results = {
        "entity_annotation": entity_agreement(),
        "decision_review": decision_agreement(),
        "graphrag_ratings": graphrag_mean(),
    }

    out_path = DATA_DIR / "agreement_results.json"
    out_path.write_text(json.dumps(results, indent=2))

    # Compact human-readable summary
    ent = results["entity_annotation"]
    dec = results["decision_review"]
    gr = results["graphrag_ratings"]

    print("=" * 60)
    print("ENTITY ANNOTATION")
    print("=" * 60)
    print(f"Cohen's kappa (n={ent['overlap_n']} overlap): {ent['cohens_kappa']}")
    print(f"Percent agreement: {ent['percent_agreement']*100:.1f}%")
    print(f"Annotator A accuracy: {ent['annotator_a_accuracy']['correct']}/{ent['annotator_a_accuracy']['denom']} = {ent['annotator_a_accuracy']['accuracy']*100:.1f}%")
    print(f"Annotator B accuracy: {ent['annotator_b_accuracy']['correct']}/{ent['annotator_b_accuracy']['denom']} = {ent['annotator_b_accuracy']['accuracy']*100:.1f}%")
    print(f"Range: {ent['combined_accuracy_range_pct'][0]}% - {ent['combined_accuracy_range_pct'][1]}%")
    print()
    print("=" * 60)
    print("DECISION REVIEW")
    print("=" * 60)
    print(f"Cohen's kappa (n={dec['overlap_n']} overlap): {dec['cohens_kappa']}")
    print(f"Percent agreement: {dec['percent_agreement']*100:.1f}%")
    print(f"Merged (n={dec['merged']['n_observations']} observations):")
    print(f"  CORRECT={dec['merged']['correct_pct']}%  PARTIAL={dec['merged']['partial_pct']}%")
    print(f"  WRONG={dec['merged']['wrong_pct']}%  NOT_A_DECISION={dec['merged']['not_a_decision_pct']}%")
    print(f"  Extraction precision (CORRECT+PARTIAL excluding NOT_A_DECISION): {dec['merged']['extraction_precision_pct']}%")
    print()
    print("=" * 60)
    print("GRAPHRAG RELEVANCE")
    print("=" * 60)
    print(f"A ratings: {gr['annotator_a_ratings']}  (mean={gr['annotator_a_mean']})")
    print(f"B ratings: {gr['annotator_b_ratings']}  (mean={gr['annotator_b_mean']})")
    print(f"Combined mean ({gr['n_total']} queries): {gr['combined_mean']}")
    print()
    print(f"Full results saved to {out_path}")


if __name__ == "__main__":
    main()
