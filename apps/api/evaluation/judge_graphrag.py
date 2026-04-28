#!/usr/bin/env python3
"""Step through pre-generated GraphRAG queries, show results, collect judgments.

Loads queries from a file, runs each through the GraphRAG pipeline,
displays the results, and asks for a relevance judgment.

Usage:
    cd apps/api
    .venv/bin/python -m evaluation.judge_graphrag
"""

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
MAGENTA = "\033[95m"
RESET = "\033[0m"

QUERIES_FILE = Path(__file__).resolve().parent.parent.parent.parent / "papers" / "research-logs" / "manual-graphrag-queries.txt"
OUTPUT_FILE = Path(__file__).resolve().parent / "data" / "manual_graphrag_judgments.json"


def load_queries(filepath: Path) -> list[str]:
    queries = []
    with open(filepath) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#"):
                queries.append(line)
    return queries


async def run_query(rag, session, query: str, user_id: str = "eval-e2e"):
    try:
        subgraph, context_str, seed_ids = await rag.retrieve_context(
            query, user_id=user_id, top_k=5, depth=2, session=session
        )
        return subgraph, context_str, seed_ids
    except Exception as e:
        print(f"  {RED}Error: {e}{RESET}")
        return None, None, None


def display(query: str, idx: int, total: int, subgraph: dict, context_str: str, seed_ids: list):
    print(f"\n{'━' * 70}")
    print(f"{DIM}[{idx}/{total}]{RESET}  {BOLD}{CYAN}{query}{RESET}")
    print(f"{'━' * 70}")

    if not subgraph or not subgraph.get("nodes"):
        print(f"\n  {RED}No results found.{RESET}")
        return

    nodes = subgraph.get("nodes", [])
    decisions = [n for n in nodes if n.get("label") == "DecisionTrace"]
    entities = [n for n in nodes if n.get("label") == "Entity"]

    print(f"\n  {DIM}Found: {len(decisions)} decisions, {len(entities)} entities{RESET}")

    # Show decisions
    for i, d in enumerate(decisions[:5]):
        trigger = (d.get("trigger") or d.get("name") or "")[:90]
        decision = (d.get("decision") or d.get("agent_decision") or "")[:90]
        rationale = (d.get("rationale") or d.get("agent_rationale") or "")[:90]
        conf = d.get("confidence", "?")
        is_seed = f" {MAGENTA}★ SEED{RESET}" if d.get("id") in (seed_ids or []) else ""

        print(f"\n  {GREEN}Decision {i+1}:{RESET}{is_seed}")
        print(f"    {BOLD}Trigger:{RESET}   {trigger}")
        print(f"    {BOLD}Decision:{RESET}  {YELLOW}{decision}{RESET}")
        if rationale:
            print(f"    {BOLD}Rationale:{RESET} {rationale}")
        print(f"    {DIM}Confidence: {conf}{RESET}")

    # Show entities
    if entities:
        ent_names = [e.get("name", "?") for e in entities[:12]]
        print(f"\n  {CYAN}Entities:{RESET} {', '.join(ent_names)}")


async def main():
    from neo4j import AsyncGraphDatabase
    from services.graph_rag import GraphRAGService

    # Load queries
    if not QUERIES_FILE.exists():
        print(f"{RED}Queries file not found: {QUERIES_FILE}{RESET}")
        print(f"Create it or run: .venv/bin/python -m evaluation.query_graphrag --file PATH")
        sys.exit(1)

    queries = load_queries(QUERIES_FILE)
    print(f"\n{BOLD}GraphRAG Relevance Judging Tool{RESET}")
    print(f"Loaded {len(queries)} queries from {QUERIES_FILE.name}")
    print(f"\nFor each query, I'll show the retrieved decisions.")
    print(f"Rate relevance:  {GREEN}3{RESET}=relevant  {YELLOW}2{RESET}=partial  {RED}1{RESET}=irrelevant  {DIM}s{RESET}=skip  {DIM}q{RESET}=quit\n")

    driver = AsyncGraphDatabase.driver(
        os.environ.get("NEO4J_URI", "bolt://localhost:7687"),
        auth=(os.environ.get("NEO4J_USER", "neo4j"),
              os.environ.get("NEO4J_PASSWORD", "password"))
    )
    rag = GraphRAGService()

    judgments = []

    # Load existing judgments to resume
    if OUTPUT_FILE.exists():
        with open(OUTPUT_FILE) as f:
            judgments = json.load(f)
        judged_queries = {j["query"] for j in judgments}
        queries = [q for q in queries if q not in judged_queries]
        if judgments:
            print(f"{DIM}Resuming — {len(judgments)} already judged, {len(queries)} remaining{RESET}\n")

    async with driver.session(database="neo4j") as session:
        for i, query in enumerate(queries):
            subgraph, context_str, seed_ids = await run_query(rag, session, query)
            display(query, i + 1, len(queries), subgraph, context_str, seed_ids)

            # Get judgment
            while True:
                try:
                    score = input(f"\n  {BOLD}Relevance (3/2/1/s/q):{RESET} ").strip().lower()
                except (EOFError, KeyboardInterrupt):
                    score = "q"

                if score == "q":
                    break
                elif score == "s":
                    break
                elif score in ("1", "2", "3"):
                    decisions_found = len([n for n in (subgraph or {}).get("nodes", []) if n.get("label") == "DecisionTrace"])
                    judgments.append({
                        "query": query,
                        "relevance": int(score),
                        "decisions_found": decisions_found,
                        "entities_found": len([n for n in (subgraph or {}).get("nodes", []) if n.get("label") == "Entity"]),
                    })
                    label = {3: f"{GREEN}Relevant{RESET}", 2: f"{YELLOW}Partial{RESET}", 1: f"{RED}Irrelevant{RESET}"}
                    print(f"  → {label[int(score)]}")

                    # Auto-save
                    with open(OUTPUT_FILE, "w") as f:
                        json.dump(judgments, f, indent=2)
                    break
                else:
                    print(f"  {RED}Type 3, 2, 1, s, or q{RESET}")

            if score == "q":
                break

    await driver.close()

    # Summary
    if judgments:
        rated = [j for j in judgments if "relevance" in j]
        avg = sum(j["relevance"] for j in rated) / len(rated) if rated else 0
        dist = {1: 0, 2: 0, 3: 0}
        for j in rated:
            dist[j["relevance"]] += 1

        print(f"\n{'━' * 70}")
        print(f"{BOLD}SUMMARY{RESET}")
        print(f"  Judged: {len(rated)} queries")
        print(f"  Relevant (3): {GREEN}{dist[3]}{RESET}")
        print(f"  Partial  (2): {YELLOW}{dist[2]}{RESET}")
        print(f"  Irrelevant(1): {RED}{dist[1]}{RESET}")
        print(f"  {BOLD}Average relevance: {avg:.2f}/3.0{RESET}")
        print(f"\n  Saved to {OUTPUT_FILE}")


if __name__ == "__main__":
    asyncio.run(main())
