"""Tests for the bivariate Hawkes flow generator."""

from __future__ import annotations

import pytest

from orderflow_sdk import Engine, Side
from orderflow_sdk.flow import HawkesConfig, HawkesFlowGenerator


def test_determinism_for_equal_seeds() -> None:
    cfg = HawkesConfig(seed=7)
    a = [(e.id, e.side, e.price, e.qty, e.timestamp) for e in [next(HawkesFlowGenerator(cfg)) for _ in range(200)]]
    b = [(e.id, e.side, e.price, e.qty, e.timestamp) for e in [next(HawkesFlowGenerator(cfg)) for _ in range(200)]]
    assert a == b


def test_timestamps_strictly_increasing() -> None:
    gen = HawkesFlowGenerator(HawkesConfig(seed=3))
    events = [next(gen) for _ in range(500)]
    ts = [e.timestamp for e in events]
    assert all(t2 > t1 for t1, t2 in zip(ts, ts[1:]))


def test_ids_monotonic_from_start_id() -> None:
    gen = HawkesFlowGenerator(HawkesConfig(seed=1, start_id=100))
    ids = [next(gen).id for _ in range(50)]
    assert ids == list(range(100, 150))


def test_unstable_parameters_raise() -> None:
    with pytest.raises(ValueError, match="unstable"):
        HawkesFlowGenerator(HawkesConfig(alpha_self=0.9, alpha_cross=0.2, beta=1.0))


def test_mean_intensity_matches_closed_form() -> None:
    """For bivariate Hawkes, E[λ] = (I − A)^{-1} μ with A = α ./ β."""
    cfg = HawkesConfig(seed=2024, mu_bid=10.0, mu_ask=10.0, alpha_self=0.5, alpha_cross=0.2, beta=1.0)
    gen = HawkesFlowGenerator(cfg)

    n = 20_000
    events = [next(gen) for _ in range(n)]
    total_time = events[-1].timestamp
    empirical_rate = n / total_time

    # Closed-form stationary total intensity.
    import numpy as np

    A = gen.branching_matrix()
    mu = np.array([cfg.mu_bid, cfg.mu_ask])
    expected = float(np.linalg.solve(np.eye(2) - A, mu).sum())

    # 20k samples → generous 7% tolerance.
    assert abs(empirical_rate - expected) / expected < 0.07


def test_clustering_over_dispersion_vs_poisson() -> None:
    """Hawkes should produce over-dispersed inter-arrivals (Fano > 1).

    For a homogeneous Poisson process on a fixed window the variance of the
    count equals its mean (Fano factor = 1). Self-excitation inflates the
    count variance: bursts push the count above the mean, quiet stretches
    push it below. A Fano factor > 1 is the canonical fingerprint.
    """
    cfg = HawkesConfig(seed=99, mu_bid=20.0, mu_ask=20.0, alpha_self=0.5, alpha_cross=0.15, beta=1.0)
    gen = HawkesFlowGenerator(cfg)
    events = [next(gen) for _ in range(5_000)]

    # Partition time into equal windows; count events per window.
    window = 0.5
    total_t = events[-1].timestamp
    n_windows = int(total_t // window)
    counts = [0] * n_windows
    for e in events:
        idx = int(e.timestamp // window)
        if 0 <= idx < n_windows:
            counts[idx] += 1

    import statistics

    mean_c = statistics.fmean(counts)
    var_c = statistics.pvariance(counts)
    fano = var_c / mean_c
    assert fano > 1.5  # clear clustering signature


def test_sides_are_roughly_balanced_in_symmetric_config() -> None:
    gen = HawkesFlowGenerator(HawkesConfig(seed=11))
    events = [next(gen) for _ in range(4_000)]
    bids = sum(1 for e in events if e.side == Side.Bid)
    assert 0.42 < bids / len(events) < 0.58


def test_drives_engine_end_to_end() -> None:
    gen = HawkesFlowGenerator(HawkesConfig(seed=42))
    eng = Engine()
    trades = 0
    for _ in range(1_000):
        evt = next(gen)
        trades += len(eng.apply_limit(evt))
    assert trades + len(eng) == 1_000 or trades > 0


def test_intensities_spike_after_event_and_decay() -> None:
    """An event should push intensity above baseline; decay should bring it back."""
    import math

    cfg = HawkesConfig(
        seed=5,
        mu_bid=1.0,
        mu_ask=1.0,
        alpha_self=0.5,
        alpha_cross=0.1,
        beta=2.0,
    )
    gen = HawkesFlowGenerator(cfg)
    base_bid, _ = gen.intensities()
    assert base_bid == pytest.approx(cfg.mu_bid)

    # Trigger a few events.
    for _ in range(5):
        next(gen)

    post_bid, post_ask = gen.intensities()
    assert post_bid > cfg.mu_bid or post_ask > cfg.mu_ask

    # Decay an arbitrary large ``dt`` via a long-offset advance; intensities
    # should asymptote back toward the baseline.
    gen._decay(50.0 / cfg.beta)  # noqa: SLF001 — internal, but keeps the test hermetic
    back_bid, back_ask = gen.intensities()
    assert math.isclose(back_bid, cfg.mu_bid, rel_tol=1e-6)
    assert math.isclose(back_ask, cfg.mu_ask, rel_tol=1e-6)
