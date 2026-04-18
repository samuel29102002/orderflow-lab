"""DeepLOB-signal-driven passive market-making agent.

Strategy
--------
Each time the forecaster emits a high-confidence direction, the agent joins
the relevant side of the book with a passive limit order:

* ``p_up > threshold`` → place a **buy** at the current best bid
* ``p_down > threshold`` → place a **sell** at the current best ask

Order management is deliberately minimal to keep the behaviour legible:

* At most one resting agent order at any time.
* If the active signal still agrees with a resting order that's still at the
  correct price, leave it alone.
* Otherwise cancel and re-post at the new best, subject to a short
  ``place_cooldown_s`` that stops us re-posting multiple times per tick.

Risk-aversion (Almgren-Chriss flavour)
--------------------------------------
Almgren & Chriss parametrise optimal execution around a *quadratic*
inventory penalty: carrying inventory is costly because it's exposed to
price risk, so the utility-maximising trader shrinks the clip as
``|pos|`` grows. Here we apply the same idea — but only when the signal
would *add* to |pos|. When the signal *reduces* |pos| we let the full
base clip through so the agent flattens quickly.

Formally::

    scale(pos) = max(0, 1 - (|pos| / max_pos) ** γ)

where ``γ = risk_aversion`` controls how aggressively we back off. γ=1 is
a linear taper; γ>1 is flatter near zero and cliffs near the limit. The
clip is additionally hard-capped so the final submitted quantity can
never push ``|pos|`` past ``max_pos``.

The agent class is intentionally pure-Python with no dependency on the
Rust engine — the live driver in ``services/api`` is responsible for
turning :class:`AgentAction` records into engine submissions and for
feeding fills back in via :meth:`DeepLOBAgent.on_fill`. Everything in
this module is unit-testable without uvicorn or a loaded model.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Literal

from orderflow_engine import Side

Direction = Literal["down", "flat", "up"]


@dataclass(frozen=True, slots=True)
class ForecastSignal:
    """Direction + class probabilities, matching the DeepLOB head output."""

    direction: Direction
    probs: tuple[float, float, float]  # (p_down, p_flat, p_up)
    model_ready: bool = True

    @property
    def p_up(self) -> float:
        return self.probs[2]

    @property
    def p_down(self) -> float:
        return self.probs[0]


class AgentActionKind(str, Enum):
    NOOP = "noop"
    SUBMIT = "submit"
    CANCEL = "cancel"


@dataclass(frozen=True, slots=True)
class AgentAction:
    """Instruction for the live driver to translate into engine calls."""

    kind: AgentActionKind
    side: Side | None = None
    price: int | None = None
    qty: int | None = None
    cancel_id: int | None = None
    reason: str = ""


@dataclass(frozen=True, slots=True)
class DeepLOBAgentConfig:
    threshold: float = 0.70
    """Minimum probability on the winning class required to trade."""

    base_clip: int = 5
    """Default clip size before Almgren-Chriss scaling."""

    max_pos: int = 50
    """Hard cap on |position|; the agent will not submit orders that
    would breach this even after accounting for fills in flight."""

    risk_aversion: float = 1.5
    """Exponent γ in the quadratic inventory penalty. γ=1 is linear."""

    place_cooldown_s: float = 0.10
    """Minimum sim-seconds between two *new* submissions. Cancels to
    re-post at a moved price are still rate-limited by this."""


@dataclass(slots=True)
class AgentState:
    """Running P&L + book-keeping for display and tests.

    Cash is signed: negative after a buy (we paid), positive after a sell.
    Realised PnL is computed on inventory *reduction* using a VWAP cost
    basis; unrealised PnL marks the remaining inventory to mid.

    PnL units are *tick-values* (price × qty) — consistent with the rest
    of the simulator which keeps prices as integer ticks.
    """

    position: int = 0
    cash: float = 0.0
    realized_pnl: float = 0.0
    unrealized_pnl: float = 0.0
    fills: int = 0
    gross_traded_qty: int = 0
    open_order_id: int | None = None
    open_order_side: Side | None = None
    open_order_price: int | None = None
    open_order_qty: int | None = None
    cost_basis: float = 0.0  # VWAP of current inventory
    last_place_t: float = field(default=float("-inf"))

    @property
    def total_pnl(self) -> float:
        return self.realized_pnl + self.unrealized_pnl


class DeepLOBAgent:
    """Stateful decision function; no I/O, no engine calls of its own."""

    def __init__(self, config: DeepLOBAgentConfig | None = None) -> None:
        self.cfg = config or DeepLOBAgentConfig()
        self.state = AgentState()

    # ---- sizing ----------------------------------------------------------

    def _scaled_clip(self, side: Side) -> int:
        """Almgren-Chriss-style clip: shrink when *adding* to |pos|."""
        cfg = self.cfg
        pos = self.state.position
        adding = (side == Side.Bid and pos >= 0) or (side == Side.Ask and pos <= 0)
        if not adding:
            clip = cfg.base_clip
        else:
            load = min(1.0, abs(pos) / cfg.max_pos) if cfg.max_pos > 0 else 0.0
            penalty = max(0.0, 1.0 - load**cfg.risk_aversion)
            clip = max(0, int(round(cfg.base_clip * penalty)))

        # Hard cap so we can never punch through max_pos on a single clip.
        headroom_pos = cfg.max_pos - pos if side == Side.Bid else cfg.max_pos + pos
        return max(0, min(clip, headroom_pos))

    # ---- state updates ---------------------------------------------------

    def on_fill(self, side: Side, price: int, qty: int) -> None:
        """Called by the driver when one of our resting orders is hit."""
        if qty <= 0:
            return
        s = self.state
        signed_qty = qty if side == Side.Bid else -qty
        new_pos = s.position + signed_qty

        # VWAP cost basis for realized-vs-unrealized accounting.
        if s.position == 0 or (s.position > 0) == (signed_qty > 0):
            # Building or opening: blend into cost basis.
            if new_pos != 0:
                s.cost_basis = (
                    (s.cost_basis * s.position) + (price * signed_qty)
                ) / new_pos
            else:
                s.cost_basis = 0.0
        else:
            # Reducing or flipping: realize against current cost basis.
            closing = min(abs(s.position), qty)
            pnl_sign = 1 if s.position > 0 else -1
            s.realized_pnl += pnl_sign * closing * (price - s.cost_basis)
            remaining = qty - closing
            if remaining > 0:
                # We flipped through zero — the remainder opens a new position
                # at the fill price.
                s.cost_basis = float(price)
            elif new_pos == 0:
                s.cost_basis = 0.0

        s.position = new_pos
        s.cash -= signed_qty * price  # buys pay; sells receive
        s.fills += 1
        s.gross_traded_qty += qty

        # Any fill clears the resting order (partial fills are out of scope
        # for this simple agent — the Rust engine does fill-or-rest).
        s.open_order_id = None
        s.open_order_side = None
        s.open_order_price = None
        s.open_order_qty = None

    def on_order_gone(self) -> None:
        """The driver observed the resting order leave the book without a
        matching fill — treat as a cancel confirmation."""
        s = self.state
        s.open_order_id = None
        s.open_order_side = None
        s.open_order_price = None
        s.open_order_qty = None

    def mark_to_mid(self, mid: float | None) -> None:
        """Mark remaining inventory to the current mid price."""
        if mid is None or self.state.position == 0:
            self.state.unrealized_pnl = 0.0
            return
        self.state.unrealized_pnl = self.state.position * (mid - self.state.cost_basis)

    def record_submitted(self, order_id: int, side: Side, price: int, qty: int, t: float) -> None:
        """Driver hook: called after a successful submission."""
        s = self.state
        s.open_order_id = order_id
        s.open_order_side = side
        s.open_order_price = price
        s.open_order_qty = qty
        s.last_place_t = t

    # ---- decision -------------------------------------------------------

    def decide(
        self,
        t: float,
        best_bid: int | None,
        best_ask: int | None,
        signal: ForecastSignal,
    ) -> AgentAction:
        """Produce one :class:`AgentAction` per tick.

        The driver is expected to feed this the *current* best bid/ask and
        the active forecast; the agent returns at most one action.
        """
        cfg = self.cfg
        s = self.state

        if not signal.model_ready or best_bid is None or best_ask is None:
            if s.open_order_id is not None:
                return AgentAction(
                    kind=AgentActionKind.CANCEL,
                    cancel_id=s.open_order_id,
                    reason="signal not ready",
                )
            return AgentAction(kind=AgentActionKind.NOOP, reason="warmup")

        # Derive intent from the winning probability mass.
        want_side: Side | None = None
        if signal.p_up >= cfg.threshold:
            want_side = Side.Bid
        elif signal.p_down >= cfg.threshold:
            want_side = Side.Ask

        # No high-conviction signal: cancel any stale resting order.
        if want_side is None:
            if s.open_order_id is not None:
                return AgentAction(
                    kind=AgentActionKind.CANCEL,
                    cancel_id=s.open_order_id,
                    reason="signal=flat",
                )
            return AgentAction(kind=AgentActionKind.NOOP, reason="no signal")

        want_price = best_bid if want_side == Side.Bid else best_ask

        # If we already rest at exactly the right side & price, leave it.
        if (
            s.open_order_id is not None
            and s.open_order_side == want_side
            and s.open_order_price == want_price
        ):
            return AgentAction(kind=AgentActionKind.NOOP, reason="already resting")

        # Different side or moved price: cancel first; the driver will re-
        # invoke us next tick or we can emit the new order after cooldown.
        if s.open_order_id is not None:
            return AgentAction(
                kind=AgentActionKind.CANCEL,
                cancel_id=s.open_order_id,
                reason="signal changed",
            )

        if t - s.last_place_t < cfg.place_cooldown_s:
            return AgentAction(kind=AgentActionKind.NOOP, reason="cooldown")

        qty = self._scaled_clip(want_side)
        if qty <= 0:
            return AgentAction(kind=AgentActionKind.NOOP, reason="inventory cap")

        return AgentAction(
            kind=AgentActionKind.SUBMIT,
            side=want_side,
            price=want_price,
            qty=qty,
            reason=f"signal={signal.direction} p={max(signal.probs):.2f}",
        )
