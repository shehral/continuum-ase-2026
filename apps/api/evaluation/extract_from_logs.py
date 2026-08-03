"""Extract entity mentions from Claude Code JSONL conversation logs.

Parses conversation logs from ~/.claude/projects/-Users-shehral-continuum/,
extracts technology mentions using regex heuristics matched against the
canonical names dictionary, and outputs a CSV for downstream annotation.

Usage:
    python -m evaluation.extract_from_logs [--logs-dir DIR] [--output PATH]
"""

import argparse
import csv
import json
import os
import re
import sys
from pathlib import Path

# Allow imports from the parent apps/api directory
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from models.ontology import CANONICAL_NAMES

# Build lookup structures from the canonical names dictionary
_CANONICAL_LOWER = {k.lower(): v for k, v in CANONICAL_NAMES.items()}
_ALL_KNOWN_NAMES: set[str] = set()
for alias, canonical in CANONICAL_NAMES.items():
    _ALL_KNOWN_NAMES.add(alias.lower())
    _ALL_KNOWN_NAMES.add(canonical.lower())

# Pre-compile regex patterns for technology mentions
# CamelCase words (e.g., FastAPI, PostgreSQL, TypeORM)
_CAMEL_CASE_RE = re.compile(r"\b[A-Z][a-z]+(?:[A-Z][a-z]+)+\b")
# Words ending in common tech suffixes
_TECH_SUFFIX_RE = re.compile(
    r"\b\w+(?:\.js|\.py|\.rs|\.ts|\.go|\.rb|\.ex)\b", re.IGNORECASE
)
# Uppercase abbreviations (2-6 chars, e.g., AWS, GCP, JWT, OIDC)
_ABBREV_RE = re.compile(r"\b[A-Z]{2,6}\b")
# Hyphenated tech names (e.g., scikit-learn, docker-compose, next-auth)
_HYPHEN_TECH_RE = re.compile(r"\b[a-zA-Z]+-[a-zA-Z]+(?:-[a-zA-Z]+)*\b")

# Default logs directory — ONLY Continuum project logs are permitted.
# Logs from any other project are private and must NOT be used.
DEFAULT_LOGS_DIR = os.path.expanduser(
    "~/.claude/projects/-Users-shehral-continuum"
)
ALLOWED_PROJECT_DIRS = {
    os.path.expanduser("~/.claude/projects/-Users-shehral-continuum"),
}


def _extract_text_from_message(msg: dict) -> str | None:
    """Extract plain text content from a JSONL message object.

    Handles both string content and list-of-blocks content structures.
    Returns None if no usable text is found.
    """
    message_body = msg.get("message", {})
    content = message_body.get("content")

    if content is None:
        return None

    if isinstance(content, str):
        return content

    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "text":
                parts.append(block.get("text", ""))
            elif block.get("type") == "thinking":
                # Include thinking content as it often mentions technologies
                parts.append(block.get("thinking", ""))
        return "\n".join(parts) if parts else None

    return None


def _split_sentences(text: str) -> list[str]:
    """Split text into sentences (simple heuristic)."""
    # Split on sentence-ending punctuation followed by whitespace or end
    sentences = re.split(r"(?<=[.!?])\s+", text)
    return [s.strip() for s in sentences if s.strip()]


def _get_context_snippet(text: str, match_start: int, match_end: int) -> str:
    """Extract ~2 sentences of context around a match position."""
    sentences = _split_sentences(text)
    if not sentences:
        # Fall back to character window
        start = max(0, match_start - 200)
        end = min(len(text), match_end + 200)
        return text[start:end].strip()

    # Find which sentence contains the match
    pos = 0
    target_idx = 0
    for i, sent in enumerate(sentences):
        sent_start = text.find(sent, pos)
        if sent_start == -1:
            continue
        sent_end = sent_start + len(sent)
        if sent_start <= match_start < sent_end:
            target_idx = i
            break
        pos = sent_end

    # Take 2 sentences before and 2 after
    start_idx = max(0, target_idx - 2)
    end_idx = min(len(sentences), target_idx + 3)
    return " ".join(sentences[start_idx:end_idx])


def extract_mentions_from_text(
    text: str, conversation_id: str
) -> list[dict]:
    """Extract technology mentions from a text block.

    Returns list of dicts with keys:
        conversation_id, mention_text, context_snippet, position, extracted_type
    """
    if not text or len(text) < 5:
        return []

    mentions: list[dict] = []
    seen: set[tuple[str, int]] = set()  # (mention_lower, rough_position)

    def _add_mention(
        mention: str, start: int, end: int, extracted_type: str
    ) -> None:
        key = (mention.lower(), start // 100)  # Deduplicate within 100-char windows
        if key in seen:
            return
        seen.add(key)
        context = _get_context_snippet(text, start, end)
        mentions.append(
            {
                "conversation_id": conversation_id,
                "mention_text": mention,
                "context_snippet": context[:500],  # Cap context length
                "position": start,
                "extracted_type": extracted_type,
            }
        )

    # Strategy 1: Match against known canonical names and aliases
    text_lower = text.lower()
    for alias in sorted(_ALL_KNOWN_NAMES, key=len, reverse=True):
        # Only match as whole word
        pattern = re.compile(r"\b" + re.escape(alias) + r"\b", re.IGNORECASE)
        for m in pattern.finditer(text):
            canonical = _CANONICAL_LOWER.get(alias, alias)
            _add_mention(m.group(), m.start(), m.end(), f"canonical_match:{canonical}")

    # Strategy 2: CamelCase words (potential technology names)
    for m in _CAMEL_CASE_RE.finditer(text):
        _add_mention(m.group(), m.start(), m.end(), "camel_case")

    # Strategy 3: Tech suffix patterns (.js, .py, etc.)
    for m in _TECH_SUFFIX_RE.finditer(text):
        _add_mention(m.group(), m.start(), m.end(), "tech_suffix")

    # Strategy 4: Known abbreviations (only if they appear in CANONICAL_NAMES)
    for m in _ABBREV_RE.finditer(text):
        word = m.group()
        if word.lower() in _ALL_KNOWN_NAMES:
            canonical = _CANONICAL_LOWER.get(word.lower(), word)
            _add_mention(word, m.start(), m.end(), f"abbreviation:{canonical}")

    # Strategy 5: Hyphenated tech names
    for m in _HYPHEN_TECH_RE.finditer(text):
        word = m.group()
        if word.lower() in _ALL_KNOWN_NAMES:
            canonical = _CANONICAL_LOWER.get(word.lower(), word)
            _add_mention(word, m.start(), m.end(), f"hyphenated:{canonical}")

    return mentions


def is_main_conversation(filepath: Path) -> bool:
    """Check if a JSONL file is a main conversation (not a subagent).

    Subagent conversations are typically in subdirectories (UUID folders).
    Main conversations are JSONL files directly in the project directory.
    """
    return filepath.suffix == ".jsonl" and filepath.parent.name.startswith("-Users-")


def process_conversation(filepath: Path) -> list[dict]:
    """Process a single JSONL conversation file and extract mentions."""
    conversation_id = filepath.stem
    all_mentions: list[dict] = []

    try:
        with open(filepath, "r", encoding="utf-8") as f:
            for line_num, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue

                msg_type = obj.get("type", "")
                if msg_type not in ("user", "assistant"):
                    continue

                text = _extract_text_from_message(obj)
                if not text:
                    continue

                mentions = extract_mentions_from_text(text, conversation_id)
                all_mentions.extend(mentions)

    except (OSError, PermissionError) as exc:
        print(f"  Warning: Could not read {filepath}: {exc}", file=sys.stderr)

    return all_mentions


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Extract entity mentions from Claude Code conversation logs."
    )
    parser.add_argument(
        "--logs-dir",
        type=str,
        default=DEFAULT_LOGS_DIR,
        help=f"Directory containing JSONL logs (default: {DEFAULT_LOGS_DIR})",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=str(
            Path(__file__).resolve().parent / "data" / "extracted_mentions.csv"
        ),
        help="Output CSV path (default: evaluation/data/extracted_mentions.csv)",
    )
    parser.add_argument(
        "--max-files",
        type=int,
        default=0,
        help="Maximum number of conversation files to process (0 = all)",
    )
    args = parser.parse_args()

    logs_dir = Path(args.logs_dir)
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if not logs_dir.is_dir():
        print(f"Error: Logs directory not found: {logs_dir}", file=sys.stderr)
        sys.exit(1)

    # Privacy safeguard: only allow approved project directories
    resolved = str(logs_dir.resolve())
    if not any(resolved.startswith(d) for d in ALLOWED_PROJECT_DIRS):
        print(
            f"Error: '{resolved}' is not an allowed project directory.\n"
            f"Only these projects may be used: {ALLOWED_PROJECT_DIRS}",
            file=sys.stderr,
        )
        sys.exit(1)

    # Find main conversation JSONL files (not in subdirectories)
    jsonl_files = sorted(
        [f for f in logs_dir.iterdir() if is_main_conversation(f)],
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )

    if not jsonl_files:
        print(f"No JSONL conversation files found in {logs_dir}", file=sys.stderr)
        sys.exit(1)

    if args.max_files > 0:
        jsonl_files = jsonl_files[: args.max_files]

    print(f"Processing {len(jsonl_files)} conversation files from {logs_dir}")

    all_mentions: list[dict] = []
    for i, filepath in enumerate(jsonl_files, 1):
        print(f"  [{i}/{len(jsonl_files)}] {filepath.name}", end="")
        mentions = process_conversation(filepath)
        all_mentions.extend(mentions)
        print(f" -> {len(mentions)} mentions")

    # Deduplicate across conversations (same mention_text + same context)
    seen_keys: set[str] = set()
    unique_mentions: list[dict] = []
    for m in all_mentions:
        key = f"{m['conversation_id']}:{m['mention_text'].lower()}:{m['position']}"
        if key not in seen_keys:
            seen_keys.add(key)
            unique_mentions.append(m)

    # Write output
    fieldnames = [
        "conversation_id",
        "mention_text",
        "context_snippet",
        "position",
        "extracted_type",
    ]
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(unique_mentions)

    print(f"\nExtracted {len(unique_mentions)} unique mentions "
          f"(from {len(all_mentions)} raw matches)")
    print(f"Saved to {output_path}")


if __name__ == "__main__":
    main()
