"""Homogeneous Poisson + OU mean-reverting mid-price generator.

Historically the first generator shipped with the SDK. Kept as the baseline
against which the richer processes (:mod:`orderflow_sdk.flow.hawkes`,
:mod:`orderflow_sdk.flow.queue_reactive`) are compared.

Event timing: inter-arrivals ``~ Exp(lambda_rate)``.
Event side: ``Bernoulli(side_bias)``.
Price / qty: shared :class:`MarketContext` (OU mid + exponential offset/qty).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from orderflow_engine import Side

from ..events import LimitOrderEvent
from .base import FlowGenerator, MarketContext, MarketContextConfig


@dataclass(frozen=True, slots=True)
class FlowConfig:
    """Parameters for :class:`PoissonFlowGenerator`."""

    # arrivals
    lambda_rate: float = 100.0
    # OU mid-price
    mid0: float = 10_000.0
    mu: float = 10_000.0
    kappa: float = 2.0
    sigma: float = 5.0
    # order micro-structure
    offset_mean: float = 3.0
    qty_mean: float = 10.0
    side_bias: float = 0.5
    # ids + seeding
    seed: int = 0
    start_id: int = 1


class PoissonFlowGenerator(FlowGenerator):
    """Homogeneous Poisson arrivals with an OU mid-price."""

    name = "poisson"

    def __init__(self, config: FlowConfig) -> None:
        self.cfg = config
        self._rng = np.random.default_rng(config.seed)
        self.t: float = 0.0
        self._next_id: int = config.start_id
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

    # ---- state ------------------------------------------------------------

    @property
    def mid(self) -> float:
        return self._ctx.mid

    @property
    def next_id(self) -> int:
        return self._next_id

    # ---- iterator protocol ------------------------------------------------

    def __next__(self) -> LimitOrderEvent:
        return self._emit()

    # ---- convenience ------------------------------------------------------

    def stream(self, n: int):
        for _ in range(n):
            yield self._emit()

    def generate(self, n: int) -> list[LimitOrderEvent]:
        return [self._emit() for _ in range(n)]

    # ---- core step --------------------------------------------------------

    def _emit(self) -> LimitOrderEvent:
        cfg = self.cfg
        rng = self._rng

        dt = float(rng.exponential(1.0 / cfg.lambda_rate))
        self.t += dt
        self._ctx.evolve_mid(dt)

        side = Side.Bid if bool(rng.random() < cfg.side_bias) else Side.Ask
        price = self._ctx.draw_price(side)
        qty = self._ctx.draw_qty()

        oid = self._next_id
        self._next_id += 1
        return LimitOrderEvent(timestamp=self.t, id=oid, side=side, price=price, qty=qty)
