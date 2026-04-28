#!/usr/bin/env python3
"""Review extracted decision quality.

Pulls random decisions from Neo4j, shows the original conversation
alongside extracted fields, and collects quality judgments.

Usage:
    cd apps/api
    .venv/bin/python -m evaluation.review_decisions [--count 50]
"""

import asyncio
import json
import os
import random
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

OUTPUT_FILE = Path(__file__).resolve().parent / "data" / "v5" / "decision_quality_judgments.json"


async def load_decisions(count: int = 50):
    from neo4j import AsyncGraphDatabase

    driver = AsyncGraphDatabase.driver(
        os.environ.get("NEO4J_URI", "bolt://localhost:7687"),
        auth=(os.environ.get("NEO4J_USER", "neo4j"),
              os.environ.get("NEO4J_PASSWORD", "password"))
    )

    async with driver.session(database="neo4j") as session:
        r = await session.run("""
            MATCH (d:DecisionTrace)-[:INVOLVES]->(e:Entity)
            WITH d, collect(e.name) AS entities
            WHERE d.trigger IS NOT NULL AND d.trigger <> ''
            RETURN d.id AS id, d.trigger AS trigger, d.context AS context,
                   d.decision AS decision, d.rationale AS rationale,
                   d.confidence AS confidence, d.conversation_id AS conv_id,
                   d.options AS options, entities
            ORDER BY rand()
            LIMIT $count
        """, parameters={"count": count})
        decisions = await r.data()

    await driver.close()

    # Load original conversations for context
    conv_dir = Path(__file__).resolve().parent / "data" / "synthetic_conversations"
    conversations = {}
    for d in decisions:
        conv_id = d.get("conv_id", "")
        if conv_id and conv_id not in conversations:
            conv_file = conv_dir / f"{conv_id}.json"
            if conv_file.exists():
                with open(conv_file) as f:
                    conv = json.load(f)
                # Full conversation text
                text = "\n".join(
                    f"  {m['role'].upper()}: {m['content']}"
                    for m in conv.get("messages", [])
                )
                conversations[conv_id] = {
                    "topic": conv.get("topic", ""),
                    "preview": text,
                }

    return decisions, conversations


def display_decision(d: dict, conv_info: dict, idx: int, total: int):
    print(f"\n{'━' * 70}")
    print(f"{DIM}[{idx}/{total}]{RESET}")

    # Show conversation context
    conv_id = d.get("conv_id", "?")
    topic = conv_info.get("topic", "")
    preview = conv_info.get("preview", "")

    print(f"\n{BOLD}Conversation:{RESET} {CYAN}{conv_id}{RESET} — {topic}")
    if preview:
        print(f"{DIM}{preview}{RESET}")

    # Show extracted decision
    print(f"\n{BOLD}{GREEN}Extracted Decision:{RESET}")
    print(f"  {BOLD}Trigger:{RESET}    {d.get('trigger', '?')}")
    print(f"  {BOLD}Decision:{RESET}   {YELLOW}{d.get('decision', '?')}{RESET}")
    print(f"  {BOLD}Rationale:{RESET}  {d.get('rationale', '?')}")
    if d.get("options"):
        opts = d["options"] if isinstance(d["options"], list) else [d["options"]]
        print(f"  {BOLD}Options:{RESET}    {', '.join(str(o) for o in opts)}")
    print(f"  {BOLD}Entities:{RESET}   {', '.join(d.get('entities', []))}")
    print(f"  {BOLD}Confidence:{RESET} {d.get('confidence', '?')}")

    print(f"\n  {BOLD}Judge:{RESET} {GREEN}c{RESET}=correct  {YELLOW}p{RESET}=partial  {RED}w{RESET}=wrong  {MAGENTA}n{RESET}=not-a-decision  {DIM}s{RESET}=skip  {DIM}q{RESET}=quit")


async def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--count", type=int, default=50)
    args = parser.parse_args()

    print(f"\n{BOLD}Decision Extraction Quality Review{RESET}")
    print(f"Loading {args.count} random decisions from the graph...\n")

    decisions, conversations = await load_decisions(args.count)
    print(f"Loaded {len(decisions)} decisions")

    # Load existing judgments for resume
    judgments = []
    judged_ids = set()
    if OUTPUT_FILE.exists():
        with open(OUTPUT_FILE) as f:
            judgments = json.load(f)
        judged_ids = {j["decision_id"] for j in judgments}
        print(f"{DIM}Resuming — {len(judgments)} already judged{RESET}")

    decisions = [d for d in decisions if d["id"] not in judged_ids]
    print(f"{len(decisions)} remaining to judge\n")

    for i, d in enumerate(decisions):
        conv_id = d.get("conv_id", "")
        conv_info = conversations.get(conv_id, {"topic": "", "preview": ""})

        display_decision(d, conv_info, i + 1, len(decisions))

        while True:
            try:
                score = input(f"\n  {BOLD}Judgment:{RESET} ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                score = "q"

            if score == "q":
                break
            elif score == "s":
                break
            elif score in ("c", "p", "w", "n"):
                label = {"c": "CORRECT", "p": "PARTIAL", "w": "WRONG", "n": "NOT_A_DECISION"}[score]
                judgments.append({
                    "decision_id": d["id"],
                    "conversation_id": conv_id,
                    "trigger": d.get("trigger", "")[:100],
                    "decision": d.get("decision", "")[:100],
                    "judgment": label,
                })
                color = {"c": GREEN, "p": YELLOW, "w": RED, "n": MAGENTA}[score]
                print(f"  → {color}{label}{RESET}")

                # Auto-save
                with open(OUTPUT_FILE, "w") as f:
                    json.dump(judgments, f, indent=2)
                break
            else:
                print(f"  {RED}Type c, p, w, n, s, or q{RESET}")

        if score == "q":
            break

    # Summary
    if judgments:
        from collections import Counter
        counts = Counter(j["judgment"] for j in judgments)
        total = len(judgments)
        print(f"\n{'━' * 70}")
        print(f"{BOLD}SUMMARY{RESET}: {total} decisions reviewed")
        print(f"  {GREEN}CORRECT:{RESET}        {counts.get('CORRECT', 0)} ({counts.get('CORRECT', 0)/total*100:.0f}%)")
        print(f"  {YELLOW}PARTIAL:{RESET}        {counts.get('PARTIAL', 0)} ({counts.get('PARTIAL', 0)/total*100:.0f}%)")
        print(f"  {RED}WRONG:{RESET}          {counts.get('WRONG', 0)} ({counts.get('WRONG', 0)/total*100:.0f}%)")
        print(f"  {MAGENTA}NOT_A_DECISION:{RESET} {counts.get('NOT_A_DECISION', 0)} ({counts.get('NOT_A_DECISION', 0)/total*100:.0f}%)")
        precision = (counts.get("CORRECT", 0) + counts.get("PARTIAL", 0)) / total * 100
        print(f"\n  {BOLD}Extraction precision (correct+partial): {precision:.0f}%{RESET}")
        print(f"  Saved to {OUTPUT_FILE}")


if __name__ == "__main__":
    asyncio.run(main())
