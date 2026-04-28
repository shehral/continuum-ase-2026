#!/usr/bin/env python3
"""Evaluate the MCP server tools programmatically.

Tests all 5 MCP tools (summary, search, context, check, remember)
against the populated knowledge graph and measures accuracy, relevance,
and response quality.

Usage:
    cd apps/api
    .venv/bin/python -m evaluation.test_mcp
"""

import asyncio
import json
import os
import sys
import time
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

OUTPUT_DIR = Path(__file__).resolve().parent / "data" / "v5"


# ── Tool implementations (mirrors apps/mcp/server.py logic via direct DB) ──

async def tool_summary(session, user_id: str) -> dict:
    """Mirrors continuum_summary: returns top technologies, recent decisions, gaps."""
    start = time.monotonic()

    # Top entities
    r = await session.run("""
        MATCH (e:Entity)<-[:INVOLVES]-(d:DecisionTrace)
        RETURN e.name AS name, count(d) AS decisions
        ORDER BY decisions DESC LIMIT 10
    """)
    top_entities = await r.data()

    # Recent decisions
    r = await session.run("""
        MATCH (d:DecisionTrace)
        RETURN d.trigger AS trigger, d.decision AS decision, d.confidence AS confidence
        ORDER BY d.confidence DESC LIMIT 5
    """)
    recent_decisions = await r.data()

    # Total counts
    r = await session.run("MATCH (d:DecisionTrace) RETURN count(d) AS c")
    decision_count = (await r.single())["c"]
    r = await session.run("MATCH (e:Entity) RETURN count(e) AS c")
    entity_count = (await r.single())["c"]

    elapsed = (time.monotonic() - start) * 1000

    return {
        "success": bool(top_entities and recent_decisions),
        "decision_count": decision_count,
        "entity_count": entity_count,
        "top_entities": len(top_entities),
        "recent_decisions": len(recent_decisions),
        "latency_ms": elapsed,
    }


async def tool_search(session, query: str, user_id: str) -> dict:
    """Mirrors continuum_search: hybrid search for decisions."""
    start = time.monotonic()

    try:
        # Fulltext search on decisions
        r = await session.run("""
            CALL db.index.fulltext.queryNodes('decision_fulltext', $query)
            YIELD node, score
            WHERE score > 0.5
            RETURN node.id AS id, node.trigger AS trigger, node.decision AS decision, score
            ORDER BY score DESC LIMIT 5
        """, parameters={"query": query})
        results = await r.data()

        # Also search entities
        r = await session.run("""
            CALL db.index.fulltext.queryNodes('entity_fulltext', $query)
            YIELD node, score
            RETURN node.id AS id, node.name AS name, score
            ORDER BY score DESC LIMIT 5
        """, parameters={"query": query})
        entity_results = await r.data()

        elapsed = (time.monotonic() - start) * 1000
        return {
            "success": True,
            "decision_results": len(results),
            "entity_results": len(entity_results),
            "total_results": len(results) + len(entity_results),
            "latency_ms": elapsed,
            "results": results[:3],
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "latency_ms": (time.monotonic() - start) * 1000,
        }


async def tool_context(session, entity_name: str, user_id: str) -> dict:
    """Mirrors continuum_context: get everything about an entity."""
    start = time.monotonic()

    # Find entity
    r = await session.run("""
        MATCH (e:Entity)
        WHERE toLower(e.name) = toLower($name)
        OPTIONAL MATCH (e)<-[:INVOLVES]-(d:DecisionTrace)
        RETURN e.name AS name, e.type AS type,
               collect({trigger: d.trigger, decision: d.decision, confidence: d.confidence}) AS decisions
        LIMIT 1
    """, parameters={"name": entity_name})
    rec = await r.single()

    elapsed = (time.monotonic() - start) * 1000

    if rec and rec["name"]:
        decisions = [d for d in rec["decisions"] if d.get("trigger")]
        return {
            "success": True,
            "entity_found": True,
            "entity_name": rec["name"],
            "entity_type": rec["type"],
            "decision_count": len(decisions),
            "latency_ms": elapsed,
        }
    else:
        return {
            "success": True,
            "entity_found": False,
            "latency_ms": elapsed,
        }


async def tool_check(session, proposed_decision: str, entities: list[str], user_id: str) -> dict:
    """Mirrors continuum_check: check for prior art before making a decision."""
    start = time.monotonic()

    similar_decisions = []
    contradictions = []

    for entity_name in entities:
        # Find decisions involving this entity
        r = await session.run("""
            MATCH (e:Entity)<-[:INVOLVES]-(d:DecisionTrace)
            WHERE toLower(e.name) = toLower($name)
            RETURN d.id AS id, d.trigger AS trigger, d.decision AS decision,
                   d.rationale AS rationale, d.confidence AS confidence
        """, parameters={"name": entity_name})
        related = await r.data()

        for d in related:
            similar_decisions.append({
                "trigger": d["trigger"],
                "decision": d["decision"],
                "entity": entity_name,
            })

    # Determine recommendation
    if contradictions:
        recommendation = "resolve_contradiction"
    elif similar_decisions:
        recommendation = "review_similar"
    else:
        recommendation = "proceed"

    elapsed = (time.monotonic() - start) * 1000

    return {
        "success": True,
        "recommendation": recommendation,
        "similar_count": len(similar_decisions),
        "contradiction_count": len(contradictions),
        "latency_ms": elapsed,
    }


async def tool_remember(session, trigger: str, decision: str, rationale: str,
                         entities: list[str], user_id: str) -> dict:
    """Mirrors continuum_remember: record a new decision."""
    from uuid import uuid4
    start = time.monotonic()

    decision_id = str(uuid4())

    # Create decision
    await session.run("""
        CREATE (d:DecisionTrace {
            id: $id, trigger: $trigger, decision: $decision,
            rationale: $rationale, confidence: 0.9,
            source: 'mcp_test', user_id: $user_id
        })
    """, parameters={
        "id": decision_id, "trigger": trigger,
        "decision": decision, "rationale": rationale,
        "user_id": user_id,
    })

    # Link entities
    linked = 0
    for ename in entities:
        r = await session.run("""
            MATCH (e:Entity) WHERE toLower(e.name) = toLower($name)
            RETURN e.id AS id LIMIT 1
        """, parameters={"name": ename})
        rec = await r.single()
        if rec:
            await session.run("""
                MATCH (d:DecisionTrace {id: $did}), (e:Entity {id: $eid})
                MERGE (d)-[:INVOLVES]->(e)
            """, parameters={"did": decision_id, "eid": rec["id"]})
            linked += 1

    # Verify it was stored
    r = await session.run(
        "MATCH (d:DecisionTrace {id: $id}) RETURN d.id AS id",
        parameters={"id": decision_id}
    )
    stored = await r.single()

    elapsed = (time.monotonic() - start) * 1000

    return {
        "success": bool(stored),
        "decision_id": decision_id,
        "entities_linked": linked,
        "latency_ms": elapsed,
    }


# ── Test cases ───────────────────────────────────────────────────────

SEARCH_QUERIES = [
    {"query": "PostgreSQL", "expect_results": True, "description": "Common entity search"},
    {"query": "state management React", "expect_results": True, "description": "Multi-term decision search"},
    {"query": "caching Redis Memcached", "expect_results": True, "description": "Technology comparison search"},
    {"query": "authentication JWT session", "expect_results": True, "description": "Auth decision search"},
    {"query": "serverless Lambda Workers", "expect_results": True, "description": "Cloud decision search"},
    {"query": "CI/CD pipeline", "expect_results": True, "description": "DevOps decision search"},
    {"query": "machine learning PyTorch", "expect_results": True, "description": "ML decision search"},
    {"query": "mobile React Native Flutter", "expect_results": True, "description": "Mobile decision search"},
    {"query": "ORM database", "expect_results": True, "description": "ORM selection search"},
    {"query": "monitoring observability", "expect_results": True, "description": "Observability search"},
    {"query": "xyzzy_nonexistent_tech", "expect_results": False, "description": "Non-existent entity (negative test)"},
    {"query": "quantum computing blockchain NFT", "expect_results": False, "description": "Out-of-domain (negative test)"},
]

CONTEXT_ENTITIES = [
    {"name": "PostgreSQL", "expect_found": True, "expect_decisions": True},
    {"name": "React", "expect_found": True, "expect_decisions": True},
    {"name": "Docker", "expect_found": True, "expect_decisions": True},
    {"name": "Kubernetes", "expect_found": True, "expect_decisions": True},
    {"name": "Redis", "expect_found": True, "expect_decisions": True},
    {"name": "FastAPI", "expect_found": True, "expect_decisions": True},
    {"name": "Rust", "expect_found": True, "expect_decisions": True},
    {"name": "AWS", "expect_found": True, "expect_decisions": True},
    {"name": "xyzzy_fake", "expect_found": False, "expect_decisions": False},
    {"name": "quantum_computer_9000", "expect_found": False, "expect_decisions": False},
]

CHECK_PROPOSALS = [
    {
        "proposed": "Switch from PostgreSQL to MongoDB for document storage",
        "entities": ["PostgreSQL", "MongoDB"],
        "expect_similar": True,
        "description": "Propose change to existing tech — should find prior decisions about PostgreSQL",
    },
    {
        "proposed": "Use Redis for caching API responses",
        "entities": ["Redis"],
        "expect_similar": True,
        "description": "Propose using already-decided tech — should find prior Redis decisions",
    },
    {
        "proposed": "Adopt Kubernetes for container orchestration",
        "entities": ["Kubernetes", "Docker"],
        "expect_similar": True,
        "description": "Propose K8s — should find Docker/K8s decisions",
    },
    {
        "proposed": "Use a completely novel framework called ZorbDB",
        "entities": ["ZorbDB"],
        "expect_similar": False,
        "description": "Novel tech — no prior art expected",
    },
    {
        "proposed": "Switch from React to Vue for the frontend",
        "entities": ["React", "Vue"],
        "expect_similar": True,
        "description": "Propose changing frontend framework — should find React decisions",
    },
]

REMEMBER_TESTS = [
    {
        "trigger": "Need a testing framework for the Python backend",
        "decision": "pytest with pytest-asyncio",
        "rationale": "Best async support, widely adopted, good plugin ecosystem",
        "entities": ["pytest", "Python"],
        "description": "Record a new testing decision",
    },
    {
        "trigger": "Need to containerize the ML inference service",
        "decision": "Docker with NVIDIA Container Toolkit",
        "rationale": "GPU access in containers, compatible with existing K8s deployment",
        "entities": ["Docker", "Kubernetes"],
        "description": "Record a containerization decision",
    },
    {
        "trigger": "Need a linter for TypeScript codebase",
        "decision": "Biome over ESLint",
        "rationale": "Faster, single tool for linting and formatting, Rust-based",
        "entities": ["TypeScript"],
        "description": "Record a tooling decision",
    },
]


# ── Main ─────────────────────────────────────────────────────────────

async def main():
    driver = AsyncGraphDatabase.driver(
        os.environ.get("NEO4J_URI", "bolt://localhost:7687"),
        auth=(os.environ.get("NEO4J_USER", "neo4j"),
              os.environ.get("NEO4J_PASSWORD", "password"))
    )

    print("=" * 60)
    print("MCP TOOL EVALUATION")
    print("=" * 60)

    results = {
        "summary": {},
        "search": [],
        "context": [],
        "check": [],
        "remember": [],
    }

    async with driver.session(database="neo4j") as session:
        # ── Tool 1: Summary ──
        print("\n--- Tool 1: continuum_summary ---")
        summary = await tool_summary(session, "eval-mcp")
        results["summary"] = summary
        status = "PASS" if summary["success"] else "FAIL"
        print(f"  {status} | {summary['decision_count']} decisions, {summary['entity_count']} entities | {summary['latency_ms']:.0f}ms")

        # ── Tool 2: Search ──
        print("\n--- Tool 2: continuum_search ---")
        search_pass = 0
        search_total = len(SEARCH_QUERIES)
        for sq in SEARCH_QUERIES:
            r = await tool_search(session, sq["query"], "eval-mcp")
            expected = sq["expect_results"]
            actual = r["total_results"] > 0
            passed = (expected == actual) or (expected and actual)
            if passed:
                search_pass += 1
            status = "PASS" if passed else "FAIL"
            results["search"].append({**sq, **r, "passed": passed})
            print(f"  {status} | '{sq['query'][:40]}' → {r['total_results']} results | {r['latency_ms']:.0f}ms | {sq['description']}")
        print(f"  Search accuracy: {search_pass}/{search_total} ({search_pass/search_total*100:.0f}%)")

        # ── Tool 3: Context ──
        print("\n--- Tool 3: continuum_context ---")
        context_pass = 0
        context_total = len(CONTEXT_ENTITIES)
        for ce in CONTEXT_ENTITIES:
            r = await tool_context(session, ce["name"], "eval-mcp")
            found_match = r.get("entity_found", False) == ce["expect_found"]
            decision_match = True
            if ce["expect_decisions"] and r.get("entity_found"):
                decision_match = r.get("decision_count", 0) > 0
            passed = found_match and decision_match
            if passed:
                context_pass += 1
            status = "PASS" if passed else "FAIL"
            dec_count = r.get("decision_count", 0) if r.get("entity_found") else "N/A"
            results["context"].append({**ce, **r, "passed": passed})
            print(f"  {status} | '{ce['name']}' → found={r.get('entity_found')}, decisions={dec_count} | {r['latency_ms']:.0f}ms")
        print(f"  Context accuracy: {context_pass}/{context_total} ({context_pass/context_total*100:.0f}%)")

        # ── Tool 4: Check ──
        print("\n--- Tool 4: continuum_check ---")
        check_pass = 0
        check_total = len(CHECK_PROPOSALS)
        for cp in CHECK_PROPOSALS:
            r = await tool_check(session, cp["proposed"], cp["entities"], "eval-mcp")
            expected_similar = cp["expect_similar"]
            actual_similar = r["similar_count"] > 0
            passed = expected_similar == actual_similar
            if passed:
                check_pass += 1
            status = "PASS" if passed else "FAIL"
            results["check"].append({**cp, **r, "passed": passed})
            print(f"  {status} | '{cp['proposed'][:50]}' → {r['recommendation']} ({r['similar_count']} similar) | {r['latency_ms']:.0f}ms")
        print(f"  Check accuracy: {check_pass}/{check_total} ({check_pass/check_total*100:.0f}%)")

        # ── Tool 5: Remember ──
        print("\n--- Tool 5: continuum_remember ---")
        remember_pass = 0
        remember_total = len(REMEMBER_TESTS)
        for rt in REMEMBER_TESTS:
            r = await tool_remember(
                session, rt["trigger"], rt["decision"], rt["rationale"],
                rt["entities"], "eval-mcp"
            )
            passed = r["success"]
            if passed:
                remember_pass += 1
            status = "PASS" if passed else "FAIL"
            results["remember"].append({**rt, **r, "passed": passed})
            print(f"  {status} | '{rt['description']}' → stored={r['success']}, linked={r['entities_linked']} | {r['latency_ms']:.0f}ms")
        print(f"  Remember accuracy: {remember_pass}/{remember_total} ({remember_pass/remember_total*100:.0f}%)")

        # Verify remembered decisions can be found
        print("\n--- Verification: Can we find remembered decisions? ---")
        verify_pass = 0
        for rt in REMEMBER_TESTS:
            r = await tool_search(session, rt["trigger"][:50], "eval-mcp")
            found = r["total_results"] > 0
            if found:
                verify_pass += 1
            status = "PASS" if found else "FAIL"
            print(f"  {status} | Search for '{rt['trigger'][:50]}' → {r['total_results']} results")
        print(f"  Verification: {verify_pass}/{len(REMEMBER_TESTS)}")

    await driver.close()

    # ── Summary ──
    print("\n" + "=" * 60)
    print("MCP EVALUATION SUMMARY")
    print("=" * 60)

    tool_results = {
        "summary": {"pass": 1 if results["summary"]["success"] else 0, "total": 1},
        "search": {"pass": sum(1 for r in results["search"] if r["passed"]), "total": len(results["search"])},
        "context": {"pass": sum(1 for r in results["context"] if r["passed"]), "total": len(results["context"])},
        "check": {"pass": sum(1 for r in results["check"] if r["passed"]), "total": len(results["check"])},
        "remember": {"pass": sum(1 for r in results["remember"] if r["passed"]), "total": len(results["remember"])},
    }

    total_pass = sum(t["pass"] for t in tool_results.values())
    total_tests = sum(t["total"] for t in tool_results.values())

    for tool_name, tr in tool_results.items():
        pct = tr["pass"] / tr["total"] * 100 if tr["total"] else 0
        print(f"  {tool_name:12s}: {tr['pass']}/{tr['total']} ({pct:.0f}%)")
    print(f"  {'OVERALL':12s}: {total_pass}/{total_tests} ({total_pass/total_tests*100:.0f}%)")

    # Latency summary
    all_latencies = []
    for r in results["search"]:
        all_latencies.append(r.get("latency_ms", 0))
    for r in results["context"]:
        all_latencies.append(r.get("latency_ms", 0))
    for r in results["check"]:
        all_latencies.append(r.get("latency_ms", 0))
    all_latencies.sort()
    if all_latencies:
        print(f"\n  Latency: p50={all_latencies[len(all_latencies)//2]:.0f}ms, "
              f"p95={all_latencies[int(len(all_latencies)*0.95)]:.0f}ms, "
              f"mean={sum(all_latencies)/len(all_latencies):.0f}ms")

    # Save
    output = {
        "tool_results": tool_results,
        "total_pass": total_pass,
        "total_tests": total_tests,
        "overall_accuracy": round(total_pass / total_tests * 100, 1),
        "details": results,
    }
    output_path = OUTPUT_DIR / "mcp_eval_results.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(output, f, indent=2, default=str)
    print(f"\n  Saved to {output_path}")


if __name__ == "__main__":
    asyncio.run(main())
