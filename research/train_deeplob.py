#!/usr/bin/env python3
"""train_deeplob — fit the DeepLOB 3-class next-move classifier.

Reads a parquet produced by ``research/collect_data.py``, turns it into
sliding ``(T, F)`` windows, runs SGD on CPU, saves the trained weights to
``research/artifacts/deeplob.pt``.

The training set is deliberately tiny so the whole loop runs in seconds on
a laptop — about what a junior quant would reach for before spending GPU
time. Reported accuracy should comfortably beat the majority-class
baseline printed alongside it.

Run from the repo root (venv activated)::

    .venv/bin/python research/train_deeplob.py
    .venv/bin/python research/train_deeplob.py --epochs 10 --batch-size 256
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import torch
from torch import nn
from torch.utils.data import DataLoader, TensorDataset

API_APP = Path(__file__).resolve().parent.parent / "services" / "api"
if str(API_APP) not in sys.path:
    sys.path.insert(0, str(API_APP))

from app.models.deeplob import (  # noqa: E402
    DEFAULT_HORIZON_STEPS,
    DEFAULT_SEQ_LEN,
    FEATURE_DIM,
    DeepLOB,
)


def build_windows(
    df: pd.DataFrame,
    seq_len: int,
    horizon_steps: int,
) -> tuple[np.ndarray, np.ndarray]:
    """Materialise a ``(N, seq_len, FEATURE_DIM)`` tensor + labels from rows."""
    feat_cols = [f"f{k}" for k in range(FEATURE_DIM)]
    label_col = f"label_h{horizon_steps}"
    if label_col not in df.columns:
        raise ValueError(f"missing label column {label_col}; re-run collect_data with matching horizon")

    feats = df[feat_cols].to_numpy(dtype=np.float32)  # (N_rows, F)
    labels = df[label_col].to_numpy(dtype=np.int64)

    # Sliding window via strides: avoids a Python loop on 36k rows.
    n_rows, f = feats.shape
    n_windows = n_rows - seq_len + 1
    if n_windows <= 0:
        raise ValueError(f"dataset too small for seq_len={seq_len}: have {n_rows} rows")

    # ``as_strided`` gives us zero-copy views; we materialise once so DataLoader
    # workers don't have to reason about the underlying storage.
    windows = np.lib.stride_tricks.sliding_window_view(feats, window_shape=(seq_len, f))
    # shape: (n_windows, 1, seq_len, f); drop the singleton axis
    windows = windows[:, 0, :, :].copy()
    # Label for window ending at index ``i + seq_len - 1`` is the label of that row.
    window_labels = labels[seq_len - 1 :]

    return windows, window_labels


def train_one_epoch(
    model: DeepLOB,
    loader: DataLoader,
    loss_fn: nn.Module,
    opt: torch.optim.Optimizer,
) -> tuple[float, float]:
    model.train()
    total, correct, loss_sum = 0, 0, 0.0
    for xb, yb in loader:
        opt.zero_grad()
        logits = model(xb)
        loss = loss_fn(logits, yb)
        loss.backward()
        opt.step()
        loss_sum += float(loss.item()) * yb.size(0)
        correct += int((logits.argmax(-1) == yb).sum().item())
        total += yb.size(0)
    return loss_sum / total, correct / total


@torch.no_grad()
def evaluate(model: DeepLOB, loader: DataLoader, loss_fn: nn.Module) -> tuple[float, float, np.ndarray]:
    model.eval()
    total, correct, loss_sum = 0, 0, 0.0
    confusion = np.zeros((3, 3), dtype=np.int64)
    for xb, yb in loader:
        logits = model(xb)
        loss = loss_fn(logits, yb)
        loss_sum += float(loss.item()) * yb.size(0)
        preds = logits.argmax(-1)
        correct += int((preds == yb).sum().item())
        total += yb.size(0)
        for y_true, y_pred in zip(yb.numpy(), preds.numpy()):
            confusion[int(y_true), int(y_pred)] += 1
    return loss_sum / total, correct / total, confusion


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--data", type=Path, default=None, help="parquet path; defaults to newest file in research/datasets/")
    p.add_argument("--seq-len", type=int, default=DEFAULT_SEQ_LEN)
    p.add_argument("--horizon-steps", type=int, default=DEFAULT_HORIZON_STEPS)
    p.add_argument("--epochs", type=int, default=6)
    p.add_argument("--batch-size", type=int, default=256)
    p.add_argument("--lr", type=float, default=2e-3)
    p.add_argument("--val-frac", type=float, default=0.2)
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--out", type=Path, default=Path("research/artifacts/deeplob.pt"))
    return p.parse_args()


def _newest_parquet(dir_: Path) -> Path:
    files = sorted(dir_.glob("*.parquet"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not files:
        raise FileNotFoundError(f"no parquet files in {dir_}; run collect_data.py first")
    return files[0]


def main() -> None:
    args = parse_args()
    torch.manual_seed(args.seed)
    np.random.seed(args.seed)

    data_path = args.data or _newest_parquet(Path("research/datasets"))
    print("═" * 70)
    print(" Orderflow Lab — train_deeplob")
    print("═" * 70)
    print(f" data    : {data_path}")
    print(f" seq_len : {args.seq_len}")
    print(f" horizon : {args.horizon_steps} steps")
    print(f" epochs  : {args.epochs}")
    print(f" batch   : {args.batch_size}")
    print(f" lr      : {args.lr}")

    df = pd.read_parquet(data_path)
    windows, labels = build_windows(df, args.seq_len, args.horizon_steps)
    print(f" windows : {len(windows):,}  (F={FEATURE_DIM})")

    # Time-ordered split — classification on rolling book state is a time
    # series, shuffling would leak future info into training.
    n = len(windows)
    split = int(n * (1.0 - args.val_frac))
    x_train, y_train = windows[:split], labels[:split]
    x_val, y_val = windows[split:], labels[split:]

    # Class priors printed to make the baseline honest.
    maj_cls = int(np.bincount(y_train, minlength=3).argmax())
    baseline = float((y_val == maj_cls).mean())
    print(f" majority class on train: {('down','flat','up')[maj_cls]}  ⇒ val baseline acc={baseline:.3f}")

    train_ds = TensorDataset(torch.from_numpy(x_train), torch.from_numpy(y_train))
    val_ds = TensorDataset(torch.from_numpy(x_val), torch.from_numpy(y_val))
    train_loader = DataLoader(train_ds, batch_size=args.batch_size, shuffle=True)
    val_loader = DataLoader(val_ds, batch_size=args.batch_size, shuffle=False)

    model = DeepLOB(seq_len=args.seq_len)
    print(f" model   : {model.num_parameters():,} parameters")
    # Class-balanced CE — flat usually dominates, otherwise the model just
    # learns to emit it every time.
    class_counts = np.bincount(y_train, minlength=3).astype(np.float32)
    class_weight = torch.from_numpy(class_counts.sum() / (3.0 * class_counts + 1e-8))
    loss_fn = nn.CrossEntropyLoss(weight=class_weight)
    opt = torch.optim.Adam(model.parameters(), lr=args.lr)

    print()
    print(" epoch  train_loss  train_acc  val_loss   val_acc")
    start = time.perf_counter()
    best_val = -1.0
    for epoch in range(1, args.epochs + 1):
        tl, ta = train_one_epoch(model, train_loader, loss_fn, opt)
        vl, va, _ = evaluate(model, val_loader, loss_fn)
        mark = "  *" if va > best_val else ""
        best_val = max(best_val, va)
        print(f"  {epoch:>3}   {tl:>8.4f}   {ta:>7.3f}   {vl:>7.4f}   {va:>6.3f}{mark}")

    elapsed = time.perf_counter() - start
    print(f"\n trained in {elapsed:.1f}s  best_val_acc={best_val:.3f}")

    _, va, confusion = evaluate(model, val_loader, loss_fn)
    print("\n confusion matrix on validation (rows=true, cols=pred):")
    print("            down    flat      up")
    for i, name in enumerate(("down", "flat", "up")):
        print(f"   {name:<4}  {confusion[i, 0]:>6}  {confusion[i, 1]:>6}  {confusion[i, 2]:>6}")

    # Latency smoke test — keeps the <20ms budget honest.
    model.eval()
    x = torch.from_numpy(windows[:1]).float()
    with torch.no_grad():
        for _ in range(3):
            model(x)  # warm-up
        start = time.perf_counter()
        iters = 50
        for _ in range(iters):
            model(x)
        per_call = (time.perf_counter() - start) / iters * 1000
    print(f"\n inference: {per_call:.2f} ms / single-batch forward pass (target <20 ms)")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    torch.save(
        {
            "state_dict": model.state_dict(),
            "seq_len": args.seq_len,
            "horizon_steps": args.horizon_steps,
            "feature_dim": FEATURE_DIM,
            "class_names": ["down", "flat", "up"],
            "val_acc": va,
            "val_baseline": baseline,
        },
        args.out,
    )
    size_kb = args.out.stat().st_size / 1024
    print(f" wrote {args.out} ({size_kb:.1f} KB)")
    print("═" * 70)


if __name__ == "__main__":
    main()
