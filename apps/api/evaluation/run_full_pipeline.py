#!/usr/bin/env python3
"""Full 200-conversation extraction + GraphRAG evaluation pipeline.

Steps:
1. Wipe Neo4j graph + flush Redis
2. Extract decisions from all 200 synthetic conversations via LLM
3. Compute entity embeddings for all entities
4. Ensure fulltext indexes exist
5. Graph statistics
6. GraphRAG evaluation (hybrid retrieval + context pipeline + config comparison)
7. Save all results to evaluation/data/v5/ and papers/research-logs/

Usage:
    cd apps/api
    .venv/bin/python -m evaluation.run_full_pipeline
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

# Suppress extremely verbose Neo4j notification logging
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

import redis.asyncio as aioredis
from neo4j import AsyncGraphDatabase


# ═══════════════════════════════════════════════════════════════════
# STEP 1: Wipe graph clean
# ═══════════════════════════════════════════════════════════════════

async def wipe_graph(driver):
    """Delete all nodes and relationships from Neo4j and flush Redis."""
    print("\n" + "=" * 60)
    print("STEP 1: WIPING GRAPH CLEAN")
    print("=" * 60)

    async with driver.session(database="neo4j") as session:
        # Count existing nodes
        r = await session.run("MATCH (n) RETURN count(n) AS c")
        count = (await r.single())["c"]
        print(f"  Existing nodes: {count}")

        # Delete in batches to avoid memory issues
        deleted = 0
        while True:
            r = await session.run(
                "MATCH (n) WITH n LIMIT 5000 DETACH DELETE n RETURN count(*) AS c"
            )
            batch = (await r.single())["c"]
            deleted += batch
            if batch == 0:
                break
            print(f"  Deleted {deleted} nodes so far...")

        print(f"  Total deleted: {deleted} nodes")

        # Verify clean
        r = await session.run("MATCH (n) RETURN count(n) AS c")
        remaining = (await r.single())["c"]
        print(f"  Remaining nodes: {remaining}")

    # Flush Redis
    try:
        redis_url = os.environ.get("REDIS_URL", "redis://127.0.0.1:6379")
        redis_client = aioredis.from_url(redis_url, decode_responses=True)
        await redis_client.flushall()
        await redis_client.close()
        print("  Redis flushed")
    except Exception as e:
        print(f"  Redis flush warning: {e}")

    print("  Graph wiped clean.")


# ═══════════════════════════════════════════════════════════════════
# STEP 2: Extract decisions from all 200 conversations
# ═══════════════════════════════════════════════════════════════════

async def extract_decision_from_conversation(llm_client, conversation: dict) -> list[dict]:
    """Use the LLM to extract structured decisions from a conversation."""
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
        # Strip thinking tags
        response = re.sub(r'<think>.*?</think>', '', response, flags=re.DOTALL).strip()

        # Try to find JSON array
        start = response.find('[')
        end = response.rfind(']') + 1
        if start >= 0 and end > start:
            try:
                decisions = json.loads(response[start:end])
                return decisions if isinstance(decisions, list) else []
            except json.JSONDecodeError:
                # Repair truncated JSON
                text = response[start:end]
                last_brace = text.rfind('}')
                if last_brace > 0:
                    repaired = text[:last_brace + 1] + ']'
                    try:
                        decisions = json.loads(repaired)
                        return decisions if isinstance(decisions, list) else []
                    except json.JSONDecodeError:
                        pass

        # If no closing ']', try repair from opening '['
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
    decision_id = str(uuid4())

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

    entities_linked = 0
    for entity_name in decision.get("entities", []):
        if not entity_name or len(entity_name) < 2:
            continue
        try:
            resolved = await resolver.resolve(entity_name, "technology")
            entity_id = resolved.id

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


async def run_extraction(driver) -> dict:
    """Run extraction on all 200 conversations."""
    print("\n" + "=" * 60)
    print("STEP 2: EXTRACTING DECISIONS FROM 200 CONVERSATIONS")
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
    print("EXTRACTION SUMMARY")
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


# ═══════════════════════════════════════════════════════════════════
# STEP 3: Compute entity embeddings
# ═══════════════════════════════════════════════════════════════════

async def compute_embeddings(driver) -> dict:
    """Compute embeddings for all entities and decisions without embeddings."""
    print("\n" + "=" * 60)
    print("STEP 3: COMPUTING ENTITY & DECISION EMBEDDINGS")
    print("=" * 60)

    from services.embeddings import get_embedding_service
    svc = get_embedding_service()

    start = time.monotonic()
    entity_count = 0
    decision_count = 0
    errors = 0

    # Embed entities
    async with driver.session(database="neo4j") as session:
        r = await session.run(
            "MATCH (e:Entity) WHERE e.embedding IS NULL RETURN e.id AS id, e.name AS name, e.type AS type"
        )
        entities = await r.data()
        print(f"  Entities without embeddings: {len(entities)}")

        # Batch embed entities
        batch_size = 32
        for batch_start in range(0, len(entities), batch_size):
            batch = entities[batch_start:batch_start + batch_size]
            texts = [f"{e.get('type', 'technology')}: {e['name']}" for e in batch]
            try:
                embeddings = await svc.embed_texts(texts, input_type="passage")
                for e, emb in zip(batch, embeddings):
                    if emb:
                        await session.run(
                            "MATCH (e:Entity {id: $id}) SET e.embedding = $embedding",
                            parameters={"id": e["id"], "embedding": emb}
                        )
                        entity_count += 1
                print(f"  Embedded entities {batch_start+1}-{min(batch_start+batch_size, len(entities))} of {len(entities)}")
            except Exception as e:
                print(f"  Embedding batch error: {e}")
                errors += 1

    # Embed decisions
    async with driver.session(database="neo4j") as session:
        r = await session.run(
            """MATCH (d:DecisionTrace) WHERE d.embedding IS NULL
            RETURN d.id AS id, d.trigger AS trigger, d.context AS context,
                   d.decision AS decision, d.rationale AS rationale, d.options AS options"""
        )
        decisions = await r.data()
        print(f"  Decisions without embeddings: {len(decisions)}")

        for batch_start in range(0, len(decisions), batch_size):
            batch = decisions[batch_start:batch_start + batch_size]
            texts = []
            for d in batch:
                parts = [
                    f"Decision Trigger: {d.get('trigger', '')}",
                    f"Context: {d.get('context', '')}",
                    f"Final Decision: {d.get('decision', '')}",
                    f"Rationale: {d.get('rationale', '')}",
                ]
                opts = d.get("options") or []
                if isinstance(opts, list):
                    parts.append(f"Options: {', '.join(opts)}")
                texts.append("\n".join(parts))

            try:
                embeddings = await svc.embed_texts(texts, input_type="passage")
                for d, emb in zip(batch, embeddings):
                    if emb:
                        await session.run(
                            "MATCH (d:DecisionTrace {id: $id}) SET d.embedding = $embedding",
                            parameters={"id": d["id"], "embedding": emb}
                        )
                        decision_count += 1
                print(f"  Embedded decisions {batch_start+1}-{min(batch_start+batch_size, len(decisions))} of {len(decisions)}")
            except Exception as e:
                print(f"  Decision embedding batch error: {e}")
                errors += 1

    elapsed = time.monotonic() - start
    print(f"\n  Entities embedded: {entity_count}")
    print(f"  Decisions embedded: {decision_count}")
    print(f"  Errors: {errors}")
    print(f"  Time: {elapsed:.1f}s")

    return {
        "entities_embedded": entity_count,
        "decisions_embedded": decision_count,
        "errors": errors,
        "time_s": round(elapsed, 1),
    }


# ═══════════════════════════════════════════════════════════════════
# STEP 4: Ensure fulltext indexes exist
# ═══════════════════════════════════════════════════════════════════

async def ensure_indexes(driver):
    """Create or recreate fulltext indexes."""
    print("\n" + "=" * 60)
    print("STEP 4: ENSURING FULLTEXT INDEXES")
    print("=" * 60)

    async with driver.session(database="neo4j") as session:
        # Drop existing indexes
        for idx_name in ["decision_fulltext", "entity_fulltext"]:
            try:
                await session.run(f"DROP INDEX {idx_name} IF EXISTS")
                print(f"  Dropped existing index: {idx_name}")
            except Exception as e:
                print(f"  Could not drop {idx_name}: {e}")

        # Create decision fulltext index
        await session.run(
            """CREATE FULLTEXT INDEX decision_fulltext IF NOT EXISTS
            FOR (d:DecisionTrace) ON EACH [d.trigger, d.context, d.decision, d.rationale]"""
        )
        print("  Created decision_fulltext index")

        # Create entity fulltext index
        await session.run(
            """CREATE FULLTEXT INDEX entity_fulltext IF NOT EXISTS
            FOR (e:Entity) ON EACH [e.name]"""
        )
        print("  Created entity_fulltext index")

        # Create vector indexes if they don't exist
        try:
            await session.run(
                """CREATE VECTOR INDEX decision_embedding IF NOT EXISTS
                FOR (d:DecisionTrace) ON (d.embedding)
                OPTIONS {indexConfig: {`vector.dimensions`: 2048, `vector.similarity_function`: 'cosine'}}"""
            )
            print("  Created decision_embedding vector index")
        except Exception as e:
            print(f"  Decision vector index: {e}")

        try:
            await session.run(
                """CREATE VECTOR INDEX entity_embedding IF NOT EXISTS
                FOR (e:Entity) ON (e.embedding)
                OPTIONS {indexConfig: {`vector.dimensions`: 2048, `vector.similarity_function`: 'cosine'}}"""
            )
            print("  Created entity_embedding vector index")
        except Exception as e:
            print(f"  Entity vector index: {e}")

        # Wait for indexes to come online
        print("  Waiting for indexes to populate...")
        await asyncio.sleep(5)

        # Verify indexes
        r = await session.run("SHOW INDEXES YIELD name, state, type RETURN name, state, type")
        indexes = await r.data()
        for idx in indexes:
            print(f"    {idx['name']}: {idx['state']} ({idx['type']})")


# ═══════════════════════════════════════════════════════════════════
# STEP 5: Graph statistics
# ═══════════════════════════════════════════════════════════════════

async def graph_statistics(driver) -> dict:
    """Compute comprehensive graph statistics."""
    print("\n" + "=" * 60)
    print("STEP 5: GRAPH STATISTICS")
    print("=" * 60)

    stats = {}

    async with driver.session(database="neo4j") as session:
        # Node counts by label
        r = await session.run("MATCH (n) RETURN labels(n)[0] AS label, count(n) AS c ORDER BY c DESC")
        node_counts = await r.data()
        stats["node_counts"] = {n["label"]: n["c"] for n in node_counts}
        total_nodes = sum(n["c"] for n in node_counts)
        stats["total_nodes"] = total_nodes
        print(f"\n  Nodes:")
        for n in node_counts:
            print(f"    {n['label']}: {n['c']}")
        print(f"    TOTAL: {total_nodes}")

        # Relationship counts
        r = await session.run("MATCH ()-[r]->() RETURN type(r) AS type, count(r) AS c ORDER BY c DESC")
        rel_counts = await r.data()
        stats["relationship_counts"] = {r_["type"]: r_["c"] for r_ in rel_counts}
        total_rels = sum(r_["c"] for r_ in rel_counts)
        stats["total_relationships"] = total_rels
        print(f"\n  Relationships:")
        for r_ in rel_counts:
            print(f"    {r_['type']}: {r_['c']}")
        print(f"    TOTAL: {total_rels}")

        # Graph density
        if total_nodes > 1:
            density = total_rels / (total_nodes * (total_nodes - 1))
            stats["graph_density"] = round(density, 6)
            print(f"\n  Graph density: {density:.6f}")

        # Avg entities per decision
        r = await session.run("""
            MATCH (d:DecisionTrace)-[:INVOLVES]->(e:Entity)
            WITH d, count(e) AS entity_count
            RETURN avg(entity_count) AS avg_entities, max(entity_count) AS max_entities,
                   min(entity_count) AS min_entities, stdev(entity_count) AS std_entities
        """)
        rec = await r.single()
        if rec and rec["avg_entities"]:
            stats["avg_entities_per_decision"] = round(rec["avg_entities"], 2)
            stats["max_entities_per_decision"] = rec["max_entities"]
            stats["min_entities_per_decision"] = rec["min_entities"]
            stats["std_entities_per_decision"] = round(rec["std_entities"], 2) if rec["std_entities"] else 0
            print(f"\n  Entities per decision:")
            print(f"    Avg: {rec['avg_entities']:.2f}")
            print(f"    Max: {rec['max_entities']}, Min: {rec['min_entities']}, Std: {rec['std_entities']:.2f}")

        # Avg decisions per entity
        r = await session.run("""
            MATCH (e:Entity)<-[:INVOLVES]-(d:DecisionTrace)
            WITH e, count(d) AS dec_count
            RETURN avg(dec_count) AS avg_decisions, max(dec_count) AS max_decisions,
                   min(dec_count) AS min_decisions, stdev(dec_count) AS std_decisions
        """)
        rec = await r.single()
        if rec and rec["avg_decisions"]:
            stats["avg_decisions_per_entity"] = round(rec["avg_decisions"], 2)
            stats["max_decisions_per_entity"] = rec["max_decisions"]
            stats["min_decisions_per_entity"] = rec["min_decisions"]
            stats["std_decisions_per_entity"] = round(rec["std_decisions"], 2) if rec["std_decisions"] else 0
            print(f"\n  Decisions per entity:")
            print(f"    Avg: {rec['avg_decisions']:.2f}")
            print(f"    Max: {rec['max_decisions']}, Min: {rec['min_decisions']}, Std: {rec['std_decisions']:.2f}")

        # Domain distribution
        r = await session.run("""
            MATCH (d:DecisionTrace)
            WHERE d.conversation_id IS NOT NULL
            WITH d.conversation_id AS conv_id, count(d) AS dec_count
            RETURN conv_id, dec_count
            ORDER BY dec_count DESC LIMIT 10
        """)
        top_convs = await r.data()
        print(f"\n  Top conversations by decision count:")
        for tc in top_convs:
            print(f"    {tc['conv_id']}: {tc['dec_count']} decisions")

        # Top 15 most connected entities
        r = await session.run("""
            MATCH (e:Entity)<-[:INVOLVES]-(d:DecisionTrace)
            RETURN e.name AS name, e.type AS type, count(d) AS decisions
            ORDER BY decisions DESC LIMIT 15
        """)
        top_entities = await r.data()
        stats["top_entities"] = top_entities
        print(f"\n  Top 15 most-connected entities:")
        for e in top_entities:
            print(f"    {e['name']} ({e.get('type', '?')}): {e['decisions']} decisions")

        # Entity type distribution
        r = await session.run("MATCH (e:Entity) RETURN e.type AS type, count(e) AS c ORDER BY c DESC")
        entity_types = await r.data()
        stats["entity_type_distribution"] = {et["type"]: et["c"] for et in entity_types}
        print(f"\n  Entity type distribution:")
        for et in entity_types:
            print(f"    {et['type']}: {et['c']}")

        # Average confidence
        r = await session.run("MATCH (d:DecisionTrace) RETURN avg(d.confidence) AS avg_conf")
        avg_conf = (await r.single())["avg_conf"]
        if avg_conf:
            stats["avg_confidence"] = round(avg_conf, 3)
            print(f"\n  Avg decision confidence: {avg_conf:.3f}")

        # Isolated entities
        r = await session.run("MATCH (e:Entity) WHERE NOT (e)<-[:INVOLVES]-() RETURN count(e) AS c")
        isolated = (await r.single())["c"]
        r = await session.run("MATCH (e:Entity) RETURN count(e) AS c")
        total_entities = (await r.single())["c"]
        stats["isolated_entities"] = isolated
        stats["total_entities"] = total_entities
        print(f"\n  Isolated entities (no decisions): {isolated}/{total_entities}")

        # Embedding coverage
        r = await session.run("MATCH (e:Entity) WHERE e.embedding IS NOT NULL RETURN count(e) AS c")
        entities_with_emb = (await r.single())["c"]
        r = await session.run("MATCH (d:DecisionTrace) WHERE d.embedding IS NOT NULL RETURN count(d) AS c")
        decisions_with_emb = (await r.single())["c"]
        stats["entities_with_embeddings"] = entities_with_emb
        stats["decisions_with_embeddings"] = decisions_with_emb
        print(f"\n  Embedding coverage:")
        print(f"    Entities: {entities_with_emb}/{total_entities}")
        r2 = await session.run("MATCH (d:DecisionTrace) RETURN count(d) AS c")
        total_dec = (await r2.single())["c"]
        print(f"    Decisions: {decisions_with_emb}/{total_dec}")
        stats["total_decisions"] = total_dec

    return stats


# ═══════════════════════════════════════════════════════════════════
# STEP 6: GraphRAG Evaluation
# ═══════════════════════════════════════════════════════════════════

async def generate_ground_truth_queries(driver) -> list[dict]:
    """Generate test queries from the graph itself."""
    queries = []

    async with driver.session(database="neo4j") as session:
        # Type 1: Entity-centric queries
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

        # Type 2: Decision-centric queries
        result = await session.run("""
            MATCH (d:DecisionTrace)-[:INVOLVES]->(e:Entity)
            WHERE d.trigger IS NOT NULL AND d.trigger <> ''
            WITH d, collect(e.name) AS entities
            RETURN d.id AS id, d.trigger AS trigger, d.decision AS decision,
                   d.rationale AS rationale, entities
            ORDER BY rand() LIMIT 15
        """)
        for rec in await result.data():
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


async def test_search_endpoint(session, query: str) -> dict:
    """Test hybrid retrieval."""
    from services.graph_rag import GraphRAGService
    rag = GraphRAGService()
    start = time.monotonic()

    try:
        results = await rag.hybrid_retrieve(query, user_id="eval-e2e", limit=10, session=session)
        latency = (time.monotonic() - start) * 1000

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


async def test_fulltext_only(session, query: str) -> dict:
    """Test fulltext-only retrieval (no vector)."""
    from services.graph_rag import GraphRAGService
    rag = GraphRAGService()
    start = time.monotonic()

    try:
        ids = await rag._fulltext_search(session, query, "eval-e2e", limit=10)
        latency = (time.monotonic() - start) * 1000

        node_data = []
        if ids:
            node_result = await session.run(
                "UNWIND $ids AS nid MATCH (n {id: nid}) RETURN n.id AS id, n.name AS name, labels(n)[0] AS label",
                parameters={"ids": ids}
            )
            node_data = await node_result.data()

        return {
            "success": True,
            "result_count": len(ids),
            "results": node_data,
            "result_ids": ids,
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


async def test_full_retrieve_context(session, query: str, user_id: str = "eval-e2e") -> dict:
    """Test the full retrieve_context pipeline."""
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


def compute_retrieval_metrics(queries: list[dict], results: list[dict]) -> dict:
    """Compute retrieval quality metrics."""
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

        if q["type"] == "entity_lookup":
            entity_total += 1
            expected = q["expected_entity"].lower()
            if expected in retrieved_names or any(expected in n for n in retrieved_names):
                entity_hits += 1
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
    return {
        "entity_recall": round(entity_hits / entity_total, 4) if entity_total else 0,
        "entity_hits": entity_hits,
        "entity_total": entity_total,
        "decision_recall": round(decision_hits / decision_total, 4) if decision_total else 0,
        "decision_hits": decision_hits,
        "decision_total": decision_total,
        "comparison_recall": round(comparison_hits / comparison_total, 4) if comparison_total else 0,
        "comparison_hits": comparison_hits,
        "comparison_total": comparison_total,
        "mrr": round(sum(mrr_scores) / len(mrr_scores), 4) if mrr_scores else 0,
        "latency_p50_ms": round(latencies[len(latencies) // 2], 1) if latencies else 0,
        "latency_p95_ms": round(latencies[int(len(latencies) * 0.95)], 1) if latencies else 0,
        "latency_mean_ms": round(sum(latencies) / len(latencies), 1) if latencies else 0,
    }


async def run_graphrag_evaluation(driver) -> dict:
    """Run full GraphRAG evaluation."""
    print("\n" + "=" * 60)
    print("STEP 6: GRAPHRAG EVALUATION")
    print("=" * 60)

    # Phase 1: Generate ground truth queries
    print("\nPhase 1: Generating test queries from knowledge graph...")
    queries = await generate_ground_truth_queries(driver)
    type_counts = Counter(q["type"] for q in queries)
    print(f"  Generated {len(queries)} queries: {dict(type_counts)}")

    # Phase 2: Test hybrid retrieval
    print("\nPhase 2: Testing hybrid retrieval...")
    hybrid_results = []
    async with driver.session(database="neo4j") as session:
        for i, q in enumerate(queries):
            result = await test_search_endpoint(session, q["query"])
            hybrid_results.append(result)
            status = "ok" if result["success"] else "FAIL"
            print(f"  [{i+1}/{len(queries)}] {status} | {result['result_count']} results | "
                  f"{result['latency_ms']:.0f}ms | {q['query'][:60]}...")

    # Phase 3: Test fulltext-only retrieval (for config comparison)
    print("\nPhase 3: Testing fulltext-only retrieval...")
    fulltext_results = []
    async with driver.session(database="neo4j") as session:
        for i, q in enumerate(queries):
            result = await test_fulltext_only(session, q["query"])
            fulltext_results.append(result)
            status = "ok" if result["success"] else "FAIL"
            print(f"  [{i+1}/{len(queries)}] {status} | {result['result_count']} results | "
                  f"{result['latency_ms']:.0f}ms")

    # Phase 4: Test full retrieve_context pipeline (hybrid + expansion)
    print("\nPhase 4: Testing full retrieve_context pipeline...")
    context_results = []
    async with driver.session(database="neo4j") as session:
        for i, q in enumerate(queries):
            result = await test_full_retrieve_context(session, q["query"])
            context_results.append(result)
            status = "ok" if result["success"] else "FAIL"
            nodes = result.get("node_count", 0)
            edges = result.get("edge_count", 0)
            ctx_len = result.get("context_length", 0)
            print(f"  [{i+1}/{len(queries)}] {status} | {nodes} nodes, {edges} edges | "
                  f"context: {ctx_len} chars | {result['latency_ms']:.0f}ms")

    # Compute metrics for each config
    print("\n" + "=" * 60)
    print("RETRIEVAL METRICS")
    print("=" * 60)

    hybrid_metrics = compute_retrieval_metrics(queries, hybrid_results)
    fulltext_metrics = compute_retrieval_metrics(queries, fulltext_results)

    print(f"\n--- Hybrid RRF (fulltext + vector) ---")
    print(f"  Entity lookup recall:    {hybrid_metrics['entity_recall']:.1%} ({hybrid_metrics['entity_hits']}/{hybrid_metrics['entity_total']})")
    print(f"  Decision search recall:  {hybrid_metrics['decision_recall']:.1%} ({hybrid_metrics['decision_hits']}/{hybrid_metrics['decision_total']})")
    print(f"  Comparison recall:       {hybrid_metrics['comparison_recall']:.1%} ({hybrid_metrics['comparison_hits']}/{hybrid_metrics['comparison_total']})")
    print(f"  MRR:                     {hybrid_metrics['mrr']:.3f}")
    print(f"  Latency p50/p95/mean:    {hybrid_metrics['latency_p50_ms']:.0f}/{hybrid_metrics['latency_p95_ms']:.0f}/{hybrid_metrics['latency_mean_ms']:.0f}ms")

    print(f"\n--- Fulltext Only ---")
    print(f"  Entity lookup recall:    {fulltext_metrics['entity_recall']:.1%} ({fulltext_metrics['entity_hits']}/{fulltext_metrics['entity_total']})")
    print(f"  Decision search recall:  {fulltext_metrics['decision_recall']:.1%} ({fulltext_metrics['decision_hits']}/{fulltext_metrics['decision_total']})")
    print(f"  Comparison recall:       {fulltext_metrics['comparison_recall']:.1%} ({fulltext_metrics['comparison_hits']}/{fulltext_metrics['comparison_total']})")
    print(f"  MRR:                     {fulltext_metrics['mrr']:.3f}")
    print(f"  Latency p50/p95/mean:    {fulltext_metrics['latency_p50_ms']:.0f}/{fulltext_metrics['latency_p95_ms']:.0f}/{fulltext_metrics['latency_mean_ms']:.0f}ms")

    # Context pipeline stats
    successful_ctx = [r for r in context_results if r.get("success")]
    ctx_stats = {}
    if successful_ctx:
        ctx_stats = {
            "success_rate": len(successful_ctx) / len(context_results),
            "avg_nodes": round(sum(r["node_count"] for r in successful_ctx) / len(successful_ctx), 1),
            "avg_edges": round(sum(r["edge_count"] for r in successful_ctx) / len(successful_ctx), 1),
            "avg_context_chars": round(sum(r["context_length"] for r in successful_ctx) / len(successful_ctx), 0),
            "avg_latency_ms": round(sum(r["latency_ms"] for r in successful_ctx) / len(successful_ctx), 1),
        }
        print(f"\n--- Full Pipeline (hybrid + expansion) ---")
        print(f"  Success rate:    {ctx_stats['success_rate']:.1%}")
        print(f"  Avg subgraph:    {ctx_stats['avg_nodes']:.0f} nodes, {ctx_stats['avg_edges']:.0f} edges")
        print(f"  Avg context:     {ctx_stats['avg_context_chars']:.0f} chars")
        print(f"  Avg latency:     {ctx_stats['avg_latency_ms']:.0f}ms")

    return {
        "queries_generated": len(queries),
        "query_types": dict(type_counts),
        "hybrid_metrics": hybrid_metrics,
        "fulltext_metrics": fulltext_metrics,
        "context_pipeline": ctx_stats,
        "config_comparison": {
            "fulltext_only": {
                "entity_recall": fulltext_metrics["entity_recall"],
                "decision_recall": fulltext_metrics["decision_recall"],
                "comparison_recall": fulltext_metrics["comparison_recall"],
                "mrr": fulltext_metrics["mrr"],
                "latency_mean_ms": fulltext_metrics["latency_mean_ms"],
            },
            "hybrid_rrf": {
                "entity_recall": hybrid_metrics["entity_recall"],
                "decision_recall": hybrid_metrics["decision_recall"],
                "comparison_recall": hybrid_metrics["comparison_recall"],
                "mrr": hybrid_metrics["mrr"],
                "latency_mean_ms": hybrid_metrics["latency_mean_ms"],
            },
            "hybrid_rrf_expansion": {
                "success_rate": ctx_stats.get("success_rate", 0),
                "avg_nodes": ctx_stats.get("avg_nodes", 0),
                "avg_edges": ctx_stats.get("avg_edges", 0),
                "avg_context_chars": ctx_stats.get("avg_context_chars", 0),
                "avg_latency_ms": ctx_stats.get("avg_latency_ms", 0),
            },
        },
    }


# ═══════════════════════════════════════════════════════════════════
# STEP 7: Save all results
# ═══════════════════════════════════════════════════════════════════

def save_results(extraction_results: dict, graph_stats: dict, graphrag_results: dict, embedding_stats: dict):
    """Save all results to evaluation/data/v5/ and papers/research-logs/."""
    print("\n" + "=" * 60)
    print("STEP 7: SAVING RESULTS")
    print("=" * 60)

    v5_dir = Path(__file__).resolve().parent / "data" / "v5"
    v5_dir.mkdir(parents=True, exist_ok=True)

    # 1. E2E extraction results
    e2e_path = v5_dir / "e2e_full_results.json"
    with open(e2e_path, "w") as f:
        json.dump(extraction_results, f, indent=2)
    print(f"  Saved: {e2e_path}")

    # 2. GraphRAG results
    graphrag_path = v5_dir / "graphrag_full_results.json"
    with open(graphrag_path, "w") as f:
        json.dump(graphrag_results, f, indent=2)
    print(f"  Saved: {graphrag_path}")

    # 3. Retrieval config comparison
    config_path = v5_dir / "retrieval_config_full.json"
    with open(config_path, "w") as f:
        json.dump(graphrag_results.get("config_comparison", {}), f, indent=2)
    print(f"  Saved: {config_path}")

    # 4. Graph topology
    topo_path = v5_dir / "graph_topology_full.json"
    with open(topo_path, "w") as f:
        json.dump(graph_stats, f, indent=2)
    print(f"  Saved: {topo_path}")

    # 5. Research log markdown
    papers_dir = Path(__file__).resolve().parent.parent.parent.parent / "papers" / "research-logs"
    papers_dir.mkdir(parents=True, exist_ok=True)
    log_path = papers_dir / "FULL-EXTRACTION-LOG.md"

    hybrid = graphrag_results.get("hybrid_metrics", {})
    fulltext = graphrag_results.get("fulltext_metrics", {})
    ctx = graphrag_results.get("context_pipeline", {})
    config = graphrag_results.get("config_comparison", {})

    md = f"""# Full 200-Conversation Extraction & GraphRAG Evaluation Log

**Date:** {time.strftime('%Y-%m-%d %H:%M:%S')}
**Pipeline:** LLM extraction -> entity resolution -> Neo4j storage -> embedding -> GraphRAG evaluation
**LLM:** NVIDIA Llama 3.3 Nemotron Super 49B v1.5 (max_tokens=4096, sanitize_input=False)
**Embeddings:** NVIDIA NV-EmbedQA 1B v2 (2048 dimensions)

---

## 1. Extraction Results

| Metric | Value |
|--------|-------|
| Conversations processed | {extraction_results.get('conversations', 0)} |
| Conversations with decisions | {extraction_results.get('conversations_with_decisions', 0)} |
| Extraction success rate | {extraction_results.get('extraction_success_rate', 0):.1%} |
| Total decisions extracted | {extraction_results.get('total_decisions', 0)} |
| Avg decisions per conversation | {extraction_results.get('avg_decisions_per_conv', 0)} |
| Total entity-decision links | {extraction_results.get('total_entity_links', 0)} |
| Avg extraction time (per conv) | {extraction_results.get('avg_extraction_time_s', 0)}s |
| Total pipeline time | {extraction_results.get('total_pipeline_time_s', 0)}s ({extraction_results.get('total_pipeline_time_s', 0)/60:.1f} min) |
| Failed conversations | {len(extraction_results.get('failed_conversations', []))} |

### Decisions by Domain

| Domain | Count |
|--------|-------|
"""
    for domain, count in sorted(extraction_results.get("decisions_by_domain", {}).items(), key=lambda x: -x[1]):
        md += f"| {domain} | {count} |\n"

    md += f"""
## 2. Knowledge Graph Topology

| Metric | Value |
|--------|-------|
| Total nodes | {graph_stats.get('total_nodes', 0)} |
| DecisionTrace nodes | {graph_stats.get('node_counts', {}).get('DecisionTrace', 0)} |
| Entity nodes | {graph_stats.get('node_counts', {}).get('Entity', 0)} |
| Total relationships | {graph_stats.get('total_relationships', 0)} |
| Graph density | {graph_stats.get('graph_density', 0)} |
| Avg entities per decision | {graph_stats.get('avg_entities_per_decision', 0)} |
| Avg decisions per entity | {graph_stats.get('avg_decisions_per_entity', 0)} |
| Isolated entities | {graph_stats.get('isolated_entities', 0)} / {graph_stats.get('total_entities', 0)} |
| Entities with embeddings | {graph_stats.get('entities_with_embeddings', 0)} |
| Decisions with embeddings | {graph_stats.get('decisions_with_embeddings', 0)} |
| Avg confidence | {graph_stats.get('avg_confidence', 0)} |

### Entity Type Distribution

| Type | Count |
|------|-------|
"""
    for etype, count in sorted(graph_stats.get("entity_type_distribution", {}).items(), key=lambda x: -x[1]):
        md += f"| {etype} | {count} |\n"

    md += f"""
### Top 15 Most-Connected Entities

| Entity | Type | Decisions |
|--------|------|-----------|
"""
    for e in graph_stats.get("top_entities", []):
        md += f"| {e.get('name', '?')} | {e.get('type', '?')} | {e.get('decisions', 0)} |\n"

    md += f"""
### Embedding Stats

| Metric | Value |
|--------|-------|
| Entities embedded | {embedding_stats.get('entities_embedded', 0)} |
| Decisions embedded | {embedding_stats.get('decisions_embedded', 0)} |
| Embedding errors | {embedding_stats.get('errors', 0)} |
| Embedding time | {embedding_stats.get('time_s', 0)}s |

## 3. GraphRAG Retrieval Evaluation

Test queries generated: {graphrag_results.get('queries_generated', 0)}
Query types: {graphrag_results.get('query_types', {})}

### Hybrid RRF (Fulltext + Vector)

| Metric | Value |
|--------|-------|
| Entity lookup recall | {hybrid.get('entity_recall', 0):.1%} ({hybrid.get('entity_hits', 0)}/{hybrid.get('entity_total', 0)}) |
| Decision search recall | {hybrid.get('decision_recall', 0):.1%} ({hybrid.get('decision_hits', 0)}/{hybrid.get('decision_total', 0)}) |
| Comparison recall | {hybrid.get('comparison_recall', 0):.1%} ({hybrid.get('comparison_hits', 0)}/{hybrid.get('comparison_total', 0)}) |
| Mean Reciprocal Rank | {hybrid.get('mrr', 0):.3f} |
| Latency p50 | {hybrid.get('latency_p50_ms', 0):.0f}ms |
| Latency p95 | {hybrid.get('latency_p95_ms', 0):.0f}ms |
| Latency mean | {hybrid.get('latency_mean_ms', 0):.0f}ms |

### Fulltext Only

| Metric | Value |
|--------|-------|
| Entity lookup recall | {fulltext.get('entity_recall', 0):.1%} ({fulltext.get('entity_hits', 0)}/{fulltext.get('entity_total', 0)}) |
| Decision search recall | {fulltext.get('decision_recall', 0):.1%} ({fulltext.get('decision_hits', 0)}/{fulltext.get('decision_total', 0)}) |
| Comparison recall | {fulltext.get('comparison_recall', 0):.1%} ({fulltext.get('comparison_hits', 0)}/{fulltext.get('comparison_total', 0)}) |
| Mean Reciprocal Rank | {fulltext.get('mrr', 0):.3f} |
| Latency p50 | {fulltext.get('latency_p50_ms', 0):.0f}ms |
| Latency p95 | {fulltext.get('latency_p95_ms', 0):.0f}ms |
| Latency mean | {fulltext.get('latency_mean_ms', 0):.0f}ms |

### Full Pipeline (Hybrid + Subgraph Expansion)

| Metric | Value |
|--------|-------|
| Success rate | {ctx.get('success_rate', 0):.1%} |
| Avg subgraph nodes | {ctx.get('avg_nodes', 0)} |
| Avg subgraph edges | {ctx.get('avg_edges', 0)} |
| Avg context length | {ctx.get('avg_context_chars', 0)} chars |
| Avg latency | {ctx.get('avg_latency_ms', 0):.0f}ms |

### Retrieval Configuration Comparison

| Config | Entity Recall | Decision Recall | Comparison Recall | MRR | Mean Latency |
|--------|--------------|-----------------|-------------------|-----|-------------|
| Fulltext only | {config.get('fulltext_only', {}).get('entity_recall', 0):.1%} | {config.get('fulltext_only', {}).get('decision_recall', 0):.1%} | {config.get('fulltext_only', {}).get('comparison_recall', 0):.1%} | {config.get('fulltext_only', {}).get('mrr', 0):.3f} | {config.get('fulltext_only', {}).get('latency_mean_ms', 0):.0f}ms |
| Hybrid RRF | {config.get('hybrid_rrf', {}).get('entity_recall', 0):.1%} | {config.get('hybrid_rrf', {}).get('decision_recall', 0):.1%} | {config.get('hybrid_rrf', {}).get('comparison_recall', 0):.1%} | {config.get('hybrid_rrf', {}).get('mrr', 0):.3f} | {config.get('hybrid_rrf', {}).get('latency_mean_ms', 0):.0f}ms |
| Hybrid + Expansion | - | - | - | - | {config.get('hybrid_rrf_expansion', {}).get('avg_latency_ms', 0):.0f}ms |

## 4. Failed Conversations

"""
    failed = extraction_results.get("failed_conversations", [])
    if failed:
        for fc in failed:
            md += f"- **{fc['id']}**: {fc['error'][:200]}\n"
    else:
        md += "None.\n"

    md += f"""
---
*Generated by `evaluation/run_full_pipeline.py` on {time.strftime('%Y-%m-%d %H:%M:%S')}*
"""

    with open(log_path, "w") as f:
        f.write(md)
    print(f"  Saved: {log_path}")


# ═══════════════════════════════════════════════════════════════════
# MAIN — supports batch mode via CLI arguments
# ═══════════════════════════════════════════════════════════════════

async def run_extraction_batch(driver, start: int, end: int) -> dict:
    """Run extraction on a subset of conversations (start..end exclusive)."""
    print(f"\n{'=' * 60}")
    print(f"EXTRACTING CONVERSATIONS {start+1} to {end}")
    print(f"{'=' * 60}")

    from services.llm import get_llm_client
    llm = get_llm_client()

    conv_dir = Path(__file__).resolve().parent / "data" / "synthetic_conversations"
    conv_files = sorted(conv_dir.glob("conv-*.json"))
    batch_files = conv_files[start:end]
    print(f"  Processing {len(batch_files)} conversations (index {start}-{end-1})")

    user_id = "eval-e2e"
    total_decisions = 0
    total_entities_linked = 0
    decisions_per_conv = []
    extraction_times = []
    domain_decisions = Counter()
    failed_convs = []
    per_conv_results = []

    pipeline_start = time.monotonic()

    for i, conv_file in enumerate(batch_files):
        global_idx = start + i
        with open(conv_file, encoding="utf-8") as f:
            conv = json.load(f)

        conv_id = conv.get("id", conv_file.stem)
        domain = conv.get("domain", "unknown")
        topic = conv.get("topic", "")

        print(f"\n[{global_idx+1}/200] {conv_id}: {topic}")

        t0 = time.monotonic()
        try:
            decisions = await extract_decision_from_conversation(llm, conv)
        except Exception as e:
            print(f"  FATAL extraction error: {e}")
            decisions = []
            failed_convs.append({"id": conv_id, "error": str(e)})

        extraction_time = time.monotonic() - t0
        extraction_times.append(extraction_time)
        print(f"  Extracted {len(decisions)} decisions in {extraction_time:.1f}s")

        conv_decisions_stored = 0
        conv_entities_linked = 0

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

        decisions_per_conv.append(conv_decisions_stored)
        per_conv_results.append({
            "conv_id": conv_id, "domain": domain, "topic": topic,
            "decisions_extracted": len(decisions), "decisions_stored": conv_decisions_stored,
            "entities_linked": conv_entities_linked,
            "extraction_time_s": round(extraction_time, 2),
        })

    pipeline_time = time.monotonic() - pipeline_start
    convs_with_decisions = sum(1 for d in decisions_per_conv if d > 0)

    # Save batch results incrementally
    v5_dir = Path(__file__).resolve().parent / "data" / "v5"
    v5_dir.mkdir(parents=True, exist_ok=True)
    batch_path = v5_dir / f"extraction_batch_{start}_{end}.json"
    batch_result = {
        "batch_start": start, "batch_end": end,
        "conversations": len(batch_files),
        "conversations_with_decisions": convs_with_decisions,
        "total_decisions": total_decisions,
        "total_entity_links": total_entities_linked,
        "avg_extraction_time_s": round(sum(extraction_times) / len(extraction_times), 2) if extraction_times else 0,
        "total_time_s": round(pipeline_time, 1),
        "decisions_by_domain": dict(domain_decisions),
        "decisions_per_conv": decisions_per_conv,
        "failed_conversations": failed_convs,
        "per_conv_results": per_conv_results,
    }
    with open(batch_path, "w") as f:
        json.dump(batch_result, f, indent=2)
    print(f"\n  Batch results saved to {batch_path}")
    print(f"  Batch: {total_decisions} decisions from {convs_with_decisions}/{len(batch_files)} convs in {pipeline_time:.0f}s")

    return batch_result


async def merge_batch_results() -> dict:
    """Merge all batch extraction results into a single result."""
    v5_dir = Path(__file__).resolve().parent / "data" / "v5"
    batch_files = sorted(v5_dir.glob("extraction_batch_*.json"))

    merged = {
        "conversations": 0,
        "conversations_with_decisions": 0,
        "total_decisions": 0,
        "total_entity_links": 0,
        "extraction_success_rate": 0,
        "avg_decisions_per_conv": 0,
        "avg_extraction_time_s": 0,
        "total_pipeline_time_s": 0,
        "decisions_by_domain": Counter(),
        "decisions_per_conv": [],
        "failed_conversations": [],
        "per_conv_results": [],
    }

    all_times = []
    for bf in batch_files:
        with open(bf) as f:
            batch = json.load(f)
        merged["conversations"] += batch["conversations"]
        merged["conversations_with_decisions"] += batch["conversations_with_decisions"]
        merged["total_decisions"] += batch["total_decisions"]
        merged["total_entity_links"] += batch["total_entity_links"]
        merged["total_pipeline_time_s"] += batch["total_time_s"]
        for d, c in batch.get("decisions_by_domain", {}).items():
            merged["decisions_by_domain"][d] += c
        merged["decisions_per_conv"].extend(batch["decisions_per_conv"])
        merged["failed_conversations"].extend(batch.get("failed_conversations", []))
        merged["per_conv_results"].extend(batch.get("per_conv_results", []))
        for pcr in batch.get("per_conv_results", []):
            all_times.append(pcr["extraction_time_s"])

    if merged["conversations"] > 0:
        merged["extraction_success_rate"] = round(
            merged["conversations_with_decisions"] / merged["conversations"], 4)
        merged["avg_decisions_per_conv"] = round(
            sum(merged["decisions_per_conv"]) / len(merged["decisions_per_conv"]), 2)
    if all_times:
        merged["avg_extraction_time_s"] = round(sum(all_times) / len(all_times), 2)

    merged["decisions_by_domain"] = dict(merged["decisions_by_domain"])
    return merged


async def main():
    import argparse
    parser = argparse.ArgumentParser(description="Full pipeline or batch extraction")
    parser.add_argument("--step", choices=["wipe", "extract", "post", "all"], default="all",
                        help="Pipeline step: wipe, extract (batch), post (embed+index+eval+save), all")
    parser.add_argument("--start", type=int, default=0, help="Batch start index (inclusive)")
    parser.add_argument("--end", type=int, default=200, help="Batch end index (exclusive)")
    parser.add_argument("--no-wipe", action="store_true", help="Skip graph wipe")
    args = parser.parse_args()

    pipeline_start = time.monotonic()

    neo4j_uri = os.environ.get("NEO4J_URI", "bolt://127.0.0.1:7687")
    neo4j_user = os.environ.get("NEO4J_USER", "neo4j")
    neo4j_password = os.environ.get("NEO4J_PASSWORD", "password")
    driver = AsyncGraphDatabase.driver(neo4j_uri, auth=(neo4j_user, neo4j_password))

    async with driver.session(database="neo4j") as session:
        result = await session.run("RETURN 1")
        await result.consume()
    print("Connected to Neo4j")

    try:
        if args.step == "wipe":
            await wipe_graph(driver)

        elif args.step == "extract":
            if not args.no_wipe and args.start == 0:
                await wipe_graph(driver)
            await run_extraction_batch(driver, args.start, args.end)

        elif args.step == "post":
            # Merge batch results
            extraction_results = await merge_batch_results()
            print(f"Merged extraction results: {extraction_results['total_decisions']} decisions from {extraction_results['conversations']} convs")

            embedding_stats = await compute_embeddings(driver)
            await ensure_indexes(driver)
            graph_stats = await graph_statistics(driver)
            graphrag_results = await run_graphrag_evaluation(driver)
            save_results(extraction_results, graph_stats, graphrag_results, embedding_stats)

        elif args.step == "all":
            await wipe_graph(driver)
            # Extract in one go (for when running with enough time)
            extraction_results = await run_extraction(driver)
            embedding_stats = await compute_embeddings(driver)
            await ensure_indexes(driver)
            graph_stats = await graph_statistics(driver)
            graphrag_results = await run_graphrag_evaluation(driver)
            save_results(extraction_results, graph_stats, graphrag_results, embedding_stats)

        total_time = time.monotonic() - pipeline_start
        print(f"\n{'=' * 60}")
        print(f"STEP '{args.step}' COMPLETE in {total_time:.1f}s ({total_time/60:.1f} min)")
        print(f"{'=' * 60}")

    finally:
        await driver.close()


if __name__ == "__main__":
    asyncio.run(main())
