# orderflow-engine (PyO3 bindings)

PyO3 wrapper around `orderbook-core`. Compiled as a `cdylib` that Python imports as `orderflow_engine`.

## Build

From a Python 3.12 venv with `maturin` installed:

```bash
# From services/engine/py/
maturin develop --release
```

`maturin develop` builds the extension and installs it into the active venv as an editable wheel.

## Usage

```python
from orderflow_engine import OrderBook, NewOrder, Side

book = OrderBook()
trades = book.submit(NewOrder(id=1, side=Side.Ask, price=100, qty=5))
book.best_ask()  # -> 100
```

See `packages/sdk-py/` for the higher-level Python wrapper.
