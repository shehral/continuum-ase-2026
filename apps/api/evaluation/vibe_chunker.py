"""Segment the recovered Vibe Voyager Claude Code session into decision-bearing chunks.

Input: ~/.claude/projects/-Users-shehral-vibe/af736a61-19c5-4b5e-87c6-b2175d6cb964.jsonl
       (3,299 lines; 576 user + 792 assistant turns; 2026-03-08 06:10-20:50 UTC)

Output: apps/api/evaluation/data/v5/vibe_chunks/
  - chunk_01.jsonl, chunk_02.jsonl, ... (one self-contained sub-conversation each)
  - index.json (metadata: timestamps, message counts, first user prompt, topic guess)

Segmentation rule: idle gap >= 15 minutes between consecutive user/assistant events
starts a new chunk.  Chunks with fewer than 4 messages are dropped (too thin to
contain a decision).

Secret scrubbing: regex passes strip API keys, bearer tokens, password-bearing
lines, and raw .env content before any chunk is written.  The scrubbing is
conservative -- it prefers false positives (replacing something benign) over
false negatives (leaking a secret into the paper).

Run from apps/api/ after activating the venv:
    .venv/bin/python -m evaluation.vibe_chunker
"""

from __future__ import annotations

import json
import re
from collections import Counter
from datetime import datetime
from pathlib import Path

VIBE_PROJECT_DIR = Path.home() / ".claude/projects/-Users-shehral-vibe"
MAIN_SESSION = VIBE_PROJECT_DIR / "af736a61-19c5-4b5e-87c6-b2175d6cb964.jsonl"
SUBAGENT_DIR = VIBE_PROJECT_DIR / "af736a61-19c5-4b5e-87c6-b2175d6cb964" / "subagents"
OUT_DIR = Path(__file__).parent / "data" / "v5" / "vibe_chunks"
# Skip subagent files below this size -- they're typically trivial scratch /
# "check if X exists" callouts with no decision content.
MIN_SUBAGENT_BYTES = 30_000

# Subagent files to drop entirely (by source filename), per author direction.
# These contain content or topics we do not want in the open-sourced artifact.
SUBAGENT_FILE_BLACKLIST: set[str] = set()
# A subagent that pulled content from the Continuum repo -- the author asked
# to exclude it so the case study doesn't accidentally reference Continuum's
# internal structure. Actual filename is resolved at runtime by topic match.

# Chunk topics whose presence means we skip the chunk wholesale (detected by
# matching the first user prompt against the substring).
TOPIC_BLACKLIST: tuple[str, ...] = (
    "explore /Users/shehral/continuum",  # exploring Continuum repo
    "explore /users/shehral/continuum",
)

IDLE_GAP_SECONDS = 5 * 60          # break preference at >= 5 min idle
TARGET_USER_TURNS_PER_CHUNK = 30   # force-split large chunks at this boundary
MIN_MESSAGES_PER_CHUNK = 4


# --- Secret scrubbing ---------------------------------------------------------
# Order matters: match longer/more specific patterns first.
# --- Path / identity scrubbing -----------------------------------------------
# "vibe" is public (github.com/shehral/vibe) so paths inside it are safe to
# publish. Any OTHER first-level directory under /Users/shehral/ is treated as
# private and the rest of the path is redacted.
_VIBE_ROOT_RE = re.compile(r"/Users/shehral/vibe(?=/|\b)")
_OTHER_PROJECT_RE = re.compile(r"/Users/shehral/([A-Za-z0-9_.-]+)(/[^\s\"'`]*)?")
_USER_HOME_RE = re.compile(r"/Users/shehral(?=/|\b)")

# Bare project names / personal domains that appear in prose and need redaction.
# Keep "vibe" (and "Vibe Voyager") intact because the project is public.
PRIVATE_PROJECT_NAMES = [
    "cs5008-guide", "cs5008", "CS5008", "CS5008-guide",
    "CS6120", "cs6120",
    "CS5330", "cs5330", "CS5330-Su25",
    "CS5001",
    "signatureassignment",
    "continuum-nlp", "continuum-guide",
    # NOTE: "continuum" itself is the host project -- not redacted because
    # the paper's repo is named continuum and will be public at submission.
    "theoria-web", "theoria-private",
    "research-posters",
    "my-website",
    "nexus",
    "aria",
    "CTCD", "ctcd",
    "Resume",
    "eid",
    "wpm",
    "Forge",
    "Desktop-SV-Courses-5330",
]

# Build a single-pass regex for project-name occurrences in prose.
# Matches the name as a whole word (or with common suffixes like .com, /, etc.).
# Ordered longest-first so longer names take precedence over shorter prefixes.
_NAME_RE = re.compile(
    r"\b(" + "|".join(sorted((re.escape(n) for n in PRIVATE_PROJECT_NAMES), key=len, reverse=True)) + r")\b"
)

# Author's personal domain -- redact any subdomain-or-root reference.
_SHEHRAL_DOMAIN_RE = re.compile(r"\b(?:[a-z0-9-]+\.)?shehral\.com\b", re.IGNORECASE)

# GitHub URLs under github.com/shehral/<repo> -- redact all except /vibe.
_GITHUB_RE = re.compile(r"\bgithub\.com/shehral/([A-Za-z0-9._-]+)", re.IGNORECASE)


def scrub_paths(text: str) -> str:
    """Replace absolute filesystem paths to privatize the transcript.

    - /Users/shehral/vibe/... -> /home/dev/vibe/...  (public project, safe)
    - /Users/shehral/<other>/... -> /home/dev/[REDACTED_PROJECT]/...
    - /Users/shehral -> /home/dev (bare home references)

    Order matters: match vibe first, then other-project patterns, then bare home.
    """
    if not text:
        return text
    text = _VIBE_ROOT_RE.sub("/home/dev/vibe", text)

    def _other(m: re.Match[str]) -> str:
        project = m.group(1)
        # A handful of things under ~/ are not private-project names.
        if project in {"vibe", "Downloads", "Desktop"}:
            tail = m.group(2) or ""
            return f"/home/dev/{project}{tail}"
        # Everything else becomes a redacted project.
        return "/home/dev/[REDACTED_PROJECT]"

    text = _OTHER_PROJECT_RE.sub(_other, text)
    text = _USER_HOME_RE.sub("/home/dev", text)

    # Personal domain (e.g., cs5008.shehral.com) -> [REDACTED_DOMAIN]
    text = _SHEHRAL_DOMAIN_RE.sub("[REDACTED_DOMAIN]", text)

    # GitHub repos under github.com/shehral/ -> keep vibe only, redact others
    def _gh(m: re.Match[str]) -> str:
        repo = m.group(1)
        if repo.lower() == "vibe":
            return f"github.com/shehral/{repo}"
        return "github.com/[AUTHOR]/[REDACTED_REPO]"

    text = _GITHUB_RE.sub(_gh, text)

    # Bare private-project-name references in prose (e.g., "cs5008-guide",
    # "nexus") -> [REDACTED_PROJECT]. Keeps the reasoning intact but strips
    # the identifiers.
    text = _NAME_RE.sub("[REDACTED_PROJECT]", text)

    return text


# Tool result markers: when a tool_result block exceeds this many characters and
# references a non-vibe path, we replace the whole content with a short notice.
LARGE_TOOL_RESULT_THRESHOLD = 200
EXTERNAL_PROJECT_MARKERS = (
    "[REDACTED_PROJECT]",  # produced by scrub_paths above
)


SECRET_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    # AWS access keys (20-char AK...) + secret keys (40-char base64ish)
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "[REDACTED_AWS_KEY]"),
    (re.compile(r"(?<![A-Za-z0-9])[A-Za-z0-9/+=]{40}(?![A-Za-z0-9/+=])"), "[REDACTED_LONG_TOKEN]"),
    # OpenAI / Anthropic / generic sk- tokens
    (re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"), "[REDACTED_SK_TOKEN]"),
    # Bearer tokens in headers or strings
    (re.compile(r"(?i)bearer\s+[A-Za-z0-9\-_.=]{20,}"), "Bearer [REDACTED_BEARER]"),
    # Explicit key/secret/password assignments
    (re.compile(r"(?i)(api[_-]?key|secret[_-]?key|access[_-]?token|auth[_-]?token|password|passwd|pwd|token)\s*[:=]\s*[\"']?[^\s\"']{6,}[\"']?"),
     lambda m: f"{m.group(1)}=[REDACTED]"),
    # .env-style lines with an = assignment and an uppercase-snake-case key
    (re.compile(r"\b([A-Z][A-Z0-9_]{4,}_(?:KEY|SECRET|TOKEN|PASSWORD|PWD))\s*=\s*\S+"),
     lambda m: f"{m.group(1)}=[REDACTED]"),
    # JWT-like three-segment base64 tokens
    (re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b"), "[REDACTED_JWT]"),
    # Long hex tokens (likely fingerprints / session ids in code)
    (re.compile(r"\b[a-fA-F0-9]{40,}\b"), "[REDACTED_HEX]"),
]


def scrub(text: str) -> str:
    """Apply path scrubbing + all secret-scrubbing regexes.

    Safe to call repeatedly. Returns text unchanged on error.
    """
    if not text:
        return text
    text = scrub_paths(text)
    for pat, repl in SECRET_PATTERNS:
        try:
            text = pat.sub(repl, text)
        except Exception:
            continue
    return text


def redact_large_external_tool_result(content: str | list | None) -> str | list | None:
    """If a tool_result contains external-project content, replace it with a
    short marker.  This prevents raw file contents from non-vibe projects from
    appearing in the open-sourced transcripts while preserving the STRUCTURE
    (the extraction LLM still sees 'a tool was called, got a result')."""
    if content is None:
        return None
    if isinstance(content, str):
        if len(content) > LARGE_TOOL_RESULT_THRESHOLD and any(m in content for m in EXTERNAL_PROJECT_MARKERS):
            return "[REDACTED: file content from an external project]"
        return content
    if isinstance(content, list):
        new: list = []
        for b in content:
            if isinstance(b, dict) and b.get("type") == "text":
                t = b.get("text", "")
                if len(t) > LARGE_TOOL_RESULT_THRESHOLD and any(m in t for m in EXTERNAL_PROJECT_MARKERS):
                    new.append({**b, "text": "[REDACTED: file content from an external project]"})
                else:
                    new.append(b)
            else:
                new.append(b)
        return new
    return content


# --- Message text extraction -------------------------------------------------
def extract_text(event: dict) -> str:
    """Extract plain-text content from a user or assistant event.

    User messages: message.content is a string or a list of content blocks.
    Assistant messages: message.content is a list of blocks, each with type in
    {text, tool_use, tool_result, thinking}. We keep only text + tool_use name
    (for context) and drop the raw tool_use input to avoid dumping full code
    blocks into the paper's evaluation.
    """
    msg = event.get("message") or {}
    content = msg.get("content")
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    parts: list[str] = []
    if isinstance(content, list):
        for block in content:
            if not isinstance(block, dict):
                continue
            btype = block.get("type")
            if btype == "text":
                parts.append(block.get("text", ""))
            elif btype == "thinking":
                # skip reasoning text -- it's noisy and not decision content
                continue
            elif btype == "tool_use":
                name = block.get("name", "?")
                parts.append(f"[tool_use: {name}]")
            elif btype == "tool_result":
                res = block.get("content")
                if isinstance(res, str):
                    parts.append(f"[tool_result]: {res[:500]}")
                elif isinstance(res, list):
                    texts = [b.get("text", "") for b in res if isinstance(b, dict) and b.get("type") == "text"]
                    if texts:
                        parts.append(f"[tool_result]: {' '.join(texts)[:500]}")
    return "\n".join(p for p in parts if p)


# --- Chunking -----------------------------------------------------------------
def load_events(path: Path) -> list[dict]:
    events = []
    with path.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            if ev.get("type") in ("user", "assistant"):
                events.append(ev)
    return events


def chunk_events(events: list[dict]) -> list[list[dict]]:
    """Group events into decision-bearing chunks.

    Two split criteria combined (whichever triggers first):
      1. Idle gap >= IDLE_GAP_SECONDS between consecutive events.
      2. After TARGET_USER_TURNS_PER_CHUNK user turns accumulate in the current
         chunk, the next user turn starts a new chunk.

    This produces chunks that are (a) topically coherent because natural pauses
    break them, and (b) bounded in size so large continuous runs get subdivided.
    """
    if not events:
        return []
    events.sort(key=lambda e: e.get("timestamp", ""))
    chunks: list[list[dict]] = [[events[0]]]
    user_turns_in_current = 1 if events[0].get("type") == "user" else 0

    for prev, cur in zip(events, events[1:]):
        start_new = False
        try:
            t_prev = datetime.fromisoformat(prev["timestamp"].replace("Z", "+00:00"))
            t_cur = datetime.fromisoformat(cur["timestamp"].replace("Z", "+00:00"))
            if (t_cur - t_prev).total_seconds() >= IDLE_GAP_SECONDS:
                start_new = True
        except (KeyError, ValueError):
            pass

        if (not start_new
                and cur.get("type") == "user"
                and user_turns_in_current >= TARGET_USER_TURNS_PER_CHUNK):
            start_new = True

        if start_new:
            chunks.append([cur])
            user_turns_in_current = 1 if cur.get("type") == "user" else 0
        else:
            chunks[-1].append(cur)
            if cur.get("type") == "user":
                user_turns_in_current += 1

    return [c for c in chunks if len(c) >= MIN_MESSAGES_PER_CHUNK]


SYSTEM_INJECTED_PREFIXES = (
    "<command-", "<local-command", "<system-reminder",
    "Base directory for this skill", "Caveat: The messages below",
    "[Request interrupted", "[tool_result", "<user-memory",
)


def first_user_prompt_raw(chunk: list[dict]) -> str:
    """Return the first real human-looking user prompt in a chunk, UNSCRUBBED.
    Used for blacklist matching and local review only -- never written to the
    open-sourced index."""
    for ev in chunk:
        if ev.get("type") != "user":
            continue
        text = extract_text(ev)
        if not text:
            continue
        stripped = text.strip()
        if any(stripped.startswith(p) for p in SYSTEM_INJECTED_PREFIXES):
            continue
        if stripped.startswith("<") and stripped.split()[0].endswith(">"):
            continue
        return stripped
    for ev in chunk:
        if ev.get("type") == "assistant":
            text = extract_text(ev)
            if text:
                return text.strip()
    return ""


def first_user_prompt(chunk: list[dict]) -> str:
    """Scrubbed version -- safe to publish in the index."""
    return scrub(first_user_prompt_raw(chunk))


def topic_guess(prompt: str, limit: int = 100) -> str:
    """Take the first sentence of the first user prompt as a topic hint."""
    if not prompt:
        return "(no user prompt)"
    clean = re.sub(r"\s+", " ", prompt).strip()
    for sep in (". ", "? ", "! ", "\n"):
        if sep in clean[:limit * 2]:
            clean = clean.split(sep)[0] + sep.strip()
            break
    if len(clean) > limit:
        clean = clean[:limit].rstrip() + "..."
    return clean


def _scrub_tree(obj):
    """Recursively scrub every string value in a JSON-like tree. Keys are not
    modified (structural). This catches leaks in top-level event fields like
    ``cwd``, ``gitBranch``, tool_use input paths, etc."""
    if isinstance(obj, str):
        return scrub(obj)
    if isinstance(obj, list):
        return [_scrub_tree(x) for x in obj]
    if isinstance(obj, dict):
        return {k: _scrub_tree(v) for k, v in obj.items()}
    return obj


def _scrub_chunk(chunk: list[dict]) -> list[dict]:
    """Three-pass scrub:
      pass 1 (recursive): scrub every string value in the entire event tree --
              paths, secrets, project names, domains.
      pass 2: for tool_result content that now contains the [REDACTED_PROJECT]
              marker, replace the whole content with a short notice so the
              structure is preserved but no external file content leaks.
    """
    # Pass 1: recursive string scrub over the whole event tree.
    scrubbed: list[dict] = [_scrub_tree(ev) for ev in chunk]

    # Pass 2: tool_result content that now contains the [REDACTED_PROJECT]
    # marker (i.e., came from an external project file read) gets replaced
    # with a short notice so raw file bodies don't appear in the artifact.
    for ev in scrubbed:
        msg = ev.get("message") or {}
        content = msg.get("content")
        if isinstance(content, list):
            new_blocks = []
            for b in content:
                if isinstance(b, dict) and b.get("type") == "tool_result":
                    new_blocks.append({**b, "content": redact_large_external_tool_result(b.get("content"))})
                else:
                    new_blocks.append(b)
            msg["content"] = new_blocks
    return scrubbed


def _chunk_is_blacklisted(chunk: list[dict]) -> bool:
    """Drop chunks whose RAW first user prompt triggers the TOPIC_BLACKLIST.
    We check the unscrubbed version because the blacklist keys on absolute
    paths that get rewritten by scrub_paths()."""
    prompt = first_user_prompt_raw(chunk) or ""
    low = prompt.lower()
    return any(b in low for b in TOPIC_BLACKLIST)


def _write_chunk(chunk_id: str, chunk: list[dict], source: str) -> dict:
    out_path = OUT_DIR / f"{chunk_id}.jsonl"
    with out_path.open("w") as f:
        for ev in chunk:
            f.write(json.dumps(ev) + "\n")
    users = sum(1 for e in chunk if e.get("type") == "user")
    assts = sum(1 for e in chunk if e.get("type") == "assistant")
    prompt = first_user_prompt(chunk)
    return {
        "id": chunk_id,
        "file": out_path.name,
        "source": source,
        "messages": len(chunk),
        "user_turns": users,
        "assistant_turns": assts,
        "start": chunk[0].get("timestamp", ""),
        "end": chunk[-1].get("timestamp", ""),
        "first_user_prompt": prompt,
        "topic": topic_guess(prompt),
    }


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    # Clean any previous run so the index stays consistent
    for old in OUT_DIR.glob("chunk_*.jsonl"):
        old.unlink()
    old_index = OUT_DIR / "index.json"
    if old_index.exists():
        old_index.unlink()

    index: list[dict] = []
    chunk_counter = 0

    # --- 1. Main session (human-orchestrator dialogue) ---------------------
    main_events = load_events(MAIN_SESSION)
    print(f"Loaded {len(main_events):,} user/assistant events from main session {MAIN_SESSION.name}")
    main_chunks = chunk_events(main_events)
    print(f"Segmented into {len(main_chunks)} main-session chunks "
          f"(idle gap >= {IDLE_GAP_SECONDS//60}min OR >= {TARGET_USER_TURNS_PER_CHUNK} user turns)")
    dropped_blacklist = 0
    for chunk in main_chunks:
        if _chunk_is_blacklisted(chunk):
            dropped_blacklist += 1
            continue
        chunk_counter += 1
        entry = _write_chunk(f"chunk_{chunk_counter:02d}",
                             _scrub_chunk(chunk), "main_session")
        index.append(entry)

    # --- 2. Subagent files (autonomous agent execution) --------------------
    subagent_files = sorted(SUBAGENT_DIR.glob("agent-*.jsonl")) if SUBAGENT_DIR.exists() else []
    print(f"Found {len(subagent_files)} subagent files; processing those >= {MIN_SUBAGENT_BYTES:,} bytes...")
    kept_sub = 0
    for f in subagent_files:
        if f.stat().st_size < MIN_SUBAGENT_BYTES:
            continue
        events = load_events(f)
        if len(events) < MIN_MESSAGES_PER_CHUNK:
            continue
        if _chunk_is_blacklisted(events):
            dropped_blacklist += 1
            continue
        chunk_counter += 1
        entry = _write_chunk(f"chunk_{chunk_counter:02d}",
                             _scrub_chunk(events), "subagent")
        entry["subagent_file"] = f.name
        index.append(entry)
        kept_sub += 1
    print(f"Kept {kept_sub} subagent chunks (dropped {dropped_blacklist} via topic blacklist)")

    (OUT_DIR / "index.json").write_text(json.dumps(index, indent=2))

    # Summary to stdout
    print()
    print("=" * 100)
    print(f"{'#':<9} {'source':<14} {'msgs':>5} {'u':>4} {'a':>4}  {'start':<20} topic")
    print("=" * 100)
    for entry in index:
        topic = (entry["topic"] or "")[:60]
        print(f"{entry['id']:<9} {entry['source']:<14} {entry['messages']:>5} {entry['user_turns']:>4} "
              f"{entry['assistant_turns']:>4}  {entry['start'][:19]:<20} {topic}")
    print()
    total_msgs = sum(e["messages"] for e in index)
    total_u = sum(e["user_turns"] for e in index)
    total_a = sum(e["assistant_turns"] for e in index)
    print(f"Total: {len(index)} chunks, {total_msgs:,} messages ({total_u:,} user + {total_a:,} assistant)")
    main_count = sum(1 for e in index if e["source"] == "main_session")
    sub_count = sum(1 for e in index if e["source"] == "subagent")
    print(f"  {main_count} main-session chunks (orchestrator dialogue)")
    print(f"  {sub_count} subagent chunks (autonomous agent execution)")
    print(f"Wrote to {OUT_DIR}")


if __name__ == "__main__":
    main()
