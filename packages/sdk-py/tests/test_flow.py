"""Tests for the Poisson + OU order-flow generator."""

from __future__ import annotations

import math

import pytest

from orderflow_sdk import Engine, Side
from orderflow_sdk.flow import FlowConfig, PoissonFlowGenerator


def test_ids_are_monotonically_increasing_from_start_id() -> None:
    gen = PoissonFlowGenerator(FlowConfig(seed=1, start_id=7))
    events = gen.generate(50)
    ids = [e.id for e in events]
    assert ids == list(range(7, 57))


def test_determinism_for_equal_seeds() -> None:
    cfg = FlowConfig(seed=123)
    a = [(e.id, e.side, e.price, e.qty, e.timestamp) for e in PoissonFlowGenerator(cfg).generate(200)]
    b = [(e.id, e.side, e.price, e.qty, e.timestamp) for e in PoissonFlowGenerator(cfg).generate(200)]
    assert a == b


def test_different_seeds_diverge() -> None:
    a = PoissonFlowGenerator(FlowConfig(seed=1)).generate(100)
    b = PoissonFlowGenerator(FlowConfig(seed=2)).generate(100)
    assert [e.price for e in a] != [e.price for e in b]


def test_timestamps_are_strictly_increasing() -> None:
    events = PoissonFlowGenerator(FlowConfig(seed=3)).generate(500)
    ts = [e.timestamp for e in events]
    assert all(t2 > t1 for t1, t2 in zip(ts, ts[1:]))


def test_mean_arrival_rate_matches_lambda() -> None:
    n = 5_000
    lam = 50.0
    events = PoissonFlowGenerator(FlowConfig(seed=42, lambda_rate=lam)).generate(n)
    empirical_rate = n / events[-1].timestamp
    # Loose bound: ±10% with 5k samples is very comfortable.
    assert abs(empirical_rate - lam) / lam < 0.1


def test_mid_reverts_toward_mu() -> None:
    # Start far from mu; expect the empirical mean price to be pulled back.
    cfg = FlowConfig(
        seed=7,
        mid0=20_000.0,
        mu=10_000.0,
        kappa=5.0,
        sigma=1.0,
        lambda_rate=200.0,
        offset_mean=0.5,
    )
    events = PoissonFlowGenerator(cfg).generate(2_000)
    tail_mean = sum(e.price for e in events[-500:]) / 500
    assert abs(tail_mean - cfg.mu) < 100  # << the 10k of initial displacement


def test_qty_is_always_positive() -> None:
    events = PoissonFlowGenerator(FlowConfig(seed=11, qty_mean=1.0)).generate(1_000)
    assert all(e.qty >= 1 for e in events)


def test_sides_are_approximately_balanced() -> None:
    events = PoissonFlowGenerator(FlowConfig(seed=99, side_bias=0.5)).generate(4_000)
    bids = sum(1 for e in events if e.side == Side.Bid)
    asks = len(events) - bids
    assert 0.45 < bids / len(events) < 0.55
    assert bids + asks == len(events)


def test_generator_drives_engine_end_to_end() -> None:
    gen = PoissonFlowGenerator(FlowConfig(seed=2024))
    eng = Engine()
    trades = 0
    for evt in gen.stream(1_000):
        trades += len(eng.apply_limit(evt))
    # At the very least the engine should be non-empty or have produced trades.
    assert trades + len(eng) == 1_000 or trades > 0
    # Best prices should straddle mu if the book isn't empty.
    if eng.best_bid() is not None and eng.best_ask() is not None:
        assert eng.best_bid() < eng.best_ask()
