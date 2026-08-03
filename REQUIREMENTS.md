# REQUIREMENTS

## Packaging architecture

The artifact is distributed as **plain source** (no container or VM image), archived as a source tarball on
Zenodo. It is architecture-independent Python and TypeScript with no compiled or platform-specific binaries.

- **Developed and tested on:** macOS 15 (Darwin, arm64 / Apple Silicon)
- **Also expected to run on:** x86-64 Linux and x86-64 macOS. All runtime dependencies (Python wheels, Node
  packages, and the Docker images below) publish both `linux/amd64` and `linux/arm64` variants.
- **Not tested on:** Windows (native). Windows users should use WSL2.

## Verifying the reported results (no external services required)

The cached result files backing every number in the paper are committed under
`apps/api/evaluation/data/v5/`. Inspecting them requires **only a text editor or `python3 -m json.tool`** — no
API keys, no database, no network access. `README.md` § "Reproducing the paper's results" maps each research
question and each headline number to its source file.

**Requirements for verification only:** any machine, any OS, ~50 MB disk.

## Re-executing the pipeline end to end

Re-running the pipeline (as opposed to verifying the cached numbers) has heavier requirements.

### Hardware

- **CPU:** any modern x86-64 or arm64 processor; no GPU required (all model inference is remote)
- **RAM:** 8 GB minimum, 16 GB recommended (three database containers plus the API and web dev servers)
- **Disk:** ~5 GB (source, Python virtualenv, `node_modules`, and Docker volumes)
- **Network:** required — LLM extraction and embeddings call a remote API

### Software

| Component | Version | Purpose |
|---|---|---|
| Docker Desktop | 4.x+ | runs the three datastores |
| PostgreSQL | 18 (via Docker) | user accounts, metadata |
| Neo4j | 2025.01 (via Docker) | knowledge graph |
| Redis | 7.4 (via Docker) | caching, rate limiting |
| Python | 3.12+ | backend and all evaluation scripts |
| Node.js | 24 LTS | frontend |
| pnpm | 9+ | JavaScript package manager |

### Third-party service credentials

Live extraction and embedding-based entity resolution require an **NVIDIA NIM API** account
(<https://build.nvidia.com/>), which offers a free tier. Two separate keys are read from the environment:

- `NVIDIA_API_KEY` — LLM inference (`nvidia/llama-3.3-nemotron-super-49b-v1.5`)
- `NVIDIA_EMBEDDING_API_KEY` — embeddings (`nvidia/llama-3.2-nv-embedqa-1b-v2`)

These are **not** needed to verify the cached results.

### Expected runtimes

| Task | Approximate time |
|---|---|
| Inspect cached result files | seconds |
| Infrastructure startup (`docker-compose up -d`) | 1–2 minutes |
| Dependency install (`pnpm install` + `pip install -e`) | 5–10 minutes |
| Entity-resolution evaluation + ablation | ~5 minutes |
| Full 200-conversation LLM extraction | ~100 minutes (rate-limited to 40 requests/minute on the free tier) |
| Vibe Voyager case-study extraction (77 chunks) | ~35 minutes |

## Known constraints on exact reproduction

LLM extraction is **non-deterministic**: two runs over the same 200 conversations produced 1.82 and 1.92
decisions per conversation respectively (a 5.2% aggregate difference), which the paper reports in Section 3.
Re-execution should therefore be expected to land close to, but not exactly on, the published extraction
numbers. The entity-resolution, B-cubed, agreement, and retrieval figures are deterministic given a fixed
graph state.
