# Contributing

This repository is the replication package for an ASE 2026 Industry Showcase paper. The paper has been accepted at the ASE 2026 Industry Showcase; bug reports and replication-quality issues are welcome.

## Running the system locally

See `README.md` for setup. The TL;DR:

```bash
docker-compose up -d
pnpm install && cd apps/api && python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
pnpm dev
```

## Project conventions (for issue triage and PRs)

### Backend (Python, FastAPI)

- All database operations are async (`async def`, `await`, async SQLAlchemy)
- Pydantic v2 for request/response validation; `model_config = ConfigDict(strict=True)` on schemas
- Neo4j queries always use `parameters={...}` dict — never `query=` kwarg, which clashes with the positional Cypher string argument
- LLM calls go through `services.llm.get_llm_client()`; default provider is NVIDIA NIM with Bedrock fallback
- Always pass `sanitize_input=False` when calling the LLM on synthetic conversations; the prompt sanitizer flags `USER:`/`ASSISTANT:` labels as injection

### Frontend (Next.js 16, React 19)

- App Router (`app/` directory), Server Components by default; `'use client'` only for interactivity
- TailwindCSS v4 with semantic tokens; never hardcode colors, always use `bg-primary`, `text-foreground`, etc.
- `cn()` from `lib/utils` for className composition — no string concatenation
- `lucide-react` for icons exclusively
- `@xyflow/react` for graph visualizations; `recharts` for stats; `framer-motion` (or its successor `motion`) for animation

### Evaluation scripts

- All scripts live under `apps/api/evaluation/`
- Run from `apps/api/` with the venv active (`.venv/bin/python -m evaluation.<script>`)
- Wipe Neo4j before any extraction run (`docker-compose down && docker-compose up -d`) to avoid accumulating decisions across runs
- True extraction yield is ~1.8–2.0 decisions/conversation; numbers above this likely indicate accumulated runs

### Privacy and scrubbing

The `vibe_chunks/` dataset was produced by `evaluation/vibe_chunker.py`, which scrubs absolute paths, personal-domain subdomains, secret tokens, and external file content from real Claude Code logs. If you want to apply the same scrubber to your own logs, the relevant function is `vibe_chunker.scrub()`. The `_NAME_RE` blocklist accepts additional private-project names if you fork the script.

## Reporting issues

If you find a discrepancy between a number in the paper and a number you compute by running an evaluation script, please open an issue with:

- The metric name (e.g., "RQ3 entity resolution accuracy")
- The paper's claim
- The number you got
- The script you ran and any environment details

We aim to respond within 5 business days.
