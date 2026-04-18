"""DeepLOB-style next-move classifier.

A compact re-implementation of the CNN + LSTM architecture from Zhang,
Zohren & Roberts (2019), tuned down to ~15k parameters so a single-batch
forward pass comfortably finishes in <20 ms on a modern CPU.

Input / output contract
-----------------------
* Features: for each of ``LEVELS=10`` book levels we pack
  ``(ask_price_off, ask_qty_log, bid_price_off, bid_qty_log)`` giving
  ``FEATURE_DIM = 40`` scalars per snapshot. ``build_feature_row`` is the
  single source of truth for that packing — collector, trainer, and live
  inference must all call it.
* Input tensor shape: ``(B, T=DEFAULT_SEQ_LEN, FEATURE_DIM)``.
* Output: logits over three classes ``[down, flat, up]`` describing the
  sign of the mid-price change over ``DEFAULT_HORIZON_STEPS`` snapshots
  (which at the default 20 Hz tick rate is 500 ms sim-time).

Normalisation
-------------
Prices are stored relative to the *current* mid (``price - mid``), so the
CNN sees queue shape rather than absolute levels — this kills the slow OU
drift that would otherwise dominate the signal. Quantities are passed
through ``log1p(q) / log1p(qty_scale)`` so a few outliers don't blow up
the activations.
"""

from __future__ import annotations

import math
from typing import Sequence

import torch
from torch import Tensor, nn

LEVELS: int = 10
"""Number of book levels per side fed into the model."""

FEATURE_DIM: int = 4 * LEVELS
"""40 = 10 levels × (ask_price, ask_qty, bid_price, bid_qty)."""

DEFAULT_SEQ_LEN: int = 50
"""Lookback window in snapshots. 50 × 50 ms = 2.5 s of sim-time at 20 Hz."""

DEFAULT_HORIZON_STEPS: int = 10
"""Prediction horizon in snapshots. 10 × 50 ms = 500 ms of sim-time at 20 Hz."""

DEFAULT_TICK_THRESHOLD: float = 0.5
"""Mid-move magnitude (ticks) below which the label is 'flat'."""

DEFAULT_QTY_SCALE: float = 50.0
"""Normaliser for order-book quantities — rough order of the top-book size."""


def build_feature_row(
    bids: Sequence[tuple[int, int]],
    asks: Sequence[tuple[int, int]],
    mid: float,
    *,
    qty_scale: float = DEFAULT_QTY_SCALE,
    levels: int = LEVELS,
) -> list[float]:
    """Pack a single book snapshot into the fixed-length feature row.

    ``bids`` and ``asks`` are ``(price, qty)`` pairs sorted best→worst.
    Missing levels are zero-padded so the row is always ``FEATURE_DIM``
    long. Prices are emitted *relative to the mid* in ticks and quantities
    are log-normalised so the scale stays ~O(1) regardless of flow rate.
    """
    denom = math.log1p(qty_scale)
    row: list[float] = []
    for k in range(levels):
        if k < len(asks):
            ap, aq = asks[k]
            ap_off = float(ap) - mid
            aq_norm = math.log1p(float(aq)) / denom
        else:
            ap_off, aq_norm = 0.0, 0.0
        if k < len(bids):
            bp, bq = bids[k]
            bp_off = float(bp) - mid
            bq_norm = math.log1p(float(bq)) / denom
        else:
            bp_off, bq_norm = 0.0, 0.0
        row.extend([ap_off, aq_norm, bp_off, bq_norm])
    return row


class DeepLOB(nn.Module):
    """Small CNN → GRU head with a 3-class softmax.

    Three conv stages progressively collapse the 40-wide feature axis
    (price/qty pairs → bid/ask pairs → across-level pooling) while
    preserving the time axis. The time-major output then feeds a single
    GRU whose last hidden state is classified.

    We use a GRU rather than an LSTM to keep the parameter count low — at
    ``hidden=32`` it's ~6k params vs ~8.5k for the LSTM, and the
    short-horizon signal we're predicting doesn't benefit from a cell gate.
    """

    def __init__(
        self,
        seq_len: int = DEFAULT_SEQ_LEN,
        feature_dim: int = FEATURE_DIM,
        hidden: int = 32,
        num_classes: int = 3,
    ) -> None:
        super().__init__()
        assert feature_dim == FEATURE_DIM, "feature_dim must equal FEATURE_DIM"
        self.seq_len = seq_len
        self.hidden = hidden

        # Stage 1: collapse each (price, qty) pair.            (B, 1,  T, 40) → (B, 16, T, 20)
        # Stage 2: collapse each (ask-half, bid-half) pair.     → (B, 16, T, 10)
        # Stage 3: pool across all 10 levels.                    → (B, 32, T, 1)
        # Short 1D kernels along the time axis sprinkled in for local temporal structure.
        self.conv = nn.Sequential(
            nn.Conv2d(1, 16, kernel_size=(1, 2), stride=(1, 2)),
            nn.LeakyReLU(0.01),
            nn.Conv2d(16, 16, kernel_size=(3, 1), padding=(1, 0)),
            nn.LeakyReLU(0.01),
            nn.Conv2d(16, 16, kernel_size=(1, 2), stride=(1, 2)),
            nn.LeakyReLU(0.01),
            nn.Conv2d(16, 16, kernel_size=(3, 1), padding=(1, 0)),
            nn.LeakyReLU(0.01),
            nn.Conv2d(16, 32, kernel_size=(1, LEVELS)),
            nn.LeakyReLU(0.01),
        )

        self.gru = nn.GRU(32, hidden, batch_first=True)
        self.head = nn.Linear(hidden, num_classes)

    def forward(self, x: Tensor) -> Tensor:
        # x: (B, T, F=40)
        if x.dim() != 3 or x.size(-1) != FEATURE_DIM:
            raise ValueError(f"expected (B, T, {FEATURE_DIM}), got {tuple(x.shape)}")
        x = x.unsqueeze(1)              # (B, 1, T, 40)
        x = self.conv(x)                # (B, 32, T, 1)
        x = x.squeeze(-1).transpose(1, 2)  # (B, T, 32)
        _out, h = self.gru(x)           # h: (1, B, hidden)
        return self.head(h.squeeze(0))  # (B, num_classes)

    @torch.no_grad()
    def predict_proba(self, x: Tensor) -> Tensor:
        self.eval()
        return torch.softmax(self.forward(x), dim=-1)

    def num_parameters(self) -> int:
        return sum(p.numel() for p in self.parameters())
