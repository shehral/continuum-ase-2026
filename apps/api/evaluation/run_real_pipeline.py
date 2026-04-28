#!/usr/bin/env python3
"""Run synthetic conversations through Continuum's REAL entity resolution pipeline.

Requires:
- Docker services running (Neo4j, PostgreSQL, Redis): docker-compose up -d
- Backend running: pnpm dev:api (or uvicorn)
- A registered user with a valid JWT token

This script:
1. Reads synthetic conversation JSON files
2. Extracts entity mentions using regex heuristics (same as prepare_synthetic_annotation.py)
3. For each mention, calls the REAL entity resolution pipeline via the backend API
4. Produces an annotation sheet with real pipeline predictions

Usage:
    # First, ensure services are running:
    # docker-compose up -d && pnpm dev:api

    # Then get a JWT token (register/login):
    # curl -X POST http://localhost:8000/api/users/register \
    #   -H "Content-Type: application/json" \
    #   -d '{"name":"Eval","email":"eval@test.com","password":"eval1234"}'
    # curl -X POST http://localhost:8000/api/users/login \
    #   -H "Content-Type: application/json" \
    #   -d '{"email":"eval@test.com","password":"eval1234"}'

    python -m evaluation.run_real_pipeline --token YOUR_JWT_TOKEN [--api-url http://localhost:8000]
"""

import argparse
import asyncio
import csv
import json
import os
import re
import sys
import time
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    import httpx
except ImportError:
    print("Error: httpx not installed. Run: .venv/bin/pip install httpx", file=sys.stderr)
    sys.exit(1)

from models.ontology import CANONICAL_NAMES, normalize_entity_name

# ── Entity extraction (same heuristics as prepare_synthetic_annotation.py) ──

_CANONICAL_LOWER = {k.lower(): v for k, v in CANONICAL_NAMES.items()}
_ALL_KNOWN = set()
for _a, _c in CANONICAL_NAMES.items():
    _ALL_KNOWN.add(_a.lower())
    _ALL_KNOWN.add(_c.lower())

_CAMEL_RE = re.compile(r"\b[A-Z][a-z]+(?:[A-Z][a-z]+)+\b")
_TECH_SUFFIX_RE = re.compile(r"\b\w+(?:\.js|\.py|\.rs|\.ts|\.go|\.rb|\.ex)\b", re.IGNORECASE)
_ABBREV_RE = re.compile(r"\b[A-Z]{2,6}\b")
_HYPHEN_RE = re.compile(r"\b[a-zA-Z]+-[a-zA-Z]+(?:-[a-zA-Z]+)*\b")

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
        if key in seen or len(mention) < 2:
            return
        seen.add(key)
        ctx_start = max(0, start - 150)
        ctx_end = min(len(text), start + len(mention) + 150)
        context = text[ctx_start:ctx_end].replace("\n", " ").strip()
        mentions.append({
            "mention_id": str(uuid4())[:8],
            "conversation_id": conv_id,
            "mention_text": mention,
            "conversation_context": context,
        })

    text_lower = text.lower()
    for alias, canonical in CANONICAL_NAMES.items():
        alias_lower = alias.lower()
        idx = 0
        while True:
            pos = text_lower.find(alias_lower, idx)
            if pos == -1:
                break
            before_ok = pos == 0 or not text[pos - 1].isalnum()
            after_pos = pos + len(alias)
            after_ok = after_pos >= len(text) or not text[after_pos].isalnum()
            if before_ok and after_ok:
                actual = text[pos:pos + len(alias)]
                add(actual, pos, f"canonical_match:{canonical}")
            idx = pos + 1

    for m in _CAMEL_RE.finditer(text):
        add(m.group(), m.start(), "camelcase")
    for m in _TECH_SUFFIX_RE.finditer(text):
        add(m.group(), m.start(), "tech_suffix")
    for m in _ABBREV_RE.finditer(text):
        if m.group() not in _SKIP_ABBREVS and m.group().lower() in _ALL_KNOWN:
            add(m.group(), m.start(), "abbreviation")
    for m in _HYPHEN_RE.finditer(text):
        if m.group().lower() in _ALL_KNOWN:
            add(m.group(), m.start(), "hyphenated")

    return mentions


# ── Real pipeline resolution via API ──

async def resolve_via_api(
    client: httpx.AsyncClient,
    api_url: str,
    token: str,
    mention: str,
    entity_type: str = "technology",
) -> dict:
    """Call the real entity resolution pipeline via the backend API.

    Uses the graph endpoint to create/resolve an entity, which triggers
    the full EntityResolver pipeline internally.
    """
    # Use the search endpoint to check if the entity exists
    # Then use the graph entity endpoint to resolve
    headers = {"Authorization": f"Bearer {token}"}

    # First, try searching for the entity
    try:
        search_resp = await client.get(
            f"{api_url}/api/search",
            params={"query": mention, "type": "entity"},
            headers=headers,
            timeout=30.0,
        )
        if search_resp.status_code == 200:
            results = search_resp.json()
            if results and len(results) > 0:
                top = results[0]
                return {
                    "predicted": top.get("data", {}).get("name", top.get("name", mention)),
                    "confidence": top.get("score", 0.5),
                    "stage": "search_match",
                    "entity_id": top.get("id", ""),
                }
    except (httpx.RequestError, httpx.TimeoutException) as e:
        pass

    # If search didn't find it, try the entity resolution directly
    # by posting to the capture/extract endpoint or using direct DB access
    # For evaluation, we'll use a direct resolution endpoint if available
    try:
        # Try the agent context endpoint which does entity resolution
        context_resp = await client.get(
            f"{api_url}/api/agent/context/{mention}",
            headers=headers,
            timeout=30.0,
        )
        if context_resp.status_code == 200:
            data = context_resp.json()
            entity_name = data.get("entity", {}).get("name", mention)
            return {
                "predicted": entity_name,
                "confidence": 0.9,
                "stage": "agent_context",
                "entity_id": data.get("entity", {}).get("id", ""),
            }
    except (httpx.RequestError, httpx.TimeoutException):
        pass

    # Fallback: use canonical resolution locally
    from models.ontology import get_canonical_name
    canon = get_canonical_name(mention)
    if canon.lower() != mention.strip().lower():
        return {
            "predicted": canon,
            "confidence": 0.95,
            "stage": "canonical_fallback",
            "entity_id": "",
        }

    return {
        "predicted": normalize_entity_name(mention),
        "confidence": 0.5,
        "stage": "unresolved",
        "entity_id": "",
    }


async def resolve_via_direct_db(
    mention: str,
    entity_type: str,
    neo4j_driver,
    user_id: str,
) -> dict:
    """Resolve using the ACTUAL EntityResolver class directly against Neo4j.

    This is the most accurate evaluation — it runs the real 7-stage pipeline.
    """
    from services.entity_resolver import EntityResolver

    async with neo4j_driver.session(database="neo4j") as session:
        resolver = EntityResolver(session, user_id=user_id)
        result = await resolver.resolve(mention, entity_type)

        return {
            "predicted": result.name,
            "confidence": result.confidence,
            "stage": result.match_method,
            "entity_id": result.id,
            "is_new": result.is_new,
        }


async def run_direct_pipeline(args):
    """Run entity resolution directly via Neo4j (most accurate)."""
    from neo4j import AsyncGraphDatabase

    # Load Neo4j config
    neo4j_uri = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
    neo4j_user = os.environ.get("NEO4J_USER", "neo4j")
    neo4j_password = os.environ.get("NEO4J_PASSWORD", "password")

    driver = AsyncGraphDatabase.driver(neo4j_uri, auth=(neo4j_user, neo4j_password))

    try:
        # Verify connection
        async with driver.session(database="neo4j") as session:
            result = await session.run("RETURN 1 AS n")
            await result.consume()
        print("Connected to Neo4j successfully")
    except Exception as e:
        print(f"Error connecting to Neo4j: {e}", file=sys.stderr)
        print("Make sure docker-compose is running: docker-compose up -d", file=sys.stderr)
        sys.exit(1)

    # Load conversations
    conv_dir = Path(args.conversations_dir)
    conv_files = sorted(conv_dir.glob("conv-*.json"))
    print(f"Found {len(conv_files)} conversation files")

    all_results = []
    total_mentions = 0
    resolve_times = []

    for conv_file in conv_files:
        try:
            with open(conv_file, encoding="utf-8") as f:
                conv = json.load(f)
        except (json.JSONDecodeError, OSError):
            continue

        conv_id = conv.get("id", conv_file.stem)
        full_text = "\n\n".join(m.get("content", "") for m in conv.get("messages", []))
        mentions = extract_mentions(full_text, conv_id)

        for mention_data in mentions[:args.max_per_conv]:
            mention_text = mention_data["mention_text"]
            total_mentions += 1

            start_time = time.monotonic()
            try:
                result = await resolve_via_direct_db(
                    mention_text, "technology", driver, args.user_id
                )
            except Exception as e:
                result = {
                    "predicted": normalize_entity_name(mention_text),
                    "confidence": 0.0,
                    "stage": f"error:{type(e).__name__}",
                    "entity_id": "",
                    "is_new": True,
                }
            elapsed_ms = (time.monotonic() - start_time) * 1000
            resolve_times.append(elapsed_ms)

            all_results.append({
                "mention_id": mention_data["mention_id"],
                "conversation_id": conv_id,
                "mention_text": mention_text,
                "conversation_context": mention_data["conversation_context"],
                "pipeline_predicted": result["predicted"],
                "pipeline_confidence": f"{result['confidence']:.2f}",
                "pipeline_stage": result["stage"],
                "latency_ms": f"{elapsed_ms:.1f}",
                "is_new": str(result.get("is_new", "")),
                "annotator_judgment": "",
            })

            if total_mentions % 50 == 0:
                print(f"  Processed {total_mentions} mentions...")

    await driver.close()

    # Write results
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    fieldnames = [
        "mention_id", "conversation_id", "mention_text",
        "conversation_context", "pipeline_predicted",
        "pipeline_confidence", "pipeline_stage", "latency_ms",
        "is_new", "annotator_judgment",
    ]

    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(all_results)

    # Print stats
    print(f"\nProcessed {total_mentions} mentions from {len(conv_files)} conversations")
    print(f"Output: {output_path}")

    if resolve_times:
        resolve_times.sort()
        p50 = resolve_times[len(resolve_times) // 2]
        p95 = resolve_times[int(len(resolve_times) * 0.95)]
        p99 = resolve_times[int(len(resolve_times) * 0.99)]
        print(f"\nLatency: p50={p50:.1f}ms, p95={p95:.1f}ms, p99={p99:.1f}ms")

    # Stage distribution
    stage_counts: dict[str, int] = {}
    for r in all_results:
        stage = r["pipeline_stage"]
        stage_counts[stage] = stage_counts.get(stage, 0) + 1
    print(f"\nStage distribution:")
    for stage, count in sorted(stage_counts.items(), key=lambda x: -x[1]):
        pct = count / total_mentions * 100
        print(f"  {stage}: {count} ({pct:.1f}%)")

    # Count auto-markable
    auto_correct = sum(1 for r in all_results if r["pipeline_stage"] == "exact")
    print(f"\nAuto-markable as CORRECT (exact matches): {auto_correct}")
    print(f"Need manual annotation: {total_mentions - auto_correct}")
    print(f"\nTo annotate:")
    print(f"  .venv/bin/python -m evaluation.annotate_cli --input {output_path}")


async def run_api_pipeline(args):
    """Run entity resolution via the REST API (requires backend running)."""
    async with httpx.AsyncClient() as client:
        # Test connection
        try:
            resp = await client.get(f"{args.api_url}/api/health", timeout=5.0)
            print(f"Backend reachable: {resp.status_code}")
        except httpx.ConnectError:
            print(f"Error: Cannot reach backend at {args.api_url}", file=sys.stderr)
            print("Start it with: pnpm dev:api", file=sys.stderr)
            sys.exit(1)

        # Load and process conversations
        conv_dir = Path(args.conversations_dir)
        conv_files = sorted(conv_dir.glob("conv-*.json"))
        print(f"Found {len(conv_files)} conversation files")

        all_results = []
        total = 0

        for conv_file in conv_files:
            try:
                with open(conv_file, encoding="utf-8") as f:
                    conv = json.load(f)
            except (json.JSONDecodeError, OSError):
                continue

            conv_id = conv.get("id", conv_file.stem)
            full_text = "\n\n".join(m.get("content", "") for m in conv.get("messages", []))
            mentions = extract_mentions(full_text, conv_id)

            for mention_data in mentions[:args.max_per_conv]:
                total += 1
                start = time.monotonic()
                result = await resolve_via_api(
                    client, args.api_url, args.token,
                    mention_data["mention_text"]
                )
                elapsed = (time.monotonic() - start) * 1000

                all_results.append({
                    "mention_id": mention_data["mention_id"],
                    "conversation_id": conv_id,
                    "mention_text": mention_data["mention_text"],
                    "conversation_context": mention_data["conversation_context"],
                    "pipeline_predicted": result["predicted"],
                    "pipeline_confidence": f"{result['confidence']:.2f}",
                    "pipeline_stage": result["stage"],
                    "latency_ms": f"{elapsed:.1f}",
                    "annotator_judgment": "",
                })

                if total % 50 == 0:
                    print(f"  Processed {total} mentions...")

        # Write output
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        fieldnames = [
            "mention_id", "conversation_id", "mention_text",
            "conversation_context", "pipeline_predicted",
            "pipeline_confidence", "pipeline_stage", "latency_ms",
            "annotator_judgment",
        ]
        with open(output_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(all_results)

        print(f"\nProcessed {total} mentions")
        print(f"Output: {output_path}")
        print(f"\nTo annotate:")
        print(f"  .venv/bin/python -m evaluation.annotate_cli --input {output_path}")


def main():
    parser = argparse.ArgumentParser(
        description="Run synthetic conversations through the real Continuum pipeline."
    )
    parser.add_argument(
        "--mode",
        choices=["direct", "api"],
        default="direct",
        help="'direct' = connect to Neo4j directly (recommended), "
             "'api' = use REST API (requires backend running)",
    )
    parser.add_argument(
        "--conversations-dir",
        type=str,
        default=str(Path(__file__).resolve().parent / "data" / "synthetic_conversations"),
    )
    parser.add_argument(
        "--output",
        type=str,
        default=str(Path(__file__).resolve().parent / "data" / "real_pipeline_annotation_sheet.csv"),
    )
    parser.add_argument(
        "--token",
        type=str,
        default="",
        help="JWT token for API mode (get from /api/users/login)",
    )
    parser.add_argument(
        "--api-url",
        type=str,
        default="http://localhost:8000",
    )
    parser.add_argument(
        "--user-id",
        type=str,
        default="eval-user",
        help="User ID for direct mode (used for user-scoped resolution)",
    )
    parser.add_argument(
        "--max-per-conv",
        type=int,
        default=20,
    )
    args = parser.parse_args()

    if args.mode == "direct":
        # Load .env file for Neo4j credentials
        env_path = Path(__file__).resolve().parent.parent / ".env"
        if env_path.exists():
            with open(env_path) as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        key, _, value = line.partition("=")
                        os.environ.setdefault(key.strip(), value.strip())

        asyncio.run(run_direct_pipeline(args))
    else:
        if not args.token:
            print("Error: --token required for API mode", file=sys.stderr)
            sys.exit(1)
        asyncio.run(run_api_pipeline(args))


if __name__ == "__main__":
    main()
