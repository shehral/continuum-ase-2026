# Continuum — Replication Package

**ASE 2026 Industry Showcase**
*Continuum: Automated Construction and Retrieval of Software Decision Knowledge Graphs from Developer-AI Conversations*

Mohammad Ali Shehral · Karthik Ravi · Nikhil Trivedi · Akram Bayat
Khoury College of Computer Sciences, Northeastern University, San Jose

---

## What is this?

This repository is the replication package for the paper above. It contains:

- The full source code for the **Continuum** system (FastAPI backend, Next.js frontend, MCP server, polyglot persistence)
- The synthetic conversation dataset used for entity-resolution and decision-extraction evaluation (200 generated developer-AI conversations across 9 technical domains)
- The evaluation scripts that produce every number reported in the paper
- The two-annotator inter-annotator agreement data (Karthik Ravi and Nikhil Trivedi as annotators A and B respectively)
- The 77 scrubbed conversation chunks from the **Vibe Voyager** real-log case study, plus the 379 extracted decision traces

The paper PDF and a 30-second demo video link are in the paper's archived snapshot on Zenodo (DOI to be added at camera-ready).

## Repository layout

```
apps/
  api/                      FastAPI backend (Python 3.12, async)
    evaluation/             All evaluation scripts and data
      data/
        synthetic_conversations/   200 generated dev-AI conversations
        v5/
          synthetic_conversations/ Same 200, run-2 snapshot
          vibe_chunks/             77 scrubbed real-log chunks
          vibe_extraction_results.json
          annotator_a/             Karthik's annotation labels
          annotator_b/             Nikhil's annotation labels
          agreement_results.json   Cohen's kappa + merged precision
          *_results.json           Per-RQ result files
  web/                      Next.js 16 frontend (App Router, React 19)
  mcp/                      Model Context Protocol server (5 tools)
infra/                      Grafana dashboards + Prometheus config
k8s/                        Kubernetes overlays
docker-compose.yml          Local dev infra (PostgreSQL, Neo4j, Redis)
```

## Setup

### Prerequisites

- Docker Desktop 4.x+
- Node.js 24 LTS
- pnpm 9+
- Python 3.12+
- (Optional, for full LLM features) NVIDIA NIM API account at <https://build.nvidia.com/>

### 1. Install dependencies

```bash
pnpm install
cd apps/api
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
cd ../..
```

### 2. Configure environment

```bash
cp apps/api/.env.example apps/api/.env
cp apps/web/.env.example apps/web/.env.local
```

Edit each file. The two critical settings:

- `NVIDIA_API_KEY` and `NVIDIA_EMBEDDING_API_KEY` (from build.nvidia.com — both required for live extraction; not required to inspect the cached `*_results.json` files)
- `SECRET_KEY` (in api/.env) and `NEXTAUTH_SECRET` (in web/.env.local) **must be identical** — the frontend signs JWTs with this and the backend verifies. Generate with:
  ```bash
  python3 -c "import secrets; print(secrets.token_urlsafe(32))"
  ```

### 3. Start infrastructure + apps

```bash
docker-compose up -d   # PostgreSQL on 5432, Neo4j on 7474/7687, Redis on 6379
pnpm db:migrate        # run Alembic migrations
pnpm dev               # frontend on 3000, backend on 8000
```

## Reproducing the paper's results

All evaluation scripts run from `apps/api/` with the venv active. Cached result JSONs are committed under `apps/api/evaluation/data/v5/` so reviewers can verify numbers without burning LLM API calls.

| RQ | What it measures | Script | Output file |
|---|---|---|---|
| RQ1 | Decision extraction yield | `evaluation/run_end_to_end.py` | `data/v5/e2e_run2_results.json` |
| RQ2 | Decision extraction precision (two-reviewer) | `evaluation/compute_agreement.py` | `data/v5/agreement_results.json` |
| RQ3 | Entity resolution accuracy + ablation | `evaluation/run_full_pipeline.py`, `evaluation/run_full_ablation.py` | `data/v5/{train_test,ablation,bcubed,significance}_results.json` |
| RQ3 | Baselines (SBERT, SpaCy NER, fuzzy, exact) | `evaluation/{sbert,spacy}_baseline.py` | `data/v5/{sbert,spacy}_baseline_results.json` |
| RQ4 | Knowledge graph topology | `evaluation/run_full_pipeline.py` | `data/v5/graph_topology_run2.json` |
| RQ5 | GraphRAG retrieval | `evaluation/test_graphrag.py`, `evaluation/judge_graphrag.py` | `data/v5/graphrag_run2_results.json` |
| RQ6 | MCP tool integration | `evaluation/test_mcp.py` | `data/v5/mcp_eval_results.json` |
| Real-log case study | Vibe Voyager extraction | `evaluation/run_vibe_extraction.py` | `data/v5/vibe_extraction_results.json` |

Headline numbers (cross-check against paper Section 4):

| Metric | Paper claim | Source file |
|---|---|---|
| Entity resolution accuracy | 97.2% (95% CI [96.2, 98.3]) | `train_test_results.json` |
| B-cubed F1 | 0.979 | `bcubed_results.json` |
| Inter-annotator κ (entities) | 0.76 | `agreement_results.json` |
| Inter-annotator κ (decisions) | 0.07 | `agreement_results.json` |
| Decision extraction precision | 75.0%–97.3% | `agreement_results.json` |
| GraphRAG hybrid recall | 100% | `graphrag_run2_results.json` |
| Vibe case study | 379 decisions, 290 entities, 65% agent / 35% human | `vibe_extraction_results.json` |

## Datasets

### Synthetic corpus (200 conversations)

Generated with `evaluation/generate_conversations.py` using template-based prompts across 9 technical domains. AI-assisted generation; see Section 4 *Threats to Validity* in the paper.

### Vibe Voyager real-log chunks (77)

Conversation transcripts from the public **Vibe Voyager** project build (<https://github.com/shehral/vibe>), segmented into 77 decision-bearing chunks and aggressively scrubbed for personal identifiers, secret tokens, external project references, and personal-domain subdomains. The scrubbing logic is in `apps/api/evaluation/vibe_chunker.py` — every line of every chunk passes through it. Verified leak-free.

### Annotator data (annotator_a, annotator_b)

Released with the explicit consent of both annotators (the paper's second and third authors). `annotator_a` is Karthik Ravi; `annotator_b` is Nikhil Trivedi. Each directory contains 233 entity annotations, 25 decision reviews, and 5 GraphRAG relevance ratings, with a deliberate 30-mention and 10-decision overlap for inter-annotator agreement.

### Canonical mapping dictionary (534 entries)

`apps/api/models/ontology.py` — the curated technology-name mapping that drives Stage 3 of the entity resolver. Source-of-truth for what reviewers should expect the resolver to canonicalize correctly.

## Citing this work

```bibtex
@inproceedings{shehral2026continuum,
  title     = {Continuum: Automated Construction and Retrieval of Software Decision Knowledge Graphs from Developer-AI Conversations},
  author    = {Shehral, Mohammad Ali and Ravi, Karthik and Trivedi, Nikhil and Bayat, Akram},
  booktitle = {Proceedings of the 41st IEEE/ACM International Conference on Automated Software Engineering (ASE) -- Industry Showcase},
  year      = {2026},
  address   = {Munich, Germany},
  note      = {Replication package: https://github.com/shehral/continuum-ase-2026},
}
```

## License

[MIT](./LICENSE) — free to use, modify, and distribute with attribution.

## Contact

- **Mohammad Ali Shehral** — shehral.m@northeastern.edu (corresponding author)
- Open an issue at <https://github.com/shehral/continuum-ase-2026/issues> for replication questions.

## Acknowledgements

Synthetic conversations were generated programmatically with AI assistance. The evaluation infrastructure, paper polishing, and portions of the system implementation were co-developed with AI coding assistants (Claude Code, Cursor); the *Vibe Voyager* case study is itself an instance of such co-development, intentionally chosen for its visibility-on-AI-decision-making properties. All research decisions, claims, and final text are the authors' responsibility, disclosed in line with ACM policy on generative AI.
