#!/usr/bin/env python3
"""autocorrelation_comparison — are Hawkes trades bursty? prove it numerically.

Runs the Poisson and Hawkes flow generators through the Rust matching engine
for a fixed horizon (sim-seconds), then compares clustering diagnostics on
both the raw *arrival* stream and the executed *trade* stream:

1. **Fano factor** ``Var[N(Δ)] / E[N(Δ)]`` of counts in fixed-width time bins.
   Under a homogeneous Poisson process ``Fano → 1``; self-excitation inflates
   it. This is the canonical signature in Bacry, Mastromatteo, Muzy (2015),
   "Hawkes processes in finance".

2. **ACF of per-bin counts** at short lags. Poisson → flat near zero;
   Hawkes → positive and slowly decaying (the exponential kernel shows up as
   an approximately exponential ACF).

3. **ACF of signed trades** (``+1`` bid / ``−1`` ask). Note that a single
   aggressive order that sweeps multiple price levels produces several fills
   with the same sign, so the signs-ACF is elevated for *both* generators;
   the interesting comparison is still the delta between them.

Run from the repo root with the venv activated::

    .venv/bin/python research/notebooks/autocorrelation_comparison.py
    .venv/bin/python research/notebooks/autocorrelation_comparison.py --horizon 600 --bin-width 0.5 --plot acf.png
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass

import numpy as np
from orderflow_sdk import Engine, Side
from orderflow_sdk.flow import (
    FlowConfig,
    FlowGenerator,
    HawkesConfig,
    HawkesFlowGenerator,
    PoissonFlowGenerator,
)


@dataclass(frozen=True, slots=True)
class Streams:
    arrivals: np.ndarray       # shape (n_events,), sim-seconds
    trade_times: np.ndarray    # shape (n_trades,), sim-seconds
    trade_signs: np.ndarray    # shape (n_trades,), ±1 int8


def run_generator(gen: FlowGenerator, horizon: float) -> Streams:
    """Drive ``gen`` through a fresh :class:`Engine` until ``gen.t >= horizon``."""
    eng = Engine()
    arrivals: list[float] = []
    trade_times: list[float] = []
    trade_signs: list[int] = []

    for evt in gen:
        if evt.timestamp > horizon:
            break
        arrivals.append(evt.timestamp)
        for t in eng.apply_limit(evt):
            trade_times.append(evt.timestamp)
            trade_signs.append(1 if t.taker_side == Side.Bid else -1)

    return Streams(
        arrivals=np.asarray(arrivals, dtype=np.float64),
        trade_times=np.asarray(trade_times, dtype=np.float64),
        trade_signs=np.asarray(trade_signs, dtype=np.int8),
    )


def bin_counts(times: np.ndarray, horizon: float, bin_width: float) -> np.ndarray:
    edges = np.arange(0.0, horizon + bin_width, bin_width)
    counts, _ = np.histogram(times, bins=edges)
    return counts


def sample_acf(x: np.ndarray, max_lag: int) -> np.ndarray:
    """Biased sample autocorrelation of a mean-centered series, lags 1..max_lag."""
    x = np.asarray(x, dtype=np.float64)
    n = x.size
    if n == 0:
        return np.zeros(max_lag)
    xc = x - x.mean()
    denom = float((xc * xc).sum())
    if denom == 0.0:
        return np.zeros(max_lag)
    out = np.empty(max_lag)
    for k in range(1, max_lag + 1):
        out[k - 1] = float((xc[:-k] * xc[k:]).sum()) / denom
    return out


def fano(counts: np.ndarray) -> float:
    mean = float(counts.mean())
    if mean == 0.0:
        return float("nan")
    return float(counts.var()) / mean


def report(label: str, s: Streams, horizon: float, bin_width: float, max_lag: int) -> dict:
    arr_counts = bin_counts(s.arrivals, horizon, bin_width)
    trd_counts = bin_counts(s.trade_times, horizon, bin_width)

    arr_acf = sample_acf(arr_counts.astype(np.float64), max_lag)
    trd_acf = sample_acf(trd_counts.astype(np.float64), max_lag)
    sign_acf = sample_acf(s.trade_signs.astype(np.float64), max_lag)

    n_arr = s.arrivals.size
    n_trd = s.trade_times.size
    bid_frac = float((s.trade_signs > 0).sum()) / max(n_trd, 1)

    print(
        f" {label:<8}"
        f"  arrivals={n_arr:>6}  trades={n_trd:>6}"
        f"  bid%={bid_frac:>4.0%}"
        f"  Fano_arr(Δ={bin_width:g}s)={fano(arr_counts):>5.2f}"
        f"  Fano_trd={fano(trd_counts):>5.2f}"
    )
    return {
        "arr_acf": arr_acf,
        "trd_acf": trd_acf,
        "sign_acf": sign_acf,
    }


def print_acf_table(title: str, lags: np.ndarray, poisson_acf: np.ndarray, hawkes_acf: np.ndarray) -> None:
    print()
    print(f" {title}")
    print(f" {'lag':>4}  {'poisson':>10}  {'hawkes':>10}  {'Δ':>10}")
    for k, lag in enumerate(lags):
        d = hawkes_acf[k] - poisson_acf[k]
        print(f" {int(lag):>4}  {poisson_acf[k]:>+10.4f}  {hawkes_acf[k]:>+10.4f}  {d:>+10.4f}")


def maybe_plot(path: str, lags: np.ndarray, poisson_acf: np.ndarray, hawkes_acf: np.ndarray, bin_width: float) -> None:
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        print(f"\n (matplotlib not installed — skipping plot at {path})")
        return

    fig, ax = plt.subplots(figsize=(8, 4), dpi=140)
    ax.axhline(0.0, color="#555", linewidth=0.6)
    ax.vlines(lags - 0.12, 0.0, poisson_acf, color="#3b82f6", linewidth=2, label="Poisson")
    ax.vlines(lags + 0.12, 0.0, hawkes_acf, color="#d946ef", linewidth=2, label="Hawkes")
    ax.scatter(lags - 0.12, poisson_acf, s=14, color="#3b82f6")
    ax.scatter(lags + 0.12, hawkes_acf, s=14, color="#d946ef")
    ax.set_xlabel(f"lag (bins of {bin_width:g}s)")
    ax.set_ylabel("sample ACF of arrival counts")
    ax.set_title("Per-bin arrival counts — Poisson vs. Hawkes")
    ax.grid(True, alpha=0.25)
    ax.legend(loc="best", frameon=False)
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)
    print(f"\n wrote plot → {path}")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--horizon", type=float, default=300.0, help="simulation horizon in sim-seconds (default: 300)")
    p.add_argument("--seed", type=int, default=7, help="seed for both generators (default: 7)")
    p.add_argument("--max-lag", type=int, default=15, help="maximum ACF lag in bins (default: 15)")
    p.add_argument("--bin-width", type=float, default=1.0, help="bin width in sim-seconds for Fano/count ACF (default: 1)")
    p.add_argument("--plot", type=str, default=None, help="optional path to write a PNG of the arrival-count ACF")
    return p.parse_args()


def main() -> None:
    args = parse_args()

    poisson_cfg = FlowConfig(seed=args.seed, lambda_rate=80.0)
    # Chosen so the steady-state total intensity matches the Poisson λ:
    # μ_total / (1 − ρ) with ρ = (α_self + α_cross) / β = 0.75 ⇒ 20 / 0.25 = 80.
    hawkes_cfg = HawkesConfig(
        seed=args.seed,
        mu_bid=10.0,
        mu_ask=10.0,
        alpha_self=0.6,
        alpha_cross=0.15,
        beta=1.0,
    )

    print("═" * 76)
    print(" Orderflow Lab — trade clustering comparison (Poisson vs. Hawkes)")
    print("═" * 76)
    print(f" horizon={args.horizon:g}s  seed={args.seed}  max_lag={args.max_lag}  bin_width={args.bin_width:g}s")
    print()

    poisson_stream = run_generator(PoissonFlowGenerator(poisson_cfg), args.horizon)
    hawkes_stream = run_generator(HawkesFlowGenerator(hawkes_cfg), args.horizon)

    poisson = report("poisson", poisson_stream, args.horizon, args.bin_width, args.max_lag)
    hawkes = report("hawkes", hawkes_stream, args.horizon, args.bin_width, args.max_lag)

    lags = np.arange(1, args.max_lag + 1)
    print_acf_table(
        f"ACF of arrival counts per {args.bin_width:g}s bin (the canonical clustering signature)",
        lags,
        poisson["arr_acf"],
        hawkes["arr_acf"],
    )
    print_acf_table(
        f"ACF of trade counts per {args.bin_width:g}s bin",
        lags,
        poisson["trd_acf"],
        hawkes["trd_acf"],
    )
    print_acf_table(
        "ACF of trade signs (signs persist from multi-level sweeps; look at the Δ column)",
        lags,
        poisson["sign_acf"],
        hawkes["sign_acf"],
    )

    print()
    print("─ Interpretation ──────────────────────────────────────────────────")
    print(" Fano_arr ≈ 1 for Poisson (CV²=1 by construction) and >1 for Hawkes.")
    print(" Arrival-count ACF: Poisson sits near 0; Hawkes shows positive,")
    print(" slowly-decaying autocorrelation — the exponential kernel's print.")
    print(" That is the burstiness you'll see in the live Trade Tape.")
    print("═" * 76)

    if args.plot is not None:
        maybe_plot(args.plot, lags, poisson["arr_acf"], hawkes["arr_acf"], args.bin_width)


if __name__ == "__main__":
    main()
