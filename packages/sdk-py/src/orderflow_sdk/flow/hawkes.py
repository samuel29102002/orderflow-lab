"""Bivariate Hawkes process with exponential kernels.

Models self- and cross-exciting order flow on the (bid, ask) pair. An
aggressive buy lifts the buy intensity (momentum) and — with a smaller
weight — also the sell intensity (mean-reversion / liquidity response),
producing the "clustering" that plain Poisson cannot.

Mathematical model
------------------
Let component 0 = ``Side.Bid``, component 1 = ``Side.Ask``. The conditional
intensity of component *i* at time *t* is::

    λ_i(t) = μ_i + Σ_j α[i,j] · Σ_{t_k^j < t} exp(-β[i,j] · (t − t_k^j))

With an exponential kernel we carry a 2×2 "excitation state"::

    h[i,j](t) = Σ_{t_k^j < t} exp(-β[i,j] · (t − t_k^j))

which decays deterministically between events and jumps by +1 at every
arrival. This keeps :meth:`__next__` ``O(1)`` — no history scan.

Simulation (Ogata thinning)
---------------------------
Between events the intensity only decays (exponential kernels), so the
total intensity at the current time is an upper bound for the total
intensity on any subsequent sub-interval. We draw a candidate arrival
``τ ∼ Exp(Σ_i λ_i(t))``, decay ``h`` forward by ``τ``, then accept with
probability ``(Σ_i λ_i(t+τ)) / (Σ_i λ_i(t))`` (the usual thinning
acceptance). On accept, pick the component by its current intensity share.
On reject, keep the decayed state and try again.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from orderflow_engine import Side

from ..events import LimitOrderEvent
from .base import FlowGenerator, MarketContext, MarketContextConfig

_BID = 0
_ASK = 1


@dataclass(frozen=True, slots=True)
class HawkesConfig:
    """Parameters for :class:`HawkesFlowGenerator`.

    Components are indexed ``[0 = bid, 1 = ask]``. The defaults target a
    branching ratio of ~0.75 (stable) and a steady-state total intensity of
    ~80 events per unit time, matching the default :class:`FlowConfig`.

    Stability condition: the spectral radius of ``alpha / beta`` must be
    strictly less than 1. For the symmetric 2×2 defaults this reduces to
    ``alpha_self/beta_self + alpha_cross/beta_cross < 1``.
    """

    # Baseline intensities (events per unit time per side).
    mu_bid: float = 10.0
    mu_ask: float = 10.0
    # Self-excitation (a bid excites the bid intensity).
    alpha_self: float = 0.6
    # Cross-excitation (a bid excites the ask intensity and vice versa).
    alpha_cross: float = 0.15
    # Decay rate of the exponential kernel (same for every entry by default).
    beta: float = 1.0
    # OU mid-price & micro-structure (shared with the Poisson generator).
    mid0: float = 10_000.0
    mu: float = 10_000.0
    kappa: float = 1.5
    sigma: float = 4.0
    offset_mean: float = 3.0
    qty_mean: float = 10.0
    # ids + seeding
    seed: int = 0
    start_id: int = 1
    # Fraction of orders that are aggressive (cross the spread).
    market_fraction: float = 0.15
    # Safety bound on the per-event rejection loop.
    max_thinning_attempts: int = 10_000


class HawkesFlowGenerator(FlowGenerator):
    """Bivariate self- & cross-exciting Hawkes flow with exponential kernel."""

    name = "hawkes"

    def __init__(self, config: HawkesConfig) -> None:
        self.cfg = config
        self._rng = np.random.default_rng(config.seed)
        self.t: float = 0.0
        self._next_id: int = config.start_id

        self._mu = np.array([config.mu_bid, config.mu_ask], dtype=np.float64)
        self._alpha = np.array(
            [
                [config.alpha_self, config.alpha_cross],
                [config.alpha_cross, config.alpha_self],
            ],
            dtype=np.float64,
        )
        self._beta = np.full((2, 2), config.beta, dtype=np.float64)
        # Excitation state. h[i,j] decays with β[i,j], jumps on type-j events.
        self._h = np.zeros((2, 2), dtype=np.float64)

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

        # Fail fast if parameters are unstable — runaway processes would
        # choke the sim loop.
        self._check_stability()

    # ---- introspection ----------------------------------------------------

    @property
    def next_id(self) -> int:
        return self._next_id

    @property
    def mid(self) -> float:
        return self._ctx.mid

    def intensities(self) -> tuple[float, float]:
        """Current ``(λ_bid, λ_ask)``. Useful for tests and diagnostics."""
        lam = self._mu + np.einsum("ij,ij->i", self._alpha, self._h)
        return float(lam[_BID]), float(lam[_ASK])

    def branching_matrix(self) -> np.ndarray:
        return self._alpha / self._beta

    # ---- iterator protocol ------------------------------------------------

    def __next__(self) -> LimitOrderEvent:
        return self._emit()

    # ---- core step --------------------------------------------------------

    def _emit(self) -> LimitOrderEvent:
        cfg = self.cfg
        rng = self._rng

        for _ in range(cfg.max_thinning_attempts):
            lam = self._mu + np.einsum("ij,ij->i", self._alpha, self._h)
            lam_bar = float(lam.sum())
            if lam_bar <= 0.0:
                # Degenerate configuration — fall back to baseline.
                lam_bar = float(self._mu.sum())

            tau = float(rng.exponential(1.0 / lam_bar))
            self._decay(tau)
            self.t += tau

            lam_new = self._mu + np.einsum("ij,ij->i", self._alpha, self._h)
            lam_total = float(lam_new.sum())

            if rng.random() * lam_bar < lam_total:
                # Accept; pick component proportional to current intensity.
                component = _BID if rng.random() * lam_total < lam_new[_BID] else _ASK
                self._jump(component)
                return self._build_event(component)
            # Reject: h has already decayed; try again from the new state.

        raise RuntimeError(
            "Hawkes thinning exceeded max attempts — check parameter stability"
        )

    # ---- Hawkes state transitions ----------------------------------------

    def _decay(self, dt: float) -> None:
        if dt <= 0.0:
            return
        self._h *= np.exp(-self._beta * dt)
        # OU mid evolves on the same wall-clock.
        self._ctx.evolve_mid(dt)

    def _jump(self, component: int) -> None:
        # A type-j event adds +1 to h[i,j] for every i (it excites every
        # component's intensity through α[i,j]).
        self._h[:, component] += 1.0

    def _build_event(self, component: int) -> LimitOrderEvent:
        side = Side.Bid if component == _BID else Side.Ask
        # Aggressive orders cross the spread, enabling market-maker fills.
        if bool(self._rng.random() < self.cfg.market_fraction):
            price = self._ctx.draw_price(Side.Ask if side == Side.Bid else Side.Bid)
        else:
            price = self._ctx.draw_price(side)
        qty = self._ctx.draw_qty()
        oid = self._next_id
        self._next_id += 1
        return LimitOrderEvent(
            timestamp=self.t, id=oid, side=side, price=price, qty=qty
        )

    # ---- stability sanity ------------------------------------------------

    def _check_stability(self) -> None:
        branching = self._alpha / self._beta
        spectral_radius = float(np.max(np.abs(np.linalg.eigvals(branching))))
        if not math.isfinite(spectral_radius) or spectral_radius >= 1.0:
            raise ValueError(
                "Hawkes parameters are unstable: spectral radius of α/β "
                f"= {spectral_radius:.3f} ≥ 1"
            )
