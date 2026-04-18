# orderbook-core

Rust matching engine for Orderflow Lab. Deterministic continuous-double-auction LOB with price-time (FIFO) priority. Integer arithmetic only — prices in ticks, qty in lots.

## Status

v0 — matching core.

- `OrderBook::submit` — limit order; crosses in price-time order, remainder rests.
- `OrderBook::cancel` — O(level-depth) removal via index.
- `OrderBook::modify` — in-place amend-down keeps priority; price change or qty-up is cancel-replace.
- `OrderBook::apply(Command)` — dispatch for replay pipelines.
- Every outcome is replayable: same commands → byte-identical trade stream and book state.

## Build

```bash
cargo build --release
cargo test          # 18 spec tests + 4 property tests (proptest)
cargo clippy --all-targets -- -D warnings
```

### macOS note

The crate ships a `.cargo/config.toml` that sets `SDKROOT` to the Command Line Tools SDK as a fallback. If you have a full Xcode install with an accepted license, your env wins (the fallback uses `force = false`).

## Invariants (property-tested)

1. **No self-cross** — `best_bid < best_ask` whenever both sides are populated.
2. **FIFO priority** — within each level, resting-order seqs are strictly increasing.
3. **Quantity conservation** — `submitted = resting + canceled + 2 × traded`.
4. **Determinism** — same command stream → identical outcomes and identical book state.
5. **Index consistency** — every contained id is observable on exactly one level.

## Roadmap

- Week 3-4: Python bindings via PyO3 + maturin; Redis Streams event emission.
- Week 5-6: byte-hash determinism CI check on a canonical scenario.
- Beyond: Hawkes-driven flow, queue-reactive generators, benchmark harness (Criterion).

See `PROJECT_DESIGN.md` Phase 3 and Phase 8 for the full design.
