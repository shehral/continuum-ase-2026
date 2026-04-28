"""Run ablation study on the entity resolution pipeline.

For each pipeline configuration (full, minus one stage, minus combinations),
re-runs the benchmark and produces a comparison table in CSV and LaTeX format.

Usage:
    python -m evaluation.ablation [--input PATH] [--output-dir DIR]
"""

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Any

# Allow imports from the parent apps/api directory
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from evaluation.benchmark import (
    ALL_STAGES,
    STAGE_ALIAS,
    STAGE_CACHE,
    STAGE_CANONICAL,
    STAGE_EMBEDDING,
    STAGE_EXACT,
    STAGE_FUZZY,
    format_results,
    run_benchmark,
)

# ---------------------------------------------------------------------------
# Ablation configurations
# ---------------------------------------------------------------------------

ABLATION_CONFIGS: list[dict[str, Any]] = [
    {
        "name": "Full pipeline",
        "description": "All stages enabled",
        "disabled": set(),
    },
    {
        "name": "-Cache",
        "description": "Disable stage 1 (cache lookup)",
        "disabled": {STAGE_CACHE},
    },
    {
        "name": "-Canonical",
        "description": "Disable stage 3 (canonical lookup)",
        "disabled": {STAGE_CANONICAL},
    },
    {
        "name": "-Alias",
        "description": "Disable stage 4 (alias search)",
        "disabled": {STAGE_ALIAS},
    },
    {
        "name": "-Fuzzy",
        "description": "Disable stage 5/6 (fuzzy matching)",
        "disabled": {STAGE_FUZZY},
    },
    {
        "name": "-Embedding",
        "description": "Disable stage 7 (embedding similarity)",
        "disabled": {STAGE_EMBEDDING},
    },
    {
        "name": "-Canonical-Fuzzy",
        "description": "Disable stages 3 and 5/6 (canonical + fuzzy)",
        "disabled": {STAGE_CANONICAL, STAGE_FUZZY},
    },
]


def run_ablation(
    annotated_rows: list[dict],
    fuzzy_threshold: int = 85,
    verbose: bool = True,
) -> list[dict[str, Any]]:
    """Run all ablation configurations and collect results.

    Args:
        annotated_rows: Rows with mention_text and annotator_judgment.
        fuzzy_threshold: Fuzzy match threshold.
        verbose: Whether to print progress.

    Returns:
        List of dicts, one per configuration, with all metrics.
    """
    ablation_results: list[dict[str, Any]] = []

    for i, config in enumerate(ABLATION_CONFIGS, 1):
        name = config["name"]
        disabled = config["disabled"]
        enabled = set(ALL_STAGES) - disabled

        if verbose:
            print(
                f"  [{i}/{len(ABLATION_CONFIGS)}] {name} "
                f"(disabled: {disabled or 'none'})"
            )

        results = run_benchmark(
            annotated_rows,
            enabled_stages=enabled,
            fuzzy_threshold=fuzzy_threshold,
        )

        ablation_results.append(
            {
                "config_name": name,
                "description": config["description"],
                "disabled_stages": sorted(disabled),
                **results,
            }
        )

    return ablation_results


def format_ablation_csv(results: list[dict[str, Any]]) -> list[dict]:
    """Format ablation results as flat CSV rows."""
    rows: list[dict] = []
    for r in results:
        rows.append(
            {
                "Configuration": r["config_name"],
                "Description": r["description"],
                "Accuracy": f"{r['accuracy']:.4f}",
                "B3-Precision": f"{r['bcubed_precision']:.4f}",
                "B3-Recall": f"{r['bcubed_recall']:.4f}",
                "B3-F1": f"{r['bcubed_f1']:.4f}",
                "Total": r["total_mentions"],
                "Disabled": ", ".join(r["disabled_stages"]) or "none",
            }
        )
    return rows


def format_ablation_latex(results: list[dict[str, Any]]) -> str:
    """Format ablation results as a LaTeX table."""
    lines: list[str] = []
    lines.append(r"\begin{table}[ht]")
    lines.append(r"\centering")
    lines.append(r"\caption{Entity Resolution Ablation Study}")
    lines.append(r"\label{tab:ablation}")
    lines.append(r"\begin{tabular}{lcccc}")
    lines.append(r"\toprule")
    lines.append(
        r"\textbf{Configuration} & \textbf{Accuracy} & "
        r"\textbf{B$^3$ Precision} & \textbf{B$^3$ Recall} & "
        r"\textbf{B$^3$ F1} \\"
    )
    lines.append(r"\midrule")

    for r in results:
        name_escaped = r["config_name"].replace("_", r"\_").replace("-", r"\textminus ")
        acc = f"{r['accuracy']:.4f}"
        p = f"{r['bcubed_precision']:.4f}"
        rec = f"{r['bcubed_recall']:.4f}"
        f1 = f"{r['bcubed_f1']:.4f}"

        # Bold the best values
        if r["config_name"] == "Full pipeline":
            name_escaped = r"\textbf{" + name_escaped + "}"
            acc = r"\textbf{" + acc + "}"
            p = r"\textbf{" + p + "}"
            rec = r"\textbf{" + rec + "}"
            f1 = r"\textbf{" + f1 + "}"

        lines.append(f"{name_escaped} & {acc} & {p} & {rec} & {f1} " + r"\\")

    lines.append(r"\bottomrule")
    lines.append(r"\end{tabular}")
    lines.append(r"\end{table}")
    return "\n".join(lines)


def format_ablation_text(results: list[dict[str, Any]]) -> str:
    """Format ablation results as a readable text table."""
    lines: list[str] = []
    lines.append("=" * 80)
    lines.append("ABLATION STUDY RESULTS")
    lines.append("=" * 80)
    lines.append("")

    header = (
        f"{'Configuration':<22s}  {'Accuracy':>8s}  {'B3-P':>8s}  "
        f"{'B3-R':>8s}  {'B3-F1':>8s}  {'N':>5s}"
    )
    lines.append(header)
    lines.append("-" * len(header))

    for r in results:
        lines.append(
            f"{r['config_name']:<22s}  {r['accuracy']:>8.4f}  "
            f"{r['bcubed_precision']:>8.4f}  {r['bcubed_recall']:>8.4f}  "
            f"{r['bcubed_f1']:>8.4f}  {r['total_mentions']:>5d}"
        )

    lines.append("")

    # Compute deltas from full pipeline
    if results:
        full = results[0]
        lines.append("--- Delta from Full Pipeline ---")
        for r in results[1:]:
            delta_acc = r["accuracy"] - full["accuracy"]
            delta_f1 = r["bcubed_f1"] - full["bcubed_f1"]
            lines.append(
                f"  {r['config_name']:<22s}  "
                f"Accuracy: {delta_acc:+.4f}  "
                f"B3-F1: {delta_f1:+.4f}"
            )

    lines.append("=" * 80)
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run ablation study on entity resolution pipeline."
    )
    parser.add_argument(
        "--input",
        type=str,
        default=str(
            Path(__file__).resolve().parent / "data" / "annotation_sheet.csv"
        ),
        help="Annotated CSV with annotator_judgment column",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default=str(Path(__file__).resolve().parent / "data"),
        help="Output directory for ablation results",
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

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    if not input_path.is_file():
        print(f"Error: Input file not found: {input_path}", file=sys.stderr)
        sys.exit(1)

    # Read input
    with open(input_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    # Map columns if using synthetic data
    if args.synthetic:
        mapped_rows = [
            {
                "mention_text": r.get("variant", ""),
                "annotator_judgment": r.get("canonical", ""),
            }
            for r in rows
        ]
        rows = mapped_rows
    else:
        rows = [r for r in rows if r.get("annotator_judgment", "").strip()]

    if not rows:
        print("Error: No annotated rows found.", file=sys.stderr)
        sys.exit(1)

    print(f"Running ablation study on {len(rows)} mentions...")
    print(f"Configurations: {len(ABLATION_CONFIGS)}")
    print()

    results = run_ablation(rows, fuzzy_threshold=args.fuzzy_threshold)

    # Print text summary
    text_summary = format_ablation_text(results)
    print(text_summary)

    # Save CSV
    csv_path = output_dir / "ablation_results.csv"
    csv_rows = format_ablation_csv(results)
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(csv_rows[0].keys()))
        writer.writeheader()
        writer.writerows(csv_rows)
    print(f"\nCSV saved to {csv_path}")

    # Save LaTeX
    latex_path = output_dir / "ablation_table.tex"
    latex_content = format_ablation_latex(results)
    with open(latex_path, "w", encoding="utf-8") as f:
        f.write(latex_content)
    print(f"LaTeX saved to {latex_path}")

    # Save full JSON
    json_path = output_dir / "ablation_results.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"JSON saved to {json_path}")


if __name__ == "__main__":
    main()
