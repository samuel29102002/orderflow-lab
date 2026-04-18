# Orderflow Lab — Final State

*Frozen at the end of Week 11–12 (Execution Lab). This document is the
single source of truth for what exists, where it lives, and how the pieces
fit together. Companion to `PROJECT_DESIGN.md` (the original roadmap);
where they disagree, this file wins.*

---

## 1. One-paragraph summary

Orderflow Lab is a self-contained market-microstructure simulator and
research platform. A Rust matching engine (`services/engine`) is driven by
pluggable Python flow generators (Poisson / Hawkes / Queue-Reactive) via a
PyO3 bridge. A FastAPI gateway (`services/api`) runs the simulation on an
asyncio loop, feeds a DeepLOB neural forecaster (PyTorch CPU), drives a
DeepLOB-signal-based trading agent, and broadcasts the resulting book +
trades + forecast + agent state over a single WebSocket. A Next.js 15
dashboard (`apps/web`) renders the order book, mid-price chart, trade tape,
a live forecast badge, and an Agent P&L card. Everything runs locally —
no GPU, no external data feed, no paid infra.

---

## 2. Repository layout

```
quant/
├── apps/
│   └── web/                 # Next.js 15 dashboard (client)
├── services/
│   ├── engine/              # Rust matching engine (cargo workspace)
│   │   ├── core/            # pure-Rust book: price-time priority, L2 depth
│   │   └── py/              # PyO3 bindings → orderflow_engine module
│   └── api/                 # FastAPI gateway (Python 3.12)
│       └── app/
│           ├── core/        # Settings (pydantic-settings) — env-driven config
│           ├── domain/      # Pydantic wire schemas
│           ├── services/    # simulation / forecast / agent_driver / broadcaster
│           ├── api/         # HTTP + WebSocket routers
│           └── main.py      # create_app + lifespan DI
├── packages/
│   ├── sdk-py/              # Python strategy SDK (importable engine wrapper + agents)
│   │   └── src/orderflow_sdk/
│   │       ├── engine.py    # Engine wrapper around OrderBook
│   │       ├── flow/        # PoissonFlowGenerator / HawkesFlowGenerator / QueueReactiveFlowGenerator
│   │       ├── events.py    # LimitOrderEvent dataclass
│   │       └── agents/      # DeepLOBAgent + ForecastSignal + AgentAction
│   ├── sdk-ts/              # (placeholder)
│   ├── ui/                  # (placeholder, Tailwind v4 shared tokens)
│   └── schema/              # (placeholder)
├── research/
│   ├── collect_data.py      # Hawkes-driven LOB dataset collector → parquet
│   ├── train_deeplob.py     # PyTorch trainer, class-weighted CE
│   ├── artifacts/           # trained deeplob.pt checkpoint lives here
│   ├── datasets/            # parquet snapshots
│   └── notebooks/
├── infra/
│   └── docker/              # Docker-compose for local Postgres/Redis (not on critical path)
├── PROJECT_DESIGN.md        # Original 12-week roadmap
└── FINAL_STATE.md           # *this file*
```

---

## 3. Data flow (single WebSocket tick)

```
┌──────────────────────────┐     ┌──────────────────┐
│ FlowGenerator            │     │ DeepLOBAgent     │
│ (Poisson / Hawkes / QR)  │     │ (pure Python)    │
│  • observe(book_state)   │     │  • decide()      │
│  • next() → LimitOrder   │     │  • on_fill()     │
└───────────┬──────────────┘     └────────┬─────────┘
            │ Event stream                │
            ▼                             ▼
     ┌──────────────────────────────────────────────┐
     │ Simulation tick loop (services/api)          │
     │   1. observe → flow                          │
     │   2. consume events → engine.apply_limit     │
     │   3. build L2 snapshot                       │
     │   4. Forecaster.push_snapshot + predict      │
     │   5. AgentDriver.step (engine.submit/cancel) │
     │   6. Broadcaster.publish(BookSnapshot)       │
     └────────────┬─────────────────────────────────┘
                  │ model_dump_json
                  ▼
     ┌──────────────────────────────────────────────┐
     │ Broadcaster (fan-out, per-client queues)     │
     │   • drops oldest on slow client              │
     │   • exposes latest_agent_state for /health   │
     └────────────┬─────────────────────────────────┘
                  │ WebSocket /ws/stream
                  ▼
     ┌──────────────────────────────────────────────┐
     │ Next.js client (apps/web)                    │
     │   useOrderflowStream → { snapshot, trades,   │
     │     priceSeries, forecast, agent, ... }      │
     │   → OrderBookPanel / PriceChart / TradeTape  │
     │     / ForecastBadge / AgentCard              │
     └──────────────────────────────────────────────┘
```

Every 1/`tick_hz` seconds the simulation atomically advances the book,
builds one `BookSnapshot`, and fans it out. The agent's decision happens
**inside** the same tick under the simulation lock, so trades the agent
takes are visible on the same frame they were executed.

---

## 4. Components, annotated

### 4.1 Rust matching engine (`services/engine/core`)
- Price-time priority, L2 depth, `BTreeMap<Price, VecDeque<ResidentOrder>>`
- Exposes: `submit`, `cancel`, `modify`, `best_bid/ask`, `spread`, `mid`,
  `level_prices`, `level_qty`, `level_orders`, `contains`, `__len__`
- **Trade record**: `seq, maker_id, taker_id, taker_side, price, qty` — the
  `maker_id` field is what lets the Python agent driver attribute fills to
  its own resting orders.
- 22 Rust tests green (`cargo test`).

### 4.2 PyO3 bridge (`services/engine/py`)
- Surfaces `OrderBook`, `NewOrder`, `Trade`, `ResidentOrder`, `Side`,
  `ModifyOutcome` to Python as `orderflow_engine`.
- Module built in-place by maturin; imported lazily by
  `orderflow_sdk.engine`.

### 4.3 Python SDK (`packages/sdk-py`)
- `orderflow_sdk.Engine`: thin wrapper that auto-allocates order IDs and
  tracks a monotonic `_next_id`. `apply_limit(event)` bumps `_next_id` past
  flow events so explicit-ID and auto-allocated IDs don't collide.
- `orderflow_sdk.flow`: three generators sharing a `FlowGenerator`
  protocol. `observe(BookState)` is called each tick so reactive generators
  (HLR-style queue-reactive) can see the book.
  - **Poisson**: exponential inter-arrivals, offset-from-mid drawn from
    configurable distribution.
  - **Hawkes**: mutually-exciting point process via Ogata thinning,
    configurable self/cross excitation and decay.
  - **Queue-Reactive**: intensity modulated by `spread`, `imbalance`, and
    offset from baseline.
- `orderflow_sdk.agents.DeepLOBAgent`: described in §4.6.
- 45 pytest tests green.

### 4.4 FastAPI gateway (`services/api`)
- **`app/main.py`** (`lifespan`): builds Broadcaster, Forecaster (loads
  checkpoint relative to `services/api/`), AgentDriver, and Simulation; wires
  everything into `app.state`.
- **`app/core/config.py`** (`Settings`): env-prefixed (`ORDERFLOW_*`) config
  for tick_hz, sim_speed, generator selection, forecaster path, and agent
  knobs (`agent_enabled`, `agent_threshold`, `agent_base_clip`,
  `agent_max_pos`, `agent_risk_aversion`, `agent_place_cooldown_s`).
- **`app/domain/schemas.py`**: `BookSnapshot`, `TradeDTO`, `Level`, `Hello`,
  `GeneratorChanged`, `ForecastDTO`, `AgentStateDTO`. `BookSnapshot.agent`
  is optional so the stream still works with the agent disabled.
- **`app/services/simulation.py`**: the core tick loop. `_consume_events_until`
  returns `(trades, maker_ids)` — the parallel `maker_ids` list is
  internal, passed to the agent driver for fill reconciliation and never
  reaches the wire DTO.
- **`app/services/forecast.py`**: wraps the DeepLOB model; keeps a rolling
  `deque[seq_len=50]` feature window; graceful-degrades with
  `model_ready=False` if no checkpoint or window not yet full.
- **`app/services/agent_driver.py`**: the bridge between the pure-Python
  agent and the Rust engine. Allocates agent IDs in `[id_offset=1e9, ∞)`
  to guarantee no collision with flow-generated IDs. Reconciles fills by
  scanning `maker_ids` for the agent's open order, marks inventory to mid,
  calls `agent.decide`, translates the returned `AgentAction` into
  `engine.submit(..., id=oid)` / `engine.cancel(cid)`.
- **`app/services/broadcaster.py`**: bounded per-client queues (size 8),
  drops oldest on slow client, single JSON serialisation per frame. Caches
  the last broadcast `AgentStateDTO` in `latest_agent_state` so `/health`
  can surface PnL without a subscription.

### 4.5 DeepLOB forecaster (`services/api/app/models/deeplob.py`, `research/*`)
- Architecture: three conv stages (40→20→10→1 feature-width) + GRU(32) +
  Linear(3). ~13.7k params, ~0.6 ms CPU inference per forward pass.
- **Inputs**: 50-step × 40-feature window. Each row = 10 LOB levels × 4
  features: `(ask_price - mid, log1p(ask_qty)/log1p(scale),
  bid_price - mid, log1p(bid_qty)/log1p(scale))`. Same feature builder
  shared across collector, trainer, and live inference — no train/serve
  skew.
- **Labels**: 3-class `{down, flat, up}` over an H=10-step horizon with a
  0.5-tick threshold.
- **Training** (`research/train_deeplob.py`): class-weighted CrossEntropy
  to counter the ≈86 % flat imbalance from mean-reverting OU mid; 8 epochs
  / ~2 min on CPU. Time-ordered train/val split (no shuffling) to prevent
  future leakage.
- **Data collection** (`research/collect_data.py`): drives the Hawkes
  generator for 30 sim-minutes at 688× real-time, dumps top-K book +
  forward label to parquet (~36 k rows in ~2.6 s).

### 4.6 DeepLOB trading agent (`packages/sdk-py/src/orderflow_sdk/agents/deeplob_agent.py`)
- Pure Python, no Rust dependency. Unit-testable without uvicorn or a
  loaded model.
- **Policy**: at most one resting passive order. If `p_up ≥ threshold` join
  best bid; if `p_down ≥ threshold` join best ask; otherwise cancel any
  stale rest. If best price moves or signal flips, cancel + re-post (rate-
  limited by `place_cooldown_s`).
- **Almgren-Chriss sizing** (asymmetric):

  ```
  penalty(pos) = max(0, 1 − (|pos| / max_pos) ^ γ)   # γ = risk_aversion
  clip_add    = round(base_clip · penalty)           # when adding to |pos|
  clip_reduce = base_clip                            # when reducing |pos|
  final_clip  = min(clip, max_pos − side·pos)        # hard headroom cap
  ```

  γ > 1 gives a flat penalty near zero and cliffs near the inventory
  limit; γ = 1 is a linear taper; γ = 0 blocks adding the moment we hold
  anything (tested).
- **P&L accounting**: VWAP cost basis. Realised PnL crystallises on
  position-reducing fills; flip-through-zero correctly realises the
  closing portion and re-opens cost basis at the fill price. Unrealised
  PnL = `position × (mid − cost_basis)`. `total_pnl = realized + unrealized`.
- **15 pytest tests** covering every branch of `decide()`, the AC sizing
  equations, PnL bookkeeping, and the cooldown / already-resting
  short-circuits.

### 4.7 Web dashboard (`apps/web`)
- Next.js 15 App Router, Tailwind v4, one client component tree. No SSR of
  live state — the WebSocket is opened client-side.
- **`hooks/useOrderflowStream.ts`**: single `WebSocket('/ws/stream')`
  subscriber with capped exponential-backoff reconnect. Exposes
  `{ status, hello, snapshot, trades, priceSeries, forecast, agent,
  framesPerSec, droppedConnections }`. Ring-buffers the trade tape and
  price series to bounded lengths.
- **Components**:
  - `StatusBar` — connection pill, generator toggle, stream health stats,
    sim-parameter panel that swaps per generator.
  - `OrderBookPanel` — 10-level depth with cumulative-qty bars.
  - `PriceChart` — `lightweight-charts` line series of mid, with a live
    `ForecastBadge` (▲ UP / ─ FLAT / ▼ DOWN + probability + horizon).
  - `TradeTape` — ring-buffered taker-side-coloured trade list.
  - `AgentCard` — three-panel tile (total PnL with realised/unrealised
    breakdown · position + fills/gross-qty · resting order + cost basis).
    Rendered on its own row under `StatusBar` so it's always visible.

---

## 5. Known ID-space contract

The matching engine's internal `_next_id` counter is shared between the
flow generator's `apply_limit(event_with_explicit_id)` calls and the
agent's `engine.submit(..., id=agent_id)` calls. To guarantee no collision
the agent allocates IDs from a reserved high-offset range
(`AgentDriverConfig.id_offset = 1_000_000_000` by default). Flow generators
all start from id=1 and increment by one per event, so at realistic tick
rates the 1B gap is effectively infinite.

If this invariant is ever violated the engine raises
`ValueError: duplicate order id`, which the simulation loop logs and
propagates — it will not silently misattribute fills.

---

## 6. Tests & verification

| Suite                              | Count | How                                     |
|------------------------------------|------:|-----------------------------------------|
| Rust engine (`services/engine`)    |    22 | `cargo test`                            |
| SDK (`packages/sdk-py/tests`)      |    45 | `pytest packages/sdk-py/tests`          |
| API (`services/api/tests`)         |     1 | `pytest services/api/tests` (separately) |

The SDK suite includes:
- 15 DeepLOB agent tests (decide / AC sizing / PnL bookkeeping).
- 9 Hawkes tests (intensity decay, cross-excitation, Ogata thinning).
- 6 Queue-Reactive tests (imbalance sensitivity, spread response).
- 9 flow + 6 engine lifecycle tests.

Because both pytest roots use `tests/`, they must be invoked separately
(pytest's rootdir collisions on duplicate module names).

A self-contained end-to-end smoke exists — boot `Simulation` with the
Hawkes generator, a stubbed high-confidence forecast, and
`agent_enabled=True`; within 2 s of sim time the agent accumulates fills,
realised + unrealised PnL, and the broadcaster's `latest_agent_state`
reflects it.

---

## 7. Running it locally

```bash
# One-off build (Rust + Python deps)
cd services/engine/py && maturin develop --release --manifest-path Cargo.toml
pip install -e packages/sdk-py services/api

# Terminal 1 — API
cd services/api && uvicorn app.main:app --reload

# Terminal 2 — web
cd apps/web && pnpm dev
```

Environment knobs (`.env` or `ORDERFLOW_*`):

```
ORDERFLOW_SIM_GENERATOR=hawkes
ORDERFLOW_SIM_TICK_HZ=20
ORDERFLOW_SIM_SPEED=1.0

ORDERFLOW_FORECAST_ENABLED=true
ORDERFLOW_FORECAST_MODEL_PATH=../../research/artifacts/deeplob.pt

ORDERFLOW_AGENT_ENABLED=true
ORDERFLOW_AGENT_THRESHOLD=0.70
ORDERFLOW_AGENT_BASE_CLIP=5
ORDERFLOW_AGENT_MAX_POS=50
ORDERFLOW_AGENT_RISK_AVERSION=1.5
ORDERFLOW_AGENT_PLACE_COOLDOWN_S=0.10
```

---

## 8. Roadmap items *not* implemented (deliberate freezes)

- **Multi-agent framework** — one hard-wired DeepLOBAgent only.
- **Order modification** — agent uses cancel-and-resubmit, not `modify`.
- **Partial fills** — engine does full-qty matching; the agent state
  machine assumes the resting order is cleared by a single fill event.
- **Persistence / replay** — no Postgres or event log; the Docker-compose
  file exists but nothing requires it.
- **Worker service** — `services/workers` is a placeholder.
- **Auth** — no auth on `/ws/stream` or `/control/*`.
- **GPU training** — explicit project constraint; model is CPU-small
  enough (~14k params) that CPU inference hits 0.6 ms.

These are intentional scope cuts, not regressions. The architecture leaves
room for each (see `PROJECT_DESIGN.md` §11 for the original plan).

---

*End of frozen state.*
