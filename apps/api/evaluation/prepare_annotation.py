"""Prepare an annotation spreadsheet from extracted mentions.

Runs each extracted mention through an offline simulation of the entity
resolution pipeline (canonical lookup + fuzzy matching) and produces a CSV
with a blank annotator_judgment column for human review.

Usage:
    python -m evaluation.prepare_annotation [--input PATH] [--output PATH]
"""

import argparse
import csv
import sys
from pathlib import Path
from uuid import uuid4

# Allow imports from the parent apps/api directory
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from models.ontology import CANONICAL_NAMES, get_canonical_name, normalize_entity_name

try:
    from rapidfuzz import fuzz
except ImportError:
    fuzz = None  # type: ignore[assignment]
    print(
        "Warning: rapidfuzz not installed. Fuzzy matching will be skipped.",
        file=sys.stderr,
    )


# Build reverse lookup: canonical_name -> set of known aliases
_CANONICAL_TO_ALIASES: dict[str, set[str]] = {}
for _alias, _canonical in CANONICAL_NAMES.items():
    _CANONICAL_TO_ALIASES.setdefault(_canonical, set()).add(_alias.lower())

# All unique canonical names
_ALL_CANONICAL_NAMES: list[str] = sorted(set(CANONICAL_NAMES.values()))

# Default thresholds (matching entity_resolver.py defaults)
DEFAULT_FUZZY_THRESHOLD = 85  # 0-100 scale for rapidfuzz
DEFAULT_EMBEDDING_THRESHOLD = 0.90


class OfflineResolver:
    """Offline entity resolution simulator.

    Implements stages that can run without Neo4j or Redis:
    - Stage 2: Exact match against canonical names dictionary
    - Stage 3: Canonical lookup
    - Stage 4: Alias search against known aliases
    - Stage 5/6: Fuzzy match using rapidfuzz

    Stages 1 (cache) and 7 (embedding) require live infrastructure
    and are skipped in offline mode.
    """

    def __init__(self, fuzzy_threshold: int = DEFAULT_FUZZY_THRESHOLD):
        self.fuzzy_threshold = fuzzy_threshold

    def resolve(self, mention_text: str) -> dict:
        """Resolve a mention to a canonical entity.

        Returns dict with keys: predicted, confidence, stage.
        """
        normalized = normalize_entity_name(mention_text)

        # Stage 2: Exact match — is the normalized text itself a canonical name?
        for canonical in _ALL_CANONICAL_NAMES:
            if canonical.lower() == normalized:
                return {
                    "predicted": canonical,
                    "confidence": 1.0,
                    "stage": "exact",
                }

        # Stage 3: Canonical lookup — check if it is a known alias
        canonical = get_canonical_name(mention_text)
        if canonical.lower() != normalized:
            return {
                "predicted": canonical,
                "confidence": 0.95,
                "stage": "canonical",
            }

        # Stage 4: Alias search — check all alias sets
        for canon_name, aliases in _CANONICAL_TO_ALIASES.items():
            if normalized in aliases:
                return {
                    "predicted": canon_name,
                    "confidence": 0.92,
                    "stage": "alias",
                }

        # Stage 5/6: Fuzzy match (if rapidfuzz available)
        if fuzz is not None:
            best_score = 0
            best_match = None
            for canon_name in _ALL_CANONICAL_NAMES:
                score = fuzz.ratio(normalized, canon_name.lower())
                if score >= self.fuzzy_threshold and score > best_score:
                    best_score = score
                    best_match = canon_name

            if best_match is not None:
                return {
                    "predicted": best_match,
                    "confidence": best_score / 100.0,
                    "stage": "fuzzy",
                }

        # No match found
        return {
            "predicted": "",
            "confidence": 0.0,
            "stage": "unresolved",
        }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Prepare annotation spreadsheet from extracted mentions."
    )
    parser.add_argument(
        "--input",
        type=str,
        default=str(
            Path(__file__).resolve().parent / "data" / "extracted_mentions.csv"
        ),
        help="Input CSV of extracted mentions",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=str(
            Path(__file__).resolve().parent / "data" / "annotation_sheet.csv"
        ),
        help="Output annotation CSV path",
    )
    parser.add_argument(
        "--fuzzy-threshold",
        type=int,
        default=DEFAULT_FUZZY_THRESHOLD,
        help=f"Fuzzy match threshold 0-100 (default: {DEFAULT_FUZZY_THRESHOLD})",
    )
    args = parser.parse_args()

    input_path = Path(args.input)
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if not input_path.is_file():
        print(f"Error: Input file not found: {input_path}", file=sys.stderr)
        print(
            "Run extract_from_logs.py first to generate extracted_mentions.csv",
            file=sys.stderr,
        )
        sys.exit(1)

    resolver = OfflineResolver(fuzzy_threshold=args.fuzzy_threshold)

    # Read input mentions
    with open(input_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        mentions = list(reader)

    print(f"Processing {len(mentions)} mentions through offline resolver...")

    rows: list[dict] = []
    stage_counts: dict[str, int] = {}

    for i, mention in enumerate(mentions, 1):
        mention_text = mention.get("mention_text", "")
        if not mention_text:
            continue

        result = resolver.resolve(mention_text)
        stage = result["stage"]
        stage_counts[stage] = stage_counts.get(stage, 0) + 1

        rows.append(
            {
                "mention_id": str(uuid4())[:8],
                "mention_text": mention_text,
                "conversation_context": mention.get("context_snippet", ""),
                "pipeline_predicted": result["predicted"],
                "pipeline_confidence": f"{result['confidence']:.2f}",
                "pipeline_stage": stage,
                "annotator_judgment": "",  # Left blank for human annotators
            }
        )

        if i % 500 == 0:
            print(f"  Processed {i}/{len(mentions)}")

    # Write annotation spreadsheet
    fieldnames = [
        "mention_id",
        "mention_text",
        "conversation_context",
        "pipeline_predicted",
        "pipeline_confidence",
        "pipeline_stage",
        "annotator_judgment",
    ]
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    # Summary
    print(f"\nAnnotation spreadsheet: {len(rows)} rows")
    print("Resolution stage distribution:")
    for stage, count in sorted(stage_counts.items(), key=lambda x: -x[1]):
        pct = 100.0 * count / len(rows) if rows else 0
        print(f"  {stage:>12s}: {count:>5d}  ({pct:.1f}%)")
    print(f"\nSaved to {output_path}")
    print(
        "Next step: Fill in the 'annotator_judgment' column with the correct "
        "canonical entity name for each mention."
    )


if __name__ == "__main__":
    main()
