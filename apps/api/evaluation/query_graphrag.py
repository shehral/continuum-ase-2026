#!/usr/bin/env python3
"""Interactive GraphRAG query tool.

Runs queries against the knowledge graph and shows retrieved context.
Use for manual relevance evaluation.

Usage:
    # Interactive mode
    cd apps/api && .venv/bin/python -m evaluation.query_graphrag

    # Batch mode (from file)
    .venv/bin/python -m evaluation.query_graphrag --file papers/research-logs/manual-graphrag-queries.txt

    # Single query
    .venv/bin/python -m evaluation.query_graphrag --query "Why was PostgreSQL chosen?"
"""

import argparse
import asyncio
import json
import os
import sys
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

BOLD = "\033[1m"
DIM = "\033[2m"
CYAN = "\033[96m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
RED = "\033[91m"
RESET = "\033[0m"


async def run_query(query: str, user_id: str = "eval-e2e"):
    from neo4j import AsyncGraphDatabase
    from services.graph_rag import GraphRAGService

    driver = AsyncGraphDatabase.driver(
        os.environ.get("NEO4J_URI", "bolt://localhost:7687"),
        auth=(os.environ.get("NEO4J_USER", "neo4j"),
              os.environ.get("NEO4J_PASSWORD", "password"))
    )
    rag = GraphRAGService()

    async with driver.session(database="neo4j") as session:
        try:
            subgraph, context_str, seed_ids = await rag.retrieve_context(
                query, user_id=user_id, top_k=5, depth=2, session=session
            )
        except Exception as e:
            print(f"{RED}Error: {e}{RESET}")
            await driver.close()
            return None, None, None

    await driver.close()
    return subgraph, context_str, seed_ids


def display_result(query: str, subgraph: dict, context_str: str, seed_ids: list):
    print(f"\n{'=' * 70}")
    print(f"{BOLD}Query:{RESET} {CYAN}{query}{RESET}")
    print(f"{'=' * 70}")

    if not subgraph or not subgraph.get("nodes"):
        print(f"{RED}No results found.{RESET}")
        return

    nodes = subgraph.get("nodes", [])
    edges = subgraph.get("edges", [])

    # Separate decisions from entities
    decisions = [n for n in nodes if n.get("label") == "DecisionTrace"]
    entities = [n for n in nodes if n.get("label") == "Entity"]

    print(f"\n{BOLD}Retrieved:{RESET} {len(decisions)} decisions, {len(entities)} entities, {len(edges)} relationships")
    print(f"{DIM}Seed nodes: {len(seed_ids)}{RESET}")

    # Show decisions
    if decisions:
        print(f"\n{BOLD}{GREEN}Decisions:{RESET}")
        for i, d in enumerate(decisions[:5]):
            trigger = d.get("trigger", d.get("name", ""))[:100]
            decision = d.get("decision", d.get("agent_decision", ""))[:100]
            confidence = d.get("confidence", "?")
            is_seed = "SEED" if d.get("id") in seed_ids else ""
            print(f"  {GREEN}{i+1}.{RESET} {trigger}")
            print(f"     → {YELLOW}{decision}{RESET}")
            print(f"     {DIM}confidence: {confidence} {is_seed}{RESET}")

    # Show top entities
    if entities:
        print(f"\n{BOLD}{CYAN}Related Entities:{RESET}")
        ent_names = [e.get("name", "?") for e in entities[:10]]
        print(f"  {', '.join(ent_names)}")

    # Show context preview
    if context_str:
        preview = context_str[:500]
        print(f"\n{BOLD}Context Preview:{RESET}")
        print(f"{DIM}{preview}...{RESET}")


async def interactive_mode():
    print(f"\n{BOLD}GraphRAG Interactive Query Tool{RESET}")
    print(f"Type a question and press Enter. Type 'q' to quit.\n")

    results = []
    while True:
        try:
            query = input(f"{BOLD}Query:{RESET} ").strip()
        except (EOFError, KeyboardInterrupt):
            break

        if not query or query.lower() == "q":
            break

        subgraph, context_str, seed_ids = await run_query(query)
        if subgraph:
            display_result(query, subgraph, context_str, seed_ids)

            # Ask for relevance judgment
            try:
                score = input(f"\n{BOLD}Relevance (1=irrelevant, 2=partial, 3=relevant, s=skip):{RESET} ").strip()
            except (EOFError, KeyboardInterrupt):
                break

            if score in ("1", "2", "3"):
                results.append({
                    "query": query,
                    "relevance": int(score),
                    "decisions_found": len([n for n in subgraph.get("nodes", []) if n.get("label") == "DecisionTrace"]),
                    "entities_found": len([n for n in subgraph.get("nodes", []) if n.get("label") == "Entity"]),
                })
                print(f"{DIM}Recorded.{RESET}")

    # Save results
    if results:
        output = Path(__file__).resolve().parent / "data" / "manual_graphrag_judgments.json"
        with open(output, "w") as f:
            json.dump(results, f, indent=2)
        avg = sum(r["relevance"] for r in results) / len(results)
        print(f"\n{BOLD}Saved {len(results)} judgments to {output}{RESET}")
        print(f"Average relevance: {avg:.2f}/3.0")


async def batch_mode(filepath: str):
    queries = []
    with open(filepath) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#"):
                queries.append(line)

    print(f"Running {len(queries)} queries from {filepath}\n")

    results = []
    for i, query in enumerate(queries):
        subgraph, context_str, seed_ids = await run_query(query)
        if subgraph:
            display_result(query, subgraph, context_str, seed_ids)
            decisions = len([n for n in subgraph.get("nodes", []) if n.get("label") == "DecisionTrace"])
            entities = len([n for n in subgraph.get("nodes", []) if n.get("label") == "Entity"])
            results.append({
                "query": query,
                "decisions_found": decisions,
                "entities_found": entities,
                "context_length": len(context_str) if context_str else 0,
            })
        else:
            results.append({"query": query, "decisions_found": 0, "entities_found": 0, "context_length": 0})
        print()

    # Summary
    found = sum(1 for r in results if r["decisions_found"] > 0)
    print(f"\n{'=' * 70}")
    print(f"{BOLD}SUMMARY{RESET}: {found}/{len(results)} queries returned decisions")
    avg_decisions = sum(r["decisions_found"] for r in results) / len(results)
    print(f"Average decisions per query: {avg_decisions:.1f}")

    output = Path(__file__).resolve().parent / "data" / "batch_graphrag_results.json"
    with open(output, "w") as f:
        json.dump(results, f, indent=2)
    print(f"Saved to {output}")


async def single_query(query: str):
    subgraph, context_str, seed_ids = await run_query(query)
    if subgraph:
        display_result(query, subgraph, context_str, seed_ids)


def main():
    parser = argparse.ArgumentParser(description="GraphRAG query tool")
    parser.add_argument("--query", type=str, help="Single query to run")
    parser.add_argument("--file", type=str, help="File with queries (one per line)")
    args = parser.parse_args()

    if args.query:
        asyncio.run(single_query(args.query))
    elif args.file:
        asyncio.run(batch_mode(args.file))
    else:
        asyncio.run(interactive_mode())


if __name__ == "__main__":
    main()
