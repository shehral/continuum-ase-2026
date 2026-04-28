"""Master script to orchestrate the full entity resolution evaluation pipeline.

Runs all evaluation steps in sequence:
1. Generate synthetic benchmark
2. Extract mentions from conversation logs
3. Prepare annotation spreadsheet
4. (Manual step: annotation by human)
5. Run benchmark on annotated data
6. Run ablation study
7. Generate all output tables

Usage:
    python -m evaluation.run_all [--skip-extraction] [--skip-annotation]
                                  [--annotated PATH] [--synthetic-only]
"""

import argparse
import subprocess
import sys
from pathlib import Path

EVAL_DIR = Path(__file__).resolve().parent
DATA_DIR = EVAL_DIR / "data"
PYTHON = sys.executable  # Use the same Python interpreter


def _run_step(description: str, cmd: list[str]) -> bool:
    """Run a subprocess step and report success/failure."""
    separator = "-" * 60
    print(f"\n{separator}")
    print(f"STEP: {description}")
    print(separator)

    result = subprocess.run(cmd, cwd=str(EVAL_DIR.parent))
    if result.returncode != 0:
        print(f"\nFAILED: {description} (exit code {result.returncode})")
        return False
    print(f"\nDONE: {description}")
    return True


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run the full entity resolution evaluation pipeline."
    )
    parser.add_argument(
        "--skip-extraction",
        action="store_true",
        help="Skip log extraction step (use existing extracted_mentions.csv)",
    )
    parser.add_argument(
        "--skip-annotation",
        action="store_true",
        help="Skip waiting for manual annotation (use existing annotation_sheet.csv)",
    )
    parser.add_argument(
        "--annotated",
        type=str,
        default=str(DATA_DIR / "annotation_sheet.csv"),
        help="Path to annotated CSV (with annotator_judgment filled in)",
    )
    parser.add_argument(
        "--synthetic-only",
        action="store_true",
        help="Run benchmark and ablation using synthetic data only "
        "(no logs extraction or annotation needed)",
    )
    parser.add_argument(
        "--fuzzy-threshold",
        type=int,
        default=85,
        help="Fuzzy match threshold 0-100 (default: 85)",
    )
    args = parser.parse_args()

    # Ensure data directory exists
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    print("=" * 60)
    print("ENTITY RESOLUTION EVALUATION PIPELINE")
    print("=" * 60)

    # -----------------------------------------------------------------------
    # Step 1: Generate synthetic benchmark
    # -----------------------------------------------------------------------
    ok = _run_step(
        "Generate synthetic benchmark",
        [
            PYTHON, "-m", "evaluation.synthetic_benchmark",
            "--output", str(DATA_DIR / "synthetic_benchmark.csv"),
        ],
    )
    if not ok:
        sys.exit(1)

    # -----------------------------------------------------------------------
    # Step 2: Extract mentions from conversation logs
    # -----------------------------------------------------------------------
    if not args.synthetic_only and not args.skip_extraction:
        ok = _run_step(
            "Extract entity mentions from conversation logs",
            [
                PYTHON, "-m", "evaluation.extract_from_logs",
                "--output", str(DATA_DIR / "extracted_mentions.csv"),
            ],
        )
        if not ok:
            print("Warning: Log extraction failed. Continuing with synthetic data.")
    elif args.skip_extraction:
        print("\n[Skipped] Log extraction (--skip-extraction)")
    elif args.synthetic_only:
        print("\n[Skipped] Log extraction (--synthetic-only)")

    # -----------------------------------------------------------------------
    # Step 3: Prepare annotation spreadsheet
    # -----------------------------------------------------------------------
    if not args.synthetic_only:
        mentions_path = DATA_DIR / "extracted_mentions.csv"
        if mentions_path.is_file():
            ok = _run_step(
                "Prepare annotation spreadsheet",
                [
                    PYTHON, "-m", "evaluation.prepare_annotation",
                    "--input", str(mentions_path),
                    "--output", str(DATA_DIR / "annotation_sheet.csv"),
                    "--fuzzy-threshold", str(args.fuzzy_threshold),
                ],
            )
            if not ok:
                print("Warning: Annotation preparation failed.")
        else:
            print(
                f"\n[Skipped] Annotation preparation "
                f"(no extracted_mentions.csv found)"
            )

    # -----------------------------------------------------------------------
    # Step 4: Manual annotation
    # -----------------------------------------------------------------------
    if not args.synthetic_only and not args.skip_annotation:
        annotation_path = DATA_DIR / "annotation_sheet.csv"
        if annotation_path.is_file():
            print("\n" + "=" * 60)
            print("MANUAL STEP REQUIRED: Annotation")
            print("=" * 60)
            print(
                f"Open the annotation spreadsheet at:\n"
                f"  {annotation_path}\n"
                f"\n"
                f"For each row, fill in the 'annotator_judgment' column with the\n"
                f"correct canonical entity name. Then re-run this script with:\n"
                f"  --skip-annotation\n"
                f"\n"
                f"Or use --synthetic-only to skip annotation and evaluate on\n"
                f"synthetic data only."
            )
            print("=" * 60)
            sys.exit(0)

    # -----------------------------------------------------------------------
    # Step 5: Run benchmark
    # -----------------------------------------------------------------------
    benchmark_args = [PYTHON, "-m", "evaluation.benchmark"]

    if args.synthetic_only:
        benchmark_args.extend([
            "--synthetic",
            "--output", str(DATA_DIR / "benchmark_results_synthetic.json"),
        ])
        step_desc = "Run benchmark (synthetic data)"
    else:
        benchmark_args.extend([
            "--input", args.annotated,
            "--output", str(DATA_DIR / "benchmark_results.json"),
        ])
        step_desc = "Run benchmark (annotated data)"

    benchmark_args.extend(["--fuzzy-threshold", str(args.fuzzy_threshold)])

    ok = _run_step(step_desc, benchmark_args)
    if not ok:
        print("Warning: Benchmark failed.")

    # -----------------------------------------------------------------------
    # Step 6: Run ablation study
    # -----------------------------------------------------------------------
    ablation_args = [
        PYTHON, "-m", "evaluation.ablation",
        "--output-dir", str(DATA_DIR),
        "--fuzzy-threshold", str(args.fuzzy_threshold),
    ]

    if args.synthetic_only:
        ablation_args.append("--synthetic")
        step_desc = "Run ablation study (synthetic data)"
    else:
        ablation_args.extend(["--input", args.annotated])
        step_desc = "Run ablation study (annotated data)"

    ok = _run_step(step_desc, ablation_args)
    if not ok:
        print("Warning: Ablation study failed.")

    # -----------------------------------------------------------------------
    # Step 7: Summary of generated files
    # -----------------------------------------------------------------------
    print("\n" + "=" * 60)
    print("EVALUATION COMPLETE")
    print("=" * 60)
    print("\nGenerated files:")

    output_files = [
        ("Synthetic benchmark", "synthetic_benchmark.csv"),
        ("Extracted mentions", "extracted_mentions.csv"),
        ("Annotation sheet", "annotation_sheet.csv"),
        ("Benchmark results (JSON)", "benchmark_results.json"),
        ("Benchmark results (synthetic)", "benchmark_results_synthetic.json"),
        ("Ablation results (CSV)", "ablation_results.csv"),
        ("Ablation results (JSON)", "ablation_results.json"),
        ("Ablation table (LaTeX)", "ablation_table.tex"),
    ]

    for desc, filename in output_files:
        filepath = DATA_DIR / filename
        status = "EXISTS" if filepath.is_file() else "  --  "
        print(f"  [{status}] {desc}: {filepath}")

    print()


if __name__ == "__main__":
    main()
