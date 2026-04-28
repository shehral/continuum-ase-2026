#!/usr/bin/env python3
"""Interactive CLI annotation tool for entity resolution evaluation.

Presents entity mentions one at a time with context and the pipeline's
prediction. The annotator types a quick judgment for each mention.

Usage:
    python -m evaluation.annotate_cli [--input PATH] [--output PATH] [--resume]

Controls:
    y        → CORRECT (pipeline prediction is right)
    n:Entity → WRONG (correct entity is "Entity")
    a        → AMBIGUOUS (can't tell from context)
    s        → NOT_ENTITY (not a real software entity)
    q        → QUIT and save progress
    u        → UNDO last judgment
    ?        → Show help

Progress is auto-saved after every judgment. Use --resume to continue
where you left off.
"""

import argparse
import csv
import json
import os
import sys
from pathlib import Path

# Allow imports from parent
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


# ── ANSI colors ──────────────────────────────────────────────────────
BOLD = "\033[1m"
DIM = "\033[2m"
RED = "\033[91m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
BLUE = "\033[94m"
MAGENTA = "\033[95m"
CYAN = "\033[96m"
RESET = "\033[0m"


def load_annotations(path: Path) -> list[dict]:
    """Load annotation CSV."""
    rows = []
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)
    return rows


def save_annotations(rows: list[dict], path: Path) -> None:
    """Save annotation CSV preserving all columns."""
    if not rows:
        return
    fieldnames = list(rows[0].keys())
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def truncate_context(ctx: str, max_len: int = 300) -> str:
    """Truncate context to readable length."""
    ctx = ctx.replace("\n", " ").strip()
    if len(ctx) > max_len:
        return ctx[:max_len] + "..."
    return ctx


def display_mention(row: dict, index: int, total: int, remaining: int) -> None:
    """Display a single mention for annotation."""
    print(f"\n{'─' * 60}")
    print(f"{DIM}[{index + 1}/{total}] {remaining} remaining{RESET}")
    print()

    mention = row.get("mention_text", "???")
    predicted = row.get("pipeline_predicted", "???")
    confidence = row.get("pipeline_confidence", "???")
    stage = row.get("pipeline_stage", "???")
    context = row.get("conversation_context", row.get("context_snippet", ""))

    print(f"  {BOLD}Mention:{RESET}    {CYAN}{mention}{RESET}")
    print(f"  {BOLD}Predicted:{RESET}  {YELLOW}{predicted}{RESET}  "
          f"{DIM}(confidence: {confidence}, stage: {stage}){RESET}")
    print()

    if context:
        # Highlight the mention in the context
        highlighted = context
        if mention in context:
            highlighted = context.replace(
                mention, f"{RED}{BOLD}{mention}{RESET}", 1
            )
        print(f"  {BOLD}Context:{RESET}")
        print(f"  {DIM}{truncate_context(highlighted)}{RESET}")
    print()


def display_help() -> None:
    """Show help text."""
    print(f"""
{BOLD}Annotation Commands:{RESET}
  {GREEN}y{RESET}          CORRECT — the pipeline's prediction is right
  {RED}n:Entity{RESET}   WRONG — type the correct entity name after 'n:'
  {YELLOW}a{RESET}          AMBIGUOUS — genuinely can't tell from context
  {MAGENTA}s{RESET}          NOT_ENTITY — this isn't a real software entity
  {BLUE}u{RESET}          UNDO — go back to the previous mention
  {DIM}q{RESET}          QUIT — save progress and exit
  {DIM}?{RESET}          Show this help
""")


def display_stats(rows: list[dict]) -> None:
    """Show annotation progress stats."""
    total = len(rows)
    done = sum(1 for r in rows if r.get("annotator_judgment", "").strip())
    correct = sum(1 for r in rows if r.get("annotator_judgment", "").startswith("CORRECT"))
    wrong = sum(1 for r in rows if r.get("annotator_judgment", "").startswith("WRONG"))
    ambiguous = sum(1 for r in rows if r.get("annotator_judgment", "") == "AMBIGUOUS")
    not_entity = sum(1 for r in rows if r.get("annotator_judgment", "") == "NOT_ENTITY")

    print(f"\n{BOLD}Progress:{RESET} {done}/{total} annotated "
          f"({done * 100 // total if total > 0 else 0}%)")
    if done > 0:
        print(f"  {GREEN}CORRECT: {correct}{RESET}  "
              f"{RED}WRONG: {wrong}{RESET}  "
              f"{YELLOW}AMBIGUOUS: {ambiguous}{RESET}  "
              f"{MAGENTA}NOT_ENTITY: {not_entity}{RESET}")
        if correct + wrong > 0:
            accuracy = correct / (correct + wrong) * 100
            print(f"  Pipeline accuracy (excl. ambiguous): {accuracy:.1f}%")


def filter_interesting(rows: list[dict]) -> list[int]:
    """Return indices of mentions worth annotating (skip obvious ones)."""
    interesting = []
    for i, row in enumerate(rows):
        # Skip if already annotated
        if row.get("annotator_judgment", "").strip():
            continue

        confidence = float(row.get("pipeline_confidence", 0))
        stage = row.get("pipeline_stage", "")

        # Skip obvious exact matches with high confidence
        # (these are almost always correct)
        if stage == "exact" and confidence >= 1.0:
            # Auto-mark as correct
            row["annotator_judgment"] = "CORRECT"
            continue

        interesting.append(i)

    return interesting


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Interactive CLI annotation tool for entity resolution."
    )
    parser.add_argument(
        "--input",
        type=str,
        default=str(
            Path(__file__).resolve().parent / "data" / "annotation_sheet.csv"
        ),
        help="Input annotation CSV (default: evaluation/data/annotation_sheet.csv)",
    )
    parser.add_argument(
        "--output",
        type=str,
        default="",
        help="Output CSV path (default: overwrites input with judgments added)",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Resume from where you left off (skip already-annotated rows)",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Show ALL mentions (don't skip obvious exact matches)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Maximum number of mentions to annotate (0 = all)",
    )
    args = parser.parse_args()

    input_path = Path(args.input)
    output_path = Path(args.output) if args.output else input_path

    if not input_path.exists():
        print(f"Error: Input file not found: {input_path}", file=sys.stderr)
        sys.exit(1)

    # Load data
    rows = load_annotations(input_path)
    total = len(rows)
    print(f"\n{BOLD}Entity Resolution Annotation Tool{RESET}")
    print(f"Loaded {total} mentions from {input_path.name}")

    # Filter to interesting mentions (or all if --all)
    if args.all:
        pending_indices = [
            i for i, r in enumerate(rows)
            if not r.get("annotator_judgment", "").strip()
        ]
    else:
        pending_indices = filter_interesting(rows)
        auto_marked = total - len(pending_indices) - sum(
            1 for r in rows if r.get("annotator_judgment", "").strip()
            and r["annotator_judgment"] != "CORRECT"
        )

    if args.limit > 0:
        pending_indices = pending_indices[:args.limit]

    remaining = len(pending_indices)
    print(f"{remaining} mentions need your judgment")

    if not args.all:
        auto_count = sum(1 for r in rows if r.get("annotator_judgment") == "CORRECT")
        print(f"{DIM}({auto_count} obvious exact matches auto-marked as CORRECT){RESET}")

    display_help()
    display_stats(rows)

    # Annotation loop
    cursor = 0
    history: list[int] = []  # for undo

    while cursor < len(pending_indices):
        idx = pending_indices[cursor]
        row = rows[idx]

        display_mention(row, cursor, len(pending_indices),
                       len(pending_indices) - cursor)

        try:
            response = input(f"  {BOLD}Judgment:{RESET} ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n\nSaving and exiting...")
            break

        if not response:
            continue

        if response == "?":
            display_help()
            continue

        if response.lower() == "q":
            print("Saving and exiting...")
            break

        if response.lower() == "u":
            if history:
                prev_cursor = history.pop()
                prev_idx = pending_indices[prev_cursor]
                rows[prev_idx]["annotator_judgment"] = ""
                cursor = prev_cursor
                print(f"{YELLOW}Undid last judgment. Back to mention {prev_cursor + 1}.{RESET}")
            else:
                print(f"{RED}Nothing to undo.{RESET}")
            continue

        # Parse judgment
        judgment = ""
        if response.lower() == "y":
            judgment = "CORRECT"
            print(f"  {GREEN}  CORRECT{RESET}")
        elif response.lower().startswith("n:"):
            correct_entity = response[2:].strip()
            if not correct_entity:
                print(f"{RED}Please specify the correct entity: n:EntityName{RESET}")
                continue
            judgment = f"WRONG: {correct_entity}"
            print(f"  {RED}  WRONG → {correct_entity}{RESET}")
        elif response.lower() == "n":
            print(f"{RED}Please specify the correct entity: n:EntityName{RESET}")
            continue
        elif response.lower() == "a":
            judgment = "AMBIGUOUS"
            print(f"  {YELLOW}  AMBIGUOUS{RESET}")
        elif response.lower() == "s":
            judgment = "NOT_ENTITY"
            print(f"  {MAGENTA}  NOT_ENTITY{RESET}")
        else:
            print(f"{RED}Unknown command: '{response}'. Type ? for help.{RESET}")
            continue

        # Record judgment
        row["annotator_judgment"] = judgment
        history.append(cursor)
        cursor += 1

        # Auto-save every 10 annotations
        if cursor % 10 == 0:
            save_annotations(rows, output_path)
            print(f"{DIM}  (auto-saved){RESET}")

    # Final save
    save_annotations(rows, output_path)
    display_stats(rows)
    print(f"\nSaved to {output_path}")
    print(f"{BOLD}Thank you for annotating!{RESET}\n")


if __name__ == "__main__":
    main()
