#!/usr/bin/env python3
"""Extract entity mentions from synthetic conversations and prepare for annotation.

Reads JSON conversation files from evaluation/data/synthetic_conversations/,
extracts technology mentions, runs them through the offline entity resolver,
and produces an annotation sheet filtered to interesting (non-obvious) cases.

Usage:
    python -m evaluation.prepare_synthetic_annotation [--conversations-dir DIR] [--output PATH] [--max-per-conv N]
"""

import argparse
import csv
import json
import os
import re
import sys
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from models.ontology import CANONICAL_NAMES, get_canonical_name, normalize_entity_name

try:
    from rapidfuzz import fuzz
except ImportError:
    fuzz = None
    print("Warning: rapidfuzz not installed. Fuzzy matching disabled.", file=sys.stderr)


# ── Lookup structures ────────────────────────────────────────────────
_CANONICAL_LOWER = {k.lower(): v for k, v in CANONICAL_NAMES.items()}
_ALL_KNOWN = set()
for _a, _c in CANONICAL_NAMES.items():
    _ALL_KNOWN.add(_a.lower())
    _ALL_KNOWN.add(_c.lower())

_ALL_CANONICAL = sorted(set(CANONICAL_NAMES.values()))

# Regex patterns
_CAMEL_RE = re.compile(r"\b[A-Z][a-z]+(?:[A-Z][a-z]+)+\b")
_TECH_SUFFIX_RE = re.compile(r"\b\w+(?:\.js|\.py|\.rs|\.ts|\.go|\.rb|\.ex)\b", re.IGNORECASE)
_ABBREV_RE = re.compile(r"\b[A-Z]{2,6}\b")
_HYPHEN_RE = re.compile(r"\b[a-zA-Z]+-[a-zA-Z]+(?:-[a-zA-Z]+)*\b")

# Common non-tech abbreviations to exclude
_SKIP_ABBREVS = {
    "THE", "AND", "FOR", "NOT", "BUT", "ARE", "WAS", "HAS", "HAD",
    "CAN", "MAY", "USE", "GET", "SET", "PUT", "RUN", "LET", "TRY",
    "ADD", "ALL", "ANY", "FEW", "HOW", "ITS", "NEW", "OLD", "OUR",
    "SAY", "SHE", "TOO", "WHO", "BOY", "DID", "HER", "HIM", "HIS",
    "MAN", "ONE", "OWN", "SO", "IF", "OR", "NO", "UP", "DO", "ON",
    "YES", "WAY", "DAY", "GOT", "END", "BIG", "BAD", "TOP", "LOW",
    "PRO", "CON", "ETC", "BTW", "FYI", "IMO", "TBH",
}


def extract_mentions(text: str, conv_id: str) -> list[dict]:
    """Extract technology entity mentions from text."""
    if not text or len(text) < 10:
        return []

    mentions = []
    seen = set()

    def add(mention: str, start: int, method: str):
        key = (mention.lower(), start // 50)
        if key in seen:
            return
        if len(mention) < 2:
            return
        seen.add(key)

        # Get context (100 chars before and after)
        ctx_start = max(0, start - 150)
        ctx_end = min(len(text), start + len(mention) + 150)
        context = text[ctx_start:ctx_end].replace("\n", " ").strip()

        mentions.append({
            "mention_id": str(uuid4())[:8],
            "conversation_id": conv_id,
            "mention_text": mention,
            "conversation_context": context,
            "extraction_method": method,
        })

    # 1. Match against canonical names (case-insensitive)
    text_lower = text.lower()
    for alias, canonical in CANONICAL_NAMES.items():
        alias_lower = alias.lower()
        idx = 0
        while True:
            pos = text_lower.find(alias_lower, idx)
            if pos == -1:
                break
            # Check word boundary
            before_ok = pos == 0 or not text[pos - 1].isalnum()
            after_pos = pos + len(alias)
            after_ok = after_pos >= len(text) or not text[after_pos].isalnum()
            if before_ok and after_ok:
                actual = text[pos:pos + len(alias)]
                add(actual, pos, f"canonical_match:{canonical}")
            idx = pos + 1

    # 2. CamelCase
    for m in _CAMEL_RE.finditer(text):
        add(m.group(), m.start(), "camelcase")

    # 3. Tech suffixes (.js, .py, etc.)
    for m in _TECH_SUFFIX_RE.finditer(text):
        add(m.group(), m.start(), "tech_suffix")

    # 4. Abbreviations (2-6 uppercase chars)
    for m in _ABBREV_RE.finditer(text):
        word = m.group()
        if word not in _SKIP_ABBREVS and word.lower() in _ALL_KNOWN:
            add(word, m.start(), "abbreviation")

    # 5. Hyphenated tech names
    for m in _HYPHEN_RE.finditer(text):
        word = m.group()
        if word.lower() in _ALL_KNOWN:
            add(word, m.start(), "hyphenated")

    return mentions


def resolve_offline(mention: str) -> tuple[str, float, str]:
    """Offline entity resolution simulation. Returns (predicted, confidence, stage)."""
    normalized = mention.strip().lower()

    # Stage 2: Exact match
    for canonical in _ALL_CANONICAL:
        if normalized == canonical.lower():
            return canonical, 1.0, "exact"

    # Stage 3: Canonical lookup
    canon = get_canonical_name(mention)
    if canon.lower() != normalized:
        return canon, 0.95, "canonical"

    # Stage 4: Alias (check if it's a known alias)
    if normalized in _CANONICAL_LOWER:
        return _CANONICAL_LOWER[normalized], 0.92, "alias"

    # Stage 5: Fuzzy match
    if fuzz is not None:
        best_score = 0
        best_match = ""
        for canonical in _ALL_CANONICAL:
            score = fuzz.ratio(normalized, canonical.lower())
            if score > best_score:
                best_score = score
                best_match = canonical
        if best_score >= 85:
            return best_match, best_score / 100.0, "fuzzy"

    # Stage 7: Create new
    return normalize_entity_name(mention), 1.0, "new"


def main():
    parser = argparse.ArgumentParser(
        description="Prepare annotation sheet from synthetic conversations."
    )
    parser.add_argument(
        "--conversations-dir",
        type=str,
        default=str(Path(__file__).resolve().parent / "data" / "synthetic_conversations"),
    )
    parser.add_argument(
        "--output",
        type=str,
        default=str(Path(__file__).resolve().parent / "data" / "synthetic_annotation_sheet.csv"),
    )
    parser.add_argument(
        "--max-per-conv",
        type=int,
        default=20,
        help="Max mentions to extract per conversation",
    )
    parser.add_argument(
        "--skip-obvious",
        action="store_true",
        default=True,
        help="Pre-filter obvious exact matches",
    )
    args = parser.parse_args()

    conv_dir = Path(args.conversations_dir)
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if not conv_dir.is_dir():
        print(f"Error: Conversations directory not found: {conv_dir}", file=sys.stderr)
        sys.exit(1)

    # Process all conversation files
    all_mentions = []
    conv_files = sorted(conv_dir.glob("conv-*.json"))
    print(f"Found {len(conv_files)} conversation files")

    for conv_file in conv_files:
        try:
            with open(conv_file, encoding="utf-8") as f:
                conv = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            print(f"  Skipping {conv_file.name}: {e}", file=sys.stderr)
            continue

        conv_id = conv.get("id", conv_file.stem)

        # Concatenate all message text
        full_text = ""
        for msg in conv.get("messages", []):
            content = msg.get("content", "")
            full_text += content + "\n\n"

        # Extract mentions
        mentions = extract_mentions(full_text, conv_id)

        # Limit per conversation
        if args.max_per_conv and len(mentions) > args.max_per_conv:
            mentions = mentions[:args.max_per_conv]

        # Resolve each mention
        for m in mentions:
            predicted, confidence, stage = resolve_offline(m["mention_text"])
            m["pipeline_predicted"] = predicted
            m["pipeline_confidence"] = f"{confidence:.2f}"
            m["pipeline_stage"] = stage
            m["annotator_judgment"] = ""

        all_mentions.extend(mentions)

    print(f"Extracted {len(all_mentions)} total mentions")

    # Optionally filter obvious cases
    if args.skip_obvious:
        interesting = []
        auto_correct = 0
        for m in all_mentions:
            if m["pipeline_stage"] == "exact" and float(m["pipeline_confidence"]) >= 1.0:
                m["annotator_judgment"] = "CORRECT"
                auto_correct += 1
            else:
                interesting.append(m)
        print(f"Auto-marked {auto_correct} exact matches as CORRECT")
        print(f"{len(interesting)} mentions need manual annotation")

    # Write output
    fieldnames = [
        "mention_id", "conversation_id", "mention_text",
        "conversation_context", "pipeline_predicted",
        "pipeline_confidence", "pipeline_stage", "annotator_judgment",
    ]

    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(all_mentions)

    print(f"\nSaved annotation sheet to {output_path}")
    print(f"\nTo annotate, run:")
    print(f"  cd apps/api && .venv/bin/python -m evaluation.annotate_cli "
          f"--input {output_path}")


if __name__ == "__main__":
    main()
