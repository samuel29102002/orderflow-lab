"""Tests for the queue-reactive flow generator."""

from __future__ import annotations

from orderflow_sdk import Engine, Side
from orderflow_sdk.flow import BookState, QueueReactiveConfig, QueueReactiveFlowGenerator


def _state(*, spread: int | None = 2, bid_qty: int = 100, ask_qty: int = 100) -> BookState:
    best_bid = 9999 if spread is not None else None
    best_ask = (9999 + spread) if spread is not None else None
    mid = None if best_bid is None or best_ask is None else (best_bid + best_ask) / 2.0
    return BookState(
        t=0.0,
        best_bid=best_bid,
        best_ask=best_ask,
        spread=spread,
        mid=mid,
        bid_top_qty=bid_qty,
        ask_top_qty=ask_qty,
    )


def test_determinism_for_equal_seeds() -> None:
    cfg = QueueReactiveConfig(seed=3)
    g1 = QueueReactiveFlowGenerator(cfg)
    g2 = QueueReactiveFlowGenerator(cfg)
    state = _state(spread=2, bid_qty=100, ask_qty=100)
    g1.observe(state)
    g2.observe(state)
    a = [(e.id, e.side, e.price, e.qty, e.timestamp) for e in [next(g1) for _ in range(200)]]
    b = [(e.id, e.side, e.price, e.qty, e.timestamp) for e in [next(g2) for _ in range(200)]]
    assert a == b


def test_tight_spread_raises_rate() -> None:
    cfg = QueueReactiveConfig(seed=11, base_lambda=100.0, baseline_spread=4)
    gen = QueueReactiveFlowGenerator(cfg)

    gen.observe(_state(spread=4))
    baseline = gen.current_rate()

    gen.observe(_state(spread=1))
    tight = gen.current_rate()

    gen.observe(_state(spread=8))
    wide = gen.current_rate()

    assert tight > baseline > wide


def test_imbalance_biases_side_distribution() -> None:
    cfg = QueueReactiveConfig(seed=7, imbalance_sensitivity=0.6)
    gen = QueueReactiveFlowGenerator(cfg)
    gen.observe(_state(spread=2, bid_qty=400, ask_qty=50))

    events = [next(gen) for _ in range(2_000)]
    bid_share = sum(1 for e in events if e.side == Side.Bid) / len(events)
    assert bid_share > 0.6  # bias should clearly tilt toward the heavier queue


def test_no_observation_falls_back_to_baseline() -> None:
    cfg = QueueReactiveConfig(seed=1, base_lambda=50.0, baseline_spread=2)
    gen = QueueReactiveFlowGenerator(cfg)
    # Without a call to observe(), rate should equal the baseline λ.
    assert gen.current_rate() == cfg.base_lambda


def test_observe_with_empty_book_uses_baseline_spread() -> None:
    cfg = QueueReactiveConfig(seed=2, base_lambda=60.0, baseline_spread=3)
    gen = QueueReactiveFlowGenerator(cfg)
    gen.observe(_state(spread=None, bid_qty=0, ask_qty=0))
    assert gen.current_rate() == cfg.base_lambda


def test_drives_engine_end_to_end_with_live_observation() -> None:
    gen = QueueReactiveFlowGenerator(QueueReactiveConfig(seed=2024))
    eng = Engine()
    for _ in range(1_000):
        evt = next(gen)
        eng.apply_limit(evt)
        # Mirror the simulation loop's observation cadence: update state
        # every few events so the generator's tilt keeps pace with the book.
        gen.observe(
            BookState(
                t=evt.timestamp,
                best_bid=eng.best_bid(),
                best_ask=eng.best_ask(),
                spread=eng.spread(),
                mid=eng.mid(),
                bid_top_qty=eng.depth(Side.Bid)[0][1] if eng.best_bid() is not None else 0,
                ask_top_qty=eng.depth(Side.Ask)[0][1] if eng.best_ask() is not None else 0,
            )
        )
    assert len(eng) > 0
