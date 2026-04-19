"""Pure-Python passive market-maker agent.

Strategy
--------
Places a bid and an ask simultaneously at a fixed half-spread from the
current mid price.  Both quotes are refreshed whenever the mid moves by
more than one tick so they stay competitive.  Earns the full spread when
both sides fill.

Unlike the DeepLOBAgent this strategy has no directional view — it is
indifferent to whether the next tick is up or down.  Inventory risk is
managed implicitly through the ``max_pos`` hard cap and the position-
aware headroom check that prevents new quotes from breaching the limit.

The class is intentionally pure-Python with no dependency on the Rust
engine.  The live driver in ``services/api`` is responsible for turning
:class:`AgentAction` records into engine submissions and for feeding
fills back via :meth:`MarketMakerAgent.on_fill`.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from orderflow_engine import Side

from .deeplob_agent import AgentAction, AgentActionKind

log = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class MarketMakerConfig:
    half_spread: int = 5
    """Ticks from mid on each side.  Quoted bid = mid−half_spread;
    quoted ask = mid+half_spread."""

    qty: int = 10
    """Lots to quote on each side."""

    max_pos: int = 100
    """Hard cap on |position|; new quotes that would breach this are skipped."""

    refresh_cooldown_s: float = 0.05
    """Minimum sim-seconds between full quote refreshes."""


@dataclass(slots=True)
class MarketMakerState:
    """Running P&L and open-order bookkeeping."""

    position: int = 0
    cash: float = 0.0
    realized_pnl: float = 0.0
    unrealized_pnl: float = 0.0
    fills: int = 0
    gross_traded_qty: int = 0
    cost_basis: float = 0.0

    bid_order_id: int | None = None
    bid_price: int | None = None
    ask_order_id: int | None = None
    ask_price: int | None = None
    last_refresh_t: float = field(default=float("-inf"))

    @property
    def total_pnl(self) -> float:
        return self.realized_pnl + self.unrealized_pnl


class MarketMakerAgent:
    """Stateful two-sided quoting agent; no I/O, no engine calls of its own."""

    def __init__(self, config: MarketMakerConfig | None = None) -> None:
        self.cfg = config or MarketMakerConfig()
        self.state = MarketMakerState()

    # ---- state updates ---------------------------------------------------

    def on_fill(self, side: Side, price: int, qty: int, order_id: int) -> None:
        """Called by the driver when one of our resting orders is hit."""
        if qty <= 0:
            return
        s = self.state
        signed_qty = qty if side == Side.Bid else -qty
        new_pos = s.position + signed_qty

        # VWAP cost-basis accounting (same logic as DeepLOBAgent).
        if s.position == 0 or (s.position > 0) == (signed_qty > 0):
            if new_pos != 0:
                s.cost_basis = (
                    (s.cost_basis * s.position) + (price * signed_qty)
                ) / new_pos
            else:
                s.cost_basis = 0.0
        else:
            closing = min(abs(s.position), qty)
            pnl_sign = 1 if s.position > 0 else -1
            s.realized_pnl += pnl_sign * closing * (price - s.cost_basis)
            remaining = qty - closing
            if remaining > 0:
                s.cost_basis = float(price)
            elif new_pos == 0:
                s.cost_basis = 0.0

        s.position = new_pos
        s.cash -= signed_qty * price
        s.fills += 1
        s.gross_traded_qty += qty

        # Clear the filled side.
        if order_id == s.bid_order_id:
            s.bid_order_id = None
            s.bid_price = None
        elif order_id == s.ask_order_id:
            s.ask_order_id = None
            s.ask_price = None

    def on_order_gone(self, order_id: int) -> None:
        """Driver hook: the order left the book without a matching fill."""
        s = self.state
        if order_id == s.bid_order_id:
            s.bid_order_id = None
            s.bid_price = None
        elif order_id == s.ask_order_id:
            s.ask_order_id = None
            s.ask_price = None

    def mark_to_mid(self, mid: float | None) -> None:
        s = self.state
        if mid is None or s.position == 0:
            s.unrealized_pnl = 0.0
            return
        s.unrealized_pnl = s.position * (mid - s.cost_basis)

    def record_submitted(
        self, side: Side, order_id: int, price: int, t: float
    ) -> None:
        """Driver hook: called after a successful engine submission."""
        s = self.state
        if side == Side.Bid:
            s.bid_order_id = order_id
            s.bid_price = price
        else:
            s.ask_order_id = order_id
            s.ask_price = price
        s.last_refresh_t = t

    # ---- decision -------------------------------------------------------

    def decide_all(
        self,
        t: float,
        mid: float | None,
        best_bid: int | None,
        best_ask: int | None,
    ) -> list[AgentAction]:
        """Return up to 4 actions: cancel/re-quote for each side as needed."""
        if mid is None or best_bid is None or best_ask is None:
            return self._cancel_all()

        cfg = self.cfg
        s = self.state

        mid_int = round(mid)
        want_bid = mid_int - cfg.half_spread
        want_ask = mid_int + cfg.half_spread

        # Don't cross the book or quote inside the spread.
        if want_bid >= best_ask or want_ask <= best_bid:
            return self._cancel_all()

        log.debug("MM quoting Bid: %d Ask: %d", want_bid, want_ask)

        actions: list[AgentAction] = []
        cooldown_ok = t - s.last_refresh_t >= cfg.refresh_cooldown_s

        # --- bid side ---
        if s.bid_order_id is not None and s.bid_price != want_bid:
            actions.append(AgentAction(
                kind=AgentActionKind.CANCEL,
                cancel_id=s.bid_order_id,
                reason="bid price moved",
            ))
        elif s.bid_order_id is None and cooldown_ok:
            bid_headroom = cfg.max_pos - s.position
            if bid_headroom > 0:
                actions.append(AgentAction(
                    kind=AgentActionKind.SUBMIT,
                    side=Side.Bid,
                    price=want_bid,
                    qty=min(cfg.qty, bid_headroom),
                    reason="quote bid",
                ))

        # --- ask side ---
        if s.ask_order_id is not None and s.ask_price != want_ask:
            actions.append(AgentAction(
                kind=AgentActionKind.CANCEL,
                cancel_id=s.ask_order_id,
                reason="ask price moved",
            ))
        elif s.ask_order_id is None and cooldown_ok:
            ask_headroom = cfg.max_pos + s.position
            if ask_headroom > 0:
                actions.append(AgentAction(
                    kind=AgentActionKind.SUBMIT,
                    side=Side.Ask,
                    price=want_ask,
                    qty=min(cfg.qty, ask_headroom),
                    reason="quote ask",
                ))

        return actions

    def _cancel_all(self) -> list[AgentAction]:
        s = self.state
        actions: list[AgentAction] = []
        if s.bid_order_id is not None:
            actions.append(AgentAction(
                kind=AgentActionKind.CANCEL,
                cancel_id=s.bid_order_id,
                reason="no mid",
            ))
        if s.ask_order_id is not None:
            actions.append(AgentAction(
                kind=AgentActionKind.CANCEL,
                cancel_id=s.ask_order_id,
                reason="no mid",
            ))
        return actions
