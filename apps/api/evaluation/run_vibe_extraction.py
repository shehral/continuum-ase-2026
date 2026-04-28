"""Run decision extraction on the Vibe Voyager case-study chunks.

Reads ``evaluation/data/v5/vibe_chunks/chunk_*.jsonl`` (produced by
``vibe_chunker.py``), converts each to the extractor's expected
``{messages: [{role, content}, ...]}`` format, and runs the LLM-based
decision extractor on every chunk.

Saves results to ``evaluation/data/v5/vibe_extraction_results.json`` with
per-chunk decisions, entities, counts, and failure reasons.

Does NOT write to Neo4j (keeps the synthetic-corpus graph clean). A separate
step can ingest these into Neo4j with ``source=vibe`` tagging if desired.

Run from apps/api/:
    .venv/bin/python -m evaluation.run_vibe_extraction
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Load .env so NVIDIA_API_KEY + NVIDIA_EMBEDDING_API_KEY are present.
env_path = Path(__file__).resolve().parent.parent / ".env"
if env_path.exists():
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip())

from services.llm import get_llm_client  # noqa: E402

CHUNKS_DIR = Path(__file__).parent / "data" / "v5" / "vibe_chunks"
OUT_PATH = Path(__file__).parent / "data" / "v5" / "vibe_extraction_results.json"
MAX_CONVERSATION_CHARS = 60_000  # hard cap per chunk to fit context windows


# --- Chunk → conversation conversion ----------------------------------------
def extract_block_text(block: dict) -> str:
    btype = block.get("type")
    if btype == "text":
        return block.get("text", "") or ""
    if btype == "thinking":
        return ""  # never include reasoning in the extractor's prompt
    if btype == "tool_use":
        name = block.get("name", "?")
        tin = block.get("input") or {}
        # Stringify first-level fields only, keep short
        fields = ", ".join(f"{k}={str(v)[:80]}" for k, v in tin.items() if isinstance(v, (str, int, float, bool)))
        return f"[tool_use: {name}({fields})]"
    if btype == "tool_result":
        res = block.get("content")
        if isinstance(res, str):
            return f"[tool_result]: {res[:400]}"
        if isinstance(res, list):
            texts = [b.get("text", "") for b in res if isinstance(b, dict) and b.get("type") == "text"]
            return f"[tool_result]: {' '.join(texts)[:400]}"
        return "[tool_result]"
    return ""


def extract_text(event: dict) -> str:
    msg = event.get("message") or {}
    content = msg.get("content")
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    parts = []
    if isinstance(content, list):
        for b in content:
            if isinstance(b, dict):
                t = extract_block_text(b)
                if t:
                    parts.append(t)
    return "\n".join(parts)


def chunk_to_conversation(chunk_path: Path) -> dict:
    """Load a chunk jsonl → {messages: [{role, content}, ...]}."""
    messages: list[dict] = []
    with chunk_path.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            t = ev.get("type")
            if t not in ("user", "assistant"):
                continue
            text = extract_text(ev)
            if not text:
                continue
            messages.append({"role": t, "content": text})

    # Hard cap on total character length to avoid blowing the LLM context
    total = 0
    trimmed: list[dict] = []
    for m in messages:
        n = len(m["content"])
        if total + n > MAX_CONVERSATION_CHARS:
            remaining = MAX_CONVERSATION_CHARS - total
            if remaining > 1000:
                trimmed.append({**m, "content": m["content"][:remaining] + "\n[...truncated...]"})
            break
        trimmed.append(m)
        total += n
    return {"chunk_id": chunk_path.stem, "messages": trimmed, "char_count": total}


# --- LLM extraction prompt ---------------------------------------------------
EXTRACT_PROMPT_TEMPLATE = """Analyze this developer-AI conversation and extract ALL technology / architectural decisions made by EITHER the human developer OR the AI agent.

For each decision, provide a JSON object with these fields:
- trigger: What prompted the decision (the problem or need)
- context: Background constraints and requirements
- options: List of alternatives considered (as array of strings)
- decision: What was chosen
- rationale: Why this was chosen over alternatives
- confidence: How explicit the decision is (0.0-1.0)
- entities: List of technology names mentioned (as array of strings)
- decided_by: "human" if the human made the call; "agent" if an AI agent made it autonomously

Focus on concrete technology / architecture choices (e.g., "use Framer Motion for animations", "chose Howler.js over Tone.js", "store state in Zustand not Redux"). Do NOT extract trivial formatting or naming choices.

Return a JSON array of decision objects. If no clear decisions are made, return an empty array [].

CONVERSATION:
{conversation_text}

Respond with ONLY valid JSON (no markdown, no explanation):"""


async def extract_from_conversation(llm, conversation: dict) -> dict:
    """Run a single extraction call. Returns {decisions, error, raw_chars}."""
    messages_text = ""
    for m in conversation["messages"]:
        role = m["role"].upper()
        messages_text += f"\n{role}: {m['content']}\n"

    prompt = EXTRACT_PROMPT_TEMPLATE.format(conversation_text=messages_text)

    try:
        response = await llm.generate(prompt, max_tokens=4096, sanitize_input=False)
    except Exception as e:
        return {"decisions": [], "error": f"llm_error: {e!r}", "raw_chars": 0}

    # Strip thinking tags
    response = re.sub(r"<think>.*?</think>", "", response, flags=re.DOTALL).strip()
    # Find JSON array
    start = response.find("[")
    end = response.rfind("]") + 1
    if start < 0 or end <= start:
        return {"decisions": [], "error": "no_array_found", "raw_chars": len(response)}
    payload = response[start:end]
    try:
        decisions = json.loads(payload)
    except json.JSONDecodeError:
        # Progressive repair: find last complete object
        last = payload.rfind("}")
        if last > 0:
            repaired = payload[: last + 1] + "]"
            try:
                decisions = json.loads(repaired)
            except json.JSONDecodeError:
                return {"decisions": [], "error": "json_parse_failed", "raw_chars": len(response)}
        else:
            return {"decisions": [], "error": "json_parse_failed", "raw_chars": len(response)}

    if not isinstance(decisions, list):
        return {"decisions": [], "error": "not_a_list", "raw_chars": len(response)}
    return {"decisions": decisions, "error": None, "raw_chars": len(response)}


# --- Main --------------------------------------------------------------------
async def main() -> None:
    if not CHUNKS_DIR.exists():
        print(f"Chunks dir not found: {CHUNKS_DIR}")
        return

    chunk_files = sorted(CHUNKS_DIR.glob("chunk_*.jsonl"))
    if not chunk_files:
        print("No chunks found.")
        return
    print(f"Found {len(chunk_files)} chunks to extract from.")

    # Load existing results for resume support (idempotent re-runs)
    existing_results: dict[str, dict] = {}
    if OUT_PATH.exists():
        try:
            prior = json.loads(OUT_PATH.read_text())
            for r in prior.get("per_chunk", []):
                existing_results[r["chunk_id"]] = r
            print(f"Resuming: {len(existing_results)} chunks already processed.")
        except Exception:
            pass

    llm = get_llm_client()

    per_chunk: list[dict] = []
    total_decisions = 0
    total_errors = 0
    started = time.time()

    for i, path in enumerate(chunk_files, 1):
        chunk_id = path.stem
        if chunk_id in existing_results and existing_results[chunk_id].get("error") is None:
            per_chunk.append(existing_results[chunk_id])
            total_decisions += len(existing_results[chunk_id].get("decisions", []))
            continue

        conv = chunk_to_conversation(path)
        n_msgs = len(conv["messages"])
        if n_msgs < 2:
            per_chunk.append({"chunk_id": chunk_id, "decisions": [], "error": "too_few_messages", "messages": n_msgs})
            continue

        t0 = time.time()
        result = await extract_from_conversation(llm, conv)
        dt = time.time() - t0
        n_dec = len(result["decisions"])
        err = result["error"]
        if err:
            total_errors += 1
        total_decisions += n_dec

        per_chunk.append({
            "chunk_id": chunk_id,
            "messages": n_msgs,
            "char_count": conv["char_count"],
            "decisions": result["decisions"],
            "error": err,
            "latency_s": round(dt, 2),
        })
        print(f"  [{i:>3}/{len(chunk_files)}] {chunk_id}  msgs={n_msgs:>4}  chars={conv['char_count']:>6,}  "
              f"decisions={n_dec}  err={err or '-'}  {dt:>5.1f}s")

        # Flush results to disk every 5 chunks (cheap durability)
        if i % 5 == 0:
            OUT_PATH.write_text(json.dumps({
                "total_chunks": len(chunk_files),
                "processed": i,
                "total_decisions_so_far": total_decisions,
                "per_chunk": per_chunk,
            }, indent=2, default=str))

    total_time = time.time() - started
    # Aggregate entity counts
    from collections import Counter
    entity_counter: Counter = Counter()
    decided_by_counter: Counter = Counter()
    for r in per_chunk:
        for d in r.get("decisions", []):
            if isinstance(d, dict):
                for e in (d.get("entities") or []):
                    if isinstance(e, str):
                        entity_counter[e] += 1
                db = d.get("decided_by")
                if db:
                    decided_by_counter[db] += 1

    summary = {
        "total_chunks": len(chunk_files),
        "extracted_chunks": len([r for r in per_chunk if not r.get("error")]),
        "failed_chunks": len([r for r in per_chunk if r.get("error")]),
        "total_decisions": total_decisions,
        "unique_entities": len(entity_counter),
        "top_entities": entity_counter.most_common(30),
        "decided_by": dict(decided_by_counter),
        "total_time_s": round(total_time, 1),
        "per_chunk": per_chunk,
    }
    OUT_PATH.write_text(json.dumps(summary, indent=2, default=str))
    print()
    print("=" * 70)
    print(f"DONE: {summary['extracted_chunks']}/{summary['total_chunks']} chunks extracted")
    print(f"      {summary['total_decisions']} decisions, {summary['unique_entities']} unique entities")
    print(f"      decided_by: {summary['decided_by']}")
    print(f"      top entities: {', '.join(e for e, _ in summary['top_entities'][:10])}")
    print(f"      total: {summary['total_time_s']}s")
    print(f"      saved to {OUT_PATH}")


if __name__ == "__main__":
    asyncio.run(main())
