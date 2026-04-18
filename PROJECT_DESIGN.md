# Quant × ML × Full-Stack Project — Deep Design Document

*Prepared 2026-04-14. Written as a senior-staff design doc fused with a quant research spec.*

---

## Phase 1 — Project Selection

### Candidate Comparison

| # | Idea | One-liner | Tech Diff | Research Diff | Wow | Resume Value | Web-Product Fit |
|---|------|-----------|-----------|---------------|-----|--------------|-----------------|
| 1 | **Market Microstructure Simulator** | Agent-based LOB simulator with pluggable strategies + live dashboard | 9 | 8 | High | Very High (quant HFT / PM roles) | Strong |
| 2 | **RL Trading System** | PPO/SAC agents trained on historical order-book data, benchmarked vs. baselines | 9 | 9 | Medium-High (crowded) | High but derivative | Medium |
| 3 | **Regime Detection Dashboard** | HMM / change-point / deep-state-space models classifying market regimes in real time | 7 | 8 | Medium | High | Strong |
| 4 | **Institutional Risk Engine** | VaR / CVaR / stress-test / factor attribution engine with a modern UI | 8 | 7 | Medium | Very High (banks, HF risk) | Strong |
| 5 | **Alternative Data Alpha Platform** | Ingest satellite / web / sentiment data, build alpha signals, backtest, rank | 9 | 9 | High | Very High | Medium-Strong |
| 6 | **AI Hedge Fund Brain** | LLM + tool-use orchestrator ingesting news/filings/prices → thesis + position suggestions | 8 | 8 | High (trendy) | High but fuzzy | Strong |
| 7 | **Limit-Order-Book Forecasting SaaS** | Deep LOB model (DeepLOB / transformer) predicting short-horizon mid-price moves, served as API | 9 | 9 | High | Very High | Strong |
| 8 | **Execution Algo Lab** | VWAP/TWAP/IS + RL execution, transaction-cost analysis, broker-agnostic backtester | 9 | 8 | High | Very High | Strong |

### Ranking & Recommendation

**Ranked:** (1) Market Microstructure Simulator → (7) LOB Forecasting → (8) Execution Lab → (4) Risk Engine → (5) Alt Data → (3) Regime → (6) AI Fund → (2) RL Trading.

**Chosen: #1 — Market Microstructure Simulator, *with an embedded LOB forecasting module (#7) and execution lab (#8) as advanced features*.**

**Why this wins:**
- Differentiated: very few public projects simulate a *full* continuous-double-auction LOB with heterogeneous agents *and* expose it as a product.
- Research-rich: combines Hawkes processes, queue-reactive models, DeepLOB, market-impact theory (Almgren-Chriss, propagator models), RL execution, and agent-based modeling.
- Visually stunning: order book heatmaps, trade tapes, P&L curves — Bloomberg-Terminal energy.
- Naturally extends into forecasting-as-a-service and execution analytics → startup surface area.
- Portfolio flex: demonstrates systems engineering (low-latency event loop), quant (stochastic processes), ML (sequence models), and product (dashboard + API).

Working title: **Orderflow Lab** (placeholder).

---

## Phase 2 — Deep Project Breakdown

### Product Vision
**Problem.** Quant researchers, students, and trading-tech teams lack a reproducible, visual, programmable sandbox to (a) simulate realistic limit-order-book dynamics, (b) plug in and benchmark strategies (market-making, execution, stat-arb), and (c) study microstructure phenomena (flash crashes, toxic flow, queue priority) without paying six figures for a vendor platform.

**Users.**
- Quant students / candidates preparing for HFT interviews.
- Buy-side execution & microstructure researchers prototyping ideas.
- Educators teaching market microstructure.
- Eventually: small prop shops using it as a replay/what-if engine.

**Why different.** Existing open tools are either (a) toy matching engines (no realistic agent flow), (b) closed vendor systems (Kx, OneTick), or (c) raw research code (ABIDES) without UX. Orderflow Lab unifies a *fast C++/Rust matching engine core* + *calibrated agent generators (Hawkes, queue-reactive)* + *ML forecaster* + *browser-native visualization* in one deployable product.

### Core Features

**MVP (Weeks 1–6)**
| Feature | Purpose | Inputs | Outputs | Complexity |
|---|---|---|---|---|
| Matching engine (price-time priority, CDA) | Deterministic core | Order events | Trades, book snapshots | High |
| Synthetic flow generator (Poisson + mean-reversion) | Produce realistic-ish order flow | Config (λ, μ, σ) | Order stream | Medium |
| Strategy SDK (Python) | Users write agents | `on_book_update`, `on_trade` hooks | Orders | Medium |
| Replay from CSV/Parquet | Run against real L2 data (LOBSTER / Binance) | Historical file | Same event bus | Medium |
| Web dashboard — live book + tape | Visualize sim | WS stream | Heatmap, tape, P&L | High |
| Scenario runner + results store | Reproducibility | Config YAML | Run artifacts | Medium |

**Advanced (Weeks 7–12)**
- Hawkes-process multivariate order-flow generator (self- & cross-exciting).
- Queue-reactive model (Huang–Lehalle–Rosenbaum).
- DeepLOB-style transformer forecaster → served as gRPC/REST.
- RL execution agent (PPO) solving Almgren-Chriss-flavored optimal execution.
- Market-impact calibration (propagator / TIM model).
- Multi-asset, cross-venue arbitrage sandbox.

**Research / Future**
- Generative LOB (diffusion or GAN over order flow).
- Toxic-flow / adverse-selection detection (VPIN, Kyle’s λ online estimation).
- Causal inference on strategy interactions (agent ablation studies).
- Federated replay: users submit encrypted strategies for public leaderboard.

---

## Phase 3 — Full-Stack Architecture

### Frontend

| Concern | Choice | Why |
|---|---|---|
| Framework | **Next.js 15 (App Router)** + React 19 | SSR for marketing pages, RSC for heavy dashboards, Vercel-friendly |
| Language | **TypeScript (strict)** | Non-negotiable for a data-dense UI |
| Styling | **Tailwind v4** + **shadcn/ui** | Fast, modern, consistent primitives |
| Charts | **uPlot** (order book heatmap, tick data — 1M+ points), **Recharts** (summary cards), **D3** (custom depth chart), **Plotly** (research notebooks view) | uPlot is the only lib that handles tick-frequency data smoothly in-browser |
| State | **Zustand** (client) + **TanStack Query** (server state) + **Jotai** for derived atoms | Redux is overkill; Zustand + Query is the 2026 default |
| Real-time | **native WebSocket** + **binary frames (MessagePack)** | JSON is 3–5x too fat for L2 updates at 1k msg/s |
| Animation | **Framer Motion** (sparingly — transitions, not decoration) | |
| Auth | **Clerk** (MVP) → self-hosted **Auth.js + Postgres** later | Clerk accelerates; migration path is clean |
| Monorepo | **Turborepo + pnpm** | Standard |

### Backend

| Concern | Choice | Why |
|---|---|---|
| API gateway | **FastAPI** (Python 3.12) | Great for ML, Pydantic v2 validation, async |
| Matching engine core | **Rust** (crate: `orderbook-core`) exposed via **PyO3** | Python is too slow for the hot loop (target: 1M msg/s single-thread) |
| Async jobs | **Celery + Redis** (MVP), later **Temporal** | Temporal wins for long-running simulations with retries |
| ML serving | **Triton Inference Server** or **BentoML** | Keeps GPU models off the API box |
| Streaming bus | **Redis Streams** (MVP) → **Redpanda/Kafka** | Replay needs ordered, replayable log |
| API style | **REST** for CRUD, **WebSocket** for live, **gRPC** between services | GraphQL overkill here; payload shapes are stable |
| Caching | **Redis** (hot book snapshots, user sessions, rate limits) | |
| Data processing | **Polars** (not pandas), **DuckDB** for ad-hoc | 10–50x pandas for tick data |

### Database

Primary: **PostgreSQL 16** with **TimescaleDB** extension. Reason: hypertables for tick/trade data, standard relational for users/scenarios, plus continuous aggregates for dashboards. A separate vector DB is *not* needed MVP; use `pgvector` if a similarity-search feature appears.

**Schema proposal (abridged):**

```sql
-- Users & workspaces
users(id uuid pk, email citext unique, created_at timestamptz, plan text)
workspaces(id uuid pk, owner_id uuid fk, name text, created_at timestamptz)

-- Scenarios (simulation configs)
scenarios(
  id uuid pk, workspace_id uuid fk, name text,
  config jsonb,            -- generator params, strategies, seeds
  git_sha text,            -- engine version
  created_at timestamptz
)

-- Runs
runs(
  id uuid pk, scenario_id uuid fk, status text,
  started_at timestamptz, finished_at timestamptz,
  seed bigint, engine_version text,
  metrics jsonb            -- summary KPIs for fast listing
)

-- Time-series (Timescale hypertables, partitioned by time)
events (
  run_id uuid, ts timestamptz, seq bigint,
  type smallint,           -- 0=add,1=cancel,2=modify,3=trade
  side smallint, price numeric(18,8), qty numeric(18,8),
  agent_id int,
  PRIMARY KEY (run_id, ts, seq)
) ;  -- hypertable on ts, chunk 1h, compress after 1d

book_snapshots (run_id, ts, depth int, bids jsonb, asks jsonb)  -- hypertable
pnl_curve     (run_id, agent_id, ts, cash, inventory, mtm)      -- hypertable

-- Strategy registry
strategies(id uuid pk, user_id uuid fk, name, language, source_hash, created_at)

-- Benchmarks / leaderboard
leaderboard_entries(run_id, strategy_id, metric text, value numeric, rank int)
```

**Indexes.** `events (run_id, ts DESC)`, `runs (workspace_id, created_at DESC)`, GIN on `scenarios.config`, hypertable compression after 24h. Continuous aggregate: `book_1s` downsample for fast zoom-out rendering.

### Cloud / Infrastructure

**MVP (cheap, ≈$40–80/mo):**
- Frontend: **Vercel Hobby/Pro** ($0–20).
- API + workers + engine: single **Fly.io** app with 2× shared-cpu-2x (~$15).
- DB: **Neon** (Postgres) + **Timescale Cloud dev** (~$0–20), **Upstash Redis** ($0–10).
- Object storage (run artifacts, parquet): **Cloudflare R2** ($0.015/GB, no egress).
- Secrets: Fly secrets; later **Doppler** or **AWS Secrets Manager**.
- CI/CD: **GitHub Actions** → Docker build → Fly deploy; preview deploys on PR.
- Observability: **Grafana Cloud free** (logs + metrics) + **Sentry free**.

**Scaled (~$500–2k/mo when paying users):**
- AWS: **EKS** (API/workers) + **Fargate** spot for batch sims + **RDS Postgres + self-hosted Timescale** on EC2 (i4i.large for NVMe) + **ElastiCache Redis** + **MSK** (Kafka) + **S3** + **CloudFront**.
- GPU: **Lambda Labs** or **RunPod** spot for model training; **g5.xlarge** on-demand for Triton serving.
- IaC: **Terraform** modules per environment (`dev`, `staging`, `prod`).
- Monitoring: **Prometheus + Grafana + Loki + Tempo** (OpenTelemetry).

---

## Phase 4 — Research Requirements

### Key Papers (study order)

| # | Paper | Why it matters | Takeaway | Impl. Diff |
|---|---|---|---|---|
| 1 | Gould et al. 2013 — *Limit Order Books* (survey) | Foundational vocabulary | Book dynamics, stylized facts | Low (read) |
| 2 | Cont, Stoikov, Talreja 2010 — *A stochastic model for order book dynamics* | Baseline generator | Birth-death process on each level | Medium |
| 3 | Hawkes 1971 + Bacry, Mastromatteo, Muzy 2015 *Hawkes processes in finance* | Self-excitation is **the** stylized fact | Fit multivariate Hawkes to event types | High |
| 4 | Huang, Lehalle, Rosenbaum 2015 *Queue-Reactive Model* | State-dependent intensities | Reproduce real LOB shape | Medium-High |
| 5 | Almgren & Chriss 2000 *Optimal Execution* | Execution benchmark | Closed-form optimal trajectory | Low (math) / Medium (impl) |
| 6 | Obizhaeva & Wang 2013 *Optimal trading with transient impact* | Propagator model | Non-trivial impact calibration | High |
| 7 | Zhang, Zohren, Roberts 2019 *DeepLOB* | Deep short-horizon forecaster | CNN+LSTM on 40-level LOB | Medium |
| 8 | Kolm, Turiel, Westray 2023 *Deep order-flow imbalance* | OFI features beat raw LOB | Feature engineering | Medium |
| 9 | Byrd, Hybinette, Balch 2020 *ABIDES* | Prior art for agent-based sim | Architecture reference | — |
| 10 | Schulman et al. 2017 *PPO* + Nevmyvaka et al. 2006 *RL for optimal execution* | RL baseline | Policy for child-order placement | High |
| 11 | Cartea, Jaimungal, Penalva *Algorithmic & HFT* (book) | The canonical text | Stochastic control toolbox | — |

### Open source to read (not copy)
- **ABIDES-Markets** (JPMC) — reference agent-based sim.
- **hftbacktest** (nkaz001) — Rust/Python L2 backtester, excellent for execution latency modeling.
- **mbt-gym** — microstructure RL gym.
- **tick** (X-DataInitiative) — Hawkes estimation.
- **Databento / LOBSTER samples** — real L2 data.

### Math you must own
Poisson & Hawkes processes, doubly-stochastic intensities, continuous-time Markov chains on the book state, Kyle’s λ, VPIN, Almgren-Chriss HJB, stochastic optimal control, Kalman & particle filters (for queue position), attention / causal masking (for DeepLOB-T).

---

## Phase 5 — System Design Details

### Service Topology (ASCII)

```
┌────────────┐  WS/REST   ┌──────────────┐   gRPC    ┌────────────────┐
│  Next.js   │──────────▶│   FastAPI    │──────────▶│  Engine (Rust) │
│  (Vercel)  │◀──────────│   Gateway    │◀──────────│  matching+sim  │
└────────────┘  SSE/WS    └──────┬───────┘           └──────┬─────────┘
                                 │                          │ events
                                 ▼                          ▼
                         ┌───────────────┐          ┌────────────────┐
                         │ Celery/Temporal│─────────│ Redis Streams  │
                         │   workers     │          │  (event log)   │
                         └──────┬────────┘          └──────┬─────────┘
                                │                          │
                 ┌──────────────┼──────────────┐           │
                 ▼              ▼              ▼           ▼
          Postgres+Timescale   R2/S3       Triton      Prometheus
          (runs, ts data)    (parquet)   (DeepLOB)     (metrics)
```

### REST API (excerpt)

```
POST   /v1/scenarios              → create scenario
GET    /v1/scenarios/:id
POST   /v1/scenarios/:id/run      → enqueue run, returns run_id
GET    /v1/runs/:id               → status + summary metrics
GET    /v1/runs/:id/events?from=&to=&type=  → paginated events (parquet or json)
GET    /v1/runs/:id/book?ts=      → book snapshot at t
POST   /v1/strategies             → upload/register strategy
GET    /v1/leaderboard?metric=sharpe
WS     /v1/runs/:id/stream        → live events (msgpack frames)
POST   /v1/forecast               → DeepLOB inference (features in, distribution out)
```

**Example** `POST /v1/scenarios`:
```json
{
  "name": "MM vs toxic flow",
  "duration_s": 3600,
  "seed": 42,
  "asset": {"tick_size": 0.01, "lot_size": 1},
  "generators": [
    {"type": "hawkes", "params_ref": "calibrated/BTC-USDT-2024Q4"}
  ],
  "agents": [
    {"id": "mm1", "strategy": "avellaneda_stoikov", "params": {"gamma": 0.1, "k": 1.5}},
    {"id": "tox", "strategy": "informed_trader", "params": {"signal_snr": 0.3}}
  ],
  "metrics": ["pnl", "inventory_rms", "fill_ratio", "adverse_selection"]
}
```

Response `POST /v1/forecast`:
```json
{
  "model": "deeplob-t-v0.3",
  "horizon_ticks": 10,
  "proba": {"up": 0.41, "flat": 0.37, "down": 0.22},
  "expected_return_bps": 0.8,
  "inference_ms": 2.4
}
```

### Background Jobs
- `run_simulation(run_id)` — Temporal workflow; child activities: `prepare_data`, `spawn_engine`, `stream_events`, `persist_artifacts`, `compute_metrics`.
- `calibrate_hawkes(dataset_id)` — fit MLE, store params.
- `train_deeplob(dataset_id, config)` — GPU queue.
- `nightly_leaderboard_refresh`.

### Event Flow (one simulated tick)
1. Engine advances clock; generator samples next event from calibrated Hawkes intensity.
2. Event applied to in-memory book; resulting trades emitted.
3. Engine pushes `(run_id, seq, event)` to Redis Stream + append to parquet buffer.
4. Strategy agents (in same process for speed; sandboxed for user code) receive callbacks and may enqueue orders.
5. Gateway fans out via WebSocket (msgpack) at decimated rate (e.g., 60 fps) to browser.
6. Every 1s: snapshot + PnL flushed to Timescale.

### Folder Structure (Turborepo)

```
orderflow-lab/
├── apps/
│   ├── web/                 # Next.js
│   └── docs/                # Mintlify or Nextra
├── services/
│   ├── api/                 # FastAPI
│   ├── workers/             # Celery/Temporal
│   └── engine/              # Rust crate + PyO3 bindings
├── packages/
│   ├── ui/                  # shadcn components
│   ├── sdk-ts/              # typed client for the API
│   ├── sdk-py/              # Python SDK for strategies
│   └── schema/              # Pydantic + zod mirrored models (generated)
├── infra/
│   ├── terraform/
│   └── docker/
├── research/
│   ├── notebooks/
│   └── papers/
└── .github/workflows/
```

### Testing
- Engine: property-based (Hypothesis + proptest) on invariants (price-time priority, conservation of quantity, no self-trade).
- Determinism: same seed → byte-identical event log (hash asserted in CI).
- Performance: criterion (Rust) budget of ≥500k events/s single-thread.
- API: pytest + schemathesis (OpenAPI fuzz).
- Frontend: Playwright for dashboard interactions; Storybook for components.
- Research: notebook regression (papermill) on reference datasets.

---

## Phase 6 — UI / UX

Aesthetic: **Bloomberg-Terminal-meets-Linear**. Dark-first (#0B0D12 background, #E6E9EF text, electric-teal #2AF1C9 accent for bids, magenta #F23BB7 for asks, desaturated amber for warnings). Fonts: **Inter** UI, **JetBrains Mono** numerics. Dense grids, thin 1px dividers, tabular numbers, zero emoji.

### Pages

| Page | Purpose | Key Components |
|---|---|---|
| `/` Landing | Convert | Hero with live mini-sim canvas, feature grid, pricing |
| `/app` Dashboard | Portfolio of runs | Run cards, quick-filters, recent activity |
| `/app/scenarios/new` | Scenario builder | Form wizard (asset → generators → agents → metrics) + YAML side-by-side |
| `/app/runs/[id]` | **The star page** | Live book heatmap (uPlot), trade tape (virtualized), depth chart (D3), PnL by agent (Recharts), event inspector (time-scrubber), metric strip |
| `/app/strategies` | Registry | Code editor (Monaco), backtest launcher, versions |
| `/app/datasets` | Real-data management | Upload, calibration status |
| `/app/research` | Notebooks | Embedded JupyterLite or links to Quarto reports |
| `/app/leaderboard` | Public rankings | Sortable table, filters |
| `/app/settings` | Org, API keys, billing |

### Dashboard Shell
Left rail (icon nav), top bar (workspace switcher, command-k palette, status LED for engine), main canvas, right inspector panel (contextual). Command palette (⌘K) is the primary power-user affordance.

### Live Run Page Layout
```
┌───────────────────────────────────────────────────────────────┐
│ Top strip: run meta | elapsed | speed ▶ ▮▮ | seed | share     │
├──────────────────────────────┬────────────────────────────────┤
│  Book Heatmap (price × time) │ Depth snapshot (live)          │
│  uPlot, ~120 fps             │ D3, bid/ask ladder             │
├──────────────────────────────┼────────────────────────────────┤
│  Trade Tape (virtualized)    │ PnL per agent (Recharts)       │
├──────────────────────────────┴────────────────────────────────┤
│  Time scrubber + event inspector (seek anywhere, deterministic)│
└───────────────────────────────────────────────────────────────┘
```

---

## Phase 7 — Development Roadmap

**Week 1–2 — Foundations**
- Monorepo + CI; Dockerized dev.
- Rust matching engine v0 (price-time priority, FIFO queues, add/cancel/modify/trade). Property tests.
- FastAPI skeleton, Postgres+Timescale schema migration (Alembic).
- Next.js shell, auth (Clerk), design system.

**Week 3–4 — Simulation loop**
- Python strategy SDK + 2 reference strategies (random MM, Avellaneda–Stoikov).
- Poisson + mean-reversion generator.
- WS pipeline from engine → gateway → browser; book heatmap + tape rendering.
- Scenario + run persistence; rerun-by-seed determinism CI check.

**Week 5–6 — MVP Polish**
- Replay from LOBSTER/Binance sample.
- PnL, inventory, fill-ratio metrics + charts.
- Scenario builder UI.
- Deploy to Fly + Vercel; landing page live.
- → **Shippable MVP.**

**Week 7–8 — Realism**
- Multivariate Hawkes calibrator (use `tick`), integrate as generator.
- Queue-reactive model.
- Leaderboard + strategy registry.

**Week 9–10 — ML**
- DeepLOB-T training pipeline on LOBSTER; Triton serving.
- `/forecast` endpoint + UI overlay (predicted drift on the heatmap).

**Week 11–12 — Execution Lab**
- Almgren-Chriss closed-form solver + RL (PPO) execution agent vs. TWAP/VWAP baselines.
- Transaction-cost analysis page.

**Week 13+ — Moat**
- Propagator-model impact calibration.
- Public API + SDKs polished; docs site; pricing; Stripe.
- Write-up / arXiv note on calibration methodology.

**Smallest MVP:** deterministic Rust engine + Poisson generator + 1 reference strategy + live book heatmap on a browser. That alone is already a standout GitHub repo.

**Most impressive final:** calibrated multivariate Hawkes + queue-reactive book + DeepLOB forecast overlay + RL execution benchmark, all behind a polished SaaS with public leaderboard and published methodology.

---

## Phase 8 — Leverage Claude-Style Strengths

### 1. First-Principles Justifications (trade-offs made explicit)

- **Rust engine vs pure Python.** Python’s GIL and allocator make 1M msg/s infeasible in-process. Rust+PyO3 gives C-speed with ergonomic FFI. Alternative considered: C++ + pybind11 (harder build, worse tooling); Go (no stable Python FFI story). **Chosen:** Rust.
- **Timescale vs ClickHouse.** ClickHouse is faster for analytic scans but adds an operational surface. Timescale lets users, scenarios, and ticks live in one engine, with Postgres’ transactional guarantees. **Chosen:** Timescale now; ClickHouse later *only if* analytics become the bottleneck.
- **WebSocket+MsgPack vs SSE+JSON.** SSE is one-way and text-only; our rate (up to 10k msg/s bursts) demands binary. **Chosen:** WS + MsgPack; decimate on server to ≤60 fps.
- **Temporal vs Celery.** Celery is simpler; Temporal survives long simulations, retries, and versioning. **Chosen:** Celery for MVP, Temporal at scale.

### 2. Paper → Implementation (example: Multivariate Hawkes)

**Intuition.** Events beget events. A market order often triggers further market orders (self-excitation) and often precedes cancels on the opposite side (cross-excitation).

**Math.** Intensity for event type *i*:
λᵢ(t) = μᵢ + Σⱼ ∫₀ᵗ φᵢⱼ(t−s) dNⱼ(s), with exponential kernels φᵢⱼ(u) = αᵢⱼ βᵢⱼ e^{−βᵢⱼ u}. Stability: spectral radius of α/β < 1.

**Pseudocode (Ogata thinning simulation):**
```
t = 0
while t < T:
    λ_bar = sum_i λ_i(t)          # upper bound via current intensities
    u ~ Exp(λ_bar); t += u
    if t >= T: break
    d ~ Uniform(0, λ_bar)
    cum = 0
    for i in event_types:
        cum += λ_i(t)
        if d < cum:
            emit(i, t); update_intensities(i, t); break
```

**Production pitfalls.** (1) Numerical overflow of exponentials → recurrence update: λᵢⱼ(t_k) = e^{−βᵢⱼ Δ} λᵢⱼ(t_{k−1}) + αᵢⱼ. (2) Calibration non-convexity → use MLE with multiple restarts or EM (Lewis–Mohler). (3) Regime changes break stationarity → fit per-hour-of-day buckets. (4) Microsecond timestamps with ties → jitter or use event-sequence indexing.

### 3. Systems Thinking — Bottlenecks & Failure Modes

| Layer | Bottleneck | Mitigation |
|---|---|---|
| Engine hot loop | Cache misses on book data structures | Use array-backed price levels (not hashmaps), SoA layout, `#[inline]` |
| Engine ↔ gateway | Serialization | Zero-copy via `rkyv` or flat buffers; decimate before WS |
| WS → browser | JS main thread | Offload decode to Web Worker; uPlot is canvas-based |
| DB writes | Tick insert rate | Batched COPY into Timescale; compress chunks >24h |
| API latency | N+1 queries | TanStack Query + server-side joins; pgbouncer |
| User strategy code | Arbitrary Python (RCE risk) | gVisor / Firecracker sandbox per run; CPU & memory cgroups; no network |

Observability: OpenTelemetry traces from browser click → WS → engine step → DB write, single trace ID.

### 4. Code Quality Patterns
Pydantic v2 everywhere on the boundary; zod mirrors generated from OpenAPI. Services follow a clean split: `api/` (transport) → `services/` (use-cases) → `domain/` (pure models) → `infra/` (repos, clients). Errors are typed (`Result<T, EngineError>` in Rust; exception hierarchy + problem-details JSON in FastAPI). No `any`, no bare `except`.

### 5. Self-Critique of the Design

Weaknesses:
- **Scope risk.** Hawkes + DeepLOB + RL + SaaS is a lot. Mitigation: strict roadmap gates; ship MVP at Week 6 even if only Poisson flow exists.
- **Data licensing.** LOBSTER is free for non-commercial; Databento costs real money at scale. Mitigation: design data layer so real vs synthetic is a provider interface; commercial SKU starts only when revenue justifies licensing.
- **User-code sandboxing** is the single scariest infra item. Mitigation: MVP ships with strategies only as *configurations of built-ins* (no arbitrary code); arbitrary-code execution is Week 10+ behind Firecracker.
- **Rust/Python build matrix** can rot CI. Mitigation: `maturin` + cibuildwheel; pin toolchains.
- **Benchmark integrity.** Leaderboards invite gaming (lookahead, unrealistic fill assumptions). Mitigation: server-side deterministic execution; strategies see only the event stream the server chooses to expose.

Improvements to fold in now: (i) define a `ReplayProvider` interface v0 so historical vs synthetic is swappable; (ii) add a `/health/determinism` endpoint that reruns a canonical scenario and compares hashes; (iii) publish a public benchmark scenario from day one — it becomes a marketing artifact.

---

## Phase 9 — Format Note
This document is intentionally dense and specific: no generic advice, every choice justified, concrete code/schemas/APIs. Diagrams are ASCII for portability; swap for excalidraw in the docs site.

---

## Final Deliverable — Executive Summary

**1. Final Project Concept.**
**Orderflow Lab** is a production-grade market microstructure simulator and research platform. A Rust-core matching engine paired with calibrated stochastic order-flow generators (Poisson → multivariate Hawkes → queue-reactive) drives a browser-native, Bloomberg-Terminal-style dashboard where users run, replay, and benchmark trading strategies against realistic limit-order books. An ML layer adds DeepLOB-style short-horizon forecasting and an RL-trained execution agent, all exposed through a typed API and a public leaderboard — turning a research sandbox into a SaaS.

**2. Core Technical Stack.** Next.js 15 + TS + Tailwind + shadcn + uPlot/D3 · FastAPI + Pydantic v2 · Rust engine via PyO3 · Postgres + TimescaleDB · Redis Streams · Celery → Temporal · Triton for models · Fly.io + Vercel + R2 (MVP) → AWS EKS + RDS + MSK (scale) · Terraform + GitHub Actions · OpenTelemetry + Grafana Cloud.

**3. Key Research Components.** Multivariate Hawkes calibration; queue-reactive (Huang–Lehalle–Rosenbaum); DeepLOB-T forecaster; Almgren–Chriss + PPO execution; propagator-model market impact; VPIN/Kyle’s-λ toxicity metrics.

**4. Architecture Overview.** Browser ↔ FastAPI gateway ↔ Rust engine (in-process via PyO3 for MVP, out-of-process gRPC at scale). Event log on Redis Streams, persisted to Timescale + R2. Async workflows on Temporal. Models served by Triton. Deterministic by seed end-to-end; user interactions are time-scrubs over an immutable event log.

**5. Build Plan.** Wk1-2 engine+infra · Wk3-4 sim loop+WS · Wk5-6 MVP polish & deploy · Wk7-8 Hawkes+queue-reactive · Wk9-10 DeepLOB · Wk11-12 execution lab · Wk13+ docs, SDKs, commercial.

**6. Biggest Technical Risks.** (a) Performance cliff if engine design is Pythonic. (b) User-strategy sandbox as security boundary. (c) Data licensing for real L2. (d) Calibration instability of Hawkes over non-stationary windows. (e) Scope creep swallowing Week 6 ship.

**7. Biggest Leverage Points.** (a) Determinism as a product — reproducibility is rare and sellable. (b) The live heatmap is a viral visual — single best marketing asset. (c) Open public benchmark scenarios become an academic citation path. (d) The SDK converts passive viewers into contributors, feeding the leaderboard flywheel. (e) One genuine calibrated Hawkes + queue-reactive generator is publishable on its own; bundling it with a usable UI is category-defining.
