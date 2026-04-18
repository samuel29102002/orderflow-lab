"""State-reactive order flow inspired by Huang–Lehalle–Rosenbaum (2015).

The full HLR model conditions separate arrival processes for limit-, market-
and cancel-events on the top-of-book queue sizes. Our MVP keeps the shape
— arrival rate and microstructure tilt respond to the book — but the
generator still only emits :class:`LimitOrderEvent`\\ s (the matching engine
handles cancels / fills implicitly).

Concretely, when the book is observed each tick via :meth:`observe`:

* **Arrival rate.** Tighter spreads imply more urgency on both sides, so λ
  scales inversely with spread (clipped to ``[1, max_spread]``).
* **Aggressiveness.** Tighter spreads ⇒ smaller average offset from mid,
  pushing orders closer to or through the touch (higher fill probability).
* **Side bias.** Queue-top imbalance skews arrivals toward the heavier side
  — the dominant queue begets more of the same (persistence).

Each event is still emitted via an exponential inter-arrival on the
currently-observed rate, so the generator reduces to a vanilla Poisson
generator when the book is empty or the reactivity coefficients are zero.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from orderflow_engine import Side

from ..events import LimitOrderEvent
from .base import BookState, FlowGenerator, MarketContext, MarketContextConfig


@dataclass(frozen=True, slots=True)
class QueueReactiveConfig:
    """Parameters for :class:`QueueReactiveFlowGenerator`."""

    # Baseline arrival rate when spread is at ``baseline_spread`` ticks.
    base_lambda: float = 80.0
    # Spread bucket used to normalise λ and offset scaling.
    baseline_spread: int = 2
    max_spread_clip: int = 8
    # Tuning knobs for the reactive tilt.
    rate_sensitivity: float = 1.0
    offset_sensitivity: float = 0.75
    imbalance_sensitivity: float = 0.35
    # OU + microstructure (shared with Poisson).
    mid0: float = 10_000.0
    mu: float = 10_000.0
    kappa: float = 1.5
    sigma: float = 4.0
    offset_mean: float = 3.0
    qty_mean: float = 10.0
    # ids + seeding
    seed: int = 0
    start_id: int = 1


class QueueReactiveFlowGenerator(FlowGenerator):
    """Poisson arrivals whose rate / side / offset react to the book state."""

    name = "queue_reactive"

    def __init__(self, config: QueueReactiveConfig) -> None:
        self.cfg = config
        self._rng = np.random.default_rng(config.seed)
        self.t: float = 0.0
        self._next_id: int = config.start_id
        self._state: BookState | None = None
        self._ctx = MarketContext(
            MarketContextConfig(
                mid0=config.mid0,
                mu=config.mu,
                kappa=config.kappa,
                sigma=config.sigma,
                offset_mean=config.offset_mean,
                qty_mean=config.qty_mean,
            ),
            self._rng,
        )

    # ---- iterator + observer ---------------------------------------------

    def observe(self, state: BookState) -> None:
        self._state = state

    def __next__(self) -> LimitOrderEvent:
        return self._emit()

    # ---- introspection ---------------------------------------------------

    @property
    def mid(self) -> float:
        return self._ctx.mid

    @property
    def next_id(self) -> int:
        return self._next_id

    def current_rate(self) -> float:
        return self._rate_for(self._spread())

    # ---- reactive kernels ------------------------------------------------

    def _spread(self) -> int:
        cfg = self.cfg
        if self._state is None or self._state.spread is None:
            return cfg.baseline_spread
        return max(1, min(cfg.max_spread_clip, int(self._state.spread)))

    def _rate_for(self, spread: int) -> float:
        cfg = self.cfg
        # Smoothly scale λ: tight spread (=1) boosts it, wide spread shrinks it.
        ratio = cfg.baseline_spread / spread
        multiplier = 1.0 + cfg.rate_sensitivity * (ratio - 1.0)
        return max(1e-3, cfg.base_lambda * multiplier)

    def _offset_scale(self, spread: int) -> float:
        cfg = self.cfg
        # Tight spread → smaller offset (orders closer to / crossing the touch).
        ratio = spread / cfg.baseline_spread
        return max(0.25, cfg.offset_mean * (ratio**cfg.offset_sensitivity))

    def _side_bias(self) -> float:
        cfg = self.cfg
        state = self._state
        if state is None:
            return 0.5
        bid_q = float(state.bid_top_qty)
        ask_q = float(state.ask_top_qty)
        denom = bid_q + ask_q
        if denom <= 0.0:
            return 0.5
        imbalance = (bid_q - ask_q) / denom
        # Heavier queue attracts more new orders on that side (persistence).
        return float(np.clip(0.5 + cfg.imbalance_sensitivity * imbalance, 0.1, 0.9))

    # ---- core step --------------------------------------------------------

    def _emit(self) -> LimitOrderEvent:
        spread = self._spread()
        rate = self._rate_for(spread)
        offset_scale = self._offset_scale(spread)
        bias = self._side_bias()

        dt = float(self._rng.exponential(1.0 / rate))
        self.t += dt
        self._ctx.evolve_mid(dt)

        side = Side.Bid if float(self._rng.random()) < bias else Side.Ask
        price = self._ctx.draw_price(side, offset_scale=offset_scale)
        qty = self._ctx.draw_qty()

        oid = self._next_id
        self._next_id += 1
        return LimitOrderEvent(
            timestamp=self.t, id=oid, side=side, price=price, qty=qty
        )
