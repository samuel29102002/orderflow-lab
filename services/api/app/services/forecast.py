"""Live DeepLOB forecaster.

Maintains a rolling window of the most recent ``seq_len`` book snapshots
and serves per-tick direction predictions to the simulation loop.

Graceful degradation
--------------------
The API must boot even with no trained weights on disk (fresh checkout,
or before the user has run ``research/train_deeplob.py``). In that case
``Forecaster.predict`` returns a forecast with ``model_ready=False`` and
``direction="flat"``. The UI simply shows an "N/A" badge.

Thread safety
-------------
The simulation loop is single-threaded (asyncio) so we don't need a lock
around the rolling window. Inference is a synchronous ``forward()`` call
— on the tiny model (~15k params) that takes ~0.5 ms on a laptop CPU,
well inside the 50 ms tick budget.
"""

from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Sequence

import torch

from app.models.deeplob import (
    DEFAULT_HORIZON_STEPS,
    DEFAULT_SEQ_LEN,
    FEATURE_DIM,
    DeepLOB,
    build_feature_row,
)

log = logging.getLogger(__name__)

Direction = Literal["down", "flat", "up"]
CLASS_NAMES: tuple[Direction, Direction, Direction] = ("down", "flat", "up")


@dataclass(frozen=True, slots=True)
class ForecastResult:
    """A single live forecast emitted alongside a broadcast frame."""

    direction: Direction
    probs: tuple[float, float, float]  # (down, flat, up)
    horizon_steps: int
    model_ready: bool


class Forecaster:
    """Rolling-window inference wrapper around :class:`DeepLOB`."""

    def __init__(
        self,
        checkpoint_path: Path | str | None,
        *,
        seq_len: int = DEFAULT_SEQ_LEN,
        horizon_steps: int = DEFAULT_HORIZON_STEPS,
    ) -> None:
        self._window: deque[list[float]] = deque(maxlen=seq_len)
        self._seq_len = seq_len
        self._horizon_steps = horizon_steps
        self._model: DeepLOB | None = None
        self._ready = False
        self._load_error: str | None = None
        self._load(checkpoint_path)

    # ---- loading ---------------------------------------------------------

    def _load(self, path: Path | str | None) -> None:
        if path is None:
            self._load_error = "no checkpoint path configured"
            return
        p = Path(path)
        if not p.exists():
            self._load_error = f"checkpoint not found at {p}"
            log.info("forecast: %s — running in stub mode", self._load_error)
            return
        try:
            ckpt = torch.load(p, map_location="cpu", weights_only=True)
            # Prefer the seq_len / horizon saved at training time so config
            # drift can't silently mis-wire the window.
            self._seq_len = int(ckpt.get("seq_len", self._seq_len))
            self._horizon_steps = int(ckpt.get("horizon_steps", self._horizon_steps))
            self._window = deque(maxlen=self._seq_len)
            model = DeepLOB(seq_len=self._seq_len, feature_dim=FEATURE_DIM)
            model.load_state_dict(ckpt["state_dict"])
            model.eval()
            self._model = model
            self._ready = True
            log.info(
                "forecast: loaded %s (params=%d, seq_len=%d, horizon=%d)",
                p,
                model.num_parameters(),
                self._seq_len,
                self._horizon_steps,
            )
        except Exception as exc:  # noqa: BLE001
            self._load_error = f"failed to load checkpoint: {exc!r}"
            log.exception("forecast: checkpoint load failed")

    # ---- introspection ---------------------------------------------------

    @property
    def ready(self) -> bool:
        return self._ready

    @property
    def seq_len(self) -> int:
        return self._seq_len

    @property
    def horizon_steps(self) -> int:
        return self._horizon_steps

    @property
    def load_error(self) -> str | None:
        return self._load_error

    # ---- per-tick API ----------------------------------------------------

    def push_snapshot(
        self,
        bids: Sequence[tuple[int, int]],
        asks: Sequence[tuple[int, int]],
        mid: float | None,
    ) -> None:
        """Append one snapshot to the rolling window."""
        if mid is None:
            # One-sided / empty book: reset rather than feed zeros, which
            # would contaminate the sequence as soon as the book refills.
            self._window.clear()
            return
        self._window.append(build_feature_row(bids, asks, mid))

    def predict(self) -> ForecastResult:
        """Emit a 3-class forecast from the current rolling window."""
        if not self._ready or self._model is None:
            return ForecastResult(
                direction="flat",
                probs=(0.0, 1.0, 0.0),
                horizon_steps=self._horizon_steps,
                model_ready=False,
            )
        if len(self._window) < self._seq_len:
            # Warming up — show flat so the UI badge renders something stable.
            return ForecastResult(
                direction="flat",
                probs=(0.0, 1.0, 0.0),
                horizon_steps=self._horizon_steps,
                model_ready=False,
            )
        x = torch.tensor([list(self._window)], dtype=torch.float32)  # (1, T, F)
        probs = self._model.predict_proba(x).squeeze(0).tolist()
        idx = int(max(range(3), key=lambda i: probs[i]))
        return ForecastResult(
            direction=CLASS_NAMES[idx],
            probs=(float(probs[0]), float(probs[1]), float(probs[2])),
            horizon_steps=self._horizon_steps,
            model_ready=True,
        )
