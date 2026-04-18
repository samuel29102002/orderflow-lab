#!/usr/bin/env python3
"""simulation_v0 — synthetic-flow smoke + throughput benchmark.

Runs a Poisson + OU flow through the Rust matching engine and reports
throughput, trade counts, and the resting book state. This is the first
end-to-end signal that the Rust core, the PyO3 bindings, and the Python SDK
are wired correctly.

Run from the repo root with the venv activated:

    .venv/bin/python research/simulation_v0.py
    .venv/bin/python research/simulation_v0.py --orders 100000 --seed 7
"""

from __future__ import annotations

import argparse
import time
from dataclasses import asdict

from orderflow_sdk import Engine, Side, engine_version
from orderflow_sdk.flow import FlowConfig, PoissonFlowGenerator


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--orders", type=int, default=10_000, help="number of limit-order events to generate (default: 10 000)")
    p.add_argument("--seed", type=int, default=42, help="RNG seed for reproducibility (default: 42)")
    p.add_argument("--lambda-rate", dest="lambda_rate", type=float, default=500.0, help="Poisson arrival rate λ (default: 500)")
    p.add_argument("--mid0", type=float, default=10_000.0, help="initial mid-price in ticks (default: 10 000)")
    p.add_argument("--mu", type=float, default=10_000.0, help="OU reversion target (default: 10 000)")
    p.add_argument("--kappa", type=float, default=2.0, help="OU mean-reversion speed (default: 2.0)")
    p.add_argument("--sigma", type=float, default=5.0, help="OU diffusion σ in ticks per √time (default: 5.0)")
    p.add_argument("--offset-mean", dest="offset_mean", type=float, default=3.0, help="mean price offset from mid in ticks (default: 3)")
    p.add_argument("--qty-mean", dest="qty_mean", type=float, default=10.0, help="mean order quantity (default: 10)")
    p.add_argument("--depth-levels", type=int, default=5, help="number of book levels to print per side (default: 5)")
    return p.parse_args()


def human(n: float) -> str:
    return f"{n:,.0f}"


def print_config(cfg: FlowConfig, n: int) -> None:
    print("═" * 60)
    print(" Orderflow Lab — simulation_v0")
    print("═" * 60)
    print(f" engine       : orderflow_engine {engine_version}")
    print(f" orders       : {human(n)}")
    for k, v in asdict(cfg).items():
        print(f" {k:13}: {v}")


def run(cfg: FlowConfig, n: int) -> tuple[Engine, float, int]:
    """Pre-materialise events, then time just the engine ingestion loop.

    Generator work (RNG + OU evolution) is excluded from the rate measurement
    so the reported orders/sec reflects matching-engine + PyO3 crossing cost.
    """
    gen = PoissonFlowGenerator(cfg)
    events = gen.generate(n)  # generation cost excluded from the timer

    eng = Engine()
    trade_count = 0

    start = time.perf_counter()
    apply = eng.apply_limit
    for evt in events:
        trade_count += len(apply(evt))
    elapsed = time.perf_counter() - start

    return eng, elapsed, trade_count


def print_book(eng: Engine, depth_levels: int) -> None:
    bid_depth = eng.depth(Side.Bid)[:depth_levels]
    ask_depth = eng.depth(Side.Ask)[:depth_levels]

    print()
    print("─ Book top ──────────────────────────────────────────────────")
    print(f" best_bid : {eng.best_bid()}")
    print(f" best_ask : {eng.best_ask()}")
    print(f" spread   : {eng.spread()}")
    mid = eng.mid()
    print(f" mid      : {mid:.2f}" if mid is not None else " mid      : —")
    print(f" resting  : {len(eng)} orders")

    print()
    print(f"─ Top {depth_levels} bids ({'price':>8}  {'qty':>8})")
    for price, qty in bid_depth:
        print(f"              {price:>8}  {qty:>8}")
    print(f"─ Top {depth_levels} asks ({'price':>8}  {'qty':>8})")
    for price, qty in ask_depth:
        print(f"              {price:>8}  {qty:>8}")


def main() -> None:
    args = parse_args()
    cfg = FlowConfig(
        lambda_rate=args.lambda_rate,
        mid0=args.mid0,
        mu=args.mu,
        kappa=args.kappa,
        sigma=args.sigma,
        offset_mean=args.offset_mean,
        qty_mean=args.qty_mean,
        seed=args.seed,
    )

    print_config(cfg, args.orders)
    eng, elapsed, trades = run(cfg, args.orders)

    rate = args.orders / elapsed if elapsed > 0 else float("inf")
    fill_ratio = trades / args.orders

    print()
    print("─ Throughput ────────────────────────────────────────────────")
    print(f" elapsed       : {elapsed * 1e3:,.2f} ms")
    print(f" orders/sec    : {human(rate)}")
    print(f" ns per order  : {(elapsed / args.orders) * 1e9:,.0f}")
    print(f" trades        : {human(trades)}  ({fill_ratio:.1%} fill ratio)")

    print_book(eng, args.depth_levels)
    print("═" * 60)


if __name__ == "__main__":
    main()
