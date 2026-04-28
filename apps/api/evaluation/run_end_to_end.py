#!/usr/bin/env python3
"""Run the FULL Continuum pipeline end-to-end on synthetic conversations.

Extracts decisions using the LLM, resolves entities, creates relationships,
and reports comprehensive knowledge graph statistics.

This produces the numbers for the full system paper (RQ1: extraction yield,
RQ3: graph structure quality).

Usage:
    cd apps/api
    .venv/bin/python -m evaluation.run_end_to_end
"""

import asyncio
import json
import os
import sys
import time
from collections import Counter
from pathlib import Path

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


async def extract_decision_from_conversation(llm_client, conversation: dict) -> list[dict]:
    """Use the LLM to extract structured decisions from a conversation."""
    # Build conversation text
    messages_text = ""
    for msg in conversation.get("messages", []):
        role = msg.get("role", "unknown").upper()
        content = msg.get("content", "")
        messages_text += f"\n{role}: {content}\n"

    prompt = f"""Analyze this developer-AI conversation and extract ALL technology decisions made.

For each decision, provide a JSON object with these fields:
- trigger: What prompted the decision (the problem or need)
- context: Background constraints and requirements
- options: List of alternatives considered (as array of strings)
- decision: What was chosen
- rationale: Why this was chosen over alternatives
- confidence: How explicit the decision is (0.0-1.0)
- entities: List of technology names mentioned (as array of strings)

Return a JSON array of decision objects. If no clear decisions are made, return an empty array [].

CONVERSATION:
{messages_text}

Respond with ONLY valid JSON (no markdown, no explanation):"""

    try:
        response = await llm_client.generate(prompt, max_tokens=4096, sanitize_input=False)
        # Strip thinking tags if present
        import re
        response = re.sub(r'<think>.*?</think>', '', response, flags=re.DOTALL).strip()
        # Try to find JSON array in response
        start = response.find('[')
        end = response.rfind(']') + 1
        if start >= 0 and end > start:
            try:
                decisions = json.loads(response[start:end])
                return decisions if isinstance(decisions, list) else []
            except json.JSONDecodeError:
                # Try to repair truncated JSON by finding the last complete object
                text = response[start:end]
                # Find the last complete '}' that closes an object in the array
                last_brace = text.rfind('}')
                if last_brace > 0:
                    repaired = text[:last_brace + 1] + ']'
                    try:
                        decisions = json.loads(repaired)
                        return decisions if isinstance(decisions, list) else []
                    except json.JSONDecodeError:
                        pass
        # If no closing ']', try to repair from just the opening '['
        if start >= 0:
            text = response[start:]
            last_brace = text.rfind('}')
            if last_brace > 0:
                repaired = text[:last_brace + 1] + ']'
                try:
                    decisions = json.loads(repaired)
                    return decisions if isinstance(decisions, list) else []
                except json.JSONDecodeError:
                    pass
        return []
    except Exception as e:
        print(f"    LLM extraction error: {e}")
        return []


async def store_decision(session, decision: dict, conv_id: str, user_id: str, resolver) -> dict:
    """Store a decision and its entities in Neo4j."""
    from uuid import uuid4

    decision_id = str(uuid4())

    # Create DecisionTrace node
    await session.run(
        """
        CREATE (d:DecisionTrace {
            id: $id,
            trigger: $trigger,
            context: $context,
            decision: $decision,
            rationale: $rationale,
            confidence: $confidence,
            source: 'synthetic',
            conversation_id: $conv_id,
            user_id: $user_id,
            options: $options
        })
        """,
        parameters={
            "id": decision_id,
            "trigger": decision.get("trigger", ""),
            "context": decision.get("context", ""),
            "decision": decision.get("decision", ""),
            "rationale": decision.get("rationale", ""),
            "confidence": float(decision.get("confidence", 0.5)),
            "conv_id": conv_id,
            "user_id": user_id,
            "options": decision.get("options", []),
        }
    )

    # Resolve and link entities
    entities_linked = 0
    for entity_name in decision.get("entities", []):
        if not entity_name or len(entity_name) < 2:
            continue
        try:
            resolved = await resolver.resolve(entity_name, "technology")
            entity_id = resolved.id

            # Create entity if new
            if resolved.is_new:
                await session.run(
                    """
                    MERGE (e:Entity {id: $id})
                    ON CREATE SET e.name = $name, e.type = $type,
                                  e.user_id = $user_id, e.aliases = $aliases
                    """,
                    parameters={
                        "id": entity_id,
                        "name": resolved.name,
                        "type": resolved.type,
                        "user_id": user_id,
                        "aliases": resolved.aliases or [],
                    }
                )

            # Create INVOLVES relationship
            await session.run(
                """
                MATCH (d:DecisionTrace {id: $did}), (e:Entity {id: $eid})
                MERGE (d)-[:INVOLVES]->(e)
                """,
                parameters={"did": decision_id, "eid": entity_id}
            )
            entities_linked += 1
        except Exception as e:
            pass  # Skip failed entity resolution

    return {
        "decision_id": decision_id,
        "entities_linked": entities_linked,
        "trigger": decision.get("trigger", "")[:80],
    }


async def main():
    neo4j_uri = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
    neo4j_user = os.environ.get("NEO4J_USER", "neo4j")
    neo4j_password = os.environ.get("NEO4J_PASSWORD", "password")
    driver = AsyncGraphDatabase.driver(neo4j_uri, auth=(neo4j_user, neo4j_password))

    # Verify connection
    async with driver.session(database="neo4j") as session:
        result = await session.run("RETURN 1")
        await result.consume()
    print("Connected to Neo4j")

    # Initialize LLM client
    from services.llm import get_llm_client
    llm = get_llm_client()
    print("LLM client initialized")

    # Load conversations
    conv_dir = Path(__file__).resolve().parent / "data" / "synthetic_conversations"
    conv_files = sorted(conv_dir.glob("conv-*.json"))
    print(f"Found {len(conv_files)} conversations")

    user_id = "eval-e2e"

    # Process each conversation
    total_decisions = 0
    total_entities_linked = 0
    decisions_per_conv = []
    extraction_times = []
    domain_decisions = Counter()

    for i, conv_file in enumerate(conv_files):
        with open(conv_file, encoding="utf-8") as f:
            conv = json.load(f)

        conv_id = conv.get("id", conv_file.stem)
        domain = conv.get("domain", "unknown")
        topic = conv.get("topic", "")

        print(f"\n[{i+1}/{len(conv_files)}] {conv_id}: {topic}")

        # Extract decisions via LLM
        start = time.monotonic()
        decisions = await extract_decision_from_conversation(llm, conv)
        extraction_time = time.monotonic() - start
        extraction_times.append(extraction_time)

        print(f"  Extracted {len(decisions)} decisions in {extraction_time:.1f}s")

        # Store each decision
        async with driver.session(database="neo4j") as session:
            from services.entity_resolver import EntityResolver
            resolver = EntityResolver(session, user_id=user_id)

            for dec in decisions:
                try:
                    result = await store_decision(session, dec, conv_id, user_id, resolver)
                    total_decisions += 1
                    total_entities_linked += result["entities_linked"]
                    domain_decisions[domain] += 1
                    print(f"    Decision: {result['trigger']}... ({result['entities_linked']} entities)")
                except Exception as e:
                    print(f"    Error storing decision: {e}")

        decisions_per_conv.append(len(decisions))

    # ═══════════════════════════════════════════
    # Final Statistics
    # ═══════════════════════════════════════════
    print("\n" + "=" * 60)
    print("END-TO-END PIPELINE RESULTS")
    print("=" * 60)

    # Graph stats
    async with driver.session(database="neo4j") as session:
        result = await session.run("MATCH (n) RETURN labels(n)[0] AS label, count(n) AS c ORDER BY c DESC")
        nodes = await result.data()

        result = await session.run("MATCH ()-[r]->() RETURN type(r) AS type, count(r) AS c ORDER BY c DESC")
        rels = await result.data()

        result = await session.run("MATCH (e:Entity) RETURN e.type AS type, count(e) AS c ORDER BY c DESC")
        entity_types = await result.data()

        result = await session.run("""
            MATCH (e:Entity)<-[:INVOLVES]-(d:DecisionTrace)
            RETURN e.name AS name, count(d) AS decisions
            ORDER BY decisions DESC LIMIT 15
        """)
        top_entities = await result.data()

        result = await session.run("MATCH (d:DecisionTrace) RETURN avg(d.confidence) AS avg_conf")
        avg_conf = await result.single()

        # Graph density
        result = await session.run("MATCH (n) RETURN count(n) AS nodes")
        node_count = (await result.single())["nodes"]
        result = await session.run("MATCH ()-[r]->() RETURN count(r) AS rels")
        rel_count = (await result.single())["rels"]

    print(f"\nConversations processed: {len(conv_files)}")
    print(f"Decisions extracted: {total_decisions}")
    print(f"Avg decisions per conversation: {sum(decisions_per_conv)/len(decisions_per_conv):.1f}")
    print(f"Entity-decision links created: {total_entities_linked}")
    print(f"Avg extraction time: {sum(extraction_times)/len(extraction_times):.1f}s")

    print(f"\nGraph:")
    total_nodes = 0
    for n in nodes:
        print(f"  {n['label']}: {n['c']}")
        total_nodes += n['c']
    print(f"  Total nodes: {total_nodes}")
    print(f"  Total relationships: {rel_count}")
    if node_count > 1:
        density = rel_count / (node_count * (node_count - 1))
        print(f"  Graph density: {density:.4f}")

    if avg_conf and avg_conf["avg_conf"]:
        print(f"\nAvg decision confidence: {avg_conf['avg_conf']:.2f}")

    print(f"\nDecisions by domain:")
    for domain, count in domain_decisions.most_common():
        print(f"  {domain}: {count}")

    print(f"\nEntity type distribution:")
    for et in entity_types:
        print(f"  {et['type']}: {et['c']}")

    print(f"\nTop 15 most-referenced entities:")
    for e in top_entities:
        print(f"  {e['name']}: {e['decisions']} decisions")

    # Save results
    output_path = Path(__file__).resolve().parent / "data" / "e2e_results.json"
    results = {
        "conversations": len(conv_files),
        "total_decisions": total_decisions,
        "avg_decisions_per_conv": round(sum(decisions_per_conv) / len(decisions_per_conv), 1),
        "total_entity_links": total_entities_linked,
        "avg_extraction_time_s": round(sum(extraction_times) / len(extraction_times), 1),
        "graph_nodes": total_nodes,
        "graph_relationships": rel_count,
        "node_breakdown": {n["label"]: n["c"] for n in nodes},
        "relationship_breakdown": {r["type"]: r["c"] for r in rels},
        "decisions_by_domain": dict(domain_decisions),
        "top_entities": top_entities,
        "decisions_per_conv": decisions_per_conv,
    }
    with open(output_path, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nResults saved to {output_path}")

    await driver.close()


if __name__ == "__main__":
    asyncio.run(main())
