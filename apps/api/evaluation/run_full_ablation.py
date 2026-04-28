#!/usr/bin/env python3
"""Full 7-stage entity resolution evaluation with seeding and ablation.

Phase 1 (Seed): Process all synthetic conversations through the real pipeline
  to populate the Neo4j graph with entities and decisions.
Phase 2 (Evaluate): Re-run all mentions against the populated graph to test
  real resolution across all 7 stages.
Phase 3 (Ablation): Disable each stage one at a time and re-run Phase 2.

Requires: Neo4j, Redis, and optionally the embedding service running.

Usage:
    cd apps/api
    .venv/bin/python -m evaluation.run_full_ablation
"""

import asyncio
import csv
import json
import os
import sys
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Load .env
env_path = Path(__file__).resolve().parent.parent / ".env"
if env_path.exists():
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, value = line.partition("=")
                os.environ.setdefault(key.strip(), value.strip())

from neo4j import AsyncGraphDatabase
from models.ontology import CANONICAL_NAMES, get_canonical_name, normalize_entity_name

import re
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
    if not text or len(text) < 10:
        return []
    mentions = []
    seen = set()

    def add(mention, start, method):
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


def load_conversations(conv_dir: Path) -> list[tuple[str, list[dict]]]:
    """Load conversations and extract mentions."""
    conv_files = sorted(conv_dir.glob("conv-*.json"))
    all_mentions = []
    for conv_file in conv_files:
        try:
            with open(conv_file, encoding="utf-8") as f:
                conv = json.load(f)
        except (json.JSONDecodeError, OSError):
            continue
        conv_id = conv.get("id", conv_file.stem)
        full_text = "\n\n".join(m.get("content", "") for m in conv.get("messages", []))
        mentions = extract_mentions(full_text, conv_id)
        all_mentions.extend(mentions[:20])
    return all_mentions


@dataclass
class AblationConfig:
    name: str
    disable_cache: bool = False
    disable_canonical: bool = False
    disable_alias: bool = False
    disable_fuzzy: bool = False
    disable_embedding: bool = False


ABLATION_CONFIGS = [
    AblationConfig(name="full"),
    AblationConfig(name="-Cache", disable_cache=True),
    AblationConfig(name="-Canonical", disable_canonical=True),
    AblationConfig(name="-Alias", disable_alias=True),
    AblationConfig(name="-Fuzzy", disable_fuzzy=True),
    AblationConfig(name="-Embedding", disable_embedding=True),
    AblationConfig(name="-Canonical-Fuzzy", disable_canonical=True, disable_fuzzy=True),
]


async def resolve_with_config(
    session, mention: str, entity_type: str, user_id: str, config: AblationConfig
) -> dict:
    """Resolve an entity with specific stages disabled for ablation."""
    from services.entity_resolver import EntityResolver
    from services.entity_cache import get_entity_cache

    resolver = EntityResolver(session, user_id=user_id)

    # Apply ablation config by monkeypatching stage methods
    original_cache = resolver.cache
    if config.disable_cache:
        class NoCache:
            """Drop-in replacement that always misses."""
            async def get_by_exact_name(self, *a, **kw): return None
            async def set_by_exact_name(self, *a, **kw): pass
            async def set_by_alias(self, *a, **kw): pass
            async def set_entity(self, *a, **kw): pass
            async def set_negative(self, *a, **kw): pass
            async def invalidate_entity(self, *a, **kw): pass
            async def invalidate_user_cache(self, *a, **kw): pass
        resolver.cache = NoCache()

    original_get_canonical = None
    if config.disable_canonical:
        import models.ontology as ont
        original_get_canonical = ont.get_canonical_name
        ont.get_canonical_name = lambda name: name

    if config.disable_alias:
        async def _no_alias(self_or_name, *a, **kw):
            return None
        resolver._find_by_alias = _no_alias

    if config.disable_fuzzy:
        async def _no_fuzzy(self_or_name, *a, **kw):
            return None  # caller checks `if fuzzy_result:` — None is falsy
        resolver._find_by_fuzzy_with_fulltext = _no_fuzzy

    if config.disable_embedding:
        # Disable the embedding service so stage 6 is skipped
        original_embed_service = resolver.embedding_service
        class NoEmbedding:
            async def embed_text(self, *a, **kw):
                raise TimeoutError("Embedding disabled for ablation")
        resolver.embedding_service = NoEmbedding()

    start = time.monotonic()
    try:
        result = await resolver.resolve(mention, entity_type)
        elapsed_ms = (time.monotonic() - start) * 1000
        return {
            "predicted": result.name,
            "confidence": result.confidence,
            "stage": result.match_method,
            "entity_id": result.id,
            "is_new": result.is_new,
            "latency_ms": elapsed_ms,
        }
    except Exception as e:
        elapsed_ms = (time.monotonic() - start) * 1000
        return {
            "predicted": normalize_entity_name(mention),
            "confidence": 0.0,
            "stage": f"error:{type(e).__name__}",
            "entity_id": "",
            "is_new": True,
            "latency_ms": elapsed_ms,
        }
    finally:
        # Restore monkeypatched methods
        if config.disable_canonical and original_get_canonical is not None:
            import models.ontology as ont
            ont.get_canonical_name = original_get_canonical
        if config.disable_cache:
            resolver.cache = original_cache
        if config.disable_embedding:
            resolver.embedding_service = original_embed_service


async def main():
    neo4j_uri = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
    neo4j_user = os.environ.get("NEO4J_USER", "neo4j")
    neo4j_password = os.environ.get("NEO4J_PASSWORD", "password")
    driver = AsyncGraphDatabase.driver(neo4j_uri, auth=(neo4j_user, neo4j_password))

    # Verify connection
    async with driver.session(database="neo4j") as session:
        result = await session.run("RETURN 1 AS n")
        await result.consume()
    print("Connected to Neo4j")

    conv_dir = Path(__file__).resolve().parent / "data" / "synthetic_conversations"
    output_dir = Path(__file__).resolve().parent / "data"
    user_id = "eval-user-ablation"

    # Load all mentions
    mentions = load_conversations(conv_dir)
    print(f"Loaded {len(mentions)} mentions from synthetic conversations")

    # ════════════════════════════════════════════
    # PHASE 1: Seed the graph
    # ════════════════════════════════════════════
    print("\n" + "=" * 60)
    print("PHASE 1: Seeding graph with entities from synthetic conversations")
    print("=" * 60)

    seed_stages = Counter()
    created_entities = {}  # name -> id mapping
    async with driver.session(database="neo4j") as session:
        from services.entity_resolver import EntityResolver
        resolver = EntityResolver(session, user_id=user_id)

        for i, m in enumerate(mentions):
            try:
                result = await resolver.resolve(m["mention_text"], "technology")
                seed_stages[result.match_method] += 1

                # If new entity, actually CREATE it in Neo4j so future lookups find it
                if result.is_new and result.name.lower() not in created_entities:
                    entity_id = result.id
                    await session.run(
                        """
                        CREATE (e:Entity {
                            id: $id,
                            name: $name,
                            type: $type,
                            user_id: $user_id,
                            aliases: $aliases
                        })
                        """,
                        parameters={
                            "id": entity_id,
                            "name": result.name,
                            "type": result.type,
                            "user_id": user_id,
                            "aliases": result.aliases or [],
                        }
                    )
                    created_entities[result.name.lower()] = entity_id

                    # Also cache it so subsequent mentions resolve via cache/exact
                    await resolver.cache.set_entity(
                        user_id, result.name.lower(),
                        {"id": entity_id, "name": result.name, "type": result.type}
                    )

            except Exception as e:
                seed_stages[f"error:{type(e).__name__}"] += 1

            if (i + 1) % 100 == 0:
                print(f"  Seeded {i + 1}/{len(mentions)} mentions...")

    print(f"  Created {len(created_entities)} unique entities in Neo4j")

    print(f"\nSeeding complete. Stage distribution:")
    for stage, count in seed_stages.most_common():
        print(f"  {stage}: {count}")

    # Check graph size
    async with driver.session(database="neo4j") as session:
        result = await session.run("MATCH (n) RETURN labels(n)[0] AS label, count(n) AS c ORDER BY c DESC")
        records = await result.data()
        print(f"\nGraph after seeding:")
        for r in records:
            print(f"  {r['label']}: {r['c']}")

    # Flush Redis cache before Phase 2
    import redis as redis_lib
    redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379")
    redis_client = redis_lib.from_url(redis_url)
    redis_client.flushall()
    print("\nRedis cache flushed for Phase 2")

    # ════════════════════════════════════════════
    # PHASE 2: Evaluate full pipeline
    # ════════════════════════════════════════════
    print("\n" + "=" * 60)
    print("PHASE 2: Evaluating full pipeline against populated graph")
    print("=" * 60)

    phase2_results = []
    async with driver.session(database="neo4j") as session:
        for i, m in enumerate(mentions):
            result = await resolve_with_config(
                session, m["mention_text"], "technology", user_id,
                AblationConfig(name="full")
            )
            phase2_results.append({
                **m,
                "pipeline_predicted": result["predicted"],
                "pipeline_confidence": f"{result['confidence']:.2f}",
                "pipeline_stage": result["stage"],
                "latency_ms": f"{result['latency_ms']:.1f}",
                "is_new": str(result.get("is_new", "")),
                "annotator_judgment": "",
            })

            if (i + 1) % 100 == 0:
                print(f"  Evaluated {i + 1}/{len(mentions)} mentions...")

    # Save Phase 2 results
    phase2_path = output_dir / "full_pipeline_annotation_sheet.csv"
    fieldnames = [
        "mention_id", "conversation_id", "mention_text",
        "conversation_context", "pipeline_predicted",
        "pipeline_confidence", "pipeline_stage", "latency_ms",
        "is_new", "annotator_judgment",
    ]
    with open(phase2_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(phase2_results)

    # Stage distribution
    stage_counts = Counter(r["pipeline_stage"] for r in phase2_results)
    print(f"\nPhase 2 stage distribution:")
    for stage, count in stage_counts.most_common():
        pct = count / len(phase2_results) * 100
        print(f"  {stage}: {count} ({pct:.1f}%)")

    # Latency stats
    latencies = [float(r["latency_ms"]) for r in phase2_results]
    latencies.sort()
    print(f"\nPhase 2 latency:")
    print(f"  p50: {latencies[len(latencies)//2]:.1f}ms")
    print(f"  p95: {latencies[int(len(latencies)*0.95)]:.1f}ms")
    print(f"  p99: {latencies[int(len(latencies)*0.99)]:.1f}ms")
    print(f"  mean: {sum(latencies)/len(latencies):.1f}ms")

    # Per-stage latency
    print(f"\nPer-stage latency (p50):")
    stage_latencies = {}
    for r in phase2_results:
        stage = r["pipeline_stage"]
        lat = float(r["latency_ms"])
        stage_latencies.setdefault(stage, []).append(lat)
    for stage, lats in sorted(stage_latencies.items()):
        lats.sort()
        p50 = lats[len(lats)//2]
        p95 = lats[int(len(lats)*0.95)] if len(lats) > 20 else lats[-1]
        p99 = lats[int(len(lats)*0.99)] if len(lats) > 100 else lats[-1]
        print(f"  {stage}: p50={p50:.1f}ms, p95={p95:.1f}ms, p99={p99:.1f}ms (n={len(lats)})")

    # ════════════════════════════════════════════
    # PHASE 3: Ablation study
    # ════════════════════════════════════════════
    print("\n" + "=" * 60)
    print("PHASE 3: Ablation study")
    print("=" * 60)

    ablation_results = []

    for config in ABLATION_CONFIGS:
        print(f"\n--- Running config: {config.name} ---")

        # Flush cache before each ablation run
        redis_client.flushall()

        config_results = []
        async with driver.session(database="neo4j") as session:
            for i, m in enumerate(mentions):
                result = await resolve_with_config(
                    session, m["mention_text"], "technology", user_id, config
                )
                config_results.append({
                    "mention_text": m["mention_text"],
                    "predicted": result["predicted"],
                    "confidence": result["confidence"],
                    "stage": result["stage"],
                    "latency_ms": result["latency_ms"],
                    "is_new": result.get("is_new", False),
                })

        # Compute stats
        stage_dist = Counter(cr["stage"] for cr in config_results)
        lats = [cr["latency_ms"] for cr in config_results]
        lats.sort()
        p50 = lats[len(lats)//2]
        p95 = lats[int(len(lats)*0.95)]
        mean_lat = sum(lats) / len(lats)

        # Count new entities (these are effectively "unresolved" - couldn't match)
        new_count = sum(1 for cr in config_results if cr["is_new"])
        resolved_count = len(config_results) - new_count
        resolution_rate = resolved_count / len(config_results) * 100

        print(f"  Stage distribution: {dict(stage_dist.most_common())}")
        print(f"  Resolution rate: {resolution_rate:.1f}% ({resolved_count}/{len(config_results)})")
        print(f"  Latency: p50={p50:.1f}ms, p95={p95:.1f}ms, mean={mean_lat:.1f}ms")

        ablation_results.append({
            "config": config.name,
            "total": len(config_results),
            "resolved": resolved_count,
            "new": new_count,
            "resolution_rate": f"{resolution_rate:.1f}",
            "p50_ms": f"{p50:.1f}",
            "p95_ms": f"{p95:.1f}",
            "mean_ms": f"{mean_lat:.1f}",
            "stages": dict(stage_dist),
        })

    # Save ablation results
    ablation_path = output_dir / "ablation_full_results.json"
    with open(ablation_path, "w") as f:
        json.dump(ablation_results, f, indent=2)

    # Save as CSV
    ablation_csv_path = output_dir / "ablation_full_results.csv"
    with open(ablation_csv_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "config", "total", "resolved", "new", "resolution_rate",
            "p50_ms", "p95_ms", "mean_ms",
        ])
        writer.writeheader()
        for ar in ablation_results:
            writer.writerow({k: v for k, v in ar.items() if k != "stages"})

    # Generate LaTeX table
    ablation_tex_path = output_dir / "ablation_full_table.tex"
    with open(ablation_tex_path, "w") as f:
        # Get full pipeline stats as baseline
        full = next(ar for ar in ablation_results if ar["config"] == "full")
        full_resolved = int(full["resolved"])
        full_p50 = float(full["p50_ms"])

        f.write("\\begin{table}[t]\n\\centering\n")
        f.write("\\caption{Ablation study: effect of removing each stage on resolution rate and latency. "
                "$\\Delta$Resolved and $\\Delta$Latency are relative to the full pipeline.}\n")
        f.write("\\label{tab:ablation}\n\\small\n")
        f.write("\\begin{tabular}{@{}l rr rr@{}}\n\\toprule\n")
        f.write("\\textbf{Config} & \\textbf{Resolved} & \\textbf{Rate} & "
                "\\textbf{p50 (ms)} & \\textbf{$\\Delta$p50} \\\\\n\\midrule\n")

        for ar in ablation_results:
            resolved = int(ar["resolved"])
            rate = ar["resolution_rate"]
            p50 = float(ar["p50_ms"])
            delta_resolved = resolved - full_resolved
            delta_p50 = p50 - full_p50

            delta_r_str = f"{delta_resolved:+d}" if ar["config"] != "full" else "--"
            delta_p_str = f"{delta_p50:+.1f}" if ar["config"] != "full" else "--"

            name = ar["config"]
            if name == "full":
                name = "Full pipeline"

            f.write(f"{name} & {resolved} & {rate}\\% & {ar['p50_ms']} & {delta_p_str} \\\\\n")

        f.write("\\bottomrule\n\\end{tabular}\n\\end{table}\n")

    print(f"\n{'=' * 60}")
    print("COMPLETE")
    print(f"{'=' * 60}")
    print(f"\nPhase 2 annotation sheet: {phase2_path}")
    print(f"Ablation results (JSON): {ablation_path}")
    print(f"Ablation results (CSV):  {ablation_csv_path}")
    print(f"Ablation LaTeX table:    {ablation_tex_path}")
    print(f"\nTo annotate Phase 2 results:")
    print(f"  .venv/bin/python -m evaluation.annotate_cli --input {phase2_path}")

    await driver.close()


if __name__ == "__main__":
    asyncio.run(main())
