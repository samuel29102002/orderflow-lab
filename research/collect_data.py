#!/usr/bin/env python3
"""collect_data — record LOB snapshots + future mid moves from the Hawkes sim.

Drives the Hawkes flow generator through the Rust engine at wall-clock-
independent speed (sim time only; no ``asyncio.sleep``), samples the top-K
book every ``tick_interval`` sim-seconds, and writes one parquet file:

    research/datasets/hawkes_<seed>_<N>.parquet

Each row holds:

    sim_t, mid, best_bid, best_ask, spread,
    f0…f{FEATURE_DIM-1}                 # packed by build_feature_row
    label_<H>                           # 0=down, 1=flat, 2=up over H steps

where ``H`` defaults to ``DEFAULT_HORIZON_STEPS`` (500 ms at 20 Hz). The
label column is populated in-place after the run so its definition lives
in one place (the horizon and tick threshold are run-time args).

The collector lives next to the sim so we can tweak generator params
without having to spin up uvicorn just to record data.

Run from the repo root (venv activated)::

    .venv/bin/python research/collect_data.py
    .venv/bin/python research/collect_data.py --sim-minutes 30 --seed 11 --tick-hz 20
"""

from __future__ import annotations

import argparse
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
import pandas as pd
from orderflow_sdk import Engine, Side
from orderflow_sdk.flow import HawkesConfig, HawkesFlowGenerator

# Allow ``from app.models.deeplob import ...`` without installing the API package.
API_APP = Path(__file__).resolve().parent.parent / "services" / "api"
if str(API_APP) not in sys.path:
    sys.path.insert(0, str(API_APP))

from app.models.deeplob import (  # noqa: E402
    DEFAULT_HORIZON_STEPS,
    DEFAULT_TICK_THRESHOLD,
    FEATURE_DIM,
    LEVELS,
    build_feature_row,
)


@dataclass(frozen=True, slots=True)
class CollectConfig:
    sim_minutes: float = 30.0
    tick_hz: float = 20.0
    seed: int = 42
    depth_levels: int = LEVELS
    horizon_steps: int = DEFAULT_HORIZON_STEPS
    tick_threshold: float = DEFAULT_TICK_THRESHOLD
    out_dir: Path = Path("research/datasets")


def run_collection(cfg: CollectConfig) -> pd.DataFrame:
    """Simulate and materialise a dataframe of features + future-move labels."""
    gen = HawkesFlowGenerator(HawkesConfig(seed=cfg.seed))
    eng = Engine()
    pending = next(gen)

    tick_interval = 1.0 / cfg.tick_hz
    horizon = cfg.sim_minutes * 60.0
    n_snapshots = int(horizon / tick_interval)

    # Pre-allocate numpy arrays so we don't pay list-append costs at 20 Hz.
    sim_t = np.empty(n_snapshots, dtype=np.float64)
    mid = np.empty(n_snapshots, dtype=np.float64)
    best_bid = np.empty(n_snapshots, dtype=np.float64)
    best_ask = np.empty(n_snapshots, dtype=np.float64)
    spread = np.empty(n_snapshots, dtype=np.float64)
    features = np.empty((n_snapshots, FEATURE_DIM), dtype=np.float32)

    t = 0.0
    start = time.perf_counter()
    for i in range(n_snapshots):
        t += tick_interval

        # Drain all events with timestamp ≤ t into the engine.
        while pending.timestamp <= t:
            eng.apply_limit(pending)
            pending = next(gen)

        # Snapshot.
        m = eng.mid()
        bb = eng.best_bid()
        ba = eng.best_ask()
        sp = eng.spread()
        bids = eng.depth(Side.Bid)[: cfg.depth_levels]
        asks = eng.depth(Side.Ask)[: cfg.depth_levels]

        sim_t[i] = t
        mid[i] = m if m is not None else np.nan
        best_bid[i] = bb if bb is not None else np.nan
        best_ask[i] = ba if ba is not None else np.nan
        spread[i] = sp if sp is not None else np.nan

        if m is None:
            features[i].fill(0.0)
        else:
            features[i] = build_feature_row(bids, asks, m)

    elapsed = time.perf_counter() - start

    # Label: direction of Δmid over H steps, relative to a tick threshold.
    # The final H rows can't be labelled (no future observation), so trim them.
    horizon_steps = cfg.horizon_steps
    future_mid = np.roll(mid, -horizon_steps)
    dmid = future_mid - mid
    label = np.where(
        dmid > cfg.tick_threshold,
        2,  # up
        np.where(dmid < -cfg.tick_threshold, 0, 1),  # down / flat
    ).astype(np.int8)
    label[-horizon_steps:] = -1  # sentinel, dropped below

    df = pd.DataFrame(
        {
            "sim_t": sim_t,
            "mid": mid,
            "best_bid": best_bid,
            "best_ask": best_ask,
            "spread": spread,
            **{f"f{k}": features[:, k] for k in range(FEATURE_DIM)},
            f"label_h{horizon_steps}": label,
        }
    )
    df = df[df[f"label_h{horizon_steps}"] >= 0].reset_index(drop=True)

    wall_rate = n_snapshots / elapsed if elapsed > 0 else float("inf")
    print(
        f" collected {len(df):,} labelled rows in {elapsed:.2f}s "
        f"({wall_rate:,.0f} snapshots/wall-sec, "
        f"speedup ×{(horizon / elapsed):,.0f} vs. real time)"
    )

    return df


def print_class_balance(df: pd.DataFrame, horizon_steps: int) -> None:
    col = f"label_h{horizon_steps}"
    counts = df[col].value_counts().sort_index()
    total = counts.sum()
    labels = {0: "down", 1: "flat", 2: "up"}
    print(" class balance:")
    for k in (0, 1, 2):
        n = int(counts.get(k, 0))
        print(f"   {labels[k]:<4}  {n:>8,}  ({n / total:.1%})")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--sim-minutes", type=float, default=30.0)
    p.add_argument("--tick-hz", type=float, default=20.0)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--depth-levels", type=int, default=LEVELS)
    p.add_argument("--horizon-steps", type=int, default=DEFAULT_HORIZON_STEPS)
    p.add_argument("--tick-threshold", type=float, default=DEFAULT_TICK_THRESHOLD)
    p.add_argument("--out-dir", type=Path, default=Path("research/datasets"))
    return p.parse_args()


def main() -> None:
    args = parse_args()
    cfg = CollectConfig(**vars(args))
    cfg.out_dir.mkdir(parents=True, exist_ok=True)

    print("═" * 70)
    print(" Orderflow Lab — collect_data (Hawkes → parquet)")
    print("═" * 70)
    for k, v in asdict(cfg).items():
        print(f" {k:<16}: {v}")
    print()

    df = run_collection(cfg)
    print_class_balance(df, cfg.horizon_steps)

    out_path = cfg.out_dir / f"hawkes_seed{cfg.seed}_m{int(cfg.sim_minutes)}_hz{int(cfg.tick_hz)}.parquet"
    df.to_parquet(out_path, index=False)
    size_mb = out_path.stat().st_size / 1024 / 1024
    print(f"\n wrote {out_path} ({size_mb:.1f} MB, {len(df):,} rows × {len(df.columns)} cols)")
    print("═" * 70)


if __name__ == "__main__":
    main()
