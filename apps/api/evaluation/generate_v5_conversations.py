#!/usr/bin/env python3
"""Generate 150 additional synthetic conversations (conv-051 through conv-200).

Template-based generation with diverse domains, entities, and surface forms.
"""

import json
import random
from pathlib import Path

OUTPUT_DIR = Path(__file__).resolve().parent / "data" / "synthetic_conversations"

# ── Topic templates ──────────────────────────────────────────────────
# Each template: (domain, topic, entities, messages)
# Messages are (role, content) tuples

TOPICS = [
    # ── Web Development ──
    ("web-development", "Choosing between Astro and Gatsby for a documentation site",
     ["Astro", "Gatsby", "React", "Vite", "MDX", "Markdown"],
     [("user", "I need to build a documentation site for our open source project. Should I use Astro or Gatsby? We already use React elsewhere."),
      ("assistant", "For a documentation site, **Astro** is the stronger choice in 2026:\n\n- **Astro**: Zero JS by default, island architecture, supports React/Vue/Svelte components. Purpose-built for content sites. MDX support is excellent.\n- **Gatsby**: Still works but has lost momentum. GraphQL data layer adds complexity. Build times can be slow for large sites.\n\nAstro with the Starlight documentation theme gives you a polished docs site out of the box. You can still use your React components via islands."),
      ("user", "What about Vite? Can I just use vite with some markdown plugin?"),
      ("assistant", "Vite alone is a build tool, not a framework. You'd need VitePress (Vue-based) or combine Vite with a meta-framework. Astro actually uses Vite under the hood for its build pipeline.\n\nIf your team is Vue-focused, VitePress is excellent for docs. But since you mentioned React, Astro + Starlight is the best fit. It uses Vite internally and lets you drop in React components where needed."),
      ("user", "ok going with astro. Does it support MDX well?"),
      ("assistant", "Yes, Astro has first-class MDX support via `@astrojs/mdx`. You can import React components directly into .mdx files, use Astro's content collections for type-safe frontmatter, and leverage the Starlight theme which handles navigation, search, and i18n out of the box.")]),

    ("web-development", "CSS-in-JS vs Tailwind for a design system",
     ["Tailwind CSS", "styled-components", "Emotion", "CSS Modules", "Panda CSS", "Vanilla Extract"],
     [("user", "Building a design system for our company. We need to choose between CSS-in-JS (styled-components or Emotion) and utility-first (Tailwind). Team is split."),
      ("assistant", "The landscape has shifted significantly. Here's the 2026 view:\n\n**Tailwind CSS**: Dominant utility-first framework. Great for rapid development, consistent spacing/colors. tailwindcss v4 is much faster.\n\n**styled-components / Emotion**: Runtime CSS-in-JS has performance overhead with React Server Components. Both are moving toward zero-runtime solutions.\n\n**Modern alternatives**:\n- **Panda CSS** - Zero-runtime CSS-in-JS with utility patterns\n- **Vanilla Extract** - Type-safe, zero-runtime CSS\n- **CSS Modules** - Simple, no runtime, works everywhere\n\nFor a design system specifically, I'd recommend **Panda CSS** or **Vanilla Extract** - you get type safety and zero runtime cost."),
      ("user", "what about just using tailwind with CVA for variants? thats what shadcn does right"),
      ("assistant", "Exactly right. shadcn/ui uses Tailwind + CVA (Class Variance Authority) for component variants, and it's become the de facto standard for React component libraries.\n\nThe pattern is:\n- Tailwind for utility classes\n- CVA for component variant logic\n- `cn()` (clsx + tailwind-merge) for className composition\n\nThis is probably the most pragmatic choice. Your team gets Tailwind's ecosystem, shadcn's component patterns, and CVA's clean variant API. No runtime CSS-in-JS overhead."),
      ("user", "Does this work well with React Server Components?"),
      ("assistant", "Yes, perfectly. Tailwind + CVA is entirely CSS-class-based - no JavaScript runtime for styling. It works identically in Server Components and Client Components. That's one of the key advantages over styled-components and Emotion, which require a client-side runtime.")]),

    ("web-development", "Next.js vs Remix vs SvelteKit for a SaaS dashboard",
     ["Next.js", "Remix", "SvelteKit", "Svelte", "React", "TypeScript", "Vercel", "Prisma"],
     [("user", "Starting a new SaaS product. Need a full-stack framework for the dashboard. Considering Next.js, Remix, or SvelteKit. Team knows React well."),
      ("assistant", "Given your team's React experience, here's my assessment:\n\n**Next.js 16** (App Router):\n- Largest ecosystem, most hiring candidates\n- Server Components, streaming, ISR\n- Vercel deployment is seamless\n- Can be complex (many rendering strategies)\n\n**Remix** (now React Router v7):\n- Excellent form handling and progressive enhancement\n- Simpler mental model than Next.js\n- Great for data-heavy dashboards\n- Smaller ecosystem\n\n**SvelteKit**:\n- Best DX and performance\n- Svelte 5 with runes is excellent\n- Smaller talent pool\n- Requires learning Svelte\n\nFor a SaaS dashboard with a React-experienced team, **Next.js** is the safe choice. If you're okay with a learning curve, SvelteKit would give you better performance."),
      ("user", "We're using Prisma for the database layer. Does that work equally well with all three?"),
      ("assistant", "Prisma works well with all three, but there are nuances:\n\n- **Next.js**: Prisma has official examples and guides. Works in Server Components and API routes. Watch out for connection pooling in serverless.\n- **Remix**: Works great in loaders/actions. Less official documentation but straightforward.\n- **SvelteKit**: Works in `+server.ts` and `+page.server.ts` load functions. Full TypeScript support.\n\nThe main concern with Prisma is serverless connection limits. Use Prisma Accelerate or PgBouncer for connection pooling if deploying to Vercel or similar platforms."),
      ("user", "going with nextjs + prisma. What about auth?"),
      ("assistant", "For Next.js + Prisma, the standard stack is **Auth.js** (formerly NextAuth). It has a Prisma adapter that auto-manages user/session tables. Supports OAuth providers, email/password, and magic links.\n\nAlternatives:\n- **Clerk**: Managed auth with great DX. More expensive but less code.\n- **Lucia**: Lightweight, self-hosted. Good if you want full control.\n- **Supabase Auth**: If you're using Supabase as your database.\n\nAuth.js v5 + Prisma adapter is the most common choice for self-hosted Next.js SaaS apps.")]),

    ("web-development", "State management in a large React application",
     ["React", "Zustand", "Jotai", "TanStack Query", "Redux Toolkit", "Recoil", "Valtio"],
     [("user", "Our React app has grown to 200+ components. Currently using Redux Toolkit but the boilerplate is killing productivity. What are the modern alternatives?"),
      ("assistant", "Redux Toolkit is already modern Redux, but there are lighter alternatives:\n\n**Zustand** (~2KB): Simple, hook-based, no providers. Most popular Redux alternative.\n**Jotai** (~3KB): Atomic state model. Great for derived state.\n**Valtio**: Proxy-based, mutable-style API. Feels like plain objects.\n**Recoil**: Facebook's atomic state. Development has stalled.\n\n**Key insight**: Most of your state is probably server state (API data). Use **TanStack Query** (React Query) for that - it handles caching, refetching, and invalidation automatically.\n\nPattern: TanStack Query for server state + Zustand for client state (UI, modals, filters)."),
      ("user", "We tried react query before but ran into issues with cache invalidation. Any tips?"),
      ("assistant", "Cache invalidation with TanStack Query is about using the right patterns:\n\n1. **Query keys**: Use structured keys like `['users', userId]` so you can invalidate precisely.\n2. **Mutations with `onSuccess`**: Invalidate related queries after mutations.\n3. **Optimistic updates**: Update the cache immediately, then sync with the server.\n4. **`staleTime`**: Set appropriate stale times per query type.\n\nThe most common mistake is making everything stale immediately (default). Set `staleTime: 5 * 60 * 1000` (5 min) for data that doesn't change often.\n\nFor your 200+ component app, I'd migrate incrementally: start with TanStack Query for data fetching, then replace Redux slices with Zustand stores one at a time."),
      ("user", "does zustand work well with typescript? we're fully typed"),
      ("assistant", "Zustand has excellent TypeScript support. It's written in TypeScript natively:\n\n```typescript\ninterface BearStore {\n  bears: number;\n  increase: () => void;\n}\n\nconst useBearStore = create<BearStore>()((set) => ({\n  bears: 0,\n  increase: () => set((state) => ({ bears: state.bears + 1 })),\n}));\n```\n\nType inference works automatically with `create<T>()`. Middlewares like `persist` and `devtools` also preserve types. It's one of the best-typed state management libraries in the React ecosystem.")]),

    # ── Backend Engineering ──
    ("backend", "Choosing between FastAPI and Express for a REST API",
     ["FastAPI", "Express.js", "Node.js", "Python", "TypeScript", "Pydantic", "OpenAPI"],
     [("user", "Building a REST API for our mobile app. Team is split between FastAPI (Python) and Express (Node.js). We need good performance and automatic API docs."),
      ("assistant", "Both are excellent choices. Key differences:\n\n**FastAPI (Python)**:\n- Automatic OpenAPI/Swagger docs\n- Pydantic validation - type-safe request/response\n- Async by default (ASGI)\n- Python ecosystem (ML, data science libraries)\n- Excellent for data-heavy APIs\n\n**Express.js (Node.js)**:\n- Huge ecosystem, most npm packages\n- TypeScript support (with setup)\n- Single language with frontend (if using React/Next.js)\n- Better for real-time (WebSocket native)\n- More manual for validation and docs\n\nIf you want automatic docs and validation out of the box, **FastAPI** wins. If you want JavaScript everywhere and the npm ecosystem, go Express (or better yet, **Fastify** which is faster)."),
      ("user", "Performance is important. We expect 10k RPM. How do they compare?"),
      ("assistant", "At 10k RPM both handle it easily. Benchmarks:\n\n- **FastAPI**: ~15,000 req/s on simple JSON endpoints (uvicorn + uvloop)\n- **Express**: ~12,000 req/s (Node.js single thread)\n- **Fastify**: ~30,000 req/s (fastest Node.js framework)\n\nFor your scale, the bottleneck will be database queries and business logic, not framework overhead. Choose based on developer productivity and ecosystem fit.\n\nIf you go FastAPI, use `uvicorn` with `--workers` for multi-process deployment. If Express, use `pm2` or Node.js cluster mode."),
      ("user", "We have some ML models to serve too. That tips it toward python right?"),
      ("assistant", "Absolutely. If you're serving ML models, Python is the clear winner:\n\n- Direct access to PyTorch, TensorFlow, scikit-learn\n- FastAPI + Pydantic for model input validation\n- Easy integration with NVIDIA Triton or TensorFlow Serving\n- Background tasks for async inference\n- NumPy/Pandas for data preprocessing in the same service\n\nWith Express, you'd need to either call Python services over HTTP (adding latency) or use ONNX runtime (limited model support).\n\nGo with **FastAPI + Pydantic + uvicorn**. Add Redis for caching model predictions and you'll have a solid stack.")]),

    ("backend", "Message queue selection: Kafka vs RabbitMQ vs Redis Streams",
     ["Apache Kafka", "RabbitMQ", "Redis", "Redis Streams", "NATS", "Pulsar"],
     [("user", "We need a message queue for our microservices. Processing about 50k events/day. Considering Kafka, RabbitMQ, or just using Redis Streams since we already have Redis running."),
      ("assistant", "At 50k events/day (~35/min), you're well within the capabilities of all three. The choice depends on your requirements:\n\n**Redis Streams**:\n- Already running, zero new infrastructure\n- Good for moderate throughput\n- Consumer groups for load balancing\n- Data persistence with AOF\n- Simple to operate\n\n**RabbitMQ**:\n- Purpose-built message broker\n- Advanced routing (exchanges, bindings)\n- Priority queues, dead letter queues\n- AMQP protocol, mature ecosystem\n\n**Apache Kafka**:\n- Overkill for 50k/day but scales to millions\n- Event log (not just queue) - replay capability\n- Stream processing with Kafka Streams\n- Complex to operate (ZooKeeper/KRaft)\n\nAt your scale, **Redis Streams** is the pragmatic choice. You avoid new infrastructure and get reliable message delivery with consumer groups."),
      ("user", "What if we grow to 1M events/day? Will redis streams still work?"),
      ("assistant", "At 1M events/day (~700/min), Redis Streams still works but you're entering the zone where a dedicated broker adds value:\n\n- Redis Streams: Works but competes with your cache workload for Redis resources\n- RabbitMQ: Handles it easily with proper configuration\n- Kafka: Still overkill unless you need event replay or stream processing\n\nMy recommendation: Start with Redis Streams now. If you hit 500K+ events/day and need advanced features (dead letter queues, priority routing), migrate to **RabbitMQ**. Only move to Kafka if you need event sourcing or real-time stream processing.\n\nAlso consider **NATS** - it's lightweight, fast, and much simpler to operate than Kafka. NATS JetStream adds persistence and exactly-once delivery.")]),

    ("backend", "Database selection: PostgreSQL vs MongoDB for a multi-tenant SaaS",
     ["PostgreSQL", "MongoDB", "DynamoDB", "CockroachDB", "SQLAlchemy", "Prisma", "Drizzle"],
     [("user", "Building a multi-tenant SaaS platform. Data is mostly structured (users, orgs, projects, tasks) but we also have unstructured data (notes, comments with rich text). PostgreSQL or MongoDB?"),
      ("assistant", "For your use case, **PostgreSQL** is the clear winner:\n\n1. **Structured data**: Relational model is perfect for users/orgs/projects/tasks\n2. **Unstructured data**: PostgreSQL's JSONB type handles rich text and flexible schemas\n3. **Multi-tenancy**: Row-level security (RLS) provides tenant isolation at the DB level\n4. **Transactions**: ACID transactions across multiple tables\n5. **Full-text search**: Built-in `tsvector` for searching notes/comments\n\nMongoDB would work for the unstructured parts but you'd miss:\n- JOIN operations for relational queries\n- Transaction support (multi-document transactions exist but are slower)\n- Row-level security for multi-tenancy\n\nPostgreSQL with JSONB gives you the best of both worlds."),
      ("user", "What ORM should we use? We're in Node.js/TypeScript"),
      ("assistant", "For Node.js + TypeScript + PostgreSQL, your top options:\n\n**Prisma**: Most popular, best DX, auto-generated types from schema. Great for rapid development. Downside: generated SQL can be suboptimal for complex queries.\n\n**Drizzle ORM**: Type-safe, SQL-like API. Closer to raw SQL, better performance. Growing fast.\n\n**Knex.js**: Query builder, not full ORM. Maximum control but less type safety.\n\nFor a SaaS with complex relational data, I'd recommend **Drizzle** - it gives you type safety without the SQL abstraction overhead of Prisma. You write SQL-like queries that are fully typed and produce predictable SQL.\n\nIf developer velocity matters more than query optimization, go Prisma."),
      ("user", "We also need to handle file uploads and attachments. S3 right?"),
      ("assistant", "Yes, **S3** (or S3-compatible storage) for file uploads. Never store files in the database. Architecture:\n\n1. Client requests a presigned upload URL from your API\n2. Client uploads directly to S3 (no load on your server)\n3. S3 triggers a webhook or your API polls for completion\n4. Store file metadata (S3 key, size, type) in PostgreSQL\n\nAlternatives to AWS S3:\n- **Cloudflare R2**: S3-compatible, no egress fees\n- **MinIO**: Self-hosted S3-compatible\n- **Supabase Storage**: If using Supabase\n\nCloudflare R2 is increasingly popular due to zero egress costs. If you're on AWS already, stick with S3.")]),

    ("backend", "API authentication: JWT vs Session-based vs API Keys",
     ["JWT", "OAuth 2.0", "OpenID Connect", "Auth0", "Clerk", "Passport.js", "Redis"],
     [("user", "Designing auth for our API. It serves both a web frontend and mobile apps. JWT, sessions, or API keys?"),
      ("assistant", "You'll likely need a combination:\n\n**Web frontend**: Session-based auth (httpOnly cookies)\n- Most secure for browser-based apps\n- CSRF protection needed but no token storage in JS\n- Server-side session store (Redis)\n\n**Mobile apps**: JWT (Bearer tokens)\n- Stateless, works offline\n- Refresh token rotation for security\n- Store in secure keychain\n\n**Third-party integrations**: API keys\n- Simple, long-lived tokens\n- Rate limiting per key\n- Scoped permissions\n\nFor OAuth2 / OpenID Connect flows, use a provider like **Auth0** or **Clerk** rather than implementing from scratch. If self-hosting, **Keycloak** is the gold standard."),
      ("user", "can we just use JWT for everything? sessions seem like extra complexity"),
      ("assistant", "You can, but there are tradeoffs:\n\n**JWT-only downsides**:\n- Can't revoke tokens (until expiry) without a blocklist\n- Token size grows with claims (sent on every request)\n- XSS vulnerability if stored in localStorage\n- Refresh token management adds complexity\n\n**Why sessions for web**:\n- Instant revocation (delete session from Redis)\n- Small cookie size\n- httpOnly flag prevents JavaScript access\n- No token refresh dance\n\nIf you go JWT-only, use short-lived access tokens (15 min) + refresh tokens stored in httpOnly cookies. This gives you the statelessness of JWT with better security than localStorage.\n\nRedis session store costs almost nothing and gives you instant session revocation. It's worth the small complexity."),
      ("user", "What about Passport.js? We're using Express"),
      ("assistant", "Passport.js is the standard auth middleware for Express, but it's showing its age:\n\n**Passport.js pros**:\n- 500+ strategies (Google, GitHub, SAML, etc.)\n- Mature, well-documented\n- Express integration is seamless\n\n**Passport.js cons**:\n- Callback-based API (not async/await native)\n- Session handling is implicit and confusing\n- Strategy ecosystem is fragmented\n\n**Modern alternatives**:\n- **Auth.js** (formerly NextAuth): Works with Express via the `@auth/express` adapter\n- **Lucia**: Lightweight, TypeScript-first\n- **Arctic**: Minimal OAuth 2.0 client library\n\nIf you need lots of OAuth providers quickly, Passport.js still works. For a cleaner TypeScript experience, consider Lucia for self-hosted auth.")]),

    # ── DevOps / Infrastructure ──
    ("devops", "Container orchestration: Kubernetes vs Docker Compose vs ECS",
     ["Kubernetes", "Docker", "Docker Compose", "AWS ECS", "AWS Fargate", "Helm", "ArgoCD"],
     [("user", "Deploying a microservices app with 5 services. Currently using Docker Compose locally. What should we use in production? K8s seems overkill but compose isn't production-ready."),
      ("assistant", "For 5 services, you're in the sweet spot where several options work:\n\n**Docker Compose on a single VM**:\n- Works for small-scale production\n- Use `docker compose up -d` with restart policies\n- No orchestration overhead\n- Manual scaling\n\n**AWS ECS / Fargate**:\n- Managed container orchestration\n- No cluster management (Fargate)\n- Auto-scaling built in\n- AWS-native (IAM, VPC, ALB integration)\n- Much simpler than K8s\n\n**Kubernetes**:\n- Overkill for 5 services unless you're planning to grow significantly\n- Complex to operate (even managed EKS/GKE)\n- Best if you need multi-cloud or on-prem\n\nFor 5 services: **ECS + Fargate** if on AWS. **Cloud Run** if on GCP. Only go K8s if you expect 20+ services or need on-prem."),
      ("user", "We're on AWS. ECS Fargate pricing is okay?"),
      ("assistant", "ECS Fargate pricing is per-vCPU-hour and per-GB-hour. For 5 services:\n\n- Each service: 0.5 vCPU, 1GB RAM ≈ $15/month\n- Total: ~$75/month for all 5 services\n- Plus ALB: ~$25/month\n- **Total: ~$100/month**\n\nCompare to:\n- EC2 instances running Docker: ~$50/month (t3.medium) but you manage the instance\n- EKS: $73/month just for the control plane + worker nodes\n\nFargate eliminates instance management. For 5 services, the premium over raw EC2 is worth the operational simplicity.\n\nUse **Spot Fargate** for non-critical services (background workers) to save 50-70%."),
      ("user", "What about deploying updates? We want CI/CD"),
      ("assistant", "For ECS + Fargate CI/CD:\n\n**Simple approach**: GitHub Actions\n1. Build Docker image\n2. Push to ECR\n3. Update ECS task definition\n4. ECS rolling deployment\n\nThis is 50 lines of YAML and handles most use cases.\n\n**Advanced**: ArgoCD (for K8s) or AWS CodePipeline\n- Blue/green deployments\n- Automatic rollback on health check failure\n- Canary deployments\n\nFor 5 services, GitHub Actions + ECS rolling updates is the sweet spot. Add health checks to your containers so ECS can detect and rollback bad deployments automatically.\n\nUse **Terraform** or **AWS CDK** to define your ECS services as infrastructure as code.")]),

    ("devops", "CI/CD pipeline: GitHub Actions vs GitLab CI vs Jenkins",
     ["GitHub Actions", "GitLab CI", "Jenkins", "CircleCI", "Terraform", "Docker"],
     [("user", "Setting up CI/CD for our monorepo. 3 services (API, web frontend, mobile). Currently on GitHub. Jenkins, GitHub Actions, or GitLab CI?"),
      ("assistant", "Since you're already on GitHub, **GitHub Actions** is the natural choice:\n\n**GitHub Actions**:\n- Native GitHub integration (no webhook setup)\n- Matrix builds for parallel testing\n- Excellent marketplace of pre-built actions\n- 2,000 free minutes/month (public repos unlimited)\n- Path filtering for monorepo (only build changed services)\n\n**GitLab CI**:\n- More powerful pipeline DSL\n- Built-in Docker registry\n- Would require migrating from GitHub\n\n**Jenkins**:\n- Maximum flexibility\n- Self-hosted = maintenance burden\n- Plugin ecosystem is aging\n- Groovy pipelines are complex\n\nFor a GitHub-hosted monorepo, **GitHub Actions** with path filtering and reusable workflows is the clear winner."),
      ("user", "How do we handle the monorepo aspect? Don't want to rebuild everything on every commit"),
      ("assistant", "Use GitHub Actions path filtering:\n\n```yaml\non:\n  push:\n    paths:\n      - 'apps/api/**'\njobs:\n  build-api:\n    runs-on: ubuntu-latest\n    steps: ...\n```\n\nFor more sophisticated monorepo support:\n- **Turborepo**: Built for JS/TS monorepos, understands dependencies\n- **Nx**: More features, steeper learning curve\n- **pnpm filtering**: `pnpm --filter api test`\n\nPattern:\n1. Use `paths` filter to trigger only relevant workflows\n2. Use Turborepo for task orchestration and caching\n3. Cache Docker layers and node_modules between runs\n4. Run affected tests only with `turbo run test --filter=[HEAD^1]`\n\nThis gives you fast CI that only builds and tests what changed.")]),

    ("devops", "Infrastructure as Code: Terraform vs Pulumi vs AWS CDK",
     ["Terraform", "Pulumi", "AWS CDK", "CloudFormation", "OpenTofu", "Ansible"],
     [("user", "Need IaC for our AWS infrastructure. Team knows TypeScript. Terraform (HCL), Pulumi (TypeScript), or AWS CDK?"),
      ("assistant", "Given your TypeScript expertise:\n\n**AWS CDK**:\n- TypeScript native\n- L2 constructs simplify common patterns\n- Generates CloudFormation under the hood\n- AWS-only (vendor lock-in)\n- Great for AWS-centric teams\n\n**Pulumi**:\n- TypeScript (or Python, Go, etc.)\n- Multi-cloud support\n- Real programming language (loops, conditions, functions)\n- State management similar to Terraform\n- Growing ecosystem\n\n**Terraform**:\n- HCL is its own language (learning curve)\n- Largest ecosystem and community\n- Multi-cloud, multi-provider\n- Mature, battle-tested\n- OpenTofu as open-source fork\n\nFor AWS-only + TypeScript team: **AWS CDK**. For multi-cloud potential: **Pulumi**. For maximum ecosystem and hiring: **Terraform**."),
      ("user", "We're AWS-only for now but might go multi-cloud in a year. Is CDK a bad bet?"),
      ("assistant", "If multi-cloud is on the roadmap, CDK is risky:\n\n- CDK generates CloudFormation, which is AWS-only\n- Migrating CDK to Terraform/Pulumi means rewriting everything\n- CDK for Terraform exists but is experimental\n\nBetter path: **Pulumi with TypeScript**\n- Write real TypeScript (your team is already productive)\n- Start with AWS provider\n- Add Azure/GCP providers when needed\n- State stored in Pulumi Cloud or self-hosted backend\n- Import existing AWS resources without downtime\n\nPulumi gives you the TypeScript DX of CDK with the multi-cloud future-proofing of Terraform. It's the best of both worlds for your situation.")]),

    # ── Data Engineering ──
    ("data-engineering", "Data pipeline: Airflow vs Dagster vs Prefect",
     ["Apache Airflow", "Dagster", "Prefect", "dbt", "Python", "Docker", "Kubernetes"],
     [("user", "Setting up a data pipeline for our analytics. ETL from PostgreSQL to a data warehouse. Should we use Airflow, Dagster, or Prefect?"),
      ("assistant", "All three are solid Python-based orchestrators. Key differences:\n\n**Apache Airflow**:\n- Industry standard, most job postings\n- DAG-based, UI is functional but dated\n- Complex to deploy and maintain\n- Huge operator ecosystem\n\n**Dagster**:\n- Software-defined assets (think about data, not tasks)\n- Excellent testing and type system\n- Built-in data quality checks\n- Modern UI with lineage visualization\n- Newer, smaller community\n\n**Prefect**:\n- Pythonic (decorate functions, not define DAGs)\n- Cloud-hosted option (less ops)\n- Good for event-driven pipelines\n- Middle ground between Airflow and Dagster\n\nFor ETL specifically, **Dagster** is the best modern choice - its asset-based paradigm maps naturally to data transformations. Pair it with **dbt** for SQL transformations."),
      ("user", "We use dbt already. Does Dagster integrate with it?"),
      ("assistant", "Yes, Dagster has first-class dbt integration via `dagster-dbt`:\n\n- Each dbt model becomes a Dagster asset automatically\n- dbt tests become Dagster asset checks\n- You can mix dbt SQL models with Python assets in the same pipeline\n- Dagster UI shows dbt lineage alongside Python transformations\n\nThe typical pattern:\n1. Extract: Python assets pull from PostgreSQL\n2. Load: Python assets write to warehouse (Snowflake/BigQuery)\n3. Transform: dbt models do the SQL transformations\n4. Dagster orchestrates the full pipeline and handles scheduling\n\nThis is arguably the most modern data stack pattern in 2026."),
      ("user", "deployment wise, can it run on k8s?"),
      ("assistant", "Yes, Dagster has native Kubernetes support:\n\n- **Dagster Helm chart**: One-command K8s deployment\n- **K8s job executor**: Each pipeline step runs as a separate K8s pod\n- **Resource limits**: Per-step CPU/memory configuration\n- **Dagster Cloud**: Managed option if you want zero ops\n\nFor your setup, I'd recommend:\n1. Development: `dagster dev` locally\n2. Staging: Docker Compose\n3. Production: Kubernetes via Helm chart\n\nDagster's K8s integration is mature - each step gets its own pod with resource limits, so a memory-hungry transformation won't affect other steps.")]),

    ("data-engineering", "Data warehouse: Snowflake vs BigQuery vs Redshift",
     ["Snowflake", "BigQuery", "Amazon Redshift", "ClickHouse", "DuckDB", "Apache Spark"],
     [("user", "Need a data warehouse for analytics. About 500GB of data, growing 10GB/month. We're on AWS but open to other options. Snowflake, BigQuery, or Redshift?"),
      ("assistant", "At 500GB with moderate growth, all three work. The choice depends on your ecosystem:\n\n**Snowflake**:\n- Cloud-agnostic (works on AWS, Azure, GCP)\n- Separation of storage and compute\n- Best for multi-cloud or cloud migration scenarios\n- Credit-based pricing (can be expensive for always-on)\n\n**BigQuery**:\n- Serverless, no cluster management\n- Pay per query (great for sporadic usage)\n- Excellent for ad-hoc analytics\n- GCP ecosystem integration\n\n**Amazon Redshift Serverless**:\n- AWS-native (best integration with S3, Glue, etc.)\n- Serverless option eliminates cluster management\n- Good if you're heavily invested in AWS\n\nAt 500GB, also consider **ClickHouse** (open-source, insanely fast for analytics) or even **DuckDB** for single-machine analytics."),
      ("user", "We do a lot of ad-hoc queries and the data team is small. Least ops overhead?"),
      ("assistant", "For minimal ops: **BigQuery** or **Redshift Serverless**.\n\n**BigQuery** wins on simplicity:\n- Truly serverless, zero cluster management\n- No indexes, no vacuuming, no tuning\n- Pay only for queries run (first 1TB/month free)\n- 500GB storage costs ~$10/month\n- Excellent Looker/Metabase/Superset integration\n\nBut you said you're on AWS. **Redshift Serverless** is the AWS equivalent:\n- Serverless, auto-scales\n- Direct S3 integration\n- AWS IAM for access control\n- Integrates with Glue catalog\n\nIf cross-cloud isn't an issue, go **Redshift Serverless** to stay in the AWS ecosystem. If you want the absolute simplest analytics warehouse, BigQuery is hard to beat.\n\nFor a small data team doing ad-hoc queries, don't overthink it. BigQuery or Redshift Serverless both get you there with minimal ops.")]),

    ("data-engineering", "Stream processing: Flink vs Spark Streaming vs Kafka Streams",
     ["Apache Flink", "Apache Spark", "Spark Streaming", "Kafka Streams", "Apache Kafka", "Databricks"],
     [("user", "We need real-time analytics on clickstream data. Processing 100k events/second. Flink, Spark Structured Streaming, or Kafka Streams?"),
      ("assistant", "At 100k events/second, all three handle the throughput. Key differences:\n\n**Apache Flink**:\n- True stream processing (not micro-batch)\n- Best latency (ms-level)\n- Excellent exactly-once semantics\n- Complex to operate\n- Best for: event-time processing, complex windowing\n\n**Spark Structured Streaming**:\n- Micro-batch (seconds, not milliseconds)\n- Unified batch + stream API\n- Great if you already use Spark/Databricks\n- Simpler mental model\n- Best for: analytics that can tolerate seconds of latency\n\n**Kafka Streams**:\n- Library, not a cluster (runs in your app)\n- Simple deployment (just a JVM app)\n- Limited windowing compared to Flink\n- Best for: lightweight transformations, enrichment\n\nFor clickstream analytics at 100k/s: **Flink** if you need ms-level latency and complex windowing. **Spark Structured Streaming** if second-level latency is OK and you use Databricks."),
      ("user", "We're using Databricks already. Spark seems like the natural fit?"),
      ("assistant", "Yes, if you're already on Databricks, **Spark Structured Streaming** is the clear choice:\n\n- Unified platform (batch ETL + streaming in same environment)\n- Delta Lake for ACID transactions on streaming data\n- Databricks autoscaling for cost optimization\n- SQL interface for analysts\n- Built-in monitoring and alerting\n\nThe architecture:\n1. Kafka ingests clickstream events\n2. Spark Structured Streaming reads from Kafka\n3. Processes in micro-batches (1-10 second triggers)\n4. Writes to Delta Lake tables\n5. Analysts query with SQL/notebooks\n\nThis gives you sub-10-second latency for dashboards, which is sufficient for most analytics use cases. If you later need ms-level processing for specific use cases (fraud detection, real-time bidding), you can add Flink for those specific streams.")]),

    # ── Security ──
    ("security", "API rate limiting strategies",
     ["Redis", "Nginx", "Token Bucket", "Sliding Window", "Cloudflare", "API Gateway"],
     [("user", "Need to add rate limiting to our API. Currently no protection. We have Redis already. What's the best approach?"),
      ("assistant", "With Redis available, you have several good options:\n\n**Algorithm choices**:\n1. **Token Bucket**: Smooth rate limiting, allows bursts. Most popular.\n2. **Sliding Window**: Prevents burst abuse at window boundaries.\n3. **Fixed Window**: Simplest but has boundary issues.\n4. **Leaky Bucket**: Constant output rate, good for downstream protection.\n\n**Implementation layers**:\n1. **Application-level (Redis)**: Most control, per-user/per-endpoint\n2. **Reverse proxy (Nginx)**: Lower latency, less granularity\n3. **CDN/WAF (Cloudflare)**: Handles DDoS, least control\n4. **API Gateway (Kong, AWS API Gateway)**: Managed, configurable\n\nRecommended: **Token bucket in Redis** for per-user limits + **Cloudflare** for DDoS protection.\n\nRedis implementation: Use `MULTI/EXEC` with key expiry. One key per user, increment and check in a transaction."),
      ("user", "What rate limits should we set? We serve both free and paid users"),
      ("assistant", "Tiered rate limiting is standard:\n\n**Free tier**:\n- 30 requests/minute per user\n- 1,000 requests/day\n- Burst: up to 10 requests in 1 second\n\n**Paid tier**:\n- 300 requests/minute per user\n- Unlimited daily\n- Burst: up to 50 requests in 1 second\n\n**Authentication endpoints**:\n- Login: 5 attempts/minute (brute force protection)\n- Registration: 3/hour\n- Password reset: 3/hour\n\n**Implementation in Redis**:\n```python\n# Token bucket: key = f\"rate:{user_id}:{endpoint}\"\n# TTL = window size\n# INCR + EXPIRE in pipeline\n```\n\nAlways return rate limit headers:\n- `X-RateLimit-Limit`: Maximum requests\n- `X-RateLimit-Remaining`: Requests left\n- `X-RateLimit-Reset`: When the window resets\n- `Retry-After`: Seconds until retry (on 429)")]),

    ("security", "Secret management: Vault vs AWS Secrets Manager vs SOPS",
     ["HashiCorp Vault", "AWS Secrets Manager", "SOPS", "Doppler", "dotenv", "Kubernetes"],
     [("user", "Currently using .env files for secrets, which is obviously not great for production. What's the right approach for managing secrets across dev/staging/prod?"),
      ("assistant", "Good instinct - .env files in production are a security risk. Options ranked by complexity:\n\n**Low complexity**:\n- **SOPS** (Mozilla): Encrypts secret files in git. Simple, git-native.\n- **Doppler**: SaaS secrets manager. Great DX, minimal setup.\n- **dotenv-vault**: Encrypted .env files with environment sync.\n\n**Medium complexity**:\n- **AWS Secrets Manager**: Managed, auto-rotation, IAM-based access.\n- **GCP Secret Manager**: Similar to AWS, GCP-native.\n\n**High complexity**:\n- **HashiCorp Vault**: Most powerful, most complex. Dynamic secrets, PKI, encryption as a service.\n\nFor most teams: **AWS Secrets Manager** if on AWS, or **Doppler** for multi-cloud. Start there and only move to Vault if you need dynamic secrets or complex access policies."),
      ("user", "We're on AWS with ECS. How does Secrets Manager integrate?"),
      ("assistant", "ECS + Secrets Manager integration is seamless:\n\n1. Store secrets in AWS Secrets Manager\n2. Reference them in ECS task definitions:\n```json\n\"secrets\": [\n  {\n    \"name\": \"DATABASE_URL\",\n    \"valueFrom\": \"arn:aws:secretsmanager:us-east-1:123:secret:prod/db-url\"\n  }\n]\n```\n3. ECS injects secrets as environment variables at container start\n4. IAM task role controls which secrets each service can access\n\nBenefits:\n- Secrets never touch your code or CI/CD pipeline\n- Automatic rotation for RDS credentials\n- Audit trail via CloudTrail\n- No code changes needed (still reads from env vars)\n\nCost: $0.40/secret/month + $0.05 per 10K API calls. Very reasonable."),
      ("user", "what about for local development? can't use secrets manager locally easily"),
      ("assistant", "For local dev, keep using `.env` files but with guardrails:\n\n1. **Never commit `.env`** - add to `.gitignore`\n2. **`.env.example`** in git with placeholder values\n3. Use different secrets for local (not production credentials)\n4. **1Password CLI** or **Doppler** can sync secrets locally\n\nPattern:\n- Local: `.env` file (dev-only credentials)\n- CI/CD: GitHub Actions secrets or AWS Secrets Manager\n- Staging/Prod: AWS Secrets Manager via ECS\n\nFor the best DX, use **Doppler**:\n- `doppler run -- npm start` injects secrets\n- Works locally and in CI/CD\n- Syncs to AWS Secrets Manager for production\n- Team can share secrets without Slack/email\n\nThis gives you security in production and convenience in development.")]),

    # ── ML/AI ──
    ("ml-ai", "Vector database selection for RAG",
     ["Pinecone", "Weaviate", "Qdrant", "Milvus", "Chroma", "pgvector", "FAISS"],
     [("user", "Building a RAG system for internal documentation search. Need a vector database. Options are Pinecone, Weaviate, Qdrant, or just pgvector since we have PostgreSQL."),
      ("assistant", "The choice depends on your scale and operational preferences:\n\n**pgvector** (PostgreSQL extension):\n- Zero new infrastructure (you have PG)\n- HNSW and IVFFlat indexes\n- Good for < 5M vectors\n- SQL interface (familiar)\n- Drawback: shares resources with your main DB\n\n**Qdrant**:\n- Purpose-built, excellent performance\n- Rust-based, very fast\n- Filtering + vector search combined\n- Self-hosted or cloud\n\n**Pinecone**:\n- Fully managed, serverless option\n- Easiest to get started\n- Pay per query\n- Limited filtering capabilities\n\n**Weaviate**:\n- GraphQL API, built-in vectorization\n- Multi-modal (text, images)\n- More features = more complexity\n\nFor internal docs search: Start with **pgvector**. If you outgrow it (>5M vectors, need dedicated scaling), migrate to **Qdrant**."),
      ("user", "We'll have about 100k documents, each embedded as ~10 chunks. So roughly 1M vectors. pgvector can handle that?"),
      ("assistant", "Yes, 1M vectors is well within pgvector's sweet spot:\n\n- HNSW index: sub-10ms queries at 1M vectors\n- Memory: ~8GB for 1M x 1536-dim vectors (OpenAI embeddings)\n- Scales to ~5M vectors comfortably on a decent instance\n\nSetup:\n```sql\nCREATE EXTENSION vector;\nCREATE TABLE document_chunks (\n  id SERIAL PRIMARY KEY,\n  content TEXT,\n  embedding vector(1536),\n  metadata JSONB\n);\nCREATE INDEX ON document_chunks USING hnsw (embedding vector_cosine_ops);\n```\n\nKey settings:\n- `maintenance_work_mem = 2GB` for index building\n- `hnsw.m = 16`, `hnsw.ef_construction = 128` (default is fine)\n- `hnsw.ef_search = 40` at query time\n\npgvector keeps your architecture simple: one database for everything. Save the specialized vector DB for when you actually need it."),
      ("user", "What embedding model should we use? OpenAI or something open source?"),
      ("assistant", "For internal documentation, both work well:\n\n**OpenAI `text-embedding-3-small`**:\n- 1536 dimensions, excellent quality\n- $0.02 per 1M tokens (~$2 for your 100k docs)\n- Simple API, no infrastructure\n\n**Open source alternatives**:\n- **NVIDIA NV-EmbedQA** (2048 dim): Great for Q&A retrieval\n- **Sentence-Transformers** (e.g., `all-MiniLM-L6-v2`): 384 dim, runs locally\n- **Nomic Embed**: Open weights, competitive quality\n- **BGE-large**: BAAI's model, excellent on MTEB benchmarks\n\nIf data privacy is a concern (internal docs shouldn't leave your network), go with a self-hosted model like **BGE-large** or **NV-EmbedQA**.\n\nIf convenience matters more: OpenAI embeddings are the easiest to integrate and the quality is top-tier.\n\nPro tip: Use **Matryoshka embeddings** (supported by OpenAI) to store shorter vectors (256 dim instead of 1536) with ~95% of the quality. Saves storage and speeds up search.")]),

    ("ml-ai", "LLM deployment: Self-hosted vs API",
     ["OpenAI", "Anthropic", "NVIDIA NIM", "vLLM", "Ollama", "Hugging Face", "GGUF", "llama.cpp"],
     [("user", "We want to use LLMs in our product but worried about cost and latency of API-based models. Should we self-host? We have some GPU budget."),
      ("assistant", "It depends on your usage patterns and requirements:\n\n**API-based (OpenAI, Anthropic, NVIDIA NIM)**:\n- Zero infrastructure\n- Always latest models\n- Pay per token\n- 100ms-2s latency\n- Best for: Variable load, latest capabilities\n\n**Self-hosted (vLLM, Ollama, llama.cpp)**:\n- Fixed GPU cost\n- Lower latency (local)\n- Data never leaves your infra\n- Model version control\n- Best for: Consistent load, data privacy, cost optimization at scale\n\n**Cost comparison** (rough estimates):\n- GPT-4o: ~$5/M input tokens\n- Self-hosted Llama 70B on A100: ~$2/M tokens at 1000 req/hour\n- Self-hosted Llama 8B on L4: ~$0.50/M tokens\n\nBreak-even is typically at 100K+ requests/day. Below that, APIs are cheaper."),
      ("user", "We process about 10K documents per day through an LLM. Mostly summarization and classification. Is self-hosting worth it?"),
      ("assistant", "At 10K docs/day, self-hosting can be cost-effective:\n\n**API cost estimate**: ~$50-100/day with GPT-4o-mini\n**Self-hosted cost**: A100 80GB at ~$2/hour = $48/day but handles much more\n\n**Recommended self-hosted stack**:\n1. **vLLM**: Best throughput, continuous batching\n2. **Model**: Llama 3.1 8B or Mistral 7B for summarization (fast, cheap)\n3. **Hardware**: L4 or A10G GPU (~$1/hour)\n4. **Serving**: NVIDIA NIM or vLLM behind an API\n\nFor classification specifically, consider fine-tuning a small model (Llama 3.1 8B) on your data. A fine-tuned small model often outperforms prompted large models for specific tasks.\n\n**Hybrid approach**: Self-host a small model for routine tasks (summarization, classification). Use API for complex tasks (reasoning, code generation). This optimizes both cost and quality.")]),

    ("ml-ai", "ML experiment tracking and model registry",
     ["MLflow", "Weights & Biases", "DVC", "Neptune", "ClearML", "Kubeflow"],
     [("user", "Our ML team is growing from 2 to 5 people. We need experiment tracking and a model registry. Evaluating MLflow, W&B, and Neptune."),
      ("assistant", "For a team of 5:\n\n**Weights & Biases (W&B)**:\n- Best UX, beautiful dashboards\n- Collaborative (share experiments, reports)\n- Cloud-hosted (minimal ops)\n- Sweeps for hyperparameter tuning\n- Free for academics, $50/user/month for teams\n\n**MLflow**:\n- Open source, self-hosted\n- Model registry with staging/production lifecycle\n- Integrates with everything\n- UI is functional but basic\n- Databricks-managed option available\n\n**Neptune**:\n- Good middle ground\n- Better UI than MLflow, less featured than W&B\n- Affordable pricing\n\n**Recommendation for 5 people**: **W&B** for experiment tracking + **MLflow** for model registry and deployment. Many teams use both:\n- W&B: Log experiments, compare runs, team dashboards\n- MLflow: Model packaging, versioning, deployment\n\nThis combination gives you the best tracking UX (W&B) with the best deployment pipeline (MLflow)."),
      ("user", "What about data versioning? We also need to track dataset changes"),
      ("assistant", "For data versioning:\n\n**DVC (Data Version Control)**:\n- Git-like workflow for data\n- `dvc push/pull` to remote storage (S3, GCS)\n- Tracks data + code + model together\n- Integrates with Git (data versions tied to commits)\n- Free, open source\n\n**Alternatives**:\n- **LakeFS**: Git-like for data lakes\n- **Delta Lake**: Versioned data tables (if using Spark)\n- **W&B Artifacts**: Dataset versioning within W&B\n\nBest combo for your team:\n- **DVC** for data versioning (tracks datasets in S3)\n- **W&B** for experiment tracking\n- **MLflow** for model registry\n\nPipeline: DVC manages data versions → training uses W&B for logging → trained models registered in MLflow → MLflow serves models\n\nDVC is the standard for data versioning in ML teams. It's Git-native, so your data versions are tied to your code commits.")]),

    # ── Mobile Development ──
    ("mobile", "React Native vs Flutter vs Native for a consumer app",
     ["React Native", "Flutter", "Swift", "Kotlin", "Expo", "Dart", "TypeScript"],
     [("user", "Building a consumer mobile app (social/content). Need both iOS and Android. Team is mostly web developers (React/TypeScript). React Native, Flutter, or go native?"),
      ("assistant", "Given your web/React background:\n\n**React Native (with Expo)**:\n- Leverages your existing React/TypeScript skills\n- Expo SDK handles 90% of native modules\n- OTA updates (push fixes without app store review)\n- Large community, lots of libraries\n- Performance: Good for most apps, not games\n\n**Flutter**:\n- Beautiful UI with Material/Cupertino widgets\n- Dart language (new learning curve)\n- Excellent performance (compiled to native ARM)\n- Great for custom, animation-heavy UIs\n- Growing but smaller ecosystem than RN\n\n**Native (Swift + Kotlin)**:\n- Best performance and platform integration\n- Double the codebase and team\n- Best for: Camera-heavy, AR, or performance-critical apps\n\nFor a social/content app with a React team: **React Native + Expo**. You'll be productive immediately and can always eject for native modules if needed."),
      ("user", "We've heard RN has performance issues. Is that still true in 2026?"),
      ("assistant", "React Native's performance has improved dramatically:\n\n**New Architecture (enabled by default since RN 0.76)**:\n- **JSI**: Direct JavaScript-to-Native bridge (no JSON serialization)\n- **Fabric**: Concurrent renderer, better UI responsiveness\n- **TurboModules**: Lazy-loaded native modules\n\n**Performance reality in 2026**:\n- 60fps scrolling: Yes, with FlashList (not FlatList)\n- Complex animations: Reanimated 3 runs on the UI thread (native performance)\n- Startup time: ~500ms with Hermes engine\n- Memory: Comparable to native for typical apps\n\n**Where RN still struggles**:\n- Heavy 3D/game rendering (use Unity instead)\n- Complex canvas operations\n- Apps with 100+ simultaneous animations\n\nFor a social/content app (feeds, profiles, messaging), React Native performance is indistinguishable from native. Instagram, Facebook, Discord, and Shopify all use React Native.")]),

    ("mobile", "Mobile backend: Supabase vs Firebase vs custom API",
     ["Supabase", "Firebase", "Firestore", "PostgreSQL", "React Native", "Expo"],
     [("user", "Need a backend for our React Native app. Evaluating Supabase, Firebase, or building a custom API with FastAPI. The app has user profiles, posts, real-time chat, and image uploads."),
      ("assistant", "For your feature set:\n\n**Supabase**:\n- PostgreSQL underneath (relational = perfect for social features)\n- Real-time subscriptions for chat\n- Storage for image uploads\n- Row-Level Security for per-user isolation\n- Auth with social logins\n- Edge Functions for custom logic\n\n**Firebase**:\n- Firestore (NoSQL) - modeling social graphs in NoSQL is painful\n- Excellent real-time sync and offline support\n- Cloud Storage for images\n- Firebase Auth (mature)\n- Cloud Functions for backend logic\n\n**Custom FastAPI**:\n- Maximum flexibility\n- More code to write and maintain\n- Need separate solutions for real-time, storage, auth\n\nFor social features (users, posts, follows, likes, chat): **Supabase**. Relational data model makes social graphs natural, real-time subscriptions handle chat, and storage handles images. It's the fastest path to a working product."),
      ("user", "How does supabase handle real-time at scale? We might get 10k concurrent users"),
      ("assistant", "Supabase real-time uses PostgreSQL's LISTEN/NOTIFY under the hood:\n\n**10K concurrent users**:\n- Supabase Pro plan supports this out of the box\n- Real-time connections are WebSocket-based\n- Each subscription is a PostgreSQL change listener\n\n**Scaling considerations**:\n- Use **Supabase Realtime** channels (not database changes) for chat\n- Database change subscriptions: Good for 1-2K per table\n- Realtime Broadcast: Better for chat (pub/sub, up to 100K connections)\n- Realtime Presence: For online status, typing indicators\n\n**Architecture for chat at scale**:\n1. Messages stored in PostgreSQL (source of truth)\n2. Real-time delivery via Supabase Broadcast channels\n3. Client subscribes to channel, not database table\n4. Offline messages synced when client reconnects\n\nAt 10K concurrent users, Supabase handles it. At 100K+, you'd want to add a dedicated message broker (Redis Pub/Sub or NATS).")]),

    # ── Systems Programming ──
    ("systems", "Choosing between Rust and Go for a CLI tool",
     ["Rust", "Go", "Python", "Cargo", "clap", "cobra"],
     [("user", "Building a CLI tool for our developer workflow. It needs to be fast, distributable as a single binary, and cross-platform. Go or Rust?"),
      ("assistant", "Both produce single binaries and are cross-platform. Key differences:\n\n**Go**:\n- Faster compilation (seconds vs minutes for Rust)\n- Simpler language, quicker to learn\n- **cobra** library for CLI (used by kubectl, docker, gh)\n- Garbage collected (no memory management)\n- Cross-compilation is trivial (`GOOS=linux GOARCH=amd64 go build`)\n- Binary size: ~10MB typical\n\n**Rust**:\n- Better runtime performance (no GC pauses)\n- **clap** library for CLI (derive macros = great DX)\n- Memory safety without GC\n- Steeper learning curve (ownership, lifetimes)\n- Cross-compilation needs toolchains\n- Binary size: ~2-5MB typical\n\nFor a CLI tool: **Go** if you want to ship fast. **Rust** if you need maximum performance or are building something performance-critical (like a build tool or compiler)."),
      ("user", "It's a devtools CLI that processes large codebases. Needs to parse files, search, and generate reports. Speed matters."),
      ("assistant", "For processing large codebases, **Rust** has the edge:\n\n- **ripgrep** (Rust): 10-50x faster than grep\n- **tree-sitter** bindings: Fast AST parsing\n- Zero-cost abstractions: Iterator chains compile to optimal loops\n- **rayon**: Parallel file processing with minimal code\n- Memory efficiency: No GC pauses during large file scans\n\nRust CLI ecosystem is excellent:\n- `clap` for arg parsing (derive macros)\n- `indicatif` for progress bars\n- `serde` for JSON/YAML/TOML\n- `walkdir` for filesystem traversal\n- `ignore` for respecting .gitignore\n\nMany modern dev tools are Rust: ripgrep, fd, bat, delta, starship, turbopack. The ecosystem for file processing and code analysis is mature.\n\nCompile time is the main downside. For a CLI tool, incremental builds are usually fast enough.")]),

    ("systems", "Embedded database: SQLite vs RocksDB vs DuckDB",
     ["SQLite", "RocksDB", "DuckDB", "LevelDB", "LMDB"],
     [("user", "Need an embedded database for our desktop app. It stores user data locally - settings, documents, and search indexes. SQLite, RocksDB, or something else?"),
      ("assistant", "**SQLite** is the default choice for embedded databases:\n\n**SQLite**:\n- The most widely deployed database in the world\n- Full SQL support with JSON extension\n- ACID transactions\n- Single file database (easy backup/sync)\n- Excellent for structured data + full-text search (FTS5)\n- Read-heavy workloads: perfect\n\n**RocksDB**:\n- Key-value store (no SQL)\n- Optimized for write-heavy workloads\n- LSM-tree based\n- Used by: CockroachDB, TiKV, Kafka\n- Overkill for a desktop app\n\n**DuckDB**:\n- Columnar, analytical (OLAP)\n- Excellent for data analysis queries\n- Not ideal for OLTP (user data, settings)\n\nFor user data, settings, documents, and search: **SQLite** with FTS5 for full-text search. It's the industry standard for desktop apps (Chrome, Firefox, iOS, Android all use SQLite internally)."),
      ("user", "What about syncing the SQLite database to the cloud?"),
      ("assistant", "Several approaches for SQLite cloud sync:\n\n**LiteFS** (Fly.io):\n- Distributed SQLite replication\n- Read replicas across regions\n- Not for offline-first sync\n\n**Turso/libSQL**:\n- SQLite fork with native replication\n- Edge deployment\n- Embedded replicas that sync to cloud\n\n**Electric SQL**:\n- Sync engine for SQLite <-> PostgreSQL\n- Offline-first, conflict resolution\n- Best for mobile/desktop with cloud sync\n\n**CR-SQLite**:\n- CRDT-based merge for SQLite\n- Peer-to-peer sync without central server\n- Experimental but promising\n\nFor a desktop app with cloud sync, **Turso embedded replicas** or **Electric SQL** are the best options. Turso gives you a local SQLite that auto-syncs to a cloud SQLite instance.")]),

    # ── Testing ──
    ("testing", "Testing strategy: Unit vs Integration vs E2E",
     ["Vitest", "Jest", "Playwright", "Cypress", "Testing Library", "MSW"],
     [("user", "Need to establish a testing strategy for our React + Node.js app. Currently zero tests. Where should we start?"),
      ("assistant", "Start with the testing pyramid and prioritize high-ROI tests:\n\n**Layer 1: Integration tests (start here)**\n- Test API endpoints with real database\n- Use **Vitest** or **Jest** for Node.js\n- Mock external services (Stripe, email)\n- Highest ROI: catches real bugs in real scenarios\n\n**Layer 2: Component tests**\n- Test React components with **Testing Library**\n- **MSW** (Mock Service Worker) for API mocking\n- Focus on user interactions, not implementation\n- **Vitest** with jsdom for fast execution\n\n**Layer 3: E2E tests (last)**\n- **Playwright** for critical user flows\n- Login, checkout, signup flows\n- Run in CI, not on every commit\n- Slowest but highest confidence\n\n**Skip**: Pure unit tests for simple functions. They have low ROI.\n\nStart with 5-10 API integration tests and 3-5 Playwright E2E tests for critical paths. That alone catches most regressions."),
      ("user", "Why Vitest over Jest? We see both used everywhere"),
      ("assistant", "Vitest advantages over Jest in 2026:\n\n1. **Speed**: Vitest uses Vite's dev server, HMR for instant re-runs. 5-10x faster.\n2. **ESM native**: No configuration for ES modules (Jest needs transforms)\n3. **TypeScript native**: No `ts-jest` needed\n4. **Configuration**: `vite.config.ts` shared with your build tool\n5. **API compatible**: Same `describe/it/expect` API as Jest\n6. **UI**: Built-in test UI for visual debugging\n\nJest is still fine, but Vitest is the modern choice for projects using Vite, React, or modern TypeScript.\n\nFor backend (Node.js API testing), both work equally well. For frontend, Vitest's integration with Vite makes it the clear winner."),
      ("user", "What about Cypress vs Playwright for E2E?"),
      ("assistant", "**Playwright** wins in 2026:\n\n1. **Multi-browser**: Chromium, Firefox, WebKit (Safari) out of the box\n2. **Speed**: Parallel execution, no Electron overhead\n3. **Auto-waiting**: Smart assertions that wait for elements\n4. **API testing**: Built-in request context for API tests\n5. **Codegen**: Record browser interactions, generate test code\n6. **Mobile emulation**: Test responsive designs\n7. **Free**: No paid tier needed (Cypress Dashboard costs money)\n\nCypress advantages:\n- Slightly better DX for simple tests\n- Time-travel debugging in browser\n- Component testing (though Vitest is better)\n\nPlaywright has passed Cypress in adoption for new projects. The multi-browser support and parallel execution alone make it the better choice. Use `playwright codegen` to quickly scaffold your first E2E tests.")]),

    # ── Architecture Patterns ──
    ("architecture", "Monolith vs Microservices",
     ["Docker", "Kubernetes", "gRPC", "REST API", "PostgreSQL", "Redis", "RabbitMQ"],
     [("user", "Starting a new project. Team of 6 developers. Should we build a monolith or start with microservices? We want to scale eventually."),
      ("assistant", "**Start with a modular monolith**, then extract microservices as needed:\n\n**Why not microservices from day 1**:\n- 6 developers is too small to own separate services\n- Network latency between services adds complexity\n- Distributed transactions are hard\n- Debugging across services requires observability infrastructure\n- Deployment complexity (you need K8s, service mesh, etc.)\n\n**Modular monolith approach**:\n1. Single deployable but with clear module boundaries\n2. Each module has its own database schema (or schema per module)\n3. Modules communicate via internal interfaces (not HTTP)\n4. When a module needs independent scaling, extract it\n\nCompanies that started monolith then extracted: Shopify, GitHub, Basecamp. Companies that regret starting with microservices: many.\n\nThe key insight: **You can always split a well-structured monolith. You can't easily merge poorly-designed microservices.**"),
      ("user", "Makes sense. But what if we need different tech stacks for different parts? Like Python for ML and Node.js for the API?"),
      ("assistant", "That's one of the valid reasons for early service separation:\n\n**Hybrid approach**:\n1. **Main application**: Monolith in Node.js (API + web)\n2. **ML service**: Separate Python service (FastAPI)\n3. **Communication**: gRPC or REST between them\n\nThis gives you:\n- Best language for each job\n- Independent scaling for ML (GPU-intensive)\n- Clear API boundary between concerns\n\nBut keep it to 2-3 services maximum at your team size:\n- API monolith (Node.js)\n- ML service (Python)\n- Maybe a background worker (same language as main)\n\nUse **Docker Compose** for local development and simple deployment. RabbitMQ or Redis for async communication between services. Don't add Kubernetes until you have 10+ services.")]),

    ("architecture", "Event sourcing vs CRUD for a financial application",
     ["Event Sourcing", "CQRS", "PostgreSQL", "Apache Kafka", "EventStoreDB", "Redis"],
     [("user", "Building a financial application (invoicing, payments, accounting). Should we use event sourcing or stick with CRUD? I've heard event sourcing is great for financial systems."),
      ("assistant", "Event sourcing is indeed well-suited for financial systems, but it's not always the right choice:\n\n**Event Sourcing benefits for finance**:\n- **Complete audit trail**: Every state change is recorded forever\n- **Temporal queries**: \"What was the balance on March 15?\"\n- **Regulatory compliance**: Immutable event log satisfies auditors\n- **Debugging**: Replay events to understand exactly what happened\n- **Reconciliation**: Compare derived state against source events\n\n**Event Sourcing costs**:\n- Significantly more complex to implement\n- Eventually consistent reads (CQRS needed)\n- Schema evolution is challenging\n- Team needs to learn new paradigm\n\n**Alternative: CRUD + Event Log**:\n- Standard CRUD operations\n- Append-only event table for audit trail\n- Simpler implementation, most of the benefits\n- PostgreSQL table with `INSERT` only (no UPDATE/DELETE)\n\nFor invoicing and basic accounting: **CRUD + event log** in PostgreSQL. For a trading platform or ledger system: **Full event sourcing** with EventStoreDB or Kafka."),
      ("user", "We need to generate monthly reports and tax summaries. Does event sourcing help there?"),
      ("assistant", "CQRS (Command Query Responsibility Segregation) paired with event sourcing excels at reporting:\n\n**Pattern**:\n1. **Write side**: Events stored immutably (Invoice Created, Payment Received, etc.)\n2. **Read side**: Materialized views optimized for queries\n3. **Reports**: Projections built from events\n\nFor monthly reports:\n- Replay events for any time period\n- Guaranteed accuracy (derived from source events)\n- Multiple projections from same events (P&L, Balance Sheet, Tax Summary)\n\n**Practical approach without full event sourcing**:\n1. PostgreSQL for CRUD operations\n2. Event log table: `(event_id, entity_type, entity_id, event_type, data, timestamp)`\n3. Materialized views or separate reporting tables updated by triggers\n4. Monthly cron jobs aggregate events into report tables\n\nThis gives you 90% of event sourcing benefits with 30% of the complexity. Use Kafka only if you need real-time event streaming to multiple consumers.")]),

    # ── Database Design ──
    ("database", "Multi-tenant database architecture",
     ["PostgreSQL", "Row-Level Security", "Citus", "pgBouncer", "Prisma", "SQLAlchemy"],
     [("user", "Designing a multi-tenant SaaS database. Three approaches: shared database with tenant_id column, schema per tenant, or database per tenant. Which is best?"),
      ("assistant", "Each has tradeoffs. For most SaaS products:\n\n**Shared database + tenant_id (recommended)**:\n- Single database, `tenant_id` on every table\n- PostgreSQL Row-Level Security (RLS) for isolation\n- Simplest operations (one migration, one backup)\n- Good for: Most SaaS, < 10K tenants\n- Risk: Noisy neighbor, but mitigated with proper indexing\n\n**Schema per tenant**:\n- Each tenant gets a PostgreSQL schema\n- Moderate isolation\n- Migrations must run per schema (can be slow)\n- Good for: Regulatory requirements\n\n**Database per tenant**:\n- Maximum isolation\n- Operational nightmare (migrations, backups, monitoring per DB)\n- Good for: Enterprise customers demanding data isolation\n\n**Recommendation**: Shared database with RLS. PostgreSQL's RLS is powerful:\n```sql\nCREATE POLICY tenant_isolation ON tasks\n  USING (tenant_id = current_setting('app.tenant_id'));\n```\n\nAdd Citus for horizontal sharding when you outgrow a single PostgreSQL instance."),
      ("user", "How do we handle connection pooling? Each tenant will have many users"),
      ("assistant", "Connection pooling is critical for multi-tenant:\n\n**PgBouncer** (recommended):\n- Sits between your app and PostgreSQL\n- Reuses connections across requests\n- Transaction pooling mode: most efficient\n- Typical: 20 PgBouncer connections serve 1000+ app connections\n\n**Supabase Supavisor** (if using Supabase):\n- Built-in pooling, no separate service\n\n**Application-level** (SQLAlchemy/Prisma):\n- SQLAlchemy: `pool_size=20, max_overflow=10`\n- Prisma: Connection pool built-in\n\n**Architecture for multi-tenant**:\n1. PgBouncer in transaction mode\n2. App sets `app.tenant_id` per request (for RLS)\n3. Connection pool: 20-50 connections per app instance\n4. Monitor with `pg_stat_activity`\n\nFor your setup: PgBouncer with transaction pooling + application pool size of 20. Each request sets `SET LOCAL app.tenant_id = 'xxx'` which is scoped to the transaction and works with RLS.")]),

    ("database", "Graph database selection: Neo4j vs ArangoDB vs TigerGraph",
     ["Neo4j", "ArangoDB", "TigerGraph", "Amazon Neptune", "Cypher", "Gremlin"],
     [("user", "Need a graph database for our knowledge management system. Storing entities, relationships, and doing path queries. Neo4j, ArangoDB, or TigerGraph?"),
      ("assistant", "For a knowledge management system:\n\n**Neo4j** (recommended):\n- Most popular graph database\n- Cypher query language (intuitive, SQL-like)\n- Excellent visualization tools\n- APOC procedures for advanced operations\n- Graph Data Science library (community detection, centrality)\n- Managed: Neo4j Aura\n\n**ArangoDB**:\n- Multi-model (document + graph + key-value)\n- AQL query language (different from Cypher)\n- Good if you need document storage alongside graph\n- Smaller community\n\n**TigerGraph**:\n- Best for massive-scale analytics\n- GSQL language (steeper learning curve)\n- Enterprise pricing\n- Overkill for knowledge management\n\n**Amazon Neptune**:\n- Managed, AWS-native\n- Supports both Gremlin and openCypher\n- Good for AWS-centric teams\n\nFor knowledge management: **Neo4j**. The Cypher query language is intuitive, the ecosystem is the largest, and the Graph Data Science library enables advanced analysis (finding clusters, important nodes, etc.)."),
      ("user", "How does Neo4j handle fulltext search? We need to search entity names and descriptions"),
      ("assistant", "Neo4j has built-in fulltext search:\n\n```cypher\n// Create fulltext index\nCREATE FULLTEXT INDEX entitySearch\nFOR (n:Entity)\nON EACH [n.name, n.description, n.aliases]\n\n// Search\nCALL db.index.fulltext.queryNodes('entitySearch', 'PostgreSQL database')\nYIELD node, score\nRETURN node.name, score\nORDER BY score DESC LIMIT 10\n```\n\nFeatures:\n- Lucene-based (same as Elasticsearch under the hood)\n- Supports fuzzy matching, wildcards, boolean queries\n- Can index multiple properties\n- Combined with graph traversal in a single query\n\nFor hybrid search (fulltext + vector similarity):\n1. Fulltext index for keyword search\n2. Vector index for semantic search (Neo4j 5.11+)\n3. Combine results with score fusion\n\nNeo4j's built-in search is sufficient for most knowledge management systems. Only add Elasticsearch if you need advanced analysis (stemming, synonyms, multilingual).")]),

    # ── Observability ──
    ("observability", "Monitoring stack: Datadog vs Grafana vs New Relic",
     ["Datadog", "Grafana", "Prometheus", "New Relic", "OpenTelemetry", "Loki", "Jaeger"],
     [("user", "Setting up monitoring for our production services. Considering Datadog, Grafana Cloud, or New Relic. We have 10 microservices on Kubernetes."),
      ("assistant", "For 10 microservices on K8s:\n\n**Datadog**:\n- Best all-in-one platform (metrics, logs, traces, APM)\n- K8s integration is excellent\n- Expensive at scale ($15-23/host/month + $12/GB logs)\n- Best for: Teams that want turnkey observability\n\n**Grafana Cloud** (LGTM stack):\n- Open-source core (Grafana + Prometheus + Loki + Tempo)\n- Can self-host for cost control\n- More assembly required\n- Best for: Teams comfortable with ops, cost-conscious\n\n**New Relic**:\n- Good APM and distributed tracing\n- Free tier is generous (100GB/month)\n- UI not as polished as Datadog\n- Best for: Budget-conscious teams getting started\n\n**Recommendation for 10 services on K8s**:\n- **Budget option**: Self-hosted Grafana + Prometheus + Loki + Tempo\n- **Balanced**: Grafana Cloud\n- **Premium**: Datadog\n\nRegardless of choice, instrument with **OpenTelemetry** so you can switch vendors later."),
      ("user", "We want to use OpenTelemetry. How does that integrate?"),
      ("assistant", "OpenTelemetry (OTel) is the right move - it's vendor-neutral instrumentation:\n\n**Architecture**:\n1. **Application SDK**: Add OTel SDK to each service\n2. **Auto-instrumentation**: HTTP, gRPC, DB queries instrumented automatically\n3. **OTel Collector**: Receives, processes, and exports telemetry\n4. **Backend**: Send to Datadog, Grafana, Jaeger, etc.\n\n**For your K8s setup**:\n```yaml\n# Deploy OTel Collector as DaemonSet\n# Receives traces from all pods on the node\napiVersion: apps/v1\nkind: DaemonSet\nmetadata:\n  name: otel-collector\n```\n\n**Three signals**:\n- **Traces**: Request flow across services (OTel → Jaeger/Tempo)\n- **Metrics**: Counters, gauges, histograms (OTel → Prometheus)\n- **Logs**: Structured logging (OTel → Loki/Elasticsearch)\n\nStart with traces (most value for microservices debugging), then add metrics and logs. OTel Collector can export to multiple backends simultaneously, so you can try Jaeger free before committing to Datadog.")]),

    # ── Frontend Build Tools ──
    ("web-development", "Build tools: Vite vs Turbopack vs Rspack",
     ["Vite", "Turbopack", "Rspack", "Webpack", "esbuild", "SWC", "Rollup"],
     [("user", "Our Webpack build takes 3 minutes. Looking at modern alternatives: Vite, Turbopack, or Rspack. Which should we migrate to?"),
      ("assistant", "All three are massive improvements over Webpack:\n\n**Vite**:\n- Dev: Instant start, HMR in milliseconds (ESM-native)\n- Build: Rollup-based, highly optimized\n- Ecosystem: Largest, most plugins\n- Used by: Nuxt, SvelteKit, Astro, Remix\n\n**Turbopack** (Vercel):\n- Built in Rust, incremental computation\n- Designed for Next.js (tight integration)\n- Still in beta for standalone use\n- Fastest for Next.js projects\n\n**Rspack**:\n- Rust-based Webpack replacement\n- Webpack-compatible (drop-in replacement)\n- 5-10x faster than Webpack\n- Best for: Migrating large Webpack configs without rewriting\n\n**Recommendation**:\n- Next.js project? → **Turbopack** (built-in)\n- New project? → **Vite**\n- Large Webpack config you can't rewrite? → **Rspack**\n\nFor your 3-minute build: Rspack could cut it to 20-30 seconds with minimal config changes. Vite would be even faster but requires more migration work."),
      ("user", "We're using Webpack with lots of custom loaders and plugins. Rspack sounds safest?"),
      ("assistant", "Yes, Rspack is the safest migration path:\n\n**Compatibility**:\n- Most Webpack loaders work unchanged\n- `babel-loader`, `css-loader`, `sass-loader` compatible\n- Plugin compatibility: ~80% of Webpack plugins work\n- Config: Rename `webpack.config.js` to `rspack.config.js`, minor tweaks\n\n**Migration steps**:\n1. Install `@rspack/cli @rspack/core`\n2. Copy your Webpack config\n3. Replace `webpack` imports with `@rspack/core`\n4. Test: most things work out of the box\n5. Replace incompatible plugins with Rspack built-ins\n\n**Rspack built-in replacements**:\n- `html-webpack-plugin` → `rspack.HtmlRspackPlugin`\n- `mini-css-extract-plugin` → `rspack.CssExtractRspackPlugin`\n- `terser-webpack-plugin` → Built-in SWC minification\n\nExpected results: 3-minute build → 20-30 seconds. Dev server startup: instant. HMR: near-instant.\n\nStart with Rspack for the quick win, then consider migrating to Vite later if you want the best DX.")]),

    # ── Cloud Services ──
    ("cloud", "Serverless: AWS Lambda vs Vercel Functions vs Cloudflare Workers",
     ["AWS Lambda", "Vercel", "Cloudflare Workers", "Deno Deploy", "Netlify Functions"],
     [("user", "Need serverless functions for our API. Comparing AWS Lambda, Vercel Functions, and Cloudflare Workers. We have a Next.js frontend on Vercel."),
      ("assistant", "Since you're already on Vercel with Next.js:\n\n**Vercel Functions** (API Routes):\n- Zero configuration (Next.js API routes just work)\n- Automatic scaling\n- Co-located with your frontend\n- Node.js runtime\n- Edge Functions option for low latency\n- Cold starts: ~200ms\n\n**Cloudflare Workers**:\n- V8 isolates (near-zero cold starts)\n- Edge-first (runs in 300+ locations)\n- Limitations: no Node.js APIs (Web Standards only)\n- Cheap ($5/month for 10M requests)\n- Best for: Lightweight API, middleware, rewrites\n\n**AWS Lambda**:\n- Maximum flexibility (any runtime)\n- VPC access (connect to RDS, ElastiCache)\n- Cold starts: 100ms-3s depending on runtime\n- Complex pricing (compute + memory + duration)\n\nFor Next.js on Vercel: **Vercel Functions** for most endpoints (it's already there). Add **Cloudflare Workers** for edge logic that needs to be fast globally. Use Lambda only if you need VPC access or specific AWS services."),
      ("user", "What about database connections from serverless? Heard that's a problem"),
      ("assistant", "Yes, connection pooling is the main serverless challenge:\n\n**The problem**: Each function invocation opens a new DB connection. At scale, you exhaust PostgreSQL's connection limit (default: 100).\n\n**Solutions**:\n\n1. **Connection poolers**:\n   - **PgBouncer**: External pooler\n   - **Supabase Supavisor**: If using Supabase\n   - **Neon Pooler**: If using Neon (serverless-native Postgres)\n\n2. **Serverless-native databases**:\n   - **Neon**: Serverless Postgres with built-in pooling\n   - **PlanetScale**: Serverless MySQL with connection handling\n   - **Turso**: Serverless SQLite\n\n3. **HTTP-based database access**:\n   - **Prisma Data Proxy**: HTTP connection to database\n   - **Supabase PostgREST**: HTTP API over PostgreSQL\n\nFor Vercel: **Neon** is the recommended PostgreSQL provider (Vercel partnership). It handles connection pooling natively and scales to zero when unused.\n\nAlternatively, use **Vercel KV** (Redis) and **Vercel Blob** (S3) for simple state, reserving the database for complex queries.")]),

    ("cloud", "Edge computing: When to use edge vs origin",
     ["Cloudflare Workers", "Vercel Edge", "AWS Lambda@Edge", "CDN", "Redis"],
     [("user", "Our API response times are 200-500ms from the US but 800-1200ms from Europe and Asia. Should we deploy to edge or add more regions?"),
      ("assistant", "Your latency pattern suggests the bottleneck is geographic distance. Options:\n\n**Option 1: Edge Functions (cheapest)**\n- Deploy lightweight logic to 300+ locations\n- **Cloudflare Workers** or **Vercel Edge Functions**\n- Best for: Auth checks, redirects, A/B testing, response transformation\n- Limitation: Can't access your database directly\n\n**Option 2: Multi-Region Database + API (most effective)**\n- Deploy API to US, EU, Asia-Pacific\n- Database read replicas in each region\n- Route users to nearest region (GeoDNS or CDN routing)\n- Cost: 3x infrastructure\n\n**Option 3: CDN + Cache (quickest win)**\n- Cache API responses at the edge\n- Cloudflare, Fastly, or CloudFront\n- `Cache-Control: max-age=60` for semi-static data\n- Reduces most requests to <50ms globally\n\n**Recommended approach**:\n1. **Now**: Add CDN caching for cacheable endpoints (quickest win)\n2. **Soon**: Move auth/routing to edge functions\n3. **Later**: Multi-region deployment for data that can't be cached"),
      ("user", "Most of our data is user-specific so caching is limited. Multi-region seems necessary?"),
      ("assistant", "For user-specific data, you're right that CDN caching is limited. Here's a practical multi-region approach:\n\n**Architecture**:\n1. **Primary region**: US (writes go here)\n2. **Read replicas**: EU, Asia-Pacific\n3. **Edge routing**: Route reads to nearest replica\n4. **Write routing**: All writes to primary (async replication)\n\n**Database options**:\n- **CockroachDB**: Multi-region by design, consistent reads\n- **PlanetScale**: MySQL with read replicas in multiple regions\n- **Neon**: Read replicas (simpler, PostgreSQL)\n- **Supabase**: Multi-region coming\n\n**If staying PostgreSQL**:\n1. Primary in US\n2. Streaming replicas in EU and APAC\n3. Application routes reads to nearest replica\n4. Writes go to primary (adds latency for non-US users)\n\nFor user-specific data: **CockroachDB** gives you the best multi-region experience with consistent reads. If you want to stay PostgreSQL, use read replicas with **Citus** for horizontal scaling or **Neon** for managed replicas.")]),
]

# Additional topics to fill out to 150
EXTRA_TOPICS = [
    ("web-development", "Form handling: React Hook Form vs Formik", ["React Hook Form", "Formik", "Zod", "Yup", "React"]),
    ("web-development", "Animation library: Motion vs GSAP", ["Motion", "GSAP", "CSS", "React", "Lottie"]),
    ("web-development", "i18n: next-intl vs react-i18next", ["next-intl", "react-i18next", "Next.js", "React", "ICU"]),
    ("web-development", "Component library: shadcn vs Radix vs MUI", ["shadcn/ui", "Radix UI", "Material UI", "Tailwind CSS", "React"]),
    ("web-development", "Monorepo tools: Turborepo vs Nx", ["Turborepo", "Nx", "pnpm", "Lerna", "npm"]),
    ("web-development", "Image optimization: Next/Image vs Cloudinary", ["Next.js", "Cloudinary", "imgix", "Sharp", "WebP"]),
    ("web-development", "Real-time: WebSocket vs SSE vs polling", ["WebSocket", "Server-Sent Events", "Socket.io", "React", "Redis"]),
    ("web-development", "CMS: Sanity vs Contentful vs Strapi", ["Sanity", "Contentful", "Strapi", "Next.js", "GraphQL"]),
    ("backend", "ORM selection: SQLAlchemy vs Tortoise vs Peewee", ["SQLAlchemy", "Tortoise ORM", "Peewee", "Python", "PostgreSQL"]),
    ("backend", "Task queue: Celery vs Dramatiq vs ARQ", ["Celery", "Dramatiq", "ARQ", "Redis", "Python", "RabbitMQ"]),
    ("backend", "API design: REST vs GraphQL vs tRPC", ["REST API", "GraphQL", "tRPC", "TypeScript", "Node.js"]),
    ("backend", "Caching strategy: Redis vs Memcached", ["Redis", "Memcached", "CDN", "PostgreSQL", "Node.js"]),
    ("backend", "Search engine: Elasticsearch vs Meilisearch vs Typesense", ["Elasticsearch", "Meilisearch", "Typesense", "Algolia"]),
    ("backend", "File storage: S3 vs GCS vs R2", ["Amazon S3", "Google Cloud Storage", "Cloudflare R2", "MinIO"]),
    ("backend", "Email service: SendGrid vs Resend vs Postmark", ["SendGrid", "Resend", "Postmark", "AWS SES", "SMTP"]),
    ("devops", "Monitoring: Prometheus vs InfluxDB vs TimescaleDB", ["Prometheus", "InfluxDB", "TimescaleDB", "Grafana"]),
    ("devops", "Log management: ELK vs Loki vs Datadog", ["Elasticsearch", "Loki", "Datadog", "Fluentd", "Grafana"]),
    ("devops", "Service mesh: Istio vs Linkerd vs Envoy", ["Istio", "Linkerd", "Envoy", "Kubernetes", "gRPC"]),
    ("devops", "DNS: Route53 vs Cloudflare DNS", ["Amazon Route 53", "Cloudflare", "DNS", "CDN", "AWS"]),
    ("devops", "SSL/TLS: Let's Encrypt vs AWS ACM", ["Let's Encrypt", "AWS ACM", "Nginx", "Cloudflare", "TLS"]),
    ("security", "Authentication: Passkeys vs passwords vs SSO", ["Passkeys", "WebAuthn", "OAuth 2.0", "SAML", "Okta"]),
    ("security", "WAF: Cloudflare vs AWS WAF vs ModSecurity", ["Cloudflare", "AWS WAF", "ModSecurity", "Nginx"]),
    ("security", "SAST: Semgrep vs SonarQube vs CodeQL", ["Semgrep", "SonarQube", "CodeQL", "GitHub", "Snyk"]),
    ("security", "Container scanning: Trivy vs Snyk vs Grype", ["Trivy", "Snyk", "Grype", "Docker", "Kubernetes"]),
    ("data-engineering", "Lakehouse: Delta Lake vs Iceberg vs Hudi", ["Delta Lake", "Apache Iceberg", "Apache Hudi", "Spark", "Databricks"]),
    ("data-engineering", "ETL: Fivetran vs Airbyte vs custom", ["Fivetran", "Airbyte", "Python", "Singer", "dbt"]),
    ("data-engineering", "Feature store: Feast vs Tecton", ["Feast", "Tecton", "Redis", "Spark", "MLflow"]),
    ("ml-ai", "LLM framework: LangChain vs LlamaIndex", ["LangChain", "LlamaIndex", "OpenAI", "Python", "RAG"]),
    ("ml-ai", "Fine-tuning: LoRA vs full fine-tune vs prompt engineering", ["LoRA", "QLoRA", "Hugging Face", "PEFT", "PyTorch"]),
    ("ml-ai", "Model serving: TensorFlow Serving vs Triton vs vLLM", ["TensorFlow Serving", "NVIDIA Triton", "vLLM", "FastAPI"]),
    ("mobile", "Navigation: React Navigation vs Expo Router", ["React Navigation", "Expo Router", "React Native", "Expo"]),
    ("mobile", "Push notifications: Firebase vs OneSignal vs Expo", ["Firebase Cloud Messaging", "OneSignal", "Expo", "APNs"]),
    ("systems", "Async runtime: Tokio vs async-std in Rust", ["Tokio", "async-std", "Rust", "Hyper", "Actix"]),
    ("systems", "Memory allocator: jemalloc vs mimalloc vs system", ["jemalloc", "mimalloc", "Rust", "Go", "C++"]),
    ("testing", "Mocking: MSW vs nock vs Mirage", ["MSW", "nock", "Mirage JS", "Vitest", "Playwright"]),
    ("testing", "Visual regression: Chromatic vs Percy vs Playwright", ["Chromatic", "Percy", "Playwright", "Storybook"]),
    ("architecture", "API versioning: URL path vs header vs content negotiation", ["REST API", "GraphQL", "OpenAPI", "Swagger"]),
    ("architecture", "Caching patterns: Write-through vs write-behind vs cache-aside", ["Redis", "Memcached", "PostgreSQL", "CDN"]),
    ("database", "Time-series: TimescaleDB vs InfluxDB vs QuestDB", ["TimescaleDB", "InfluxDB", "QuestDB", "PostgreSQL", "Grafana"]),
    ("database", "Full-text search: PostgreSQL FTS vs Elasticsearch vs Meilisearch", ["PostgreSQL", "Elasticsearch", "Meilisearch", "Typesense"]),
]

def generate_short_conversation(topic_info: tuple, rng: random.Random) -> list[dict]:
    """Generate a short 4-6 message conversation from a topic tuple."""
    domain, topic, entities, *_ = topic_info

    # Randomly select entities to discuss
    n_entities = min(len(entities), rng.randint(3, 5))
    selected = rng.sample(entities, n_entities)

    # Surface form variations
    def vary(name: str) -> str:
        r = rng.random()
        if r < 0.15 and len(name) > 3:
            return name.lower()
        if r < 0.25 and '.' in name:
            return name.replace('.', '')
        if r < 0.35 and ' ' in name:
            parts = name.split()
            return parts[0]
        return name

    messages = [
        {"role": "user", "content": f"I'm evaluating {vary(selected[0])} vs {vary(selected[1])} for our project. We're working on {topic.lower().split('for ')[-1] if 'for ' in topic.lower() else 'a new project'}. What would you recommend?"},
        {"role": "assistant", "content": f"Both {selected[0]} and {selected[1]} are solid choices. Here are the key differences:\n\n**{selected[0]}**: Popular, well-documented, large community. Good for most use cases.\n\n**{selected[1]}**: More modern approach, potentially better developer experience. Growing ecosystem.\n\nWhat are your specific requirements? Team size, performance needs, and existing tech stack matter for this decision."},
        {"role": "user", "content": f"Small team, 4 devs. We already use {vary(selected[2]) if len(selected) > 2 else 'TypeScript'}. Performance is important but developer productivity matters more."},
        {"role": "assistant", "content": f"For a small team prioritizing productivity, I'd recommend **{selected[1]}** because:\n\n1. Better DX with modern APIs\n2. Less boilerplate code\n3. Good integration with {selected[2] if len(selected) > 2 else 'your existing stack'}\n\nThe learning curve is manageable for 4 developers." + (f" You might also consider {selected[3]} as an alternative." if len(selected) > 3 else "")},
    ]

    # Sometimes add a follow-up
    if rng.random() < 0.6:
        follow_up_entity = vary(selected[-1]) if len(selected) > 2 else vary(selected[0])
        messages.extend([
            {"role": "user", "content": f"What about {follow_up_entity}? Does it integrate well with our setup?"},
            {"role": "assistant", "content": f"Yes, {selected[-1] if len(selected) > 2 else selected[0]} integrates well. It has official TypeScript support and good documentation. The community is active and you'll find plenty of examples and tutorials."},
        ])

    return messages


def main():
    rng = random.Random(42)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # Use the detailed templates first (30 detailed topics)
    all_topics = list(TOPICS)  # 30 detailed topics

    # Then add the short topics
    all_short_topics = list(EXTRA_TOPICS)  # 40 short topics

    conv_num = 51
    generated = 0

    # Phase 1: Write detailed conversations (conv-051 to conv-080)
    for topic in all_topics:
        if generated >= 150:
            break
        domain, topic_name, entities, messages = topic

        conv_id = f"conv-{conv_num:03d}"
        conversation = {
            "id": conv_id,
            "domain": domain,
            "topic": topic_name,
            "messages": [{"role": r, "content": c} for r, c in messages],
        }

        output_path = OUTPUT_DIR / f"{conv_id}.json"
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(conversation, f, indent=2, ensure_ascii=False)

        conv_num += 1
        generated += 1

    # Phase 2: Write short conversations from extra topics (conv-081 to conv-120)
    for topic_info in all_short_topics:
        if generated >= 150:
            break
        domain, topic_name, entities = topic_info

        conv_id = f"conv-{conv_num:03d}"
        messages = generate_short_conversation((domain, topic_name, entities), rng)

        conversation = {
            "id": conv_id,
            "domain": domain,
            "topic": topic_name,
            "messages": messages,
        }

        output_path = OUTPUT_DIR / f"{conv_id}.json"
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(conversation, f, indent=2, ensure_ascii=False)

        conv_num += 1
        generated += 1

    # Phase 3: Generate variations of existing topics to reach 150 (conv-121 to conv-200)
    variation_templates = [
        ("backend", "Comparing {e1} and {e2} for production deployment"),
        ("web-development", "Migrating from {e1} to {e2}"),
        ("devops", "Scaling {e1} with {e2}"),
        ("security", "Securing {e1} applications with {e2}"),
        ("data-engineering", "Building a {e1} pipeline using {e2}"),
        ("ml-ai", "Integrating {e1} with {e2} for ML workflows"),
        ("mobile", "Building a {e1} app with {e2} backend"),
        ("systems", "Performance optimization with {e1} and {e2}"),
        ("testing", "Testing {e1} applications with {e2}"),
        ("architecture", "Designing {e1} systems using {e2} patterns"),
    ]

    entity_pairs = [
        ("PostgreSQL", "Redis"), ("React", "Vue.js"), ("Docker", "Kubernetes"),
        ("FastAPI", "Django"), ("Next.js", "Nuxt"), ("TypeScript", "Go"),
        ("MongoDB", "DynamoDB"), ("Terraform", "Pulumi"), ("Jest", "Vitest"),
        ("Kafka", "RabbitMQ"), ("GraphQL", "REST API"), ("Nginx", "Caddy"),
        ("Python", "Rust"), ("SQLite", "PostgreSQL"), ("Redis", "Memcached"),
        ("AWS Lambda", "Cloudflare Workers"), ("Prisma", "Drizzle ORM"),
        ("React Native", "Flutter"), ("Playwright", "Cypress"), ("Webpack", "Vite"),
        ("Neo4j", "ArangoDB"), ("Spark", "Flink"), ("dbt", "Airflow"),
        ("Supabase", "Firebase"), ("TailwindCSS", "styled-components"),
        ("OpenAI", "Anthropic"), ("LangChain", "LlamaIndex"), ("Prometheus", "Datadog"),
        ("S3", "R2"), ("Auth0", "Clerk"), ("Snowflake", "BigQuery"),
        ("ECS", "GKE"), ("ArgoCD", "Jenkins"), ("Semgrep", "SonarQube"),
        ("Pinecone", "Qdrant"), ("MLflow", "W&B"), ("Celery", "Dramatiq"),
        ("PgBouncer", "Prisma"), ("Grafana", "Kibana"), ("Cloudflare", "AWS"),
    ]

    rng.shuffle(entity_pairs)

    pair_idx = 0
    while generated < 150:
        template_idx = generated % len(variation_templates)
        domain, topic_template = variation_templates[template_idx]

        e1, e2 = entity_pairs[pair_idx % len(entity_pairs)]
        pair_idx += 1

        topic_name = topic_template.format(e1=e1, e2=e2)
        entities = [e1, e2, "TypeScript", "Python", "Docker"]

        conv_id = f"conv-{conv_num:03d}"
        messages = generate_short_conversation((domain, topic_name, entities), rng)

        conversation = {
            "id": conv_id,
            "domain": domain,
            "topic": topic_name,
            "messages": messages,
        }

        output_path = OUTPUT_DIR / f"{conv_id}.json"
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(conversation, f, indent=2, ensure_ascii=False)

        conv_num += 1
        generated += 1

    print(f"Generated {generated} conversations (conv-051 to conv-{conv_num-1:03d})")

    # Update index.json
    index = {
        "total_conversations": conv_num - 1,
        "domains": {},
    }
    for f in sorted(OUTPUT_DIR.glob("conv-*.json")):
        with open(f) as fh:
            c = json.load(fh)
        d = c.get("domain", "unknown")
        if d not in index["domains"]:
            index["domains"][d] = 0
        index["domains"][d] += 1

    with open(OUTPUT_DIR / "index.json", "w") as f:
        json.dump(index, f, indent=2)

    print(f"Updated index.json: {index}")


if __name__ == "__main__":
    main()
