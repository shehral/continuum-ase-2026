#!/usr/bin/env python3
"""Automated GraphRAG retrieval evaluation.

Generates test queries from the knowledge graph, runs them through the
search and GraphRAG endpoints, and evaluates retrieval quality.

Produces metrics for RQ4 in the full system paper.

Usage:
    cd apps/api
    .venv/bin/python -m evaluation.test_graphrag
"""

import asyncio
import json
import os
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

env_path = Path(__file__).resolve().parent.parent / ".env"
if env_path.exists():
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, value = line.partition("=")
                os.environ.setdefault(key.strip(), value.strip())

from neo4j import AsyncGraphDatabase


# ── Test query generation ────────────────────────────────────────────

async def generate_ground_truth_queries(driver) -> list[dict]:
    """Generate test queries FROM the graph itself, so we know the expected answers."""
    queries = []

    async with driver.session(database="neo4j") as session:
        # Type 1: Entity-centric queries — "What decisions involve X?"
        result = await session.run("""
            MATCH (e:Entity)<-[:INVOLVES]-(d:DecisionTrace)
            WITH e, collect(d) AS decisions, count(d) AS dec_count
            WHERE dec_count >= 2
            RETURN e.name AS entity, e.id AS entity_id,
                   [d IN decisions | {id: d.id, trigger: d.trigger, decision: d.decision}] AS expected_decisions,
                   dec_count
            ORDER BY dec_count DESC LIMIT 15
        """)
        for rec in await result.data():
            queries.append({
                "type": "entity_lookup",
                "query": f"What decisions were made about {rec['entity']}?",
                "expected_entity": rec["entity"],
                "expected_entity_id": rec["entity_id"],
                "expected_decision_ids": [d["id"] for d in rec["expected_decisions"]],
                "expected_decision_count": rec["dec_count"],
                "expected_decisions": rec["expected_decisions"],
            })

        # Type 2: Decision-centric queries — search by trigger/rationale
        result = await session.run("""
            MATCH (d:DecisionTrace)-[:INVOLVES]->(e:Entity)
            WHERE d.trigger IS NOT NULL AND d.trigger <> ''
            WITH d, collect(e.name) AS entities
            RETURN d.id AS id, d.trigger AS trigger, d.decision AS decision,
                   d.rationale AS rationale, entities
            ORDER BY rand() LIMIT 15
        """)
        for rec in await result.data():
            # Use a natural language version of the trigger as the query
            trigger = rec["trigger"]
            if len(trigger) > 100:
                trigger = trigger[:100]
            queries.append({
                "type": "decision_search",
                "query": trigger,
                "expected_decision_id": rec["id"],
                "expected_decision_text": rec["decision"],
                "expected_entities": rec["entities"],
            })

        # Type 3: Technology comparison queries
        result = await session.run("""
            MATCH (e1:Entity)<-[:INVOLVES]-(d:DecisionTrace)-[:INVOLVES]->(e2:Entity)
            WHERE e1.name < e2.name
            WITH e1.name AS tech1, e2.name AS tech2, collect(d.id) AS decision_ids, count(d) AS co_occurrence
            WHERE co_occurrence >= 1
            RETURN tech1, tech2, decision_ids, co_occurrence
            ORDER BY co_occurrence DESC LIMIT 10
        """)
        for rec in await result.data():
            queries.append({
                "type": "comparison",
                "query": f"{rec['tech1']} vs {rec['tech2']}",
                "expected_techs": [rec["tech1"], rec["tech2"]],
                "expected_decision_ids": rec["decision_ids"],
            })

    return queries


# ── Search evaluation ────────────────────────────────────────────────

async def test_search_endpoint(session, query: str) -> dict:
    """Call the search service directly (not via HTTP — avoids needing uvicorn running)."""
    from services.graph_rag import GraphRAGService

    rag = GraphRAGService()
    start = time.monotonic()

    try:
        results = await rag.hybrid_retrieve(query, user_id="eval-e2e", limit=10, session=session)
        latency = (time.monotonic() - start) * 1000

        # Fetch actual node data for the returned IDs
        node_data = []
        if results:
            node_result = await session.run(
                "UNWIND $ids AS nid MATCH (n {id: nid}) RETURN n.id AS id, n.name AS name, labels(n)[0] AS label",
                parameters={"ids": results}
            )
            node_data = await node_result.data()

        return {
            "success": True,
            "result_count": len(results),
            "results": node_data,
            "result_ids": results,
            "latency_ms": latency,
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "result_count": 0,
            "results": [],
            "latency_ms": (time.monotonic() - start) * 1000,
        }


async def test_subgraph_expansion(session, seed_ids: list[str]) -> dict:
    """Test subgraph expansion from seed nodes."""
    from services.graph_rag import GraphRAGService

    rag = GraphRAGService()
    start = time.monotonic()

    try:
        subgraph = await rag.expand_subgraph(seed_ids, depth=2, max_nodes=50)
        latency = (time.monotonic() - start) * 1000

        return {
            "success": True,
            "node_count": len(subgraph.get("nodes", [])),
            "edge_count": len(subgraph.get("edges", [])),
            "latency_ms": latency,
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "node_count": 0,
            "edge_count": 0,
            "latency_ms": (time.monotonic() - start) * 1000,
        }


async def test_full_retrieve_context(session, query: str, user_id: str = "eval-e2e") -> dict:
    """Test the full retrieve_context pipeline (hybrid + expansion + serialization)."""
    from services.graph_rag import GraphRAGService

    rag = GraphRAGService()
    start = time.monotonic()

    try:
        subgraph, context_str, seed_ids = await rag.retrieve_context(
            query, user_id=user_id, top_k=5, depth=2, session=session
        )
        latency = (time.monotonic() - start) * 1000

        return {
            "success": True,
            "seed_count": len(seed_ids),
            "node_count": len(subgraph.get("nodes", [])),
            "edge_count": len(subgraph.get("edges", [])),
            "context_length": len(context_str),
            "context_preview": context_str[:500] if context_str else "",
            "latency_ms": latency,
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "latency_ms": (time.monotonic() - start) * 1000,
        }


# ── Evaluation metrics ───────────────────────────────────────────────

def compute_retrieval_metrics(queries: list[dict], results: list[dict]) -> dict:
    """Compute retrieval quality metrics."""
    # For entity_lookup: did the search return the expected entity?
    entity_hits = 0
    entity_total = 0
    decision_hits = 0
    decision_total = 0
    comparison_hits = 0
    comparison_total = 0

    mrr_scores = []
    latencies = []

    for q, r in zip(queries, results):
        latencies.append(r.get("latency_ms", 0))

        if not r.get("success"):
            continue

        retrieved_ids = set()
        retrieved_names = set()
        for node in r.get("results", []):
            if isinstance(node, dict):
                retrieved_ids.add(node.get("id", ""))
                name = node.get("name") or ""
                retrieved_names.add(name.lower())
                data = node.get("data", {})
                if isinstance(data, dict):
                    dname = data.get("name") or ""
                    retrieved_names.add(dname.lower())

        if q["type"] == "entity_lookup":
            entity_total += 1
            expected = q["expected_entity"].lower()
            if expected in retrieved_names or any(expected in n for n in retrieved_names):
                entity_hits += 1

            # MRR for expected decisions
            for i, node in enumerate(r.get("results", [])):
                nid = node.get("id", "") if isinstance(node, dict) else ""
                if nid in q.get("expected_decision_ids", []):
                    mrr_scores.append(1.0 / (i + 1))
                    break
            else:
                mrr_scores.append(0.0)

        elif q["type"] == "decision_search":
            decision_total += 1
            expected_id = q.get("expected_decision_id", "")
            if expected_id in retrieved_ids:
                decision_hits += 1

            # MRR
            for i, node in enumerate(r.get("results", [])):
                nid = node.get("id", "") if isinstance(node, dict) else ""
                if nid == expected_id:
                    mrr_scores.append(1.0 / (i + 1))
                    break
            else:
                mrr_scores.append(0.0)

        elif q["type"] == "comparison":
            comparison_total += 1
            expected_techs = {t.lower() for t in q.get("expected_techs", [])}
            found = expected_techs.intersection(retrieved_names)
            if len(found) >= 1:
                comparison_hits += 1

    latencies.sort()
    metrics = {
        "entity_recall": entity_hits / entity_total if entity_total else 0,
        "entity_hits": entity_hits,
        "entity_total": entity_total,
        "decision_recall": decision_hits / decision_total if decision_total else 0,
        "decision_hits": decision_hits,
        "decision_total": decision_total,
        "comparison_recall": comparison_hits / comparison_total if comparison_total else 0,
        "comparison_hits": comparison_hits,
        "comparison_total": comparison_total,
        "mrr": sum(mrr_scores) / len(mrr_scores) if mrr_scores else 0,
        "latency_p50": latencies[len(latencies) // 2] if latencies else 0,
        "latency_p95": latencies[int(len(latencies) * 0.95)] if latencies else 0,
        "latency_mean": sum(latencies) / len(latencies) if latencies else 0,
    }
    return metrics


# ── Main ─────────────────────────────────────────────────────────────

async def main():
    driver = AsyncGraphDatabase.driver(
        os.environ.get("NEO4J_URI", "bolt://localhost:7687"),
        auth=(os.environ.get("NEO4J_USER", "neo4j"),
              os.environ.get("NEO4J_PASSWORD", "password"))
    )

    print("=" * 60)
    print("GRAPHRAG RETRIEVAL EVALUATION")
    print("=" * 60)

    # Phase 1: Generate ground truth queries from the graph
    print("\nPhase 1: Generating test queries from knowledge graph...")
    queries = await generate_ground_truth_queries(driver)
    type_counts = Counter(q["type"] for q in queries)
    print(f"Generated {len(queries)} queries: {dict(type_counts)}")

    # Phase 2: Test hybrid retrieval
    print("\nPhase 2: Testing hybrid retrieval...")
    search_results = []
    async with driver.session(database="neo4j") as session:
        for i, q in enumerate(queries):
            result = await test_search_endpoint(session, q["query"])
            search_results.append(result)
            status = "ok" if result["success"] else "FAIL"
            print(f"  [{i+1}/{len(queries)}] {status} | {result['result_count']} results | "
                  f"{result['latency_ms']:.0f}ms | {q['query'][:60]}...")

    # Phase 3: Test full retrieve_context pipeline
    print("\nPhase 3: Testing full retrieve_context pipeline...")
    context_results = []
    async with driver.session(database="neo4j") as session:
        for i, q in enumerate(queries[:10]):  # Test 10 queries through full pipeline
            result = await test_full_retrieve_context(session, q["query"])
            context_results.append(result)
            status = "ok" if result["success"] else "FAIL"
            nodes = result.get("node_count", 0)
            edges = result.get("edge_count", 0)
            ctx_len = result.get("context_length", 0)
            print(f"  [{i+1}/10] {status} | {nodes} nodes, {edges} edges | "
                  f"context: {ctx_len} chars | {result['latency_ms']:.0f}ms")

    # Phase 4: Compute metrics
    print("\n" + "=" * 60)
    print("RETRIEVAL METRICS")
    print("=" * 60)

    metrics = compute_retrieval_metrics(queries, search_results)
    print(f"\nEntity lookup recall:    {metrics['entity_recall']:.1%} ({metrics['entity_hits']}/{metrics['entity_total']})")
    print(f"Decision search recall:  {metrics['decision_recall']:.1%} ({metrics['decision_hits']}/{metrics['decision_total']})")
    print(f"Comparison recall:       {metrics['comparison_recall']:.1%} ({metrics['comparison_hits']}/{metrics['comparison_total']})")
    print(f"Mean Reciprocal Rank:    {metrics['mrr']:.3f}")
    print(f"\nLatency: p50={metrics['latency_p50']:.0f}ms, p95={metrics['latency_p95']:.0f}ms, mean={metrics['latency_mean']:.0f}ms")

    # Context pipeline stats
    if context_results:
        successful = [r for r in context_results if r.get("success")]
        if successful:
            avg_nodes = sum(r["node_count"] for r in successful) / len(successful)
            avg_edges = sum(r["edge_count"] for r in successful) / len(successful)
            avg_ctx = sum(r["context_length"] for r in successful) / len(successful)
            avg_lat = sum(r["latency_ms"] for r in successful) / len(successful)
            print(f"\nFull pipeline (retrieve_context):")
            print(f"  Success rate: {len(successful)}/{len(context_results)}")
            print(f"  Avg subgraph: {avg_nodes:.0f} nodes, {avg_edges:.0f} edges")
            print(f"  Avg context length: {avg_ctx:.0f} chars")
            print(f"  Avg latency: {avg_lat:.0f}ms")

    # Phase 5: Graph topology stats
    print("\n" + "=" * 60)
    print("KNOWLEDGE GRAPH TOPOLOGY")
    print("=" * 60)

    async with driver.session(database="neo4j") as session:
        # Basic counts
        r = await session.run("MATCH (n) RETURN labels(n)[0] AS l, count(n) AS c ORDER BY c DESC")
        for rec in await r.data():
            print(f"  {rec['l']}: {rec['c']}")
        r = await session.run("MATCH ()-[rel]->() RETURN type(rel) AS t, count(rel) AS c ORDER BY c DESC")
        for rec in await r.data():
            print(f"  {rec['t']}: {rec['c']}")

        # Connectivity
        r = await session.run("""
            MATCH (e:Entity)<-[:INVOLVES]-(d:DecisionTrace)
            WITH e, count(d) AS degree
            RETURN avg(degree) AS avg_degree, max(degree) AS max_degree,
                   min(degree) AS min_degree, stdev(degree) AS std_degree
        """)
        rec = await r.single()
        print(f"\nEntity connectivity:")
        print(f"  Avg decisions per entity: {rec['avg_degree']:.1f}")
        print(f"  Max: {rec['max_degree']}, Min: {rec['min_degree']}, Std: {rec['std_degree']:.1f}")

        # Decision size
        r = await session.run("""
            MATCH (d:DecisionTrace)-[:INVOLVES]->(e:Entity)
            WITH d, count(e) AS entity_count
            RETURN avg(entity_count) AS avg_entities, max(entity_count) AS max_entities,
                   min(entity_count) AS min_entities
        """)
        rec = await r.single()
        print(f"\nDecision entity coverage:")
        print(f"  Avg entities per decision: {rec['avg_entities']:.1f}")
        print(f"  Max: {rec['max_entities']}, Min: {rec['min_entities']}")

        # Domain distribution
        r = await session.run("""
            MATCH (d:DecisionTrace)
            WHERE d.conversation_id IS NOT NULL
            RETURN d.conversation_id AS conv, count(d) AS decisions
            ORDER BY decisions DESC LIMIT 10
        """)
        recs = await r.data()
        print(f"\nTop conversations by decision count:")
        for rec in recs:
            print(f"  {rec['conv']}: {rec['decisions']} decisions")

        # Connected components (approximate)
        r = await session.run("""
            MATCH (e:Entity)
            WHERE NOT (e)<-[:INVOLVES]-()
            RETURN count(e) AS isolated
        """)
        isolated = (await r.single())["isolated"]
        r = await session.run("MATCH (e:Entity) RETURN count(e) AS total")
        total_entities = (await r.single())["total"]
        print(f"\nIsolated entities (no decisions): {isolated}/{total_entities}")

    # Save all results
    output = {
        "queries": len(queries),
        "query_types": dict(type_counts),
        "metrics": metrics,
        "context_pipeline": {
            "tested": len(context_results),
            "successful": len([r for r in context_results if r.get("success")]),
        } if context_results else {},
    }
    output_path = Path(__file__).resolve().parent / "data" / "graphrag_eval_results.json"
    with open(output_path, "w") as f:
        json.dump(output, f, indent=2)
    print(f"\nResults saved to {output_path}")

    await driver.close()


if __name__ == "__main__":
    asyncio.run(main())
