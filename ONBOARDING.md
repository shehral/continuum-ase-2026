# Continuum Onboarding Guide

> Quick reference companion to the full onboarding book (`guide/main.pdf`).
> Designed for fast lookup and AI agent context.

## Table of Contents

- [Part 0: Foundations](#part-0-foundations)
  - [Ch 1: Knowledge Graphs](#ch-1-knowledge-graphs)
  - [Ch 2: Entity Resolution](#ch-2-entity-resolution)
  - [Ch 3: Retrieval-Augmented Generation](#ch-3-retrieval-augmented-generation)
- [Part I: What Is Continuum](#part-i-what-is-continuum)
  - [Ch 4: The Problem](#ch-4-the-problem)
  - [Ch 5: System Overview](#ch-5-system-overview)
  - [Ch 6: Related Systems](#ch-6-related-systems)
- [Part II: Getting Started](#part-ii-getting-started)
  - [Ch 7: Setup & Directory Tour](#ch-7-setup--directory-tour)
  - [Ch 8: Your First Session](#ch-8-your-first-session)
  - [Ch 9: Anatomy of the Data](#ch-9-anatomy-of-the-data)
- [Part III: How It Works](#part-iii-how-it-works)
  - [Ch 10: Infrastructure Layer](#ch-10-infrastructure-layer)
  - [Ch 11: Configuration & Settings](#ch-11-configuration--settings)
  - [Ch 12: Entity Resolution Pipeline](#ch-12-entity-resolution-pipeline)
  - [Ch 13: Decision Extraction](#ch-13-decision-extraction)
  - [Ch 14: Backend API Layer](#ch-14-backend-api-layer)
  - [Ch 15: GraphRAG & Search](#ch-15-graphrag--search)
  - [Ch 16: Frontend Architecture](#ch-16-frontend-architecture)
- [Part IV: Extending Continuum](#part-iv-extending-continuum)
  - [Ch 17: How to Add Features](#ch-17-how-to-add-features)
  - [Ch 18: Exercises](#ch-18-exercises)
  - [Ch 19: Starter Project](#ch-19-starter-project)
- [Part V: Research & Future](#part-v-research--future)
  - [Ch 20: Evaluation Methodology](#ch-20-evaluation-methodology)
  - [Ch 21: Known Limitations](#ch-21-known-limitations)
  - [Ch 22: Future Directions](#ch-22-future-directions)
- [Appendix A: Configuration Reference](#appendix-a-configuration-reference)
- [Appendix B: API Reference](#appendix-b-api-reference)
- [Appendix C: Glossary](#appendix-c-glossary)
- [Appendix D: Troubleshooting](#appendix-d-troubleshooting)

---

## Part 0: Foundations

### Ch 1: Knowledge Graphs

- Continuum uses a **labeled property graph** model in Neo4j with two node types and fourteen relationship types
- Nodes carry labels (`DecisionTrace`, `Entity`), properties (key-value pairs), and relationships have types and direction
- Cypher is Neo4j's query language using ASCII-art patterns: `(node)-[:RELATIONSHIP]->(node)`

**Node types:**

| Node | Key Properties |
|------|---------------|
| `DecisionTrace` | `trigger`, `context`, `options`, `decision`, `rationale`, `confidence` (0-1), `user_id` |
| `Entity` | `name` (canonical), `type` (technology/pattern/concept/etc.), `aliases` (string[]), `embedding` (float[], 2048-d) |

**Relationship types:**

| Type | Connects | Meaning |
|------|----------|---------|
| `INVOLVES` | Decision -> Entity | Decision references this entity |
| `IS_A` | Entity -> Entity | Taxonomic (Redis *is a* datastore) |
| `PART_OF` | Entity -> Entity | Composition |
| `DEPENDS_ON` | Entity -> Entity | Runtime dependency |
| `RELATED_TO` | Entity -> Entity | General association |
| `ALTERNATIVE_TO` | Entity -> Entity | Substitutable |
| `ENABLES` | Entity -> Entity | One entity makes another possible |
| `PREVENTS` | Entity -> Entity | One entity blocks another |
| `REQUIRES` | Entity -> Entity | Hard prerequisite |
| `REFINES` | Entity -> Entity | Specialization |
| `SIMILAR_TO` | Decision -> Decision | Analogous concerns |
| `INFLUENCED_BY` | Decision -> Decision | One shaped another |
| `SUPERSEDES` | Decision -> Decision | Newer replaces older |
| `CONTRADICTS` | Decision -> Decision | Decisions in tension |

**Critical rule:** Every Neo4j query **must** include `user_id` filtering. Missing this is a data isolation bug.

```cypher
-- Correct: user-scoped query
MATCH (d:DecisionTrace)-[:INVOLVES]->(e:Entity)
WHERE d.user_id = $user_id OR d.user_id IS NULL
RETURN e.name, e.type

-- Wrong: missing user scope (leaks data across users)
MATCH (d:DecisionTrace)-[:INVOLVES]->(e:Entity)
RETURN e.name, e.type
```

**Common queries:**

```cypher
-- Find decisions about an entity
MATCH (d:DecisionTrace)-[:INVOLVES]->(e:Entity)
WHERE e.name = 'PostgreSQL'
RETURN d

-- Find decision evolution chains
MATCH (d1:DecisionTrace)-[:SUPERSEDES]->(d2:DecisionTrace)
RETURN d1, d2

-- Variable-length path traversal
MATCH (d1)-[:SUPERSEDES*1..3]->(d2)
RETURN d1, d2

-- Count user's decisions
MATCH (d:DecisionTrace)
WHERE d.user_id = $user_id
RETURN count(d)
```

---

### Ch 2: Entity Resolution

- Developers use inconsistent terminology: "postgres", "PostgreSQL", "PG", "Postgres 16" all mean the same thing
- Without resolution, the graph drowns in duplicates and queries return fragmented results
- Entity resolution is harder than it looks: no enforced schema, abbreviations are ambiguous ("PG" = PostgreSQL or Procter & Gamble), compound terms ("React Native" is not "React" + "Native")

**7-stage cascade (cheapest to most expensive):**

| Stage | Method | Details |
|-------|--------|---------|
| 1 | Cache lookup | Redis, 5-min TTL, ~40% hit rate |
| 2 | Exact match | Case-insensitive string comparison |
| 3 | Canonical lookup | 534 curated mappings (e.g., `pg` -> `PostgreSQL`) |
| 4 | Alias search | Previously resolved aliases stored on Entity nodes |
| 5 | Fuzzy match | Fulltext-accelerated RapidFuzz, >=85% threshold |
| 6 | Embedding similarity | NV-EmbedQA cosine similarity, >0.9 threshold |
| 7 | Create new | If no match found, create new Entity node |

- Pipeline short-circuits: once a stage matches, later stages are skipped
- ~83% of mentions resolved in stages 1-3 (sub-millisecond lookups)
- Evaluation uses **B-cubed** metrics (per-mention precision/recall/F1), not MUC or CEAF

**Entity resolution approach comparison:**

| Approach | Speed | Accuracy | Tradeoff |
|----------|-------|----------|----------|
| Exact matching | Fast | Brittle | Only matches identical strings |
| Fuzzy matching | Fast | Moderate | Handles typos; false positives on short strings ("Go" ~ "Go2") |
| Embedding similarity | Slow | High | Captures semantic meaning; requires embedding model |
| **Hybrid cascading** | Fast (amortized) | **High** | Tries cheap stages first, expensive only when needed (Continuum's approach) |

---

### Ch 3: Retrieval-Augmented Generation

- RAG grounds LLM responses in evidence to prevent hallucination
- Continuum uses **hybrid retrieval**: fulltext (lexical) + vector (semantic) search run in parallel
- Results fused with **Reciprocal Rank Fusion (RRF)**:

```
Score(d) = 1/(k + rank_fulltext(d)) + 1/(k + rank_vector(d))
```

where `k = 60` (smoothing constant). Documents absent from one list get effectively zero contribution from that list.

- **Ablation finding:** Removing fulltext search drops recall to 13.3%. Hybrid retrieval is essential, not optional.

**GraphRAG pipeline (5 steps):**

1. **Hybrid retrieval** -- fulltext + vector search, fused with RRF
2. **Seed node selection** -- top-K results (default 5) become starting points
3. **K-hop expansion** -- traverse outward by k hops (default 2) collecting connected nodes and relationships
4. **Context building** -- serialize subgraph into structured text
5. **Grounded generation** -- LLM generates answer citing retrieved evidence

- More seed nodes = more independent matches; hop expansion = connected context around each match
- GraphRAG retrieves *subgraphs*, not flat documents -- captures relationships, alternatives, supersession chains

---

## Part I: What Is Continuum

### Ch 4: The Problem

- AI coding conversations contain rich decision rationale, but it evaporates when the conversation window closes
- The **rationale gap**: systematic loss of decision context when the medium of decision-making (conversation) is disconnected from the medium of record (code)
- Existing approaches fail: ADRs (<5% adoption), commit messages (capture *what* not *why*), documentation (perpetually stale), Slack (unsearchable)
- The insight: the AI conversation **is** the decision record -- it already contains trigger, context, options, decision, and rationale
- Continuum passively captures conversations and extracts structured decision traces with zero developer effort

**Existing approaches and their failures:**

| Approach | Auto? | Rationale? | Searchable? | Agent? | Problem |
|----------|-------|-----------|-------------|--------|---------|
| ADRs | No | Yes | Partially | No | <5% adoption; manual effort |
| Commit messages | No | Rarely | Yes | No | Captures *what*, not *why* |
| Documentation | No | Sometimes | Yes | No | Perpetually stale |
| Slack / Chat | No | Yes | Barely | No | Ephemeral, unsearchable |

**Decision trace structure:**

| Field | Description |
|-------|-------------|
| `trigger` | What prompted the decision |
| `context` | Background constraints |
| `options` | Alternatives considered |
| `decision` | What was chosen |
| `rationale` | Why it was chosen |
| `confidence` | 0.0-1.0 model self-assessment |

---

### Ch 5: System Overview

- Three-tier architecture: React frontend -> Python API -> 3 databases + cache
- Frontend communicates via REST (CRUD), SSE (streaming AI answers), WebSocket (real-time capture)

**Five subsystems:**

| Subsystem | Purpose | Key File | Technologies |
|-----------|---------|----------|-------------|
| Capture | Passive log extraction, AI interviews | `capture.py` | WebSocket, watcher |
| Extraction | LLM decision trace extraction | `extractor.py` | NVIDIA NIM |
| Resolution | 7-stage entity deduplication | `entity_resolver.py` | RapidFuzz, Redis |
| Retrieval | Hybrid search + GraphRAG | `graph_rag.py` | Neo4j, RRF |
| Integration | AI agent access via MCP | `agent.py` | MCP (5 tools) |

**Tech stack with rationale:**

| Technology | Role | Why This Choice |
|-----------|------|-----------------|
| PostgreSQL 18 | Relational data + auth | Alembic migrations, async SQLAlchemy, mature ecosystem |
| Neo4j 2025.01 | Knowledge graph | Native graph traversal, Cypher, built-in fulltext + vector indexes |
| Redis 7.4 | Cache + rate limiting | 3 cache tiers (entity/LLM/query), token-bucket rate limiting |
| NVIDIA NIM | LLM + embeddings | 49B-param Nemotron for extraction, NV-EmbedQA (2048-d) for similarity |
| Next.js 16 | Frontend | React 19, App Router, Server Components, shadcn/ui |
| FastAPI | Backend API | Native async, automatic OpenAPI docs, Pydantic validation |

- A single decision touches all three databases plus Redis cache
- Multi-tenant: every query scoped by `user_id` from JWT token

**Data flow (conversation to queryable knowledge):**

1. A **conversation** (JSONL log file) enters via file watcher or WebSocket
2. **Extractor** (`extractor.py`) sends conversation to LLM -> returns structured decision traces as JSON
3. Each trace contains raw entity **mentions** (e.g., "postgres", "FastAPI", "Redis")
4. **Entity resolver** (`entity_resolver.py`) maps each mention to a canonical node in Neo4j, creating new nodes only when no match found
5. Decision node and `INVOLVES` edges written to **Neo4j**
6. **GraphRAG** pipeline answers queries by finding seeds via hybrid search, expanding into subgraphs, synthesizing answers

**Available scripts:**

```bash
pnpm dev          # Start frontend + backend in parallel
pnpm dev:web      # Frontend only
pnpm dev:api      # Backend only (uvicorn --reload)
pnpm build        # Build frontend
pnpm typecheck    # TypeScript type checking
pnpm lint         # ESLint
pnpm test         # Run all tests
pnpm test:api     # Backend tests (pytest)
pnpm db:migrate   # Run Alembic migrations
pnpm db:reset     # Reset database (downgrade + upgrade)
pnpm docker:up    # Start Docker services
pnpm docker:down  # Stop Docker services
pnpm docker:logs  # Tail Docker logs
```

---

### Ch 6: Related Systems

| System Category | Auto Capture | Rationale | Graph | Agent Access | Entity Dedup |
|----------------|-------------|-----------|-------|-------------|-------------|
| Architecture Decision Records | No | Yes | No | No | No |
| CodeQL / Sourcetrail | Yes | No | Yes | Partially | No |
| Conversation Analytics | Yes | Yes | No | No | No |
| General RAG Systems | Varies | No | No | Yes | No |
| **Continuum** | **Yes** | **Yes** | **Yes** | **Yes** | **Yes** |

**Three novel contributions:**
1. Automated extraction from AI conversations (zero manual effort)
2. Cascading entity resolution (7-stage pipeline, 90%+ resolved in first 3 stages)
3. Graph-aware retrieval (subgraph expansion, not flat document retrieval)

**Honest positioning:** This is a research prototype. Evaluated with synthetic conversations and automated metrics, not a longitudinal user study. Not production-ready without additional security review and scale testing.

**What has been demonstrated:**
- Decision traces can be extracted from AI conversations with reasonable accuracy using a prompted LLM
- Entity resolution can consolidate noisy mentions into canonical graph nodes across the 7-stage pipeline
- GraphRAG retrieval can surface relevant decisions and their context in response to natural-language queries
- The MCP integration enables AI agents to query the knowledge graph programmatically

**What has NOT been demonstrated:**
- Whether developers actually find the extracted knowledge useful in practice (no user study)
- How the system performs at enterprise scale (thousands of users, millions of decisions)
- Whether the knowledge graph improves downstream development outcomes (fewer repeated mistakes, faster onboarding)

**WARNING:** This is a research system. It is NOT production-ready for enterprise use without additional security review, scale testing, and user validation. Multi-tenant isolation is enforced at the application layer only, the LLM extraction has roughly 85% success rate, and no formal security audit has been conducted.

---

## Part II: Getting Started

### Ch 7: Setup & Directory Tour

**Prerequisites:**
- Node.js 24 LTS (`nvm install 24`)
- Python 3.12+ (`python3 --version`)
- Docker & Docker Compose (Docker Desktop includes Compose)
- pnpm 9+ (`npm install -g pnpm` or `corepack enable`)
- NVIDIA NIM API key from [build.nvidia.com](https://build.nvidia.com) -- need **two** keys: one for LLM (`NVIDIA_API_KEY`) and one for embeddings (`NVIDIA_EMBEDDING_API_KEY`). Alternatively, configure AWS credentials for Bedrock.

**Setup commands (6 steps, all idempotent):**

```bash
# Step 1: Clone
git clone https://github.com/shehral/continuum.git && cd continuum

# Step 2: Create environment file
cp .env.example .env
# Edit .env -- set all required variables (see table below)

# Step 3: Start infrastructure
docker-compose up -d
# Starts PostgreSQL (5432), Neo4j (7474/7687), Redis (6379) -- all on 127.0.0.1

# Step 4: Install frontend dependencies
pnpm install

# Step 5: Set up backend
cd apps/api && python3 -m venv .venv \
  && .venv/bin/pip install -e ".[dev]" && cd ../..

# Step 6: Run database migrations
pnpm db:migrate
```

**Key environment variables to configure:**

| Variable | What to set |
|----------|------------|
| `NVIDIA_API_KEY` | Your NVIDIA NIM LLM key (starts with `nvapi-`) |
| `NVIDIA_EMBEDDING_API_KEY` | Your NVIDIA NIM embedding key |
| `POSTGRES_PASSWORD` | Strong random password. Generate: `python3 -c "import secrets; print(secrets.token_urlsafe(24))"` |
| `NEO4J_PASSWORD` | Another random password for the graph database |
| `REDIS_PASSWORD` | Another random password for the cache |
| `DATABASE_URL` | Update the password segment to match `POSTGRES_PASSWORD` |
| `REDIS_URL` | Update the password segment to match `REDIS_PASSWORD` |
| `SECRET_KEY` | Random 32-byte secret. Generate: `python3 -c "import secrets; print(secrets.token_urlsafe(32))"` |
| `NEXTAUTH_SECRET` | **Must be identical to** `SECRET_KEY` |

**WARNING:** `SECRET_KEY` and `NEXTAUTH_SECRET` must be the *same* string. The backend signs JWTs with `SECRET_KEY`; the frontend verifies them with `NEXTAUTH_SECRET`. A mismatch causes silent auth failure -- you can register but every request falls back to "anonymous."

**Directory structure:**

```
continuum/
├── apps/
│   ├── web/                    # Next.js 16 frontend
│   │   ├── app/                # App Router pages
│   │   │   ├── dashboard/      # Analytics dashboard
│   │   │   ├── decisions/      # Decision list and detail views
│   │   │   ├── graph/          # Interactive knowledge graph
│   │   │   ├── search/         # Hybrid search interface
│   │   │   ├── ask/            # GraphRAG chat interface
│   │   │   ├── capture/        # Decision capture (interview + import)
│   │   │   ├── projects/       # Project management
│   │   │   └── settings/       # User settings
│   │   ├── components/         # React components
│   │   │   ├── ui/             # shadcn/ui primitives
│   │   │   ├── graph/          # Graph visualization (React Flow)
│   │   │   ├── ask/            # Chat UI components
│   │   │   ├── capture/        # Capture flow components
│   │   │   └── layout/         # App shell, sidebar
│   │   └── lib/                # Utilities (API client, helpers)
│   │
│   ├── api/                    # FastAPI backend
│   │   ├── routers/            # API endpoints (12 modules)
│   │   ├── services/           # Business logic (19 modules)
│   │   │   ├── llm.py              # LLM client (provider-agnostic)
│   │   │   ├── llm_providers/      # NVIDIA NIM + Amazon Bedrock
│   │   │   ├── embeddings.py       # NVIDIA NV-EmbedQA client
│   │   │   ├── extractor.py        # Decision extraction
│   │   │   ├── entity_resolver.py  # 7-stage entity resolution
│   │   │   ├── graph_rag.py        # GraphRAG hybrid retrieval pipeline
│   │   │   └── validator.py        # Graph validation
│   │   ├── models/             # SQLAlchemy + Pydantic schemas
│   │   │   └── ontology.py     # 530+ canonical entity mappings
│   │   ├── evaluation/         # Benchmark framework
│   │   ├── db/                 # Database connections (PG, Neo4j, Redis)
│   │   ├── middleware/         # Security headers, rate limiting
│   │   ├── tests/              # Test suite (unit, integration, e2e, load)
│   │   └── config.py           # All settings with env var defaults
│   │
│   └── mcp/                    # MCP server tools
│
├── docker-compose.yml          # PostgreSQL 18, Neo4j 2025.01, Redis 7.4
├── pnpm-workspace.yaml         # Monorepo workspace config
├── .env.example                # Environment variable template
└── infra/                      # Grafana dashboards
```

**Key files to bookmark:**

| File | Purpose | Read this when... |
|------|---------|-------------------|
| `apps/api/config.py` | All settings | ...you need to change any configuration |
| `apps/api/services/entity_resolver.py` | Core resolution algorithm | ...you are working on entity resolution |
| `apps/api/services/graph_rag.py` | Retrieval pipeline | ...you are working on search or Ask |
| `apps/api/models/ontology.py` | Canonical mappings (534) | ...you are adding entity mappings |
| `apps/api/services/extractor.py` | Decision extraction | ...you are modifying extraction prompts |
| `apps/api/services/llm.py` | LLM client | ...you are debugging LLM calls or switching providers |
| `apps/api/services/embeddings.py` | Embedding client | ...you are working on vector search |

**Common first-run problems:**
- **Port conflicts:** `lsof -i :5432` to find what's using a port. Stop conflicting service or edit `docker-compose.yml`.
- **Alembic `DuplicateTableError`:** Tables exist but `alembic_version` is missing. Fix: `cd apps/api && .venv/bin/alembic stamp head`
- **Silent auth failure:** Register works, but API returns anonymous data. Almost always a `NEXTAUTH_SECRET` != `SECRET_KEY` mismatch. Restart both after fixing.

---

### Ch 8: Your First Session

**10-step walkthrough (action items):**

1. **Start infrastructure:** `docker-compose up -d` -- verify with `docker-compose ps` (all should show `Up` or `healthy`)
2. **Start dev servers:** `pnpm dev` (both frontend at :3000 + backend at :8000) -- or `pnpm dev:web` and `pnpm dev:api` separately
3. **Register an account:** Navigate to `http://localhost:3000/register` or:
   ```bash
   curl -X POST http://localhost:8000/api/users/register \
     -H "Content-Type: application/json" \
     -d '{"name":"Demo","email":"you@demo.com","password":"demo1234"}'
   ```
4. **Create a project:** Projects page -> New Project -> name it
5. **Capture a decision:** Select project -> Capture Decision -> 7-stage AI-guided interview (Opening, Trigger, Context, Options, Decision, Rationale, Summary)
6. **View your decision:** Decisions list -> click to see trigger, context, options, decision, rationale, confidence (0.85-0.95 for well-articulated decisions)
7. **Explore the graph:** Graph view -> interactive React Flow visualization with `DecisionTrace` and `Entity` nodes connected by `INVOLVES` edges
8. **Import decisions:** Bulk JSON import format:
   ```json
   [
     {
       "trigger": "Need to select a caching layer",
       "context": "High-traffic API with 10k req/s",
       "decision": "Use Redis with TTL-based invalidation",
       "rationale": "Sub-millisecond reads, built-in TTL"
     }
   ]
   ```
9. **Search and Ask:** Hybrid Search (`Cmd+K`) for finding decisions; Ask page for natural-language Q&A with GraphRAG (streams via SSE with source cards)
10. **Explore the dashboard:** Stats cards, source breakdown chart, timeline view

- Search finds decisions; Ask *answers questions* by synthesizing across multiple decisions
- First session takes ~30 minutes
- A fresh database has no users -- register one after `docker-compose down -v`

---

### Ch 9: Anatomy of the Data

- A single decision touches three databases and a cache

**Where data lives:**

| Storage | What's Stored | Key |
|---------|--------------|-----|
| **PostgreSQL** | Relational row: `id` (UUID), `user_id`, `project_id`, `source` (interview/import/auto), `status`, all trace fields, timestamps | System of record for structured metadata |
| **Neo4j** | `DecisionTrace` node with all trace fields + 2048-d embedding; `Entity` nodes connected via `INVOLVES` edges; inter-decision relationships | System of record for relationships and semantic search |
| **Redis** | Entity cache, LLM response cache, embedding vector cache | Accelerator -- losing Redis data means nothing is permanently lost |

**Redis cache key patterns:**

| Key Pattern | TTL | Purpose |
|------------|-----|---------|
| `entity:{user_id}:exact:{name}` | 5 min | Entity resolution cache. User-scoped for data isolation. |
| `llm:{version}:extract:{md5_hash}` | 24 h | LLM response cache. Global. Invalidated by bumping `LLM_EXTRACTION_PROMPT_VERSION`. |
| `emb:nvembed:passage:{md5_hash}` | 30 d | Embedding cache. Global. Avoids redundant NVIDIA API calls. |

- Entity cache is per-user; LLM and embedding caches are global (same input -> same output regardless of user)

**PostgreSQL row (selected columns):**

| Column | Example Value |
|--------|--------------|
| `id` | `a3f7c2e1-...` (UUID, primary key) |
| `user_id` | `b8d4a1f0-...` (foreign key to users) |
| `project_id` | `c5e9b3d2-...` (foreign key to projects) |
| `source` | `"interview"` (or `"import"`, `"auto"`) |
| `status` | `"confirmed"` |
| `trigger` | `"Need to select a primary database..."` |
| `decision` | `"Use PostgreSQL as the primary database"` |
| `confidence` | `0.92` |
| `created_at` | `2026-04-04T14:23:17Z` |

**Neo4j queries for inspecting data:**

```cypher
-- Find a decision and its entities
MATCH (d:DecisionTrace)-[r:INVOLVES]->(e:Entity)
WHERE d.trigger STARTS WITH 'Need to select a primary database'
RETURN d.decision, type(r), e.name, e.type

-- View all relationship types in your graph
CALL db.relationshipTypes() YIELD relationshipType
RETURN relationshipType
```

**Embedding field weights:**

| Field | Weight |
|-------|--------|
| Title | 1.5x |
| Decision | 1.2x |
| Rationale | 1.0x (base) |
| Context | 0.8x |
| Trigger | 0.8x |

---

## Part III: How It Works

### Ch 10: Infrastructure Layer

**Three databases:**

| Service | Port | Purpose | Why Chosen |
|---------|------|---------|------------|
| PostgreSQL 18 | 5432 | Users, projects, decision metadata. Schema managed by Alembic. | ACID compliance, concurrent access |
| Neo4j 2025.01 | 7474/7687 | Knowledge graph: entity nodes, decision traces, relationships. Queried via Cypher. | Native labeled property graph, Cypher |
| Redis 7.4 | 6379 | Caching (3 tiers), rate limiting, session ephemera | Sub-millisecond reads, AOF persistence |

- PostgreSQL = system of record for *who* and *what*
- Neo4j = system of record for *how things relate*
- Redis = accelerator -- if you lose its data, nothing is permanently lost

**Docker Compose notes:**
- All ports bound to `127.0.0.1` (localhost only) -- never bind to `0.0.0.0`
- Environment variables ending with `:?` are required -- Docker Compose refuses to start without them
- Neo4j: 512 MB initial heap, 1 GB max. Community edition is single-tenant.
- Redis: `--appendonly yes` for crash-safe persistence

**Docker Compose file (complete):**

```yaml
services:
  postgres:
    image: postgres:18-alpine
    container_name: continuum-postgres
    environment:
      POSTGRES_USER: ${POSTGRES_USER:?POSTGRES_USER must be set}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:?POSTGRES_PASSWORD must be set}
      POSTGRES_DB: ${POSTGRES_DB:-continuum}
    ports:
      - "127.0.0.1:5432:5432"
    volumes:
      - postgres_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL",
             "pg_isready -U $${POSTGRES_USER} -d $${POSTGRES_DB:-continuum}"]
      interval: 10s
      timeout: 5s
      retries: 5
      start_period: 10s
    restart: unless-stopped

  neo4j:
    image: neo4j:2025.01-community
    container_name: continuum-neo4j
    environment:
      NEO4J_AUTH: ${NEO4J_USER:?}/${NEO4J_PASSWORD:?}
      NEO4J_PLUGINS: '["apoc"]'
      NEO4J_dbms_security_procedures_unrestricted: apoc.*
      NEO4J_dbms_memory_heap_initial__size: 512m
      NEO4J_dbms_memory_heap_max__size: 1G
    ports:
      - "127.0.0.1:7474:7474"   # HTTP browser
      - "127.0.0.1:7687:7687"   # Bolt protocol
    volumes:
      - neo4j_data:/data
      - neo4j_logs:/logs
    healthcheck:
      test: ["CMD", "wget", "-q", "--spider",
             "http://localhost:7474"]
      interval: 10s
      timeout: 5s
      retries: 5
      start_period: 30s
    restart: unless-stopped

  redis:
    image: redis:7.4-alpine
    container_name: continuum-redis
    ports:
      - "127.0.0.1:6379:6379"
    volumes:
      - redis_data:/data
    healthcheck:
      test: ["CMD", "redis-cli", "-a",
             "$${REDIS_PASSWORD}", "ping"]
      interval: 10s
      timeout: 5s
      retries: 5
    command: >-
      redis-server --appendonly yes
      --requirepass ${REDIS_PASSWORD:?REDIS_PASSWORD must be set}
    restart: unless-stopped

volumes:
  postgres_data:
  neo4j_data:
  neo4j_logs:
  redis_data:
```

**Volume persistence:**

```bash
# Stop containers, KEEP all data
docker-compose down

# Stop containers and DESTROY all volumes (wipes everything)
docker-compose down -v
```

**WARNING:** `docker-compose down -v` wipes everything: PostgreSQL rows, Neo4j nodes, Redis caches, Alembic migration stamp. Must re-register users, re-run migrations, re-import data. Same for `docker volume prune`.

**Alembic organization:**

```
apps/api/
├── alembic.ini     # database URL, script location
└── alembic/
    ├── env.py      # reads SQLAlchemy models, configures autogenerate
    └── versions/
        ├── 001_initial.py
        ├── 002_add_projects.py
        └── ...
```

- `alembic.ini` tells Alembic where to find the database and migration scripts
- `env.py` imports SQLAlchemy models so `--autogenerate` can diff Python definitions against live database
- `versions/` holds numbered Python scripts, each with `upgrade()` and `downgrade()` functions

**Alembic commands:**

```bash
# Apply all pending migrations
pnpm db:migrate          # or: alembic upgrade head

# Create a new migration from model changes
alembic revision --autogenerate -m "add confidence column"

# Roll back the last migration
alembic downgrade -1

# Check current migration state
alembic current

# Fix DuplicateTableError (stamp without running migrations)
alembic stamp head
```

**WARNING:** Only use `alembic stamp head` when you are certain the live schema matches the latest migration. If the schema is actually behind, stamping skips missing changes and your application encounters column-not-found errors at runtime.

**Redis key patterns:**

| Key Format | TTL | Purpose |
|-----------|-----|---------|
| `entity:{user_id}:{lookup}:{name}` | 5 min | Entity resolution cache. User-scoped. |
| `llm:{version}:extract:{hash}` | 24 h | LLM response cache. Keyed by prompt version. Global. |
| `emb:{model}:{type}:{hash}` | 30 d | Embedding vector cache. Global. |
| `rate:{user_id}` | 60 s | Rate limit counter. Per-user. |

---

### Ch 11: Configuration & Settings

- All settings in `apps/api/config.py` as Pydantic `BaseSettings` class
- Values loaded from environment variables or `.env` file
- Singleton access: `get_settings()` (backed by `@lru_cache`)

```python
from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    database_url: str = ""
    neo4j_uri: str = ""
    nvidia_api_key: SecretStr = SecretStr("")
    llm_provider: str = "nvidia"
    fuzzy_match_threshold: float = 0.85
    rate_limit_requests: int = 30
    debug: bool = False
    # ... 30+ more fields

    model_config = SettingsConfigDict(
        env_file=".env", extra="ignore"
    )

from functools import lru_cache

@lru_cache
def get_settings() -> Settings:
    return Settings()
```

- `model_config`: loads from `.env` file, ignores extra env vars
- `@lru_cache` ensures `Settings()` is constructed exactly once (avoids parsing env on every request)

**SecretStr pattern:**
- Three fields use `SecretStr`: `nvidia_api_key`, `neo4j_password`, `secret_key`
- Masked in logs and `repr()` -- shows `SecretStr('**********')`
- Access raw value via getter methods:
  ```python
  settings = get_settings()
  key = settings.get_nvidia_api_key()     # returns str
  pwd = settings.get_neo4j_password()     # returns str
  # WRONG: settings.nvidia_api_key gives SecretStr object, not str
  ```

**LLM provider switching:**

```bash
# In .env:
LLM_PROVIDER=nvidia    # default (Nemotron 49B, auto-failover to 70B on 503)
LLM_PROVIDER=bedrock   # Amazon Bedrock (Claude Sonnet 4)
```

- NVIDIA NIM: primary `nvidia/llama-3.3-nemotron-super-49b-v1.5`, fallback `nvidia/llama-3.1-nemotron-70b-instruct` (auto on 503)
- Bedrock: `anthropic.claude-sonnet-4-20250514`, region defaults to `us-west-2`

**Embedding provider:**

```bash
EMBEDDING_PROVIDER=nvidia    # default (NV-EmbedQA, 2048-d vectors)
```

- You can use NVIDIA embeddings with Bedrock LLM -- **recommended** to avoid re-indexing
- **WARNING:** Changing embedding provider changes vector dimensionality (NVIDIA=2048-d, Bedrock Titan=1024-d). Existing vectors become incompatible. Must re-embed everything.

**Key settings (top 15):**

| Setting | Default | Description |
|---------|---------|-------------|
| `LLM_PROVIDER` | `nvidia` | LLM backend: `nvidia` or `bedrock` |
| `EMBEDDING_PROVIDER` | `nvidia` | Embedding backend. Keep `nvidia` to avoid re-indexing. |
| `NVIDIA_MODEL` | `nvidia/llama-3.3-nemotron-super-49b-v1.5` | Primary LLM model |
| `LLM_FALLBACK_MODEL` | `nvidia/llama-3.1-nemotron-70b-instruct` | Fallback LLM on 503 errors |
| `LLM_FALLBACK_ENABLED` | `True` | Enable automatic model fallback |
| `FUZZY_MATCH_THRESHOLD` | `0.85` | Minimum fuzzy match score for entity resolution |
| `EMBEDDING_SIMILARITY_THRESHOLD` | `0.90` | Minimum cosine similarity for embedding-based entity match |
| `ENTITY_CACHE_TTL` | `300` | Entity cache lifetime in seconds (5 min) |
| `LLM_CACHE_TTL` | `86400` | LLM response cache lifetime (24 h) |
| `LLM_EXTRACTION_PROMPT_VERSION` | `v1` | Bump to invalidate all LLM cache entries |
| `MAX_PROMPT_TOKENS` | `70000` | Max input tokens (128k context) |
| `RATE_LIMIT_REQUESTS` | `30` | Requests per rate limit window |
| `RATE_LIMIT_WINDOW` | `60` | Rate limit window in seconds |
| `SECRET_KEY` | (empty) | JWT signing secret. Must match `NEXTAUTH_SECRET` |
| `DEBUG` | `False` | Enable debug mode (verbose logging, CORS relaxed) |

**Cache TTL rationale:**

| Cache | TTL | Why This Value |
|-------|-----|----------------|
| Entity resolution | 5 min | Entities can change when merged or aliases added. Short TTL ensures stale resolutions expire quickly. Even 5 min captures burst of repeated mentions within a single extraction. |
| LLM response | 24 h | Same input text with same prompt version = same extraction. Keyed by prompt version, so bumping `LLM_EXTRACTION_PROMPT_VERSION` invalidates all entries. |
| Embedding vector | 30 d | Embedding model doesn't change between deployments. Same text = same vector. Long TTL minimizes redundant API calls. |

**Rate limiting:**
- Authenticated users: 30 requests per 60-second window
- Anonymous users: 10 requests per 60-second window
- Sliding window: counter resets 60 seconds after first request in current window
- Redis key: `rate:{user_id}` with 60s TTL
- Exceeding limit returns HTTP 429 with `Retry-After` header
- Both parameters configurable:
  ```python
  rate_limit_requests: int = 30   # requests per window
  rate_limit_window: int = 60     # window size in seconds
  ```

---

### Ch 12: Entity Resolution Pipeline

**The 7-stage cascade:**

| Stage | Method | Confidence | Details |
|-------|--------|-----------|---------|
| 1. Cache | Redis lookup | 1.0 | Key: `entity:{user_id}:exact:{name}`, TTL 5 min. ~40% hit rate. Negative caching for names that will always be new. |
| 2. Exact | Case-insensitive Neo4j query | 1.0 | `toLower(e.name) = $name`. Searches user-scoped entities first. |
| 3. Canonical | Dictionary lookup | 0.95 | 534 curated mappings in `models/ontology.py`. O(1) lookup. One-line change to add a new alias. |
| 4. Alias | Neo4j `e.aliases` array search | 0.92 | `COALESCE(e.aliases, [])` guard prevents null-pointer errors. |
| 5. Fuzzy | Fulltext + RapidFuzz | score/100 | Two-phase: fulltext index retrieves 500 candidates, then RapidFuzz `fuzz.ratio` scores each. Threshold: 85% (configurable). Falls back to batched loading if no fulltext index. |
| 6. Embedding | NV-EmbedQA cosine similarity | similarity score | Embeds as `"{entity_type}: {name}"`. Threshold: 0.9 (configurable). Circuit breaker after 5 failures. Falls back to client-side cosine if GDS unavailable. |
| 7. Create new | Generate UUID | 1.0 | Sets `is_new=True`. Uses canonical form if available. Original input added as alias. |

**Why cascading works:**
1. **Latency** -- ~83% of lookups handled by stages 1-3 (under 1ms)
2. **Interpretability** -- every `ResolvedEntity` has `match_method` ("cached", "exact", "canonical", "alias", "fuzzy", "embedding", "new") and numeric `confidence`
3. **Graceful degradation** -- Redis down? Skip stage 1. Embedding service unreachable? Skip stage 6. Fulltext index missing? Fall back to batched loading. Pipeline always produces a result.

**Stage-by-stage code snippets:**

Cache lookup:
```python
cached = await self.cache.get_by_exact_name(
    self.user_id, normalized_name
)
if cached is not None:
    return ResolvedEntity(
        id=cached["id"], name=cached["name"],
        type=cached["type"], is_new=False,
        match_method="cached", confidence=1.0,
    )
```

Exact match query (user-scoped):
```cypher
MATCH (d:DecisionTrace)-[:INVOLVES]->(e:Entity)
WHERE (d.user_id = $user_id OR d.user_id IS NULL)
AND toLower(e.name) = $name
RETURN DISTINCT e.id AS id, e.name AS name, e.type AS type
LIMIT 1
```

Canonical lookup (excerpt from `CANONICAL_NAMES`, 10 of 534 entries):
```python
CANONICAL_NAMES = {
    "postgres":    "PostgreSQL",
    "pg":          "PostgreSQL",
    "mongo":       "MongoDB",
    "k8s":         "Kubernetes",
    "tf":          "TensorFlow",
    "react.js":    "React",
    "nextjs":      "Next.js",
    "express":     "Express.js",
    "tailwind":    "Tailwind CSS",
    "sklearn":     "scikit-learn",
    # ... 524 more entries
}
```

Alias search query:
```cypher
MATCH (d:DecisionTrace)-[:INVOLVES]->(e:Entity)
WHERE (d.user_id = $user_id OR d.user_id IS NULL)
AND ANY(alias IN COALESCE(e.aliases, [])
        WHERE toLower(alias) = $name)
RETURN DISTINCT e.id AS id, e.name AS name, e.type AS type
LIMIT 1
```

Fuzzy matching with fulltext acceleration:
```python
search_term = f"{normalized_name}*"
# ... fulltext query returns candidates ...

best_match, best_score = None, 0
for entity in candidates:
    score = fuzz.ratio(normalized_name, entity["name"].lower())
    if score >= self.fuzzy_threshold and score > best_score:
        best_score = score
        best_match = entity
```

Embedding similarity (GDS path):
```python
embedding = await self.embedding_service.embed_text(
    f"{entity_type}: {name}", input_type="passage"
)

result = await self.session.run("""
    MATCH (d:DecisionTrace)-[:INVOLVES]->(e:Entity)
    WHERE (d.user_id = $user_id OR d.user_id IS NULL)
    AND e.embedding IS NOT NULL
    WITH DISTINCT e,
         gds.similarity.cosine(e.embedding, $embedding) AS similarity
    WHERE similarity > $threshold
    RETURN e.id AS id, e.name AS name, e.type AS type, similarity
    ORDER BY similarity DESC LIMIT 1
""", embedding=embedding, threshold=threshold, user_id=self.user_id)
```

New entity creation:
```python
final_name = canonical if canonical.lower() != normalized_name else name
return ResolvedEntity(
    id=str(uuid4()),
    name=final_name,
    type=entity_type,
    is_new=True,
    match_method="new",
    confidence=1.0,
    aliases=[name] if final_name != name else [],
)
```

**`ResolvedEntity` dataclass:**

```python
@dataclass
class ResolvedEntity:
    id: Optional[str]
    name: str
    type: str
    is_new: bool = False
    match_method: Optional[str] = None  # cached, exact, canonical,
                                        # alias, fuzzy, embedding, new
    confidence: float = 1.0
    canonical_name: Optional[str] = None
    aliases: list[str] = None

    def __post_init__(self):
        if self.aliases is None:
            self.aliases = []
```

**WARNING:** `resolve()` does **NOT** write to Neo4j. It returns a `ResolvedEntity` describing what the pipeline found, but the caller must execute the actual `CREATE` query. If you call `resolve()` and discard the result, no node is created.

**Evaluation results (B-cubed metrics, 2,438 test variants):**

| Method | B-cubed P | B-cubed R | B-cubed F1 |
|--------|-----------|-----------|------------|
| **Continuum (cascade)** | **0.985** | **0.974** | **0.979** |
| SBERT cosine | 0.891 | 0.858 | 0.874 |
| Fuzzy only | 0.812 | 0.726 | 0.767 |
| Exact only | 0.793 | 0.703 | 0.746 |
| SpaCy NER | 0.583 | 0.468 | 0.521 |

McNemar's test: p < 0.001 for Continuum vs. all baselines.

---

### Ch 13: Decision Extraction

**Pipeline (5 stages):**

1. **Input** -- conversation text from capture session or bulk import
2. **Prompt construction** -- few-shot extraction prompt injected with conversation text
3. **LLM call** -- default: NVIDIA Nemotron 49B, `temperature=0.3`, `max_tokens=4096`
4. **JSON parse & repair** -- thinking tags stripped, truncated JSON repaired
5. **Validation & defaults** -- missing fields filled with safe defaults

**Extraction prompt structure:**
1. Definition of "decision" (4 categories: explicit, implicit, technical choices, implementation strategies)
2. Required fields: `trigger`, `context`, `options`, `decision`, `rationale`, `confidence`
3. Output format: "Return ONLY valid JSON, no markdown code blocks"
4. Four few-shot examples (single decision, multiple, implicit, no-decision)

Abbreviated prompt:
```python
DECISION_EXTRACTION_PROMPT = """Analyze this conversation
and extract any technical decisions made.

## What constitutes a decision?
A decision is a choice that affects the project direction,
architecture, or implementation. This includes:
- Explicit decisions: "Should we use X or Y? ..."
- Implicit decisions: "Let's use X for this"
- Technical choices: Framework, architecture, tools
- Implementation strategies: How to solve a problem

## Examples
### Example 1: Single clear decision
Conversation: "We need to pick a database. ..."
Output: [{"trigger": "...", "decision": "...", ...}]

### Example 4: No decisions (just discussion)
Output: []

## Conversation to analyze:
{conversation_text}

Return ONLY valid JSON, no markdown code blocks."""
```

Additional specialized prompts: `ARCHITECTURE_DECISION_PROMPT`, `TECHNOLOGY_DECISION_PROMPT`, `PROCESS_DECISION_PROMPT` -- narrow the LLM's focus when decision type is known.

**JSON repair strategies (tried in order):**
1. Parse as pure JSON
2. Extract from ` ```json ` code blocks
3. Extract from untyped ` ``` ` code blocks
4. Regex fallback: find last complete `}` followed by `]`

**Prompt versioning:**
- Cache key: `llm:{version}:extract:{md5(text)}`
- Controlled by `LLM_EXTRACTION_PROMPT_VERSION` in `config.py` (default: `v1`)
- Bump this value when modifying the extraction prompt to invalidate stale cached responses

```python
def _get_cache_key(self, text: str, extraction_type: str) -> str:
    text_hash = hashlib.md5(text.encode("utf-8")).hexdigest()
    version = self._settings.llm_extraction_prompt_version
    return f"llm:{version}:{extraction_type}:{text_hash}"
```

**Default values for incomplete extractions:**

```python
DEFAULT_DECISION_FIELDS = {
    "confidence": 0.5,
    "context":    "",
    "rationale":  "",
    "options":    [],
    "trigger":    "Unknown trigger",
    "decision":   "",
}
```

**Gotchas:**
- **Always use `max_tokens=4096`** -- thinking tags consume 1000-2000 tokens before JSON output begins. With `max_tokens=2000`, ~14.5% of extractions fail due to truncation.
- **Prompt sanitizer blocks evaluation:** Pass `sanitize_input=False` when calling LLM on synthetic or imported conversations -- the sanitizer flags "USER:"/"ASSISTANT:" labels as injection.
- **Multiple runs accumulate:** `save_decision()` creates new Neo4j nodes, not upserts. Wipe Neo4j before each evaluation run.
- **True extraction yield is ~1.9 decisions/conversation** with 85.5% success rate. Higher numbers indicate accumulated results from multiple runs.
- **Thinking tag stripping:** The `strip_thinking_tags()` function in `services/llm.py` removes `<think>...</think>` blocks automatically, but only AFTER the full response is received.
- **Pipeline is stateless:** Extraction takes text in and returns structured JSON out. Persistence to Neo4j, PostgreSQL, and Redis happens in a separate `save_decision()` step -- you can test extraction in isolation without touching any database.
- **Specialized prompts available:** `ARCHITECTURE_DECISION_PROMPT`, `TECHNOLOGY_DECISION_PROMPT`, `PROCESS_DECISION_PROMPT` narrow the LLM's focus when decision type is known in advance.

**Test extraction on a single conversation:**

```bash
cd apps/api
python -c "
import asyncio, json
from services.extractor import DecisionExtractor

async def test():
    ext = DecisionExtractor()
    result = await ext.extract_from_conversation(
        json.load(open(
            'evaluation/data/synthetic_conversations/conv-001.json'
        )),
        sanitize_input=False,
    )
    print(json.dumps(result, indent=2, default=str))

asyncio.run(test())
"
```

**Test a single ingestion via API:**

```bash
curl -X POST http://localhost:8000/api/ingest \
  -H "Content-Type: application/json" \
  -d '{"text": "Let us use Redis for caching."}'
```

---

### Ch 14: Backend API Layer

- FastAPI application at `apps/api/main.py`
- At startup: initializes connection pools for PostgreSQL (async SQLAlchemy), Neo4j (async Bolt driver), and Redis
- Registers 4 middleware layers (applied bottom-to-top on each request):
  1. **CORS** -- allows frontend origin only, with credentials
  2. **GZip** -- compresses responses larger than 1,000 bytes
  3. **Request size limit** -- rejects bodies exceeding 10 MB
  4. **Security headers** -- `X-Content-Type-Options`, `X-Frame-Options`, `Strict-Transport-Security`, etc.
- Installs global exception handlers for validation errors, HTTP exceptions, and circuit-breaker opens

**12 routers grouped by subsystem:**

| Subsystem | Router | Prefix | Responsibility |
|-----------|--------|--------|---------------|
| Capture | `capture.py` | `/api/capture` | Real-time conversation capture |
| Extraction | `ingest.py` | `/api/ingest` | Bulk ingestion of conversation logs |
| Extraction | `agent.py` | `/api/agent` | MCP tool integration |
| Graph | `graph.py` | `/api/graph` | Graph visualization, stats |
| Graph | `entities.py` | `/api/entities` | Entity CRUD |
| Graph | `decisions.py` | `/api/decisions` | Decision trace CRUD |
| Search | `search.py` | `/api/search` | Fulltext and hybrid search |
| Search | `ask.py` | `/api/ask` | GraphRAG Q&A with SSE streaming |
| Management | `projects.py` | `/api/projects` | Multi-project workspace |
| Management | `dashboard.py` | `/api/dashboard` | Aggregated statistics |
| Management | `export.py` | `/api/export` | Data export (JSON, CSV) |
| Management | `users.py` | `/api/users` | User registration and management |

**Authentication flow:**
1. User signs in via Next.js frontend. Auth.js issues JWT signed with `NEXTAUTH_SECRET`.
2. Frontend sends JWT in `Authorization: Bearer <token>` header.
3. Backend verifies JWT signature using `SECRET_KEY`.
4. On success, extracts `user_id` from JWT payload into request context.
5. On failure (expired, malformed, wrong secret), falls back to "anonymous" user -- no data.

**SSE event types (`/api/ask`):**

| Event | Payload | Purpose |
|-------|---------|---------|
| `context` | `{"sources": [...], "context_length": N}` | Retrieved graph context and source nodes. Sent once before first token. |
| `token` | `{"text": "..."}` | LLM response chunk. Sent repeatedly as tokens stream. |
| `done` | `{"token_count": N}` | End-of-stream marker. |
| `error` | `{"detail": "..."}` | Error during retrieval or generation. |

SSE event format:
```python
def _sse_event(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"
```

**Reshaping layer:** Neo4j returns flat dictionaries; routers reshape into frontend-ready contracts (`AskSourceNode`, `SearchResult`, etc.). Reshaping is done in the router layer, not the service layer.

**Multi-tenant isolation:** Every Neo4j query must include `WHERE d.user_id = $user_id OR d.user_id IS NULL`. Missing `user_id` filter = security bug (data leaks across users).

**Neo4j gotcha:** Never pass `query=` as a keyword argument to `session.run()` -- it clashes with the positional Cypher string argument. Always use `parameters={}` dict:

```python
# CORRECT:
result = await session.run(
    "MATCH (d:DecisionTrace) WHERE d.user_id = $user_id RETURN d",
    parameters={"user_id": user_id}
)

# WRONG (causes confusing runtime error):
result = await session.run(
    query="MATCH (d:DecisionTrace) WHERE d.user_id = $user_id RETURN d",
    user_id=user_id
)
```

**OpenAPI documentation:** Start the backend (`pnpm dev:api`) and open `http://localhost:8000/docs` for interactive Swagger UI where you can test every endpoint, see request/response schemas, and try authenticated requests by pasting your JWT into the Authorize dialog.

---

### Ch 15: GraphRAG & Search

**Hybrid search indexes:**

| Index | Type | Covers |
|-------|------|--------|
| `decision_fulltext` | Lucene fulltext | `trigger`, `context`, `decision`, `rationale`, `agent_decision`, `agent_rationale` |
| `entity_fulltext` | Lucene fulltext | `name` |
| `decision_embedding` | Vector (2048-d) | `DecisionTrace` embeddings |
| `entity_embedding` | Vector (2048-d) | `Entity` embeddings |

**RRF implementation:**

```python
RRF_K = 60

def rrf_fuse(fulltext_ids, vector_ids, k=RRF_K):
    scores = {}
    for rank, doc_id in enumerate(fulltext_ids, start=1):
        scores[doc_id] = scores.get(doc_id, 0.0) + 1.0 / (k + rank)
    for rank, doc_id in enumerate(vector_ids, start=1):
        scores[doc_id] = scores.get(doc_id, 0.0) + 1.0 / (k + rank)
    return sorted(scores, key=lambda d: scores[d], reverse=True)
```

**Pipeline (5 steps):**
1. **Hybrid retrieval** -- fulltext and vector searches run concurrently on separate Neo4j sessions (AsyncSession is not safe for concurrent use)
2. **Top-K seed selection** -- top 5 fused IDs become seed nodes
3. **K-hop expansion** -- APOC `apoc.path.subgraphAll` traverses up to 2 hops. Capped at `MAX_CONTEXT_NODES = 50`.
4. **Serialization** -- subgraph converted to structured Markdown (decisions with trigger/rationale/context, entities grouped by type, relationships as labeled edges)
5. **LLM generation** -- serialized context injected into prompt, response streamed as SSE events

**`GraphRAGService` usage:**
- Constructor: `GraphRAGService()` takes no arguments. Sessions passed as kwargs to methods.
- Entry point: `retrieve_context()` returns `(subgraph_dict, context_string, seed_ids)`
  ```python
  async def retrieve_context(
      self, query: str, user_id: str,
      top_k: int = 5, depth: int = 2, session=None,
  ) -> tuple[dict, str, list[str]]:
  ```
- Fallback: if vector search fails, pipeline falls back to fulltext-only retrieval

**Ablation table:**

| Configuration | Recall@5 | Latency Impact |
|--------------|----------|---------------|
| Full pipeline (fulltext + vector + cache) | 100% | baseline |
| No fulltext (vector only) | 13.3% | -- |
| No vector (fulltext only) | 86.7% | -- |
| No cache | 100% | 4x slower |
| No K-hop expansion (seeds only) | 60% | 2x faster |

Fulltext is the backbone. Without it, 87% of results are missed.

**GraphRAG query from command line:**

```bash
cd apps/api
.venv/bin/python evaluation/query_graphrag.py \
    --query "Why did I choose PostgreSQL?"
```

The script prints seed IDs, expanded subgraph stats, serialized context, and the LLM's answer.

**Query parameters for `/api/ask`:**
- `q` (required) -- the question to ask (min 3 chars)
- `depth` (1-3, default 2) -- graph traversal depth
- `top_k` (1-10, default 5) -- number of seed nodes to retrieve

**GraphRAG query via curl:**

```bash
curl -N "http://localhost:8000/api/ask?q=Why+did+we+choose+Redis&depth=2&top_k=5" \
  -H "Authorization: Bearer $TOKEN"
```

Response is Server-Sent Events with `context`, `token`, `done`, and `error` event types.

---

### Ch 16: Frontend Architecture

- Next.js 16 with App Router (`app/` directory), React 19, Tailwind CSS v4, shadcn/ui
- Nebula design system: dark-first theme with violet, rose, and orange accents, glassmorphism effects
- All colors defined as CSS custom properties in `app/globals.css`, consumed via Tailwind semantic classes

**Semantic color tokens (light / dark):**

| Token | Light | Dark | Usage |
|-------|-------|------|-------|
| `--primary` | Violet 48% | Violet 58% | Primary actions, focus rings |
| `--accent` | Rose 50% | Rose 60% | Secondary accents, highlights |
| `--destructive` | Red 51% | Red 45% | Delete, error states |
| `--muted` | Gray 94% | Dark 14% | Disabled, secondary text |
| `--background` | Off-white | Space 6% | Page background |
| `--card` | White | Glass 10% | Card surfaces |

**Component patterns:**

`cn()` for class names:
```typescript
<div className={cn(
  "rounded-lg border p-4",
  variant === "glass" && "backdrop-blur-xl bg-card/50",
  className
)} />
```

CVA for variants:
```typescript
const buttonVariants = cva("base-classes rounded-lg font-medium", {
  variants: {
    variant: {
      default: "bg-primary text-primary-foreground",
      glass: "backdrop-blur-xl bg-card/50 border-white/10",
      gradient: "bg-gradient-to-r from-violet-500 via-fuchsia-500 ...",
      destructive: "bg-destructive text-destructive-foreground",
    },
    size: {
      default: "h-10 px-4",
      sm: "h-8 px-3 text-sm",
      lg: "h-12 px-6 text-lg",
    },
  },
  defaultVariants: { variant: "default", size: "default" },
})
```

`React.forwardRef` pattern:
```typescript
const Card = React.forwardRef<HTMLDivElement, CardProps>(
  ({ className, variant, ...props }, ref) => (
    <div ref={ref} className={cn(cardVariants({ variant }), className)}
         {...props} />
  )
)
Card.displayName = "Card"
```

- Never concatenate class strings manually -- use `cn()` from `lib/utils.ts`
- All UI components use `React.forwardRef` for ref forwarding
- Compound components export sub-components: `Card`, `CardHeader`, `CardTitle`, `CardContent`, `CardFooter`

**Adding a new page:**
1. Create `app/(dashboard)/settings/page.tsx`
2. Export a default React component
3. Route inherits dashboard layout automatically
4. Add navigation link in `components/layout/Sidebar.tsx`

**Graph visualization:**
- React Flow (`@xyflow/react`) with custom node types + Dagre automatic layout
- Decision nodes: gradient cards with violet-to-rose background, confidence badge
- Entity nodes: colored pills tinted by entity type
- Layout modes: force-directed, hierarchical, clustered, radial
- Performance: `React.memo` with custom comparison for 500+ node graphs

**State management:**

| Kind of State | Tool | Details |
|--------------|------|---------|
| Server/async | React Query | 60s stale time, auto-refetch on window focus |
| Form | react-hook-form + Zod | Schema-first validation |
| Theme | next-themes | System/light/dark via `.dark` class on `<html>` |
| Auth session | NextAuth v5 | `SessionProvider` at root, `useSession()` hook |
| Local/ephemeral | `useState`/`useReducer` | Component-level UI state |

**Entity type colors:**

| Entity Type | Color | Hex |
|------------|-------|-----|
| Technology | Orange | `#fb923c` |
| Pattern | Rose | `#ec4899` |
| Concept | Violet | `#a78bfa` |
| Person | Emerald | `#34d399` |
| System | Green | `#4ade80` |

**Frontend gotchas:**
- **Radix ScrollArea breaks `scrollTop`:** Sets `overflow: hidden` on root. For auto-scrolling (chat panel), use plain `<div>` with `overflow-y-auto` instead.
- **React Flow hook ordering:** `useNodesState`/`useEdgesState` setters must be declared *before* any `useCallback` that references them.
- **CSS `:root` in dark mode:** `next-themes` applies `.dark` on `<html>`, so bare `:root` selectors apply in both modes. Use `:root:not(.dark)` for light-mode-only overrides.

---

## Part IV: Extending Continuum

### Ch 17: How to Add Features

**7 recipes (start with 17.1 -- smallest possible change):**

#### Recipe 17.1: Add a Canonical Mapping

- **Files:** `apps/api/models/ontology.py` (the `CANONICAL_NAMES` dictionary)
- **Steps:** Add a lowercase key -> properly-cased canonical value
- **Gotchas:** Keys must be lowercase; don't overwrite existing keys with different values; if canonical name is new, add abbreviations to `KNOWN_ABBREVIATIONS` in `evaluation/synthetic_benchmark.py`
- **Verify:** `cd apps/api && python -m evaluation.synthetic_benchmark`

#### Recipe 17.2: Add an Entity Type

- **Files:** `apps/api/models/ontology.py` (EntityType enum + `VALID_ENTITY_RELATIONSHIPS`), frontend color map, graph node style
- **Steps:**
  1. Add to EntityType enum:
     ```python
     class EntityType(Enum):
         TECHNOLOGY = "technology"
         CONCEPT = "concept"
         PATTERN = "pattern"
         SYSTEM = "system"
         PERSON = "person"
         ORGANIZATION = "organization"
         METRIC = "metric"  # <-- NEW
     ```
  2. Declare valid relationship pairs:
     ```python
     "RELATED_TO": {
         # ... existing pairs ...
         ("metric", "technology"),   # e.g., "latency RELATED_TO Redis"
         ("metric", "concept"),      # e.g., "throughput RELATED_TO caching"
     },
     ```
  3. Add frontend color entry for badges and graph nodes
  4. Update extraction prompt in `services/extractor.py` to enumerate new type
  5. Bump `LLM_EXTRACTION_PROMPT_VERSION`
- **Gotchas:** Must update `VALID_ENTITY_RELATIONSHIPS` or validator rejects relationships at runtime; update extraction prompt to include new type; bump `LLM_EXTRACTION_PROMPT_VERSION`
- **Verify:** `cd apps/api && .venv/bin/pytest tests/ -v -k entity` and `cd apps/web && pnpm typecheck`

#### Recipe 17.3: Add a Relationship Type

- **Files:** `apps/api/models/ontology.py` (RelationType enum + frozen sets + valid pairs), `apps/api/services/extractor.py`, frontend edge style
- **Steps:**
  1. Add to RelationType enum:
     ```python
     class RelationType(Enum):
         # ... existing members ...
         COMPLEMENTS = "COMPLEMENTS"  # X works well alongside Y
     ```
  2. Declare valid source/target type pairs:
     ```python
     VALID_ENTITY_RELATIONSHIPS["COMPLEMENTS"] = {
         ("technology", "technology"),  # Redis COMPLEMENTS PostgreSQL
         ("pattern", "pattern"),        # CQRS COMPLEMENTS Event Sourcing
     }
     ```
  3. Add to the correct frozen set:
     ```python
     ENTITY_ONLY_RELATIONSHIPS: frozenset[str] = frozenset([
         # ... existing ...
         "COMPLEMENTS",
     ])
     ```
  4. Update extraction prompt + frontend edge style (color, dash, arrowhead)
  5. Bump `LLM_EXTRACTION_PROMPT_VERSION`
- **Gotchas:** Must add to one of the three frozen sets (`ENTITY_ONLY_RELATIONSHIPS`, `DECISION_ONLY_RELATIONSHIPS`, `DECISION_ENTITY_RELATIONSHIPS`); `ALL_RELATIONSHIP_TYPES` recomputes automatically from the union; enum value must be all-uppercase; bump prompt version
- **Verify:**
  ```bash
  cd apps/api
  .venv/bin/pytest tests/ -v -k relationship
  python -c "from models.ontology import validate_entity_relationship; \
    print(validate_entity_relationship('COMPLEMENTS','technology','technology'))"
  ```

#### Recipe 17.4: Add an API Endpoint

- **Files:** `apps/api/routers/your_module.py` (new router), `apps/api/main.py` (register with `app.include_router()`)
- **Steps:**
  1. Create the router file:
     ```python
     # routers/health_check.py
     """Health-check router with database connectivity test."""
     from fastapi import APIRouter, Depends
     from pydantic import BaseModel

     router = APIRouter()

     class HealthResponse(BaseModel):
         status: str
         neo4j: bool
         postgres: bool

     @router.get("/", response_model=HealthResponse)
     async def health_check():
         """Return service health with dependency status."""
         return HealthResponse(status="ok", neo4j=True, postgres=True)
     ```
  2. Register in `main.py`:
     ```python
     from routers import health_check

     app.include_router(
         health_check.router,
         prefix="/api/health",
         tags=["Health"],
     )
     ```
  3. Add `user_id` dependency if endpoint needs user context
  4. Write tests in `tests/routers/test_health_check.py`
- **Gotchas:** Every data-returning endpoint must filter by `user_id`; Pydantic strict mode is project-wide; trailing slash matters (FastAPI redirects `/api/health` to `/api/health/`)
- **Verify:**
  ```bash
  curl -s http://localhost:8000/api/health/ | python -m json.tool
  ```

#### Recipe 17.5: Add an LLM Provider

- **Files:** `apps/api/services/llm_providers/your_provider.py` (implement `BaseLLMProvider`), `llm_providers/__init__.py` (register in factory), `apps/api/config.py` (new env vars)
- **Steps:**
  1. Implement the three abstract members of `BaseLLMProvider`:
     ```python
     # llm_providers/ollama.py
     """Ollama LLM provider for local model inference."""
     from typing import AsyncIterator
     from services.llm_providers.base import BaseLLMProvider

     class OllamaLLMProvider(BaseLLMProvider):
         async def generate(
             self, messages: list[dict],
             temperature: float = 0.6, max_tokens: int = 4096,
         ) -> tuple[str, dict]:
             # Call Ollama REST API
             ...

         async def generate_stream(
             self, messages: list[dict],
             temperature: float = 0.6, max_tokens: int = 4096,
         ) -> AsyncIterator[str]:
             # Stream from Ollama REST API
             ...

         @property
         def model_name(self) -> str:
             return "ollama/llama3"
     ```
  2. Register in factory (`llm_providers/__init__.py`):
     ```python
     def get_llm_provider() -> BaseLLMProvider:
         settings = get_settings()
         provider_name = getattr(settings, "llm_provider", "nvidia")
         if provider_name == "bedrock":
             from services.llm_providers.bedrock import BedrockLLMProvider
             return BedrockLLMProvider()
         elif provider_name == "ollama":           # <-- NEW
             from services.llm_providers.ollama import OllamaLLMProvider
             return OllamaLLMProvider()
         else:
             from services.llm_providers.nvidia import NvidiaLLMProvider
             return NvidiaLLMProvider()
     ```
  3. Add config vars to `config.py`:
     ```python
     ollama_base_url: str = "http://localhost:11434"
     ollama_model: str = "llama3"
     ```
  4. Set `LLM_PROVIDER=ollama` in `.env`
- **Gotchas:** `generate()` must return `(text, usage_dict)` tuple with `prompt_tokens`, `completion_tokens`, `total_tokens`; if streaming unsupported, raise `NotImplementedError`; LLMClient wraps providers with retry/rate limiting -- don't implement retries inside your provider
- **Verify:**
  ```bash
  LLM_PROVIDER=ollama python -c "
  from services.llm_providers import get_llm_provider
  p = get_llm_provider()
  print(type(p).__name__, p.model_name)
  "
  ```

#### Recipe 17.6: Add an Evaluation Script

- **Files:** `apps/api/evaluation/your_script.py`
- **Gotchas:** Run from `apps/api/`; use 140/60 train/test split; output JSON to `evaluation/data/v5/`; use `sanitize_input=False` for synthetic conversations
- **Verify:** `cd apps/api && python -m evaluation.your_script --output /tmp/test_results.json`

#### Recipe 17.7: Modify the Extraction Prompt

- **Files:** `apps/api/services/extractor.py` (prompt template), `apps/api/config.py` (`llm_extraction_prompt_version`)
- **Always bump prompt version after changing prompt** -- otherwise system serves old cached responses (silent correctness bug)
- **Gotchas:** Use `max_tokens=4096`+ (thinking tags consume tokens); run full evaluation suite (`evaluation/run_all.py`) before merging
- **Verify:**
  ```bash
  cd apps/api
  python -c "
  import asyncio, json
  from services.extractor import DecisionExtractor
  async def test():
      ext = DecisionExtractor()
      result = await ext.extract_from_conversation(
          json.load(open('evaluation/data/synthetic_conversations/conv-001.json')),
          sanitize_input=False,
      )
      print(json.dumps(result, indent=2, default=str))
  asyncio.run(test())
  "
  ```

---

### Ch 18: Exercises

#### Exercise 1: Ontology Expansion
- **Difficulty:** Easy | **Time:** ~2 h
- **Files:** `apps/api/models/ontology.py`, `apps/api/evaluation/synthetic_benchmark.py`
- **Instructions:**
  1. Pick a technical domain you know well (game dev, embedded systems, bioinformatics, etc.)
  2. Add 20 new canonical mappings to `CANONICAL_NAMES` (lowercase key -> properly cased value)
  3. For each canonical name with well-known abbreviations, add to `KNOWN_ABBREVIATIONS` in `synthetic_benchmark.py`
  4. Run benchmark: `python -m evaluation.synthetic_benchmark`
- **Acceptance criteria:** 20 new entries, benchmark passes, no existing mappings broken
- **Hints:** Look at existing category sections (DATABASES, AI/ML FRAMEWORKS) for formatting. Keys must be lowercase. Search for canonical form before adding to avoid duplicates.

#### Exercise 2: Graph Layout Enhancement
- **Difficulty:** Easy-Medium | **Time:** ~3 h
- **Files:** `apps/web/` -- graph page component and layout utilities
- **Instructions:**
  1. Study existing graph layout code (force-directed, hierarchical algorithms)
  2. Implement a **circular layout** placing nodes in a circle with most-connected node at top
  3. Add layout toggle (dropdown/button group) to graph page
  4. Ensure edges render correctly with new positions
- **Acceptance criteria:** "Circular" option in layout controls. Most-connected node at 12 o'clock. Switching back restores original. `pnpm typecheck` passes.
- **Hints:** Circular position for node i of N: `x = r * cos(2*pi*i/N)`, `y = r * sin(2*pi*i/N)`. Sort by degree descending. Use `cn()` for conditional classes.

#### Exercise 3: Search Entity Type Filter
- **Difficulty:** Medium | **Time:** ~3 h
- **Files:** `apps/api/routers/search.py`, `apps/api/services/`, `apps/web/` search page
- **Instructions:**
  1. Add optional `entity_type` query parameter to search endpoint (accept `EntityType` enum values)
  2. Update search service to filter by entity type when present, return all when absent
  3. Add frontend dropdown listing all entity types + "All" option
  4. Wire dropdown into search API call
- **Acceptance criteria:** `GET /api/search/?q=react&entity_type=technology` returns only technology entities. No filter returns all. Frontend updates in real time. Invalid types return 422. Tests pass.
- **Hints:** Use `Optional[EntityType] = None` for automatic enum validation. Add conditional `WHERE` clause on `type` property. Include entity type in React Query `queryKey`.

#### Exercise 4: New Evaluation Baseline
- **Difficulty:** Medium | **Time:** ~4 h
- **Files:** `apps/api/evaluation/tfidf_baseline.py` (new), `apps/api/evaluation/data/v5/` (output)
- **Instructions:**
  1. Create `evaluation/tfidf_baseline.py`
  2. Load synthetic benchmark CSV data
  3. Compute TF-IDF vectors with character n-grams (`analyzer="char_wb"`, `ngram_range=(2,4)`)
  4. For each test variant, find nearest canonical name by cosine similarity
  5. Compute precision, recall, F1 against ground truth
  6. Write to `evaluation/data/v5/tfidf_baseline_results.json`
- **Acceptance criteria:** Runs end-to-end. Output has precision, recall, f1. Computed on held-out test split only (60 convos). Summary comparing against pipeline F1 (0.979).
- **Hints:** Install scikit-learn: `.venv/bin/pip install scikit-learn`. Character n-grams work better than word n-grams for entity names. Use `cosine_similarity` from `sklearn.metrics.pairwise`. Benchmark CSV has `split` column.

#### Exercise 5: GraphRAG Depth Experiment
- **Difficulty:** Medium-Hard | **Time:** ~4 h
- **Files:** `apps/api/services/graph_rag.py`, `apps/api/evaluation/` (new experiment script)
- **Instructions:**
  1. Study `services/graph_rag.py` and how `retrieve_context()` uses the `depth` parameter
  2. Create script running 10 queries at depths 1, 2, 3
  3. Record per-depth: nodes retrieved, unique entity types, context string length
  4. Judge relevance of top-5 nodes (0/1/2 scale: irrelevant/partial/highly relevant)
  5. Compute average relevance per depth, plot trade-off
- **Acceptance criteria:** JSON output with per-query per-depth results. 10+ queries at all 3 depths. Summary table: depth, avg nodes, avg relevance, avg context length. Brief analysis.
- **Hints:** `retrieve_context()` returns `(subgraph, context_str, seed_ids)`. Depth 1 = direct neighbors; depth 2 = neighbors-of-neighbors. Depth 2 is likely the sweet spot. Reuse queries from `evaluation/test_graphrag.py`.

#### Exercise 6: New MCP Tool
- **Difficulty:** Hard | **Time:** ~4 h
- **Files:** `apps/mcp/` (tool definitions), `apps/api/evaluation/test_mcp.py` (test suite)
- **Instructions:**
  1. Design `continuum_timeline` tool accepting entity name, returning chronological decision list
  2. Query Neo4j for `DecisionTrace` nodes connected via `INVOLVES`, sorted by timestamp
  3. Each entry: decision summary, timestamp, confidence, SUPERSEDES/CONTRADICTS relationships
  4. Implement following existing tool patterns
  5. Write 5 test cases: no decisions (empty), one decision, chronological order, SUPERSEDES chain, CONTRADICTS pair
- **Acceptance criteria:** Tool appears in MCP tool list. Returns chronological list for "PostgreSQL". Includes relationship metadata. All 5 tests pass. Non-existent entities return empty list (not error).
- **Hints:** Study existing MCP tools for registration pattern. Cypher needs `MATCH` entity, traverse `INVOLVES`, optionally `MATCH` inter-decision relationships. Use `ORDER BY d.created_at ASC`. Existing `test_mcp.py` has 31 test cases as template.

---

### Ch 19: Starter Project

**"Decision Diff" -- a one-week full-stack project:**

| Phase | Days | Deliverable |
|-------|------|------------|
| Phase 1: Backend | Days 1-2 | Neo4j Cypher query + Pydantic models + FastAPI endpoint |
| Phase 2: Frontend | Days 3-4 | `EntityTimeline.tsx` component with glass-style cards |
| Phase 3: Evaluation | Day 5 | 5 test cases (zero decisions, single, chronological order, SUPERSEDES chain, CONTRADICTS pair) |

**Backend -- Cypher query:**

```cypher
MATCH (e:Entity {name: $entity_name})<-[:INVOLVES]-(d:DecisionTrace)
OPTIONAL MATCH (d)-[r:SUPERSEDES|CONTRADICTS]->(other:DecisionTrace)
WHERE other IN collect(d)
RETURN d {
    .id, .decision, .rationale, .confidence,
    .created_at, .context
} AS decision,
collect(DISTINCT {
    type: type(r),
    target_id: other.id,
    target_decision: other.decision
}) AS relationships
ORDER BY d.created_at ASC
```

**Backend -- Pydantic models:**

```python
class DecisionRelationship(BaseModel):
    type: str           # "SUPERSEDES" or "CONTRADICTS"
    target_id: str
    target_decision: str

class TimelineEntry(BaseModel):
    id: str
    decision: str
    rationale: str | None = None
    confidence: float
    created_at: datetime
    context: str | None = None
    relationships: list[DecisionRelationship] = []

class EntityTimelineResponse(BaseModel):
    entity_name: str
    total_decisions: int
    timeline: list[TimelineEntry]
```

**Frontend -- Component skeleton (`EntityTimeline.tsx`):**

```typescript
"use client";

import { cn } from "@/lib/utils";

interface TimelineEntry {
  id: string;
  decision: string;
  rationale: string | null;
  confidence: number;
  created_at: string;
  relationships: {
    type: "SUPERSEDES" | "CONTRADICTS";
    target_id: string;
    target_decision: string;
  }[];
}

interface EntityTimelineProps {
  entityName: string;
  entries: TimelineEntry[];
}

export function EntityTimeline({
  entityName,
  entries,
}: EntityTimelineProps) {
  return (
    <div className={cn("relative space-y-6 pl-8")}>
      {/* Vertical line */}
      <div className={cn(
        "absolute left-3 top-0 bottom-0 w-px",
        "bg-border"
      )} />

      {entries.map((entry, i) => (
        <TimelineCard
          key={entry.id}
          entry={entry}
          isLatest={i === entries.length - 1}
        />
      ))}
    </div>
  );
}
```

**Frontend design guidelines:**
- Glass-style cards consistent with Nebula theme (see `apps/web/CLAUDE.md`)
- `cn()` for className composition, semantic color tokens (no hardcoded colors)
- SUPERSEDES badges: amber/warning color (this decision replaced an older one)
- CONTRADICTS badges: red/destructive color (these decisions conflict)
- Entity type colors: match existing badge colors used elsewhere
- Each card: decision text, confidence badge, formatted timestamp, relationship badges
- Icons from `lucide-react` exclusively

**Definition of done (all 8 must be true):**
1. Neo4j query correct for 0, 1, and many decisions
2. `GET /api/entities/{id}/timeline` returns well-formed `EntityTimelineResponse`
3. Endpoint filters by `user_id`
4. `EntityTimeline.tsx` renders vertical timeline
5. SUPERSEDES and CONTRADICTS badges display correctly
6. All 5 test cases pass
7. `pnpm typecheck` passes
8. `.venv/bin/pytest tests/ -v` passes

---

## Part V: Research & Future

### Ch 20: Evaluation Methodology

**Synthetic dataset:**
- 200 developer-AI conversations across 9 domains (web dev, backend, DevOps, ML, mobile, data engineering, systems, security, cloud architecture)
- 3,070 entity mentions with ground-truth canonical names
- Surface-form variants: lowercase, uppercase, abbreviations, version-qualified, misspellings, suffix variations
- Why synthetic: reproducibility, no IRB required, domain control

**Evaluation scripts** (all in `apps/api/evaluation/`, run from `apps/api/`):

| Script | Purpose |
|--------|---------|
| `generate_conversations.py` | Generate 200 synthetic developer-AI conversations |
| `synthetic_benchmark.py` | B-cubed evaluation on 2,438 test variants (80/20 held-out split) |
| `run_full_pipeline.py` | Complete pipeline: wipe, extract, embed, index, evaluate |
| `run_full_ablation.py` | 7-stage ablation study (disable each pipeline stage) |
| `test_graphrag.py` | Automated GraphRAG retrieval evaluation |
| `test_mcp.py` | MCP tool evaluation (31 test cases) |
| `run_end_to_end.py` | LLM decision extraction on all conversations |
| `compute_calibration.py` | Expected Calibration Error (ECE) from confidence scores |
| `annotate_cli.py` | Interactive CLI for human entity annotation |
| `judge_graphrag.py` | Interactive CLI for manual retrieval relevance judging |
| `review_decisions.py` | Interactive CLI for manual decision quality review |

```bash
# Entity resolution benchmark (offline, no API needed)
cd apps/api && .venv/bin/python -m evaluation.synthetic_benchmark

# Full pipeline (requires Neo4j + NVIDIA API)
cd apps/api && .venv/bin/python -m evaluation.run_full_pipeline

# Ablation study (requires Neo4j + NVIDIA API)
cd apps/api && .venv/bin/python -m evaluation.run_full_ablation

# GraphRAG evaluation (requires Neo4j + NVIDIA API)
cd apps/api && .venv/bin/python -m evaluation.test_graphrag

# MCP tool tests (requires Neo4j + running backend)
cd apps/api && .venv/bin/python -m evaluation.test_mcp
```

**Train/test split:**
- Training: 140 conversations (build canonical dictionary + tune thresholds)
- Held-out test: 60 conversations (all reported metrics)
- Non-circular: canonical dictionary frozen before test evaluation
- Benchmark CSV has `split` column (`train`/`test`)

**Metrics:**
- **B-cubed P/R/F1**: per-mention precision and recall, averaged across all mentions. Handles singletons naturally.
- **McNemar's test**: statistical significance of paired binary outcomes between systems
- **Expected Calibration Error (ECE)**: measures whether confidence scores are well-calibrated

**B-cubed formula:**
- For each mention m:
  - Precision(m) = |predicted_cluster(m) intersect true_cluster(m)| / |predicted_cluster(m)|
  - Recall(m) = |predicted_cluster(m) intersect true_cluster(m)| / |true_cluster(m)|
- Overall P and R are averages across all mentions; F1 is their harmonic mean

**B-cubed worked example:**

| Mention | True Cluster | Predicted Cluster |
|---------|-------------|-------------------|
| postgres | PostgreSQL | PostgreSQL |
| PostgreSQL | PostgreSQL | PostgreSQL |
| PG | PostgreSQL | PG (singleton) |
| MongoDB | MongoDB | MongoDB |
| Mongo | MongoDB | MongoDB |

- System correctly groups MongoDB+Mongo but splits PG into its own cluster
- Average precision = 1.0 (never incorrectly groups unrelated mentions)
- Average recall = 0.733 (failed to recognize PG as alias for PostgreSQL)
- Pattern: high precision, lower recall on abbreviations = typical of conservative pipelines

**ECE formula:**

```
ECE = sum over bins b of: (|B_b|/N) * |accuracy(B_b) - confidence(B_b)|
```

Lower ECE = better calibration. Perfectly calibrated system has ECE = 0.

**Reproducibility (Run 1 vs. Run 2):**

| Metric | Run 1 | Run 2 | Delta |
|--------|-------|-------|-------|
| Total decisions | 364 | 383 | +19 |
| Extraction rate | 82.5% | 85.5% | +3.0% |
| Conversations with decisions | 165 | 171 | +6 |
| Avg decisions/conv | 1.82 | 1.92 | +0.10 |
| Total entity links | 1,292 | 1,282 | -10 |
| Avg extraction time (s) | 28.51 | 26.8 | -1.71 |

- 55.5% produced exactly the same number of decisions in both runs
- 77.5% were within +/-1 decision

**Verified evaluation statistics (Run 2):**

| Metric | Value | Source File |
|--------|-------|------------|
| Conversations | 200 | `e2e_run2_results.json` |
| With decisions | 171 (85.5%) | `e2e_run2_results.json` |
| Total decisions | 383 | `e2e_run2_results.json` |
| Avg decisions/conv | 1.92 | `e2e_run2_results.json` |
| Total entities | 847 | `graph_topology_run2.json` |
| Total relationships | 1,271 | `graph_topology_run2.json` |
| Avg confidence | 0.945 | `graph_topology_run2.json` |
| Avg extraction time (s) | 26.8 | `e2e_run2_results.json` |
| Canonical mappings | 534 | `ontology.py` |
| B-cubed Precision | 0.975 | `bcubed_results.json` |
| B-cubed Recall | 0.984 | `bcubed_results.json` |
| B-cubed F1 | 0.979 | `bcubed_results.json` |
| Mentions evaluated | 3,070 | `bcubed_results.json` |

**Ablation configurations:**

| Configuration | Description |
|--------------|-------------|
| Full pipeline | All 7 stages enabled (baseline) |
| No cache | Disable Redis cache lookup (stage 1) |
| No exact match | Disable case-insensitive exact match (stage 2) |
| No canonical | Disable canonical dictionary lookup (stage 3) |
| No alias | Disable alias search (stage 4) |
| No fuzzy | Disable fuzzy matching with RapidFuzz (stage 5) |
| No embedding | Disable embedding similarity (stage 6) |

**Ablation gotchas:** When monkeypatching for ablation, the cache mock needs all three methods (`get_by_exact_name`, `set_by_exact_name`, `set_by_alias`). Fuzzy stage mock must return `None` (not a tuple). Embedding stage is disabled by replacing the embedding service entirely.

**Evaluation limitations:**
1. Synthetic-only data -- metrics likely optimistic vs. real conversations
2. Single primary annotator -- potential bias, no inter-annotator agreement measured

---

### Ch 21: Known Limitations

| # | Limitation | Impact | Potential Mitigation |
|---|-----------|--------|---------------------|
| 1 | **Synthetic-only evaluation** | Reported metrics (F1=0.979) likely optimistic. Real conversations have novel abbreviations, jargon, typos outside dictionary coverage. | Collect 50-100 real conversations from open-source projects. Anonymize, annotate with 2 independent annotators, measure inter-annotator agreement. |
| 2 | **No user study** | Core value proposition (decision KG improves developer decision-making) is unvalidated. Technical correctness does not imply practical utility. | Controlled experiment: 10+ developers per group, 5 decision-making tasks. Measure decision consistency, time to decision, subjective usefulness. |
| 3 | **Weak baselines** | Not compared against strong published baselines (BLINK, EntQA, fine-tuned BERT). High F1 may reflect synthetic data simplicity. | Implement BERT entity matching + TF-IDF cosine similarity baselines. Compare on same held-out test set with McNemar's test. |
| 4 | **Two dormant stages** | Alias search (stage 4) and embedding similarity (stage 6) rarely trigger during evaluation. Add complexity without demonstrated benefit on current data. | Create adversarial test set (100+ hard mentions) designed to bypass first 4 stages. Measure activation rates. |
| 5 | **Single-project scope** | No cross-project knowledge transfer. 10 projects using PostgreSQL = 10 separate redundant knowledge graphs. | Implement cross-project entity alignment. Link entities with same canonical name across projects. Enable org-wide queries. |
| 6 | **LLM dependency** | Extraction quality tightly coupled to specific model (Nemotron). Same model produces different results across runs (364 vs. 383 decisions). | Run evaluation with 3+ LLMs (Nemotron, Claude, GPT-4). Report per-model metrics. Disentangle pipeline quality from model quality. |
| 7 | **Scale untested** | Tested with ~200 convos, ~383 decisions, ~847 entities. Linear scans in fuzzy matching, exact nearest-neighbor search, large subgraph traversals may bottleneck at scale. | Profile at 10x/100x. Replace exact NN with ANN (FAISS HNSW or pgvector). Add graph sampling for large neighborhoods. |

---

### Ch 22: Future Directions

**Semester projects (3-4 months):**

| Project | Problem | Key Deliverable |
|---------|---------|----------------|
| Real Conversation Evaluation | Synthetic-only metrics may not generalize | Anonymized real-conversation corpus + B-cubed comparison |
| Stronger Baselines | No comparison against BERT/TF-IDF/BLINK | 2+ baseline implementations + comparison table with McNemar's test |
| User Study | Practical value unvalidated | IRB-approved controlled experiment (10+ devs per group) |
| Dormant Stage Analysis | Stages 4 and 6 rarely trigger | Adversarial test set (100+ hard mentions) + activation rate analysis |
| Confidence Calibration | Confidence scores may not be well-calibrated | ECE before/after calibration + reliability diagrams |

**Thesis-level research (6-12 months):**

| Direction | Research Question |
|-----------|------------------|
| Multi-Agent Knowledge Sharing | Can multiple AI agents sharing a decision KG via MCP improve collective decision quality? |
| Cross-Project Knowledge Transfer | Can entity alignment across project KGs enable useful knowledge transfer? |
| Real-Time MCP Capture | Is real-time capture during coding more effective than post-hoc log extraction? |
| Privacy-Preserving Federated Graphs | Can organizations share decision knowledge without exposing proprietary details? |
| Temporal Graph Reasoning | Can temporal annotations enable queries about decision evolution ("When did we stop using X?")? |
| Scale and Performance | How does the system perform at 10x/100x/1000x current scale? Replace linear scans with ANN indexes. |

---

## Quick Reference: AI Configuration

| Component | Default | Details |
|-----------|---------|---------|
| **LLM (primary)** | `nvidia/llama-3.3-nemotron-super-49b-v1.5` | NVIDIA NIM API, 128k context |
| **LLM (fallback)** | `nvidia/llama-3.1-nemotron-70b-instruct` | Auto-failover on 503 errors |
| **LLM (alternative)** | `anthropic.claude-sonnet-4-20250514` | Amazon Bedrock |
| **Embeddings (default)** | `nvidia/llama-3.2-nv-embedqa-1b-v2` | 2048 dimensions |
| **Embeddings (alternative)** | `amazon.titan-embed-text-v2:0` | 1024 dimensions |
| **Provider switching** | `LLM_PROVIDER=nvidia` or `bedrock` | Single env var |
| **Embedding provider** | `EMBEDDING_PROVIDER=nvidia` | Keep nvidia even with Bedrock LLM to avoid re-indexing |
| **Embedding batch size** | 32 | Optimized for throughput (NIM supports up to 256) |
| **Rate limiting** | 30 req/min (authenticated), 10 req/min (anonymous) | Redis token bucket |
| **LLM caching** | Redis-backed, 24h TTL | Invalidated by `LLM_EXTRACTION_PROMPT_VERSION` |
| **Thinking tags** | Auto-stripped | `<think>...</think>` removed from model output |
| **Observability** | Datadog LLM tracing | `DD_TRACE_ENABLED=true` to enable |
| **Token logging** | Prompt/completion counts | Logged per LLM call |

## Quick Reference: Worked Example

A developer-AI conversation about database selection:

> **Developer:** I need to select a database for a new transaction processing service on our fintech platform. Requirements: strong consistency, ACID transactions, and complex queries on financial records.
>
> **Assistant:** For a transaction-heavy financial service, the main contenders would be PostgreSQL, MongoDB, and CockroachDB. Given your emphasis on ACID compliance and complex queries, PostgreSQL is the strongest fit.
>
> **Developer:** Good point about MongoDB transactions. We also need PostGIS later for location-based fraud detection. Going with PostgreSQL.

From this conversation, Continuum extracts:

| Field | Extracted Value |
|-------|----------------|
| Trigger | Need to select database for new service |
| Context | Building a transaction-heavy financial API |
| Options | PostgreSQL, MongoDB, CockroachDB |
| Decision | Use PostgreSQL |
| Rationale | ACID compliance critical for financial transactions; PostGIS needed for future fraud detection |
| Confidence | 0.92 |

Each entity (PostgreSQL, MongoDB, CockroachDB, PostGIS) is resolved against the knowledge graph using the 7-stage pipeline. The decision node is linked to entities via `INVOLVES` relationships.

## Quick Reference: NVIDIA NIM API Notes

- Rate limit: 40 requests/minute on free tier
- Extraction takes ~20-30s per conversation (dominated by LLM inference)
- Full 200-conversation extraction: ~100 minutes
- Use `max_tokens=4096` (not 2000) -- thinking tags consume tokens
- Implement JSON repair: find last complete `}` + `]` for truncated responses
- 85.5% extraction success rate is normal -- 14.5% fail on token limits
- Embedding method: `embed_text()` (not `embed()` or `get_embedding()`)
- Two separate API keys: `NVIDIA_API_KEY` (LLM) and `NVIDIA_EMBEDDING_API_KEY` (embeddings)
- Embedding batch size: 32 (optimized for throughput, NIM supports up to 256)

## Quick Reference: Gotchas Compilation

**Backend:**
- **Neo4j `session.run()` kwargs:** Never pass `query=` as kwarg -- it clashes with the positional Cypher string. Always use `parameters={}` dict.
- **`__pycache__` stale bytecode:** When `uvicorn --reload` doesn't pick up changes: `find apps/api -name "__pycache__" -type d -exec rm -rf {} +`
- **NVIDIA NIM 503s:** Auto-failover to fallback model via `llm_fallback_enabled=True`
- **Entity resolver doesn't persist:** `resolve()` returns `ResolvedEntity` but does NOT write to Neo4j
- **Multiple extraction runs accumulate:** Always wipe Neo4j before new evaluation runs
- **True extraction yield is ~1.9 decisions/conv:** Higher numbers = accumulated multiple runs
- **LLM thinking tags consume tokens:** Use `max_tokens=4096`+ and implement JSON repair
- **Neo4j fulltext index:** Must cover both `decision`/`rationale` AND `agent_decision`/`agent_rationale`
- **GraphRAGService() takes no constructor args:** Session passed as kwarg to methods
- **Alembic DuplicateTableError:** Fix with `alembic stamp head`
- **NEXTAUTH_SECRET must match SECRET_KEY:** Mismatch = silent auth failure
- **Fresh database has no users:** Register after `docker-compose down -v`
- **Prompt sanitizer blocks evaluation:** Use `sanitize_input=False` for synthetic conversations

**Frontend:**
- **CSS `:root` in dark mode:** Use `:root:not(.dark)` for light-mode-only overrides
- **React Flow hook ordering:** Declare `useNodesState`/`useEdgesState` before any `useCallback`
- **`ErrorState` component:** Uses `retry` prop, not `onRetry`
- **`ProjectSelector`:** Uses shadcn Command + Popover combo
- **Tooltip max-width:** Use `max-w-lg` for full content visibility
- **Radix ScrollArea:** Use plain `<div>` with `overflow-y-auto` for auto-scrolling
- **Never write `\!` in TSX:** Causes TS1127 error

## Quick Reference: Security Notes

- Docker ports bound to `127.0.0.1` (localhost only)
- Never commit `.env` file (use `.env.example` as template)
- Python dependencies isolated in virtual environment
- API keys stored as `SecretStr` in config (masked in logs)
- Security headers middleware (`X-Content-Type-Options`, `X-Frame-Options`, `Strict-Transport-Security`)
- Request size limiting (10 MB default)
- Per-user rate limiting with Redis token bucket
- Input validation on all endpoints (Pydantic strict mode)

## Quick Reference: MCP Tools

Continuum's MCP server provides 5 tools for AI agent access:

| Tool | Purpose |
|------|---------|
| `continuum_check` | Prior-art check: search for existing decisions before making a new one |
| `continuum_remember` | Record a decision made by the agent into the knowledge graph |
| `continuum_search` | Hybrid search across decisions and entities |
| `continuum_context` | Get everything known about a specific entity (decisions, relationships, aliases) |
| `continuum_summary` | High-level project overview with stats and recent decisions |

**Testing MCP tools:**

```bash
cd apps/api
.venv/bin/python -m evaluation.test_mcp
# Runs 31 test cases covering all 5 tools
```

## Quick Reference: Relationship Types

**Entity-Entity relationships:**
`IS_A`, `PART_OF`, `DEPENDS_ON`, `RELATED_TO`, `ALTERNATIVE_TO`, `ENABLES`, `PREVENTS`, `REQUIRES`, `REFINES`

**Decision-Entity relationships:**
`INVOLVES`

**Decision-Decision relationships:**
`SIMILAR_TO`, `INFLUENCED_BY`, `SUPERSEDES`, `CONTRADICTS`

**Validation:** The `validator.py` service checks:
- Relationship type validity (is the type in the allowed set?)
- Source/target type pairs (is this pair allowed for this relationship type?)
- Circular dependency detection
- Orphan detection (nodes with no relationships)
- Entity deduplication candidates

## Quick Reference: File Locations

| File / Directory | Purpose |
|-----------------|---------|
| `apps/api/config.py` | All settings with env var defaults |
| `apps/api/services/entity_resolver.py` | 7-stage cascading entity resolution |
| `apps/api/services/graph_rag.py` | GraphRAG hybrid retrieval pipeline |
| `apps/api/services/extractor.py` | Decision extraction from conversations |
| `apps/api/services/llm.py` | LLM client (provider-agnostic) |
| `apps/api/services/llm_providers/` | NVIDIA NIM + Amazon Bedrock providers |
| `apps/api/services/embeddings.py` | NVIDIA NV-EmbedQA embedding client |
| `apps/api/services/validator.py` | Graph validation and consistency |
| `apps/api/models/ontology.py` | 530+ canonical entity mappings |
| `apps/api/routers/ask.py` | GraphRAG SSE streaming endpoint |
| `apps/api/routers/search.py` | Hybrid search endpoint |
| `apps/api/routers/capture.py` | WebSocket interview capture |
| `apps/api/routers/agent.py` | MCP server tools |
| `apps/api/evaluation/` | Benchmark scripts and evaluation framework |
| `apps/api/evaluation/data/synthetic_conversations/` | 200 generated conversations (JSON) |
| `apps/api/evaluation/data/v5/` | Pipeline run results, baselines, reproducibility data |
| `apps/api/tests/` | Test suite (unit, integration, e2e, load, security) |
| `apps/web/components/graph/` | React Flow graph visualization |
| `apps/web/components/ask/` | GraphRAG chat UI |
| `apps/web/components/ui/` | shadcn/ui primitives |
| `apps/web/lib/utils.ts` | `cn()` utility and helpers |
| `apps/mcp/` | MCP server tool definitions |
| `.env.example` | Environment variable template |
| `docker-compose.yml` | Infrastructure services |
| `~/.claude/projects/*/conversations/*.jsonl` | Claude Code conversation logs |

## Quick Reference: Evaluation Data

Results and datasets stored in `apps/api/evaluation/data/`:
- `synthetic_conversations/` -- 200 generated conversations (JSON)
- `synthetic_benchmark.csv` -- Ground truth for entity resolution (includes `split` column: train/test)
- `v5/` -- Pipeline run results, baseline comparisons, reproducibility data
- `ablation_results.json` -- Stage-by-stage ablation metrics
- `bcubed_results.json` -- B-cubed precision, recall, F1
- `e2e_run2_results.json` -- End-to-end extraction results (Run 2)
- `graph_topology_run2.json` -- Graph statistics (entities, relationships, confidence)

## Quick Reference: Privacy Constraints

- ONLY Continuum project logs (`~/.claude/projects/-Users-shehral-continuum/`) may be used for research
- All other project logs (CS6120, CS5330, Resume, etc.) are private -- never access them
- Evaluation data uses synthetic conversations (generated, not real logs)
- `extract_from_logs.py` has an `ALLOWED_PROJECT_DIRS` safeguard -- respect it

## Quick Reference: Docker Services

| Service | Container Name | Port(s) | Data Volume |
|---------|---------------|---------|-------------|
| PostgreSQL 18 | `continuum-postgres` | 5432 | `postgres_data` |
| Neo4j 2025.01 | `continuum-neo4j` | 7474 (HTTP) / 7687 (Bolt) | `neo4j_data`, `neo4j_logs` |
| Redis 7.4 | `continuum-redis` | 6379 | `redis_data` |

**All ports bound to `127.0.0.1`** -- only reachable from localhost, never from the network.

```bash
# Check service status
docker-compose ps

# View logs
pnpm docker:logs

# Start services
pnpm docker:up

# Stop services (preserves data)
pnpm docker:down

# Stop and DESTROY all data
docker-compose down -v
```

## Quick Reference: Testing

```bash
# Backend unit tests
cd apps/api && .venv/bin/pytest tests/ -v

# Backend linting
cd apps/api && .venv/bin/ruff check .

# Frontend type checking
cd apps/web && pnpm typecheck

# Frontend linting
pnpm lint

# Load testing (requires k6)
cd apps/api/tests/load && k6 run load_test.js

# Security audit
cd apps/api && .venv/bin/python tests/security/audit.py
```

## Quick Reference: Useful Commands

```bash
# Backend logs
tail -f /tmp/continuum-backend.log

# Restart backend
pkill -f uvicorn && .venv/bin/uvicorn main:app --reload --host 127.0.0.1 --port 8000 > /tmp/continuum-backend.log 2>&1 &

# Clear stale pycache (when --reload doesn't pick up changes)
find apps/api -name "__pycache__" -type d -exec rm -rf {} +

# Check Neo4j data
curl -s -u neo4j:$NEO4J_PASSWORD -H "Content-Type: application/json" \
  -d '{"statements":[{"statement":"MATCH (n) RETURN labels(n)[0], count(n)"}]}' \
  http://localhost:7474/db/neo4j/tx/commit

# Check memory usage (macOS)
top -l 1 -s 0 | grep -E "^(PhysMem|Load)"

# Wipe Neo4j for fresh evaluation run
# Via API: POST /api/graph/reset
# Via Neo4j Browser: MATCH (n) DETACH DELETE n
```

---

## Appendix A: Configuration Reference

All settings defined in `apps/api/config.py` as Pydantic `BaseSettings`. Every field maps to an upper-cased environment variable. Place overrides in `.env` or export in your shell.

### Database

| Setting | Type | Default | Env Var | Description |
|---------|------|---------|---------|-------------|
| `database_url` | `str` | `""` | `DATABASE_URL` | PostgreSQL async connection string. Auto-converts `postgresql://` to `postgresql+asyncpg://`. |
| `neo4j_uri` | `str` | `""` | `NEO4J_URI` | Neo4j Bolt or `neo4j+s://` URI. |
| `neo4j_user` | `str` | `""` | `NEO4J_USER` | Neo4j username. |
| `neo4j_password` | `SecretStr` | `""` | `NEO4J_PASSWORD` | Neo4j password. Masked in logs. |
| `redis_url` | `str` | `""` | `REDIS_URL` | Redis connection string with optional password. |

### LLM Provider

| Setting | Type | Default | Env Var | Description |
|---------|------|---------|---------|-------------|
| `llm_provider` | `str` | `"nvidia"` | `LLM_PROVIDER` | Active LLM backend: `"nvidia"` or `"bedrock"`. |
| `embedding_provider` | `str` | `"nvidia"` | `EMBEDDING_PROVIDER` | Embedding backend. Keep `"nvidia"` even with Bedrock LLM to avoid re-indexing. |

### NVIDIA NIM

| Setting | Type | Default | Env Var | Description |
|---------|------|---------|---------|-------------|
| `nvidia_api_key` | `SecretStr` | `""` | `NVIDIA_API_KEY` | API key for NVIDIA NIM LLM endpoint. |
| `nvidia_model` | `str` | `nvidia/llama-3.3-nemotron-super-49b-v1.5` | `NVIDIA_MODEL` | LLM model identifier. |
| `nvidia_embedding_api_key` | `SecretStr` | `""` | `NVIDIA_EMBEDDING_API_KEY` | Separate API key for the embedding model. |
| `nvidia_embedding_model` | `str` | `nvidia/llama-3.2-nv-embedqa-1b-v2` | `NVIDIA_EMBEDDING_MODEL` | Embedding model identifier. |

### Amazon Bedrock

| Setting | Type | Default | Env Var | Description |
|---------|------|---------|---------|-------------|
| `bedrock_model_id` | `str` | `anthropic.claude-sonnet-4-20250514` | `BEDROCK_MODEL_ID` | Bedrock model ID for LLM calls. |
| `bedrock_embedding_model_id` | `str` | `amazon.titan-embed-text-v2:0` | `BEDROCK_EMBEDDING_MODEL_ID` | Bedrock embedding model. |
| `aws_region` | `str` | `"us-west-2"` | `AWS_REGION` | AWS region for Bedrock API calls. |

### Observability

| Setting | Type | Default | Env Var | Description |
|---------|------|---------|---------|-------------|
| `dd_trace_enabled` | `bool` | `False` | `DD_TRACE_ENABLED` | Enable Datadog LLM Observability tracing. |

### Embedding Cache

| Setting | Type | Default | Env Var | Description |
|---------|------|---------|---------|-------------|
| `embedding_cache_ttl` | `int` | `2592000` | `EMBEDDING_CACHE_TTL` | Embedding cache lifetime in seconds (30 days). |
| `embedding_cache_min_text_length` | `int` | `10` | `EMBEDDING_CACHE_MIN_TEXT_LENGTH` | Minimum text length to cache an embedding. |
| `embedding_batch_size` | `int` | `32` | `EMBEDDING_BATCH_SIZE` | Texts per batch for bulk embedding calls. NVIDIA NIM supports up to 256. |

### Rate Limiting

| Setting | Type | Default | Env Var | Description |
|---------|------|---------|---------|-------------|
| `rate_limit_requests` | `int` | `30` | `RATE_LIMIT_REQUESTS` | Maximum API requests per window. |
| `rate_limit_window` | `int` | `60` | `RATE_LIMIT_WINDOW` | Rate-limit window in seconds. |

### LLM Retry

| Setting | Type | Default | Env Var | Description |
|---------|------|---------|---------|-------------|
| `llm_max_retries` | `int` | `3` | `LLM_MAX_RETRIES` | Maximum retry attempts with exponential backoff. |
| `llm_retry_base_delay` | `float` | `1.0` | `LLM_RETRY_BASE_DELAY` | Base delay in seconds for exponential backoff. |

### LLM Prompt

| Setting | Type | Default | Env Var | Description |
|---------|------|---------|---------|-------------|
| `max_prompt_tokens` | `int` | `70000` | `MAX_PROMPT_TOKENS` | Maximum input tokens (Nemotron 128k context). |
| `prompt_warning_threshold` | `float` | `0.8` | `PROMPT_WARNING_THRESHOLD` | Warn when prompt exceeds this fraction of max. |

### LLM Cache

| Setting | Type | Default | Env Var | Description |
|---------|------|---------|---------|-------------|
| `llm_cache_enabled` | `bool` | `True` | `LLM_CACHE_ENABLED` | Toggle Redis-backed LLM response caching. |
| `llm_cache_ttl` | `int` | `86400` | `LLM_CACHE_TTL` | LLM cache lifetime in seconds (24 hours). |
| `llm_extraction_prompt_version` | `str` | `"v1"` | `LLM_EXTRACTION_PROMPT_VERSION` | Bump to invalidate cached extraction results. |
| `llm_fallback_model` | `str` | `nvidia/llama-3.1-nemotron-70b-instruct` | `LLM_FALLBACK_MODEL` | Secondary model used on primary 503 failures. |
| `llm_fallback_enabled` | `bool` | `True` | `LLM_FALLBACK_ENABLED` | Enable automatic fallback to secondary model. |

### Entity Cache

| Setting | Type | Default | Env Var | Description |
|---------|------|---------|---------|-------------|
| `entity_cache_ttl` | `int` | `300` | `ENTITY_CACHE_TTL` | Entity resolution cache lifetime (5 minutes). |
| `entity_cache_enabled` | `bool` | `True` | `ENTITY_CACHE_ENABLED` | Toggle entity resolution caching. |

### Similarity Thresholds

| Setting | Type | Default | Env Var | Description |
|---------|------|---------|---------|-------------|
| `similarity_threshold` | `float` | `0.85` | `SIMILARITY_THRESHOLD` | Minimum cosine similarity for `SIMILAR_TO` edges. |
| `high_confidence_similarity_threshold` | `float` | `0.90` | `HIGH_CONFIDENCE_SIMILARITY_THRESHOLD` | Threshold for high-confidence matches. |
| `fuzzy_match_threshold` | `float` | `0.85` | `FUZZY_MATCH_THRESHOLD` | RapidFuzz string similarity threshold (0-1). |
| `embedding_similarity_threshold` | `float` | `0.90` | `EMBEDDING_SIMILARITY_THRESHOLD` | Embedding cosine similarity for entity resolution. |

### Embedding Weights

| Setting | Type | Default | Env Var | Description |
|---------|------|---------|---------|-------------|
| `decision_embedding_weight_title` | `float` | `1.5` | `DECISION_EMBEDDING_WEIGHT_TITLE` | Weight multiplier for the title field. |
| `decision_embedding_weight_decision` | `float` | `1.2` | `DECISION_EMBEDDING_WEIGHT_DECISION` | Weight multiplier for the decision field. |
| `decision_embedding_weight_rationale` | `float` | `1.0` | `DECISION_EMBEDDING_WEIGHT_RATIONALE` | Base weight for the rationale field. |
| `decision_embedding_weight_context` | `float` | `0.8` | `DECISION_EMBEDDING_WEIGHT_CONTEXT` | Weight multiplier for the context field. |
| `decision_embedding_weight_trigger` | `float` | `0.8` | `DECISION_EMBEDDING_WEIGHT_TRIGGER` | Weight multiplier for the trigger field. |

### Authentication

| Setting | Type | Default | Env Var | Description |
|---------|------|---------|---------|-------------|
| `secret_key` | `SecretStr` | `""` | `SECRET_KEY` | JWT signing key. **Must match** `NEXTAUTH_SECRET`. |
| `algorithm` | `str` | `"HS256"` | `ALGORITHM` | JWT signing algorithm. |
| `access_token_expire_minutes` | `int` | `30` | `ACCESS_TOKEN_EXPIRE_MINUTES` | JWT token lifetime in minutes. |

### App

| Setting | Type | Default | Env Var | Description |
|---------|------|---------|---------|-------------|
| `debug` | `bool` | `False` | `DEBUG` | Enable debug mode and verbose logging. |
| `cors_origins` | `list[str]` | `["http://localhost:3000"]` | `CORS_ORIGINS` | Allowed CORS origins for the frontend. |

Settings with `SecretStr` type (`neo4j_password`, `nvidia_api_key`, `nvidia_embedding_api_key`, `secret_key`) are automatically masked in log output and `repr()`. Access values through getter methods, e.g., `settings.get_nvidia_api_key()`.

---

## Appendix B: API Reference

Backend REST API at `http://localhost:8000`. Interactive Swagger docs at `/docs`. All endpoints requiring auth expect `Bearer` token in `Authorization` header. Unauthenticated requests fall back to `anonymous` user scope.

### Authentication

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | `/api/users/register` | No | Register a new user account |
| POST | `/api/users/login` | No | Authenticate and receive user data |
| GET | `/api/users/me` | Yes | Get current user profile with stats |
| DELETE | `/api/users/me` | Yes | Delete account and all associated data |

### Decisions

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/api/decisions` | Optional | List decisions (paginated: `limit`, `offset`) |
| POST | `/api/decisions` | Optional | Create a decision with auto entity extraction |
| GET | `/api/decisions/{id}` | Optional | Get a single decision by ID |
| PUT | `/api/decisions/{id}` | Optional | Update decision fields |
| DELETE | `/api/decisions/{id}` | Optional | Delete a decision (preserves entities) |
| GET | `/api/decisions/needs-review` | Optional | Decisions missing human rationale |

### Search

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/api/search` | No | Search decisions and entities |
| GET | `/api/search/suggest` | No | Autocomplete suggestions |

**Query parameters for `/api/search`:**
- `query` -- Search string (min 2 chars, required)
- `type` -- Filter by `decision` or `entity`
- `expand` -- Enable graph expansion on results (`true`/`false`)
- `depth` -- Expansion depth when `expand=true` (1-3, default 1)

### Ask (GraphRAG)

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/api/ask` | Optional | Stream a graph-grounded answer (SSE) |

**Query parameters:**
- `q` -- The question to ask (min 3 chars, required)
- `depth` -- Graph traversal depth (1-3, default 2)
- `top_k` -- Number of seed nodes to retrieve (1-10, default 5)

### Graph

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/api/graph` | Optional | Paginated knowledge graph |
| GET | `/api/graph/all` | Optional | Full graph (use sparingly) |
| GET | `/api/graph/stats` | Optional | Node/edge/relationship counts |
| GET | `/api/graph/nodes/{id}` | Optional | Single node by ID |
| GET | `/api/graph/nodes/{id}/neighbors` | Optional | Neighbors of a node |
| GET | `/api/graph/nodes/{id}/similar` | Optional | Semantically similar decisions |
| GET | `/api/graph/validate` | Optional | Run graph validation checks |
| POST | `/api/graph/search/hybrid` | Optional | Hybrid lexical+semantic search |
| POST | `/api/graph/search/semantic` | Optional | Pure vector similarity search |
| POST | `/api/graph/analyze-relationships` | Optional | Discover supersedes/contradicts edges |
| GET | `/api/graph/relationships/types` | Optional | List all relationship types |
| GET | `/api/graph/sources` | Optional | List decision sources |
| GET | `/api/graph/projects` | Optional | List projects in the graph |
| DELETE | `/api/graph/reset` | Optional | Wipe all graph data (dangerous) |

### Entities

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/api/entities` | Optional | List entities linked to user's decisions |
| POST | `/api/entities` | Optional | Create or deduplicate an entity |
| GET | `/api/entities/{id}` | Optional | Get entity by ID |
| PUT | `/api/entities/{id}` | Optional | Update entity name/type |
| DELETE | `/api/entities/{id}` | Optional | Delete entity (with force option) |
| POST | `/api/entities/link` | Optional | Link entity to a decision |
| POST | `/api/entities/suggest` | Optional | Suggest entities from text |

### Capture

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | `/api/capture/sessions` | Optional | Start a new capture session |
| GET | `/api/capture/sessions/{id}` | Optional | Get session with messages |
| POST | `/api/capture/sessions/{id}/messages` | Optional | Send a message, get AI reply |
| POST | `/api/capture/sessions/{id}/complete` | Optional | Complete session, save decision |
| WS | `/api/capture/sessions/{id}/ws` | No | Real-time streaming capture |

### Agent (MCP)

Structured knowledge graph access for AI coding agents (Claude Code, Cursor, etc.) via Model Context Protocol.

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/api/agent/summary` | Optional | High-level project overview |
| POST | `/api/agent/context` | Optional | Focused context via hybrid search |
| GET | `/api/agent/context/{name}` | Optional | Everything about one entity |
| POST | `/api/agent/check` | Optional | Prior-art check before deciding |
| POST | `/api/agent/remember` | Yes | Record an agent-made decision |

### Projects

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/api/projects` | No | List all projects with counts |
| GET | `/api/projects/{name}/stats` | No | Detailed project statistics |
| DELETE | `/api/projects/{name}` | No | Delete all decisions in a project |
| POST | `/api/projects/{name}/reset` | No | Reset project for re-import |

### Dashboard

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/api/dashboard/stats` | No | Aggregated dashboard statistics |

### Export & Import

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/api/export/export` | Optional | Export decisions as JSON |
| GET | `/api/export/export/download` | Optional | Download decisions as JSON file |
| POST | `/api/export/import` | Optional | Bulk import decisions (max 500) |

### Ingest

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/api/ingest/projects` | No | List Claude log project directories |
| GET | `/api/ingest/files` | No | List JSONL conversation files |
| GET | `/api/ingest/preview` | No | Preview conversations before import |
| GET | `/api/ingest/status` | No | Current ingestion status |
| POST | `/api/ingest/trigger` | No | Start ingestion run |
| POST | `/api/ingest/import-selected` | No | Import selected conversations |
| GET | `/api/ingest/import/progress` | No | Poll import job progress |
| POST | `/api/ingest/import/cancel` | No | Cancel running import job |
| POST | `/api/ingest/watch/start` | No | Start file watcher |
| POST | `/api/ingest/watch/stop` | No | Stop file watcher |

### Health

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/health` | No | Basic liveness check |
| GET | `/health/ready` | No | Readiness probe (checks all DBs) |
| GET | `/health/live` | No | Lightweight liveness probe |
| GET | `/health/circuits` | No | Circuit breaker status dashboard |

### SSE Events for `/api/ask`

Returns `text/event-stream`. Each event has `event:` type line + `data:` JSON payload.

| Event | Payload |
|-------|---------|
| `context` | Retrieved subgraph JSON: `{nodes, edges, seed_ids}`. Each node includes `type` (decision/entity), `is_seed`, and `data` object with properties. |
| `token` | LLM output chunk: `{"text": "..."}`. Concatenate all token events to build full answer. |
| `done` | Stream complete: `{"token_count": N}`. |
| `error` | Error detail: `{"detail": "..."}`. |

### WebSocket Protocol for Capture

Connect to `/api/capture/sessions/{id}/ws` for real-time streaming capture.

**Sequence:**
1. **Connect** -- Client opens WebSocket connection
2. **Send message** -- Client sends JSON: `{"content": "user's answer"}`
3. **Receive chunks** -- Server streams `{"type":"chunk", "content":"...", "entities":[...]}`
4. **Completion** -- Server sends `{"type":"complete"}` when response finished
5. **Repeat** -- Steps 2-4 repeat until session ends

Rate-limited to 20 messages per minute per session. Messages exceeding 10 KB rejected. Server trims conversation history at 50 messages.

### Example curl Commands

```bash
# Register a user
curl -X POST http://localhost:8000/api/users/register \
  -H "Content-Type: application/json" \
  -d '{"name":"Demo","email":"ali@demo.com","password":"demo1234"}'

# Search decisions and entities
curl "http://localhost:8000/api/search?query=postgres&type=entity"

# Ask a question (SSE stream)
curl -N "http://localhost:8000/api/ask?q=Why+did+we+choose+Redis&depth=2&top_k=5" \
  -H "Authorization: Bearer $TOKEN"
```

---

## Appendix C: Glossary

| Term | Definition |
|------|-----------|
| **Ablation study** | Experiment that disables one pipeline stage at a time to measure its individual contribution |
| **B-cubed metrics** | Precision, recall, and F1 computed per mention and averaged, used to evaluate entity-resolution quality |
| **Canonical mapping** | Deterministic lookup table (534 entries) mapping common aliases to canonical entity names, e.g., `postgres` -> `PostgreSQL` |
| **Circuit breaker** | Resilience pattern that trips after repeated failures (default 5), rejecting subsequent calls until a cooldown period elapses |
| **Cypher** | Neo4j's declarative graph query language, analogous to SQL for relational databases |
| **Decision trace** | The atomic unit of knowledge in Continuum: a structured record containing trigger, context, options, decision, rationale, and confidence |
| **Entity resolution** | The 7-stage cascading pipeline that maps raw mention strings to canonical graph entities, preventing duplicates |
| **Fulltext index** | Neo4j index supporting Lucene-style text search across node properties, used as the lexical leg of hybrid search |
| **GraphRAG** | Graph-augmented Retrieval-Augmented Generation: retrieving a relevant subgraph and feeding it as context to an LLM for grounded answers |
| **Hybrid search** | Search strategy fusing lexical (fulltext) and semantic (vector) results using Reciprocal Rank Fusion for higher recall |
| **K-hop expansion** | Traversing the graph k edges out from seed nodes to capture surrounding context for the LLM prompt |
| **Labeled property graph** | Neo4j data model where nodes and edges carry labels, properties, and direction -- the storage foundation of the knowledge graph |
| **MCP (Model Context Protocol)** | Open protocol for AI agents to read and write structured context. Continuum's Agent API implements MCP-compatible endpoints |
| **Multi-tenant** | Architecture pattern where every query is scoped to a `user_id`, ensuring data isolation between accounts |
| **NV-EmbedQA** | NVIDIA's embedding model (`llama-3.2-nv-embedqa-1b-v2`) producing 2048-dimensional vectors for semantic search |
| **Ontology** | Classification schema (530+ canonical mappings) categorizing entities into types such as language, framework, database, concept |
| **RapidFuzz** | Fast C-extension fuzzy string matching library used in stage 5 of entity resolution for partial and token-sort matching |
| **Reciprocal Rank Fusion (RRF)** | Score fusion method combining ranked lists by summing `1/(k + rank)` across systems, used to merge lexical and semantic search results |
| **ResolvedEntity** | Dataclass returned by the entity resolver, carrying canonical name, type, confidence, resolution method, and match metadata |
| **Seed nodes** | Initial set of top-scoring nodes retrieved by hybrid search, from which k-hop expansion builds the context subgraph |
| **Server-Sent Events (SSE)** | Unidirectional streaming protocol over HTTP used by `/api/ask` to deliver LLM tokens incrementally |
| **Subgraph** | Subset of the full knowledge graph -- typically seed nodes plus their k-hop neighbors -- serialized as `{nodes, edges}` JSON |
| **Token bucket** | Rate-limiting algorithm backed by Redis allowing burst traffic up to bucket size, then refilling at a steady rate |
| **User scoping** | Practice of adding `WHERE d.user_id = $user_id` to every Cypher query so each user sees only their own data |
| **Vector search** | Retrieving nodes by embedding cosine similarity, the semantic leg of hybrid search |
| **WebSocket** | Full-duplex communication protocol used by the capture session endpoint for real-time interview streaming |

---

## Appendix D: Troubleshooting

| # | Symptom | Cause | Fix |
|---|---------|-------|-----|
| 1 | Auth silently fails; every request resolves to "anonymous" | `NEXTAUTH_SECRET` does not match `SECRET_KEY`. NextAuth signs JWTs with its secret; backend verifies with `SECRET_KEY`. | Set both to the same value, then restart frontend and backend. |
| 2 | Alembic `DuplicateTableError` on startup | Database tables exist but `alembic_version` table is missing or empty. | Run `alembic stamp head` to mark current schema version without re-running migrations. |
| 3 | Neo4j fulltext search returns zero results | `decision_fulltext` or `entity_fulltext` index was not created during initialization. | Check `db/neo4j.py` for index creation logic. Restart backend or manually create index via Neo4j Browser. |
| 4 | Decision extraction returns 0 decisions from valid conversations | NVIDIA API key is invalid or `max_tokens` is too low (thinking tags consume tokens). | Verify `NVIDIA_API_KEY` is set and valid. Use `max_tokens=4096` or higher. |
| 5 | All data disappeared after restarting Docker | Ran `docker-compose down -v`, which removes named volumes containing all data. | Use `docker-compose down` **without** the `-v` flag to preserve volumes. |
| 6 | Backend ignores code changes despite `--reload` | Stale `__pycache__` directories cause uvicorn to serve old bytecode. | Run: `find apps/api -name "__pycache__" -type d -exec rm -rf {} +` then restart backend. |
| 7 | Embedding service returns `None` for all texts | Circuit breaker tripped after 5 consecutive failures to NVIDIA embedding API. | Check `NVIDIA_EMBEDDING_API_KEY` is valid. Restart backend to reset circuit breaker. Inspect `/health/circuits`. |
| 8 | Rate-limited on NVIDIA NIM API (HTTP 429) | Free tier allows only 40 requests per minute. | Wait for rate window to reset, or upgrade to paid plan. For bulk operations, reduce `embedding_batch_size`. |
| 9 | React Flow graph does not render (blank canvas) | `useNodesState`/`useEdgesState` hooks declared after `useCallback` that references their setters. | Move all `useNodesState`/`useEdgesState` declarations **before** any `useCallback` definitions. |
| 10 | CSS colors appear wrong in light mode; dark mode looks fine | Bare `:root` selectors apply in both light and dark mode, overriding dark-mode tokens. | Use `:root:not(.dark)` for light-mode-only CSS custom properties. |
| 11 | Radix `ScrollArea` refuses to auto-scroll to the bottom | Radix root element sets `overflow:hidden`, preventing programmatic scroll. | Replace `ScrollArea` with plain `<div>` with `overflow-y: auto`. |
| 12 | Tooltip text is truncated in the UI | Default `max-width` on Radix Tooltip content is too small. | Add `max-w-lg` Tailwind class to `TooltipContent` component. |
| 13 | LLM response JSON is truncated or malformed | Model's `<think>...</think>` tags consume output tokens, leaving insufficient room for JSON payload. | Set `max_tokens=4096` or higher. Implement JSON repair logic finding last complete `}` + `]` pair. |
| 14 | Prompt sanitizer blocks evaluation conversations | Input sanitizer flags `USER:` / `ASSISTANT:` labels in synthetic conversations as prompt injection. | Pass `sanitize_input=False` when calling LLM on evaluation or synthetic data. |
| 15 | Multiple extraction runs show inflated decision counts | Old decisions accumulate in Neo4j because pipeline appends rather than replaces. | Wipe Neo4j database before each new evaluation run using `/api/graph/reset` or Neo4j Browser. |
