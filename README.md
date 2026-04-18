# Orderflow Lab

Market microstructure simulator and research platform. Rust matching engine, FastAPI gateway, Next.js dashboard. See `PROJECT_DESIGN.md` for the full design.

## Layout

```
orderflow-lab/
├── apps/
│   ├── web/                 # Next.js 15 dashboard
│   └── docs/                # (placeholder)
├── services/
│   ├── api/                 # FastAPI gateway (Python 3.12)
│   ├── engine/              # Rust matching engine (PyO3 later)
│   └── workers/             # (placeholder — Celery/Temporal)
├── packages/
│   ├── ui/                  # shadcn component library
│   ├── sdk-ts/              # typed TS client
│   ├── sdk-py/              # Python strategy SDK
│   └── schema/              # shared Pydantic + zod models
├── infra/
│   ├── docker/              # docker-compose for local dev
│   └── terraform/           # (placeholder)
└── research/
    ├── notebooks/
    └── papers/
```

## Prerequisites

- Node >= 20.10, pnpm >= 10
- Python 3.12
- Rust (stable) via rustup
- Docker + Docker Compose

## Quickstart

```bash
# Install JS workspace deps
pnpm install

# Start local infra (Postgres+Timescale, Redis)
docker compose -f infra/docker/docker-compose.yml up -d

# Run the web app
pnpm --filter @orderflow/web dev
```

See each package for service-specific instructions.
