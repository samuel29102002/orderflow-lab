# Orderflow Lab — Installation & Operations

A "new-terminal" guide. Follow it top-to-bottom on a clean macOS or Linux
machine and you will end with the FastAPI gateway on `:8000`, the Next.js
dashboard on `:3000`, and the DeepLOB trader printing P&L in your browser.

**Assumed working directory**: the repo root (`…/quant`). Every path below
is relative to it.

---

## 1. Prerequisites

| Tool          | Version                 | How                                          |
|---------------|-------------------------|----------------------------------------------|
| **Rust**      | 1.78 + (stable)         | `curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs \| sh` |
| **Python**    | **3.12** (not 3.13)     | `brew install python@3.12` / `uv python install 3.12` |
| **Node**      | ≥ 20.10                 | `brew install node` / `nvm install 20`       |
| **pnpm**      | ≥ 10                    | `corepack enable && corepack prepare pnpm@latest --activate` |
| **Docker**    | Desktop or Engine       | https://docs.docker.com/engine/install/      |
| **maturin**   | 1.7 +                   | *installed below, inside the venv*            |

Verify:

```bash
rustc --version           # rustc 1.78.0 or newer
python3.12 --version      # Python 3.12.x
node --version && pnpm -v # v20+ and v10+
docker --version          # Docker 24+
```

If any of these are missing, install them before continuing — the rest of
the guide assumes they're all present on `$PATH`.

---

## 2. Environment setup

### 2.1 One-line clone

```bash
git clone <repo-url> quant && cd quant
```

### 2.2 Python 3.12 venv (not Conda)

This project uses **plain venv + pip**, not Conda. If you already have a
Conda environment activated, Conda's `CONDA_PREFIX` will poison `PATH` and
cause `maturin develop` to build against the wrong Python. Neutralise it
**before** creating the venv:

```bash
# Deactivate any active Conda env
conda deactivate 2>/dev/null || true

# Unset the Conda env-var so maturin/pip don't pick up the Conda Python
unset CONDA_PREFIX
unset CONDA_DEFAULT_ENV
unset CONDA_SHLVL

# Create the project venv with the system Python 3.12
python3.12 -m venv .venv
source .venv/bin/activate

# Verify: this must point *inside* .venv and report 3.12.x
which python
python --version
```

> **Smoke test** — `python -c "import sys; print(sys.prefix)"` must print a
> path ending in `/quant/.venv`. If it prints a Conda path, re-run
> `unset CONDA_PREFIX` and re-activate the venv before proceeding.

### 2.3 Install Python deps

```bash
pip install --upgrade pip wheel
pip install maturin[patchelf]
pip install -e packages/sdk-py -e services/api
pip install torch pandas pyarrow          # for DeepLOB training + inference
pip install pytest pytest-asyncio          # test runners
pip install "psycopg[binary,pool]"        # async TimescaleDB driver (Phase 3)
```

### 2.4 Install JS deps

```bash
pnpm install
```

---

## 3. Build sequence

The build has three steps and they must happen in this order: **Rust →
Python bridge → Next.js**.

### 3.1 Build the Rust engine (maturin)

`maturin develop` compiles the PyO3 crate and drops the shared-object file
directly into your active venv's `site-packages` so `import orderflow_engine`
works from Python.

```bash
# Still inside the activated venv
cd services/engine/py
maturin develop --release
cd ../../..

# Smoke test
python -c "from orderflow_sdk import Engine, Side; e = Engine(); \
  r = e.submit(Side.Bid, 100, 5); print('engine ok:', r)"
# → engine ok: SubmitResult(order_id=1, trades=[])
```

> If maturin errors with **"Could not find a Python interpreter"**: check
> §2.2 — you're almost certainly still in a Conda env. Re-run the
> `unset CONDA_*` block.

### 3.2 Infra containers (required for persistence, optional otherwise)

The simulator runs fully in-memory without a database. To enable the
TimescaleDB sink and the `/analytics` dashboard, bring up the containers:

```bash
# Spins up timescaledb on :5432 and redis on :6379
docker compose -f infra/docker/docker-compose.yml up -d

# Verify
docker compose -f infra/docker/docker-compose.yml ps
```

If you skip this step, set `ORDERFLOW_STORAGE_ENABLED=false` (see §5) to
suppress the connection-refused warnings at startup.

### 3.3 (Optional) Train the DeepLOB model

The live system degrades gracefully when there's no checkpoint — the
`Forecast · warming` badge shows and the agent stays flat. To enable real
signal:

```bash
# Collect 30 sim-minutes of Hawkes data (~2.6s of wall time, ~36k rows)
python research/collect_data.py

# Train — ~2 min on CPU, writes research/artifacts/deeplob.pt
python research/train_deeplob.py
```

---

## 4. Running the stack

Open **two terminals**. Both need the venv activated *and* the
`CONDA_PREFIX` cleanup from §2.2 applied if Conda is installed.

### Terminal A — FastAPI gateway

```bash
source .venv/bin/activate
cd services/api
uvicorn app.main:app --reload --port 8000
```

You should see:

```
INFO     simulation started: tick_hz=20.0 speed=1.0 generator=poisson
INFO     Uvicorn running on http://127.0.0.1:8000
```

Sanity: `curl http://127.0.0.1:8000/health` returns JSON with `"status":"ok"`.

### Terminal B — Next.js dashboard

```bash
pnpm --filter @orderflow/web dev
```

Open http://localhost:3000 for the marketing landing page and
http://localhost:3000/lab for the live dashboard.

Flip the generator to **Hawkes** from the status bar to see the trader
start firing.

---

## 5. Configuration knobs

All server-side configuration is `pydantic-settings` with the prefix
`ORDERFLOW_`. Put them in `services/api/.env` or export them in the shell:

```bash
# Simulator
ORDERFLOW_SIM_GENERATOR=hawkes              # poisson | hawkes | queue_reactive
ORDERFLOW_SIM_TICK_HZ=20
ORDERFLOW_SIM_SPEED=1.0

# Forecaster
ORDERFLOW_FORECAST_ENABLED=true
ORDERFLOW_FORECAST_MODEL_PATH=../../research/artifacts/deeplob.pt

# Agent
ORDERFLOW_AGENT_ENABLED=true
ORDERFLOW_AGENT_THRESHOLD=0.70
ORDERFLOW_AGENT_BASE_CLIP=5
ORDERFLOW_AGENT_MAX_POS=50
ORDERFLOW_AGENT_RISK_AVERSION=1.5
```

Client-side config lives in `apps/web/app/lib/config.ts` — override with
`NEXT_PUBLIC_WS_URL` / `NEXT_PUBLIC_API_URL` if you run the API on a
different host.

---

## 6. Verification

Run the full test matrix before reporting a clean install:

```bash
# Rust — 22 tests
cargo test --manifest-path services/engine/Cargo.toml

# Python SDK — 45 tests (includes 15 agent tests)
pytest packages/sdk-py/tests

# API — 1 health test
#
# ⚠ Run these two suites *separately*. Both use tests/test_*.py which
# collides in pytest's rootdir resolution if invoked together.
cd services/api && pytest tests && cd ../..
```

All three should be green.

---

## 7. Troubleshooting

### "Port 5432 is already in use"

Another Postgres is listening on the default port. Either stop it:

```bash
# macOS Homebrew
brew services stop postgresql

# Linux systemd
sudo systemctl stop postgresql
```

…or point the compose file at a free port:

```bash
POSTGRES_PORT=5433 docker compose -f infra/docker/docker-compose.yml up -d
```

### "Port 3000 / 8000 already in use"

```bash
lsof -nP -iTCP:3000 -sTCP:LISTEN        # who's on 3000?
pnpm --filter @orderflow/web dev --port 3001   # or pick a new port
uvicorn app.main:app --reload --port 8001      # …and point NEXT_PUBLIC_WS_URL at it
```

### `maturin develop` errors with "No module named '_distutils_hack'"

You're building against a Conda Python. Re-run §2.2 in a **fresh**
terminal — once `CONDA_PREFIX` is in the environment, simply unsetting it
isn't always enough because some Conda shims are in `PATH`.

```bash
# Nuclear option
env -i HOME="$HOME" PATH="/usr/local/bin:/usr/bin:/bin" bash
cd /path/to/quant
python3.12 -m venv .venv && source .venv/bin/activate
# …continue from §2.3
```

### `ValueError: duplicate order id: N` in the API logs

The agent's ID allocator has collided with the flow generator's. This
should be impossible in the default configuration (agent IDs start at
`1_000_000_000` and flow IDs at `1`), but can happen if you've raised
`ORDERFLOW_SIM_TICK_HZ` into the millions *and* lowered the agent ID
offset. Fix:

```bash
# In services/api/app/services/agent_driver.py, AgentDriverConfig:
# bump id_offset higher (e.g., 10_000_000_000) — flow IDs grow at ≈
# one per event, so a 10× gap is always safe.
```

### "Forecast · off" badge doesn't change to "warming" / "up" / "down"

Either the checkpoint path is wrong or no checkpoint exists yet. Check
`services/api/app/core/config.py` → `forecast_model_path` and confirm the
file exists at that path (it's resolved relative to `services/api/`). If
it doesn't, run §3.3 to train one.

### WebSocket drops constantly

The broadcaster drops the oldest frame when a client queue fills. This is
normal for background tabs. Look at the `reconnects` counter in the status
bar — anything < 5 over several minutes is fine. If it's climbing rapidly,
check your browser console for network errors and confirm the API is
actually running on the URL `NEXT_PUBLIC_WS_URL` points at.

### Agent shows "off" in the UI even though API env has it enabled

The snapshot is missing `agent` because the API started before
`ORDERFLOW_AGENT_ENABLED` was set. Kill and restart uvicorn after editing
the `.env`, then refresh the browser.

---

## 8. Clean-up

```bash
# Stop servers (Ctrl-C in each terminal)

# Stop infra
docker compose -f infra/docker/docker-compose.yml down

# Nuke builds (safe — everything rebuilds from source)
rm -rf .venv node_modules apps/web/.next services/engine/target

# Nuke Python bytecode + pytest cache
find . -type d \( -name __pycache__ -o -name .pytest_cache \) -exec rm -rf {} +
```

---

*That's the whole install.* If you hit something this guide doesn't cover,
check `FINAL_STATE.md` for the full architecture reference.
