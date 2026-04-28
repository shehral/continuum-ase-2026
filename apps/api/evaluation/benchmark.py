"""Run benchmark evaluation of the entity resolution pipeline.

Computes B-cubed precision, recall, and F1 along with per-mention accuracy,
per-stage resolution rates, and optional latency measurements.

Inputs:
  - Annotated CSV with ground-truth annotator_judgment column filled in
  - Optionally: a live pipeline to measure latency (falls back to offline)

Usage:
    python -m evaluation.benchmark [--input PATH] [--output PATH] [--stages STAGES]
"""

import argparse
import csv
import json
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

# Allow imports from the parent apps/api directory
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from models.ontology import CANONICAL_NAMES, get_canonical_name, normalize_entity_name

try:
    from rapidfuzz import fuzz
except ImportError:
    fuzz = None  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Offline pipeline (mirrors prepare_annotation.py but with configurable stages)
# ---------------------------------------------------------------------------

_ALL_CANONICAL_NAMES: list[str] = sorted(set(CANONICAL_NAMES.values()))
_CANONICAL_TO_ALIASES: dict[str, set[str]] = {}
for _alias, _canonical in CANONICAL_NAMES.items():
    _CANONICAL_TO_ALIASES.setdefault(_canonical, set()).add(_alias.lower())

# Stage identifiers
STAGE_CACHE = "cache"
STAGE_EXACT = "exact"
STAGE_CANONICAL = "canonical"
STAGE_ALIAS = "alias"
STAGE_FUZZY = "fuzzy"
STAGE_EMBEDDING = "embedding"

ALL_STAGES = [
    STAGE_CACHE,
    STAGE_EXACT,
    STAGE_CANONICAL,
    STAGE_ALIAS,
    STAGE_FUZZY,
    STAGE_EMBEDDING,
]


class ConfigurableOfflineResolver:
    """Offline resolver with individually toggleable stages.

    Used for benchmark evaluation and ablation studies.
    """

    def __init__(
        self,
        enabled_stages: set[str] | None = None,
        fuzzy_threshold: int = 85,
    ):
        self.enabled_stages = enabled_stages or set(ALL_STAGES)
        self.fuzzy_threshold = fuzzy_threshold

    def resolve(self, mention_text: str) -> dict:
        """Resolve mention to canonical entity.

        Returns dict: predicted, confidence, stage, latency_ms.
        """
        t0 = time.perf_counter()
        normalized = normalize_entity_name(mention_text)

        # Stage 1: Cache — offline mode always misses
        # (included for completeness; ablation simply skips it)

        # Stage 2: Exact match
        if STAGE_EXACT in self.enabled_stages:
            for canonical in _ALL_CANONICAL_NAMES:
                if canonical.lower() == normalized:
                    return self._result(canonical, 1.0, STAGE_EXACT, t0)

        # Stage 3: Canonical lookup
        if STAGE_CANONICAL in self.enabled_stages:
            canonical = get_canonical_name(mention_text)
            if canonical.lower() != normalized:
                return self._result(canonical, 0.95, STAGE_CANONICAL, t0)

        # Stage 4: Alias search
        if STAGE_ALIAS in self.enabled_stages:
            for canon_name, aliases in _CANONICAL_TO_ALIASES.items():
                if normalized in aliases:
                    return self._result(canon_name, 0.92, STAGE_ALIAS, t0)

        # Stage 5/6: Fuzzy match
        if STAGE_FUZZY in self.enabled_stages and fuzz is not None:
            best_score = 0
            best_match = None
            for canon_name in _ALL_CANONICAL_NAMES:
                score = fuzz.ratio(normalized, canon_name.lower())
                if score >= self.fuzzy_threshold and score > best_score:
                    best_score = score
                    best_match = canon_name
            if best_match is not None:
                return self._result(best_match, best_score / 100.0, STAGE_FUZZY, t0)

        # Stage 7: Embedding — not available offline
        # (ablation config can toggle this; no-op here)

        return self._result("", 0.0, "unresolved", t0)

    @staticmethod
    def _result(
        predicted: str, confidence: float, stage: str, t0: float
    ) -> dict:
        elapsed_ms = (time.perf_counter() - t0) * 1000
        return {
            "predicted": predicted,
            "confidence": confidence,
            "stage": stage,
            "latency_ms": elapsed_ms,
        }


# ---------------------------------------------------------------------------
# B-cubed metrics
# ---------------------------------------------------------------------------


def compute_bcubed(
    predictions: list[str], ground_truths: list[str]
) -> dict[str, float]:
    """Compute B-cubed precision, recall, and F1.

    Each mention is assigned a predicted cluster (the predicted canonical name)
    and a ground-truth cluster (the annotator judgment). B-cubed metrics are
    defined per-mention and then macro-averaged.

    Args:
        predictions: List of predicted canonical names (one per mention).
        ground_truths: List of ground-truth canonical names (one per mention).

    Returns:
        Dict with keys: bcubed_precision, bcubed_recall, bcubed_f1.
    """
    n = len(predictions)
    if n == 0:
        return {"bcubed_precision": 0.0, "bcubed_recall": 0.0, "bcubed_f1": 0.0}

    # Build cluster maps
    pred_clusters: dict[str, list[int]] = defaultdict(list)
    truth_clusters: dict[str, list[int]] = defaultdict(list)
    for i in range(n):
        pred_clusters[predictions[i]].append(i)
        truth_clusters[ground_truths[i]].append(i)

    # For efficient lookup: mention index -> cluster members
    pred_members: dict[int, set[int]] = {}
    for cluster_name, members in pred_clusters.items():
        member_set = set(members)
        for m in members:
            pred_members[m] = member_set

    truth_members: dict[int, set[int]] = {}
    for cluster_name, members in truth_clusters.items():
        member_set = set(members)
        for m in members:
            truth_members[m] = member_set

    total_precision = 0.0
    total_recall = 0.0

    for i in range(n):
        pred_set = pred_members[i]
        truth_set = truth_members[i]
        intersection = pred_set & truth_set

        # B-cubed precision: fraction of pred-cluster mates that share truth cluster
        total_precision += len(intersection) / len(pred_set) if pred_set else 0.0
        # B-cubed recall: fraction of truth-cluster mates that share pred cluster
        total_recall += len(intersection) / len(truth_set) if truth_set else 0.0

    precision = total_precision / n
    recall = total_recall / n
    f1 = (
        2 * precision * recall / (precision + recall)
        if (precision + recall) > 0
        else 0.0
    )

    return {
        "bcubed_precision": round(precision, 4),
        "bcubed_recall": round(recall, 4),
        "bcubed_f1": round(f1, 4),
    }


# ---------------------------------------------------------------------------
# Benchmark runner
# ---------------------------------------------------------------------------


def run_benchmark(
    annotated_rows: list[dict],
    enabled_stages: set[str] | None = None,
    fuzzy_threshold: int = 85,
) -> dict[str, Any]:
    """Run the full benchmark evaluation.

    Args:
        annotated_rows: List of dicts with at least mention_text and annotator_judgment.
        enabled_stages: Which pipeline stages to enable (None = all).
        fuzzy_threshold: Fuzzy match threshold (0-100).

    Returns:
        Dict with all computed metrics.
    """
    resolver = ConfigurableOfflineResolver(
        enabled_stages=enabled_stages,
        fuzzy_threshold=fuzzy_threshold,
    )

    predictions: list[str] = []
    ground_truths: list[str] = []
    stages_used: list[str] = []
    latencies: list[float] = []
    correct = 0
    total = 0
    stage_resolution_counts: dict[str, int] = defaultdict(int)
    stage_correct_counts: dict[str, int] = defaultdict(int)

    for row in annotated_rows:
        mention_text = row.get("mention_text", "")
        truth = row.get("annotator_judgment", "").strip()

        if not mention_text or not truth:
            continue

        result = resolver.resolve(mention_text)
        predicted = result["predicted"]
        stage = result["stage"]

        predictions.append(predicted if predicted else f"__unresolved_{total}")
        ground_truths.append(truth)
        stages_used.append(stage)
        latencies.append(result["latency_ms"])

        stage_resolution_counts[stage] += 1
        total += 1

        if predicted.lower() == truth.lower():
            correct += 1
            stage_correct_counts[stage] += 1

    # Compute metrics
    accuracy = correct / total if total > 0 else 0.0
    bcubed = compute_bcubed(predictions, ground_truths)

    # Per-stage breakdown
    stage_breakdown: dict[str, dict[str, Any]] = {}
    for stage in sorted(stage_resolution_counts.keys()):
        count = stage_resolution_counts[stage]
        correct_in_stage = stage_correct_counts.get(stage, 0)
        stage_breakdown[stage] = {
            "count": count,
            "fraction": round(count / total, 4) if total > 0 else 0.0,
            "accuracy": (
                round(correct_in_stage / count, 4) if count > 0 else 0.0
            ),
        }

    # Latency statistics
    latency_stats: dict[str, float] = {}
    if latencies:
        sorted_lat = sorted(latencies)
        latency_stats = {
            "mean_ms": round(sum(sorted_lat) / len(sorted_lat), 3),
            "median_ms": round(sorted_lat[len(sorted_lat) // 2], 3),
            "p95_ms": round(sorted_lat[int(len(sorted_lat) * 0.95)], 3),
            "p99_ms": round(sorted_lat[int(len(sorted_lat) * 0.99)], 3),
        }

    return {
        "total_mentions": total,
        "accuracy": round(accuracy, 4),
        **bcubed,
        "per_stage": stage_breakdown,
        "latency": latency_stats,
        "enabled_stages": sorted(enabled_stages) if enabled_stages else ALL_STAGES,
    }


def format_results(results: dict[str, Any]) -> str:
    """Format benchmark results as a readable text summary."""
    lines: list[str] = []
    lines.append("=" * 60)
    lines.append("ENTITY RESOLUTION BENCHMARK RESULTS")
    lines.append("=" * 60)
    lines.append(f"Total mentions evaluated: {results['total_mentions']}")
    lines.append(f"Enabled stages: {', '.join(results['enabled_stages'])}")
    lines.append("")
    lines.append("--- Overall Metrics ---")
    lines.append(f"  Per-mention accuracy: {results['accuracy']:.2%}")
    lines.append(f"  B-cubed Precision:    {results['bcubed_precision']:.4f}")
    lines.append(f"  B-cubed Recall:       {results['bcubed_recall']:.4f}")
    lines.append(f"  B-cubed F1:           {results['bcubed_f1']:.4f}")
    lines.append("")
    lines.append("--- Per-Stage Breakdown ---")
    lines.append(f"  {'Stage':>12s}  {'Count':>6s}  {'Fraction':>8s}  {'Accuracy':>8s}")
    lines.append(f"  {'-'*12}  {'-'*6}  {'-'*8}  {'-'*8}")
    for stage, info in sorted(
        results.get("per_stage", {}).items(), key=lambda x: -x[1]["count"]
    ):
        lines.append(
            f"  {stage:>12s}  {info['count']:>6d}  {info['fraction']:>8.2%}  "
            f"{info['accuracy']:>8.2%}"
        )
    lines.append("")
    lat = results.get("latency", {})
    if lat:
        lines.append("--- Latency (offline, per resolution) ---")
        lines.append(f"  Mean:   {lat.get('mean_ms', 0):.3f} ms")
        lines.append(f"  Median: {lat.get('median_ms', 0):.3f} ms")
        lines.append(f"  p95:    {lat.get('p95_ms', 0):.3f} ms")
        lines.append(f"  p99:    {lat.get('p99_ms', 0):.3f} ms")
    lines.append("=" * 60)
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run entity resolution benchmark evaluation."
    )
    parser.add_argument(
        "--input",
        type=str,
        default=str(
            Path(__file__).resolve().parent / "data" / "annotation_sheet.csv"
        ),
        help="Annotated CSV with annotator_judgment column filled in",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=str(
            Path(__file__).resolve().parent / "data" / "benchmark_results.json"
        ),
        help="Output JSON file for results",
    )
    parser.add_argument(
        "--stages",
        type=str,
        default=",".join(ALL_STAGES),
        help=f"Comma-separated list of stages to enable (default: all). "
        f"Available: {','.join(ALL_STAGES)}",
    )
    parser.add_argument(
        "--fuzzy-threshold",
        type=int,
        default=85,
        help="Fuzzy match threshold 0-100 (default: 85)",
    )
    parser.add_argument(
        "--synthetic",
        action="store_true",
        help="Use synthetic benchmark data instead of annotation sheet",
    )
    args = parser.parse_args()

    # Determine input
    if args.synthetic:
        input_path = Path(__file__).resolve().parent / "data" / "synthetic_benchmark.csv"
    else:
        input_path = Path(args.input)

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if not input_path.is_file():
        print(f"Error: Input file not found: {input_path}", file=sys.stderr)
        sys.exit(1)

    # Parse stages
    enabled_stages = set(s.strip() for s in args.stages.split(",") if s.strip())
    invalid_stages = enabled_stages - set(ALL_STAGES)
    if invalid_stages:
        print(
            f"Warning: Unknown stages ignored: {invalid_stages}", file=sys.stderr
        )
        enabled_stages -= invalid_stages

    # Read input
    with open(input_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    # If using synthetic benchmark, map columns to expected format
    if args.synthetic:
        mapped_rows = []
        for row in rows:
            mapped_rows.append(
                {
                    "mention_text": row.get("variant", ""),
                    "annotator_judgment": row.get("canonical", ""),
                }
            )
        rows = mapped_rows
    else:
        # Filter to only rows with annotations
        rows = [r for r in rows if r.get("annotator_judgment", "").strip()]

    if not rows:
        print("Error: No annotated rows found in input file.", file=sys.stderr)
        print(
            "Fill in the 'annotator_judgment' column and re-run.", file=sys.stderr
        )
        sys.exit(1)

    print(f"Running benchmark on {len(rows)} annotated mentions...")
    print(f"Enabled stages: {sorted(enabled_stages)}")

    results = run_benchmark(
        rows,
        enabled_stages=enabled_stages,
        fuzzy_threshold=args.fuzzy_threshold,
    )

    # Output
    summary = format_results(results)
    print(summary)

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)
    print(f"\nDetailed results saved to {output_path}")


if __name__ == "__main__":
    main()
