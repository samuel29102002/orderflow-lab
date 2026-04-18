"""Shared machinery for all flow generators.

Every generator produces :class:`LimitOrderEvent` streams. What differs is
*when* the next event arrives (Poisson ↦ Hawkes ↦ state-reactive) and,
optionally, how the price/quantity are drawn.

This module factors out three primitives:

* :class:`BookState` — a lightweight, copy-on-read view of the book that the
  simulation loop hands to generators via :meth:`FlowGenerator.observe`.
* :class:`MarketContext` — OU mid-price plus exponential offset/quantity
  draws. Shared by every concrete generator.
* :class:`FlowGenerator` — abstract base; concrete subclasses own the
  arrival process and the side-choice logic.
"""

from __future__ import annotations

import math
from abc import ABC, abstractmethod
from dataclasses import dataclass

import numpy as np

from orderflow_engine import Side

from ..events import LimitOrderEvent


@dataclass(frozen=True, slots=True)
class BookState:
    """Snapshot of the book handed to reactive generators each tick.

    Only cheap-to-compute fields are included — generators that need deeper
    introspection can add their own reader.
    """

    t: float
    best_bid: int | None
    best_ask: int | None
    spread: int | None
    mid: float | None
    bid_top_qty: int
    ask_top_qty: int


@dataclass(frozen=True, slots=True)
class MarketContextConfig:
    """Parameters for the shared mid-price + offset/qty draw machinery."""

    mid0: float = 10_000.0
    mu: float = 10_000.0
    kappa: float = 1.5
    sigma: float = 4.0
    offset_mean: float = 3.0
    qty_mean: float = 10.0


class MarketContext:
    """Owns the mid-price and draws per-event price/qty.

    The mid evolves as an OU process with exact closed-form transitions
    between event arrivals. :meth:`draw_price` returns an integer tick price
    by adding an exponential offset (away from mid, in the order's favour —
    bids post below mid, asks post above).
    """

    def __init__(self, config: MarketContextConfig, rng: np.random.Generator) -> None:
        self.cfg = config
        self._rng = rng
        self.mid: float = float(config.mid0)

    def evolve_mid(self, dt: float) -> float:
        """Advance the OU mid by ``dt`` and return the new value."""
        cfg = self.cfg
        if cfg.kappa <= 0.0:
            self.mid = self.mid + cfg.sigma * math.sqrt(dt) * float(self._rng.standard_normal())
            return self.mid
        ek = math.exp(-cfg.kappa * dt)
        mean = cfg.mu + (self.mid - cfg.mu) * ek
        var = (cfg.sigma * cfg.sigma) * (1.0 - ek * ek) / (2.0 * cfg.kappa)
        self.mid = float(self._rng.normal(mean, math.sqrt(var)))
        return self.mid

    def draw_price(self, side: Side, *, offset_scale: float | None = None) -> int:
        """Draw an integer tick price for ``side``.

        ``offset_scale`` overrides the configured ``offset_mean`` for a single
        draw — used by reactive generators to tighten/loosen the quote in
        response to book state.
        """
        scale = offset_scale if offset_scale is not None else self.cfg.offset_mean
        offset = float(self._rng.exponential(max(scale, 1e-9)))
        if side == Side.Bid:
            return max(1, int(round(self.mid - offset)))
        return max(1, int(round(self.mid + offset)))

    def draw_qty(self, *, qty_scale: float | None = None) -> int:
        scale = qty_scale if qty_scale is not None else self.cfg.qty_mean
        return max(1, int(round(float(self._rng.exponential(max(scale, 1e-9))))))


class FlowGenerator(ABC):
    """Common iterator protocol for order-flow generators.

    Subclasses implement :meth:`__next__` to emit the next
    :class:`LimitOrderEvent`. Reactive subclasses override :meth:`observe` to
    refresh any state-dependent parameters from the current :class:`BookState`.
    """

    name: str = "generator"

    def __iter__(self) -> "FlowGenerator":
        return self

    @abstractmethod
    def __next__(self) -> LimitOrderEvent:  # pragma: no cover - abstract
        ...

    def observe(self, state: BookState) -> None:
        """Hook for state-reactive generators. Default implementation: noop."""
