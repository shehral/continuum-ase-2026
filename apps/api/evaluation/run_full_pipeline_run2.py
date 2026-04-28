#!/usr/bin/env python3
"""Run 2: Full 200-conversation extraction pipeline (no graph wipe).

Saves all results with 'run2' suffix, then compares with Run 1.

Usage:
    cd apps/api
    .venv/bin/python -m evaluation.run_full_pipeline_run2
"""

import asyncio
import json
import logging
import os
import re
import sys
import time
import traceback
from collections import Counter
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Suppress verbose logging
logging.getLogger("neo4j.notifications").setLevel(logging.ERROR)
logging.getLogger("neo4j").setLevel(logging.WARNING)

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

# Reuse functions from the existing pipeline
from evaluation.run_full_pipeline import (
    compute_embeddings,
    compute_retrieval_metrics,
    ensure_indexes,
    extract_decision_from_conversation,
    generate_ground_truth_queries,
    graph_statistics,
    run_graphrag_evaluation,
    store_decision,
    test_full_retrieve_context,
    test_fulltext_only,
    test_search_endpoint,
)


V5_DIR = Path(__file__).resolve().parent / "data" / "v5"
V5_DIR.mkdir(parents=True, exist_ok=True)


async def run_extraction_all(driver) -> dict:
    """Run extraction on all 200 conversations (NO wipe)."""
    print("\n" + "=" * 60)
    print("RUN 2: EXTRACTING DECISIONS FROM 200 CONVERSATIONS")
    print("=" * 60)

    from services.llm import get_llm_client
    llm = get_llm_client()
    print("  LLM client initialized")

    conv_dir = Path(__file__).resolve().parent / "data" / "synthetic_conversations"
    conv_files = sorted(conv_dir.glob("conv-*.json"))
    print(f"  Found {len(conv_files)} conversations")

    user_id = "eval-e2e"

    total_decisions = 0
    total_entities_linked = 0
    decisions_per_conv = []
    extraction_times = []
    domain_decisions = Counter()
    failed_convs = []
    per_conv_results = []

    pipeline_start = time.monotonic()

    for i, conv_file in enumerate(conv_files):
        with open(conv_file, encoding="utf-8") as f:
            conv = json.load(f)

        conv_id = conv.get("id", conv_file.stem)
        domain = conv.get("domain", "unknown")
        topic = conv.get("topic", "")

        # Progress every 25
        if (i + 1) % 25 == 0 or i == 0:
            elapsed = time.monotonic() - pipeline_start
            print(f"\n{'─' * 40}")
            print(f"  PROGRESS: {i+1}/200 conversations processed")
            if i > 0:
                rate = elapsed / (i + 1)
                eta = rate * (len(conv_files) - i - 1)
                print(f"  Elapsed: {elapsed:.0f}s | ETA: {eta:.0f}s ({eta/60:.1f} min)")
                print(f"  Decisions so far: {total_decisions}")
            print(f"{'─' * 40}")

        print(f"\n[{i+1}/{len(conv_files)}] {conv_id}: {topic}")

        # Extract decisions via LLM
        start = time.monotonic()
        try:
            decisions = await extract_decision_from_conversation(llm, conv)
        except Exception as e:
            print(f"  FATAL extraction error: {e}")
            decisions = []
            failed_convs.append({"id": conv_id, "error": str(e)})

        extraction_time = time.monotonic() - start
        extraction_times.append(extraction_time)

        print(f"  Extracted {len(decisions)} decisions in {extraction_time:.1f}s")

        conv_decisions_stored = 0
        conv_entities_linked = 0

        # Store each decision
        async with driver.session(database="neo4j") as session:
            from services.entity_resolver import EntityResolver
            resolver = EntityResolver(session, user_id=user_id)

            for dec in decisions:
                try:
                    result = await store_decision(session, dec, conv_id, user_id, resolver)
                    total_decisions += 1
                    conv_decisions_stored += 1
                    total_entities_linked += result["entities_linked"]
                    conv_entities_linked += result["entities_linked"]
                    domain_decisions[domain] += 1
                    print(f"    Decision: {result['trigger']}... ({result['entities_linked']} entities)")
                except Exception as e:
                    print(f"    Error storing decision: {e}")
                    traceback.print_exc()

        decisions_per_conv.append(conv_decisions_stored)

        per_conv_results.append({
            "conv_id": conv_id,
            "domain": domain,
            "topic": topic,
            "decisions_extracted": len(decisions),
            "decisions_stored": conv_decisions_stored,
            "entities_linked": conv_entities_linked,
            "extraction_time_s": round(extraction_time, 2),
        })

    pipeline_time = time.monotonic() - pipeline_start

    # Summary
    convs_with_decisions = sum(1 for d in decisions_per_conv if d > 0)
    extraction_rate = convs_with_decisions / len(conv_files) if conv_files else 0

    print("\n" + "-" * 60)
    print("RUN 2 EXTRACTION SUMMARY")
    print("-" * 60)
    print(f"  Conversations processed: {len(conv_files)}")
    print(f"  Conversations with decisions: {convs_with_decisions} ({extraction_rate:.1%})")
    print(f"  Total decisions extracted: {total_decisions}")
    print(f"  Avg decisions per conversation: {sum(decisions_per_conv)/len(decisions_per_conv):.1f}")
    print(f"  Total entity-decision links: {total_entities_linked}")
    print(f"  Avg extraction time: {sum(extraction_times)/len(extraction_times):.1f}s")
    print(f"  Total pipeline time: {pipeline_time:.1f}s ({pipeline_time/60:.1f} min)")
    if failed_convs:
        print(f"  Failed conversations: {len(failed_convs)}")
        for fc in failed_convs:
            print(f"    {fc['id']}: {fc['error'][:80]}")

    return {
        "conversations": len(conv_files),
        "conversations_with_decisions": convs_with_decisions,
        "extraction_success_rate": round(extraction_rate, 4),
        "total_decisions": total_decisions,
        "avg_decisions_per_conv": round(sum(decisions_per_conv) / len(decisions_per_conv), 2),
        "total_entity_links": total_entities_linked,
        "avg_extraction_time_s": round(sum(extraction_times) / len(extraction_times), 2),
        "total_pipeline_time_s": round(pipeline_time, 1),
        "decisions_by_domain": dict(domain_decisions),
        "decisions_per_conv": decisions_per_conv,
        "failed_conversations": failed_convs,
        "per_conv_results": per_conv_results,
    }


def save_run2_results(extraction_results: dict, graph_stats: dict,
                       graphrag_results: dict, embedding_stats: dict):
    """Save all results with 'run2' naming."""
    print("\n" + "=" * 60)
    print("SAVING RUN 2 RESULTS")
    print("=" * 60)

    # 1. E2E extraction results
    e2e_path = V5_DIR / "e2e_run2_results.json"
    with open(e2e_path, "w") as f:
        json.dump(extraction_results, f, indent=2)
    print(f"  Saved: {e2e_path}")

    # 2. Graph topology
    topo_path = V5_DIR / "graph_topology_run2.json"
    with open(topo_path, "w") as f:
        json.dump(graph_stats, f, indent=2)
    print(f"  Saved: {topo_path}")

    # 3. GraphRAG results
    graphrag_path = V5_DIR / "graphrag_run2_results.json"
    with open(graphrag_path, "w") as f:
        json.dump(graphrag_results, f, indent=2)
    print(f"  Saved: {graphrag_path}")

    # 4. Embedding stats
    emb_path = V5_DIR / "embedding_run2_stats.json"
    with open(emb_path, "w") as f:
        json.dump(embedding_stats, f, indent=2)
    print(f"  Saved: {emb_path}")


def compare_runs():
    """Compare Run 2 vs Run 1 results and save comparison."""
    print("\n" + "=" * 60)
    print("COMPARING RUN 2 vs RUN 1")
    print("=" * 60)

    run1_path = V5_DIR / "e2e_run1_results.json"
    run2_path = V5_DIR / "e2e_run2_results.json"

    if not run1_path.exists():
        print(f"  WARNING: Run 1 results not found at {run1_path}")
        return

    with open(run1_path) as f:
        run1 = json.load(f)
    with open(run2_path) as f:
        run2 = json.load(f)

    # Load topology files if available
    topo1_path = V5_DIR / "graph_topology_full.json"
    topo2_path = V5_DIR / "graph_topology_run2.json"
    topo1 = {}
    topo2 = {}
    if topo1_path.exists():
        with open(topo1_path) as f:
            topo1 = json.load(f)
    if topo2_path.exists():
        with open(topo2_path) as f:
            topo2 = json.load(f)

    # Per-conversation comparison
    run1_by_conv = {}
    for pcr in run1.get("per_conv_results", []):
        run1_by_conv[pcr["conv_id"]] = pcr

    run2_by_conv = {}
    for pcr in run2.get("per_conv_results", []):
        run2_by_conv[pcr["conv_id"]] = pcr

    # Decision count agreement
    all_conv_ids = sorted(set(run1_by_conv.keys()) | set(run2_by_conv.keys()))
    exact_match = 0
    within_one = 0
    conv_deltas = []
    for cid in all_conv_ids:
        r1 = run1_by_conv.get(cid, {}).get("decisions_stored", 0)
        r2 = run2_by_conv.get(cid, {}).get("decisions_stored", 0)
        delta = r2 - r1
        conv_deltas.append({"conv_id": cid, "run1": r1, "run2": r2, "delta": delta})
        if r1 == r2:
            exact_match += 1
        if abs(r1 - r2) <= 1:
            within_one += 1

    total_convs = len(all_conv_ids)
    exact_match_rate = exact_match / total_convs if total_convs else 0
    within_one_rate = within_one / total_convs if total_convs else 0

    # Domain comparison
    r1_domain = run1.get("decisions_by_domain", {})
    r2_domain = run2.get("decisions_by_domain", {})
    all_domains = sorted(set(r1_domain.keys()) | set(r2_domain.keys()))
    domain_comparison = {}
    for d in all_domains:
        domain_comparison[d] = {
            "run1": r1_domain.get(d, 0),
            "run2": r2_domain.get(d, 0),
            "delta": r2_domain.get(d, 0) - r1_domain.get(d, 0),
        }

    comparison = {
        "run1_file": str(run1_path),
        "run2_file": str(run2_path),
        "summary": {
            "run1_total_decisions": run1.get("total_decisions", 0),
            "run2_total_decisions": run2.get("total_decisions", 0),
            "decision_delta": run2.get("total_decisions", 0) - run1.get("total_decisions", 0),
            "run1_extraction_rate": run1.get("extraction_success_rate", 0),
            "run2_extraction_rate": run2.get("extraction_success_rate", 0),
            "run1_convs_with_decisions": run1.get("conversations_with_decisions", 0),
            "run2_convs_with_decisions": run2.get("conversations_with_decisions", 0),
            "run1_avg_decisions_per_conv": run1.get("avg_decisions_per_conv", 0),
            "run2_avg_decisions_per_conv": run2.get("avg_decisions_per_conv", 0),
            "run1_total_entity_links": run1.get("total_entity_links", 0),
            "run2_total_entity_links": run2.get("total_entity_links", 0),
            "run1_avg_extraction_time_s": run1.get("avg_extraction_time_s", 0),
            "run2_avg_extraction_time_s": run2.get("avg_extraction_time_s", 0),
            "run1_total_pipeline_time_s": run1.get("total_pipeline_time_s", 0),
            "run2_total_pipeline_time_s": run2.get("total_pipeline_time_s", 0),
        },
        "reproducibility": {
            "total_conversations": total_convs,
            "exact_match_count": exact_match,
            "exact_match_rate": round(exact_match_rate, 4),
            "within_one_count": within_one,
            "within_one_rate": round(within_one_rate, 4),
        },
        "domain_comparison": domain_comparison,
        "graph_topology_comparison": {
            "run1_total_nodes": topo1.get("total_nodes", "N/A"),
            "run2_total_nodes": topo2.get("total_nodes", "N/A"),
            "run1_total_relationships": topo1.get("total_relationships", "N/A"),
            "run2_total_relationships": topo2.get("total_relationships", "N/A"),
            "run1_total_entities": topo1.get("total_entities", "N/A"),
            "run2_total_entities": topo2.get("total_entities", "N/A"),
            "run1_total_decisions": topo1.get("total_decisions", "N/A"),
            "run2_total_decisions": topo2.get("total_decisions", "N/A"),
            "run1_avg_entities_per_decision": topo1.get("avg_entities_per_decision", "N/A"),
            "run2_avg_entities_per_decision": topo2.get("avg_entities_per_decision", "N/A"),
        },
        "per_conversation_deltas": conv_deltas,
        "run1_failed": run1.get("failed_conversations", []),
        "run2_failed": run2.get("failed_conversations", []),
    }

    # Print summary
    print(f"\n  Run 1: {run1.get('total_decisions', 0)} decisions, "
          f"{run1.get('conversations_with_decisions', 0)}/200 convs, "
          f"rate={run1.get('extraction_success_rate', 0):.1%}")
    print(f"  Run 2: {run2.get('total_decisions', 0)} decisions, "
          f"{run2.get('conversations_with_decisions', 0)}/200 convs, "
          f"rate={run2.get('extraction_success_rate', 0):.1%}")
    print(f"  Delta: {comparison['summary']['decision_delta']:+d} decisions")
    print(f"\n  Reproducibility:")
    print(f"    Exact match (same # decisions per conv): {exact_match}/{total_convs} ({exact_match_rate:.1%})")
    print(f"    Within +/-1 decision: {within_one}/{total_convs} ({within_one_rate:.1%})")
    print(f"\n  Domain comparison:")
    for d in all_domains:
        dc = domain_comparison[d]
        print(f"    {d}: Run1={dc['run1']}, Run2={dc['run2']}, delta={dc['delta']:+d}")

    # Save comparison
    comp_path = V5_DIR / "reproducibility_comparison.json"
    with open(comp_path, "w") as f:
        json.dump(comparison, f, indent=2)
    print(f"\n  Saved comparison: {comp_path}")


async def main():
    pipeline_start = time.monotonic()

    neo4j_uri = os.environ.get("NEO4J_URI", "bolt://127.0.0.1:7687")
    neo4j_user = os.environ.get("NEO4J_USER", "neo4j")
    neo4j_password = os.environ.get("NEO4J_PASSWORD", "password")
    driver = AsyncGraphDatabase.driver(neo4j_uri, auth=(neo4j_user, neo4j_password))

    # Verify connection
    async with driver.session(database="neo4j") as session:
        result = await session.run("MATCH (n) RETURN count(n) AS c")
        count = (await result.single())["c"]
    print(f"Connected to Neo4j — existing nodes: {count}")
    if count > 0:
        print(f"  WARNING: Graph has {count} existing nodes. Proceeding without wipe as instructed.")

    try:
        # Step 1: Extract all 200 conversations
        extraction_results = await run_extraction_all(driver)

        # Step 2: Compute embeddings
        embedding_stats = await compute_embeddings(driver)

        # Step 3: Ensure fulltext indexes
        await ensure_indexes(driver)

        # Step 4: Graph statistics
        graph_stats = await graph_statistics(driver)

        # Step 5: GraphRAG evaluation
        graphrag_results = await run_graphrag_evaluation(driver)

        # Step 6: Save all results as run2
        save_run2_results(extraction_results, graph_stats, graphrag_results, embedding_stats)

        # Step 7: Compare Run 2 vs Run 1
        compare_runs()

        total_time = time.monotonic() - pipeline_start
        print(f"\n{'=' * 60}")
        print(f"RUN 2 COMPLETE in {total_time:.1f}s ({total_time/60:.1f} min)")
        print(f"{'=' * 60}")

    finally:
        await driver.close()


if __name__ == "__main__":
    asyncio.run(main())
