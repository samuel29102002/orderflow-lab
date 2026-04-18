# orderflow-sdk

Python SDK for the Orderflow Lab matching engine. Wraps the `orderflow_engine`
PyO3 bindings and ships synthetic order-flow generators used by the research
simulations.

## Install (editable, from repo root)

```bash
# 1. Build the Rust matching engine into the venv
(cd services/engine/py && maturin develop --release)

# 2. Install the SDK in editable mode
.venv/bin/pip install -e packages/sdk-py
```

## Quick start

```python
from orderflow_sdk import Engine, Side
from orderflow_sdk.flow import FlowConfig, PoissonFlowGenerator

engine = Engine()
gen = PoissonFlowGenerator(FlowConfig(seed=42))

for evt in gen.stream(1_000):
    engine.apply_limit(evt)

print(engine.book)
```

## Layout

- `orderflow_sdk.Engine` — thin stateful wrapper around `OrderBook` with
  auto-incrementing order IDs and a `apply_limit` dispatcher.
- `orderflow_sdk.events` — plain dataclasses for events emitted by generators
  (`LimitOrderEvent`).
- `orderflow_sdk.flow` — synthetic order-flow generators. Current:
  Poisson arrivals with an Ornstein–Uhlenbeck mean-reverting mid-price and
  exponential offset / quantity distributions.

See `research/simulation_v0.py` for a 10 000-order benchmark.
