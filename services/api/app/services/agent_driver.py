"""Multi-agent driver: bridges pure-Python agents to the Rust engine.

Each agent lives in its own :class:`_Slot` which owns a reserved order-ID
range, a fill-attribution set, and a step/snapshot/reset interface.  The
outer :class:`AgentDriver` iterates over all slots each tick.

Slot ID ranges
--------------
* DeepLOB agent  : 1_000_000_000 – 1_999_999_999
* Market Maker   : 2_000_000_000 – 2_999_999_999

Flow generators emit monotonically-increasing IDs starting at 1, so both
ranges are safely above anything a generator will ever produce.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from orderflow_sdk import Engine, Side

from app.domain.schemas import AgentStateDTO, ForecastDTO, TradeDTO
from orderflow_sdk.agents import (
    AgentAction,
    AgentActionKind,
    DeepLOBAgent,
    DeepLOBAgentConfig,
    ForecastSignal,
    MarketMakerAgent,
    MarketMakerConfig,
)

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Slot configs
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class AgentDriverConfig:
    """Config for the DeepLOB-signal-driven directional agent."""

    enabled: bool = True
    threshold: float = 0.70
    base_clip: int = 5
    max_pos: int = 50
    risk_aversion: float = 1.5
    place_cooldown_s: float = 0.10
    id_offset: int = 1_000_000_000

    def to_agent_config(self) -> DeepLOBAgentConfig:
        return DeepLOBAgentConfig(
            threshold=self.threshold,
            base_clip=self.base_clip,
            max_pos=self.max_pos,
            risk_aversion=self.risk_aversion,
            place_cooldown_s=self.place_cooldown_s,
        )


@dataclass(slots=True)
class MarketMakerDriverConfig:
    """Config for the passive spread-earning market-maker agent."""

    enabled: bool = True
    half_spread: int = 5
    qty: int = 10
    max_pos: int = 100
    refresh_cooldown_s: float = 0.05
    id_offset: int = 2_000_000_000

    def to_agent_config(self) -> MarketMakerConfig:
        return MarketMakerConfig(
            half_spread=self.half_spread,
            qty=self.qty,
            max_pos=self.max_pos,
            refresh_cooldown_s=self.refresh_cooldown_s,
        )


# ---------------------------------------------------------------------------
# Internal slots
# ---------------------------------------------------------------------------


class _DeepLOBSlot:
    """Manages one DeepLOBAgent: reconcile fills, decide, execute."""

    def __init__(self, cfg: AgentDriverConfig) -> None:
        self.cfg = cfg
        self.agent = DeepLOBAgent(cfg.to_agent_config())
        self._own_ids: set[int] = set()
        self._next_id: int = cfg.id_offset
        # Slippage tracking: order_id → mid price at the moment of submission.
        self._mid_at_submit: dict[int, float] = {}
        self._total_slippage: float = 0.0
        self._slippage_fills: int = 0

    def reset(self) -> None:
        self.agent = DeepLOBAgent(self.cfg.to_agent_config())
        self._own_ids.clear()
        self._next_id = self.cfg.id_offset
        self._mid_at_submit.clear()
        self._total_slippage = 0.0
        self._slippage_fills = 0

    @property
    def avg_slippage(self) -> float:
        return self._total_slippage / self._slippage_fills if self._slippage_fills else 0.0

    def step(
        self,
        *,
        t: float,
        engine: Engine,
        best_bid: int | None,
        best_ask: int | None,
        mid: float | None,
        trades: list[TradeDTO],
        trade_maker_ids: list[int],
        forecast: ForecastDTO | None,
    ) -> None:
        self._reconcile_fills(trades, trade_maker_ids)
        self._check_order_alive(engine)
        self.agent.mark_to_mid(mid)

        if forecast is None:
            return

        signal = ForecastSignal(
            direction=forecast.direction,
            probs=forecast.probs,
            model_ready=forecast.model_ready,
        )
        action = self.agent.decide(t=t, best_bid=best_bid, best_ask=best_ask, signal=signal)
        self._execute(action, engine=engine, t=t, mid=mid)

    def _execute(self, action: AgentAction, *, engine: Engine, t: float, mid: float | None) -> None:
        if action.kind is AgentActionKind.NOOP:
            return
        if action.kind is AgentActionKind.CANCEL:
            cid = action.cancel_id
            if cid is None:
                return
            if engine.cancel(cid):
                self.agent.on_order_gone()
                self._mid_at_submit.pop(cid, None)
            return
        if action.kind is AgentActionKind.SUBMIT:
            assert action.side is not None and action.price is not None and action.qty is not None
            oid = self._next_id
            self._next_id += 1
            result = engine.submit(action.side, action.price, action.qty, id=oid)
            self._own_ids.add(result.order_id)
            # Record mid at decision time for slippage calculation.
            if mid is not None:
                self._mid_at_submit[result.order_id] = mid
            self.agent.record_submitted(
                order_id=result.order_id,
                side=action.side,
                price=action.price,
                qty=action.qty,
                t=t,
            )
            for trade in result.trades:
                self._record_slippage(result.order_id, trade.price)
                self.agent.on_fill(action.side, trade.price, trade.qty)

    def _reconcile_fills(self, trades: list[TradeDTO], maker_ids: list[int]) -> None:
        open_id = self.agent.state.open_order_id
        if open_id is None or not trades:
            return
        side = self.agent.state.open_order_side
        assert side is not None
        for trade, maker_id in zip(trades, maker_ids, strict=True):
            if maker_id == open_id:
                self._record_slippage(open_id, trade.price)
                self.agent.on_fill(side, trade.price, trade.qty)
                break

    def _record_slippage(self, order_id: int, fill_price: int) -> None:
        """Update running slippage average when a fill is attributed."""
        ref_mid = self._mid_at_submit.pop(order_id, None)
        if ref_mid is not None:
            self._total_slippage += abs(fill_price - ref_mid)
            self._slippage_fills += 1

    def _check_order_alive(self, engine: Engine) -> None:
        oid = self.agent.state.open_order_id
        if oid is None:
            return
        if not engine.contains(oid):
            self.agent.on_order_gone()

    def snapshot(self, mid: float | None) -> AgentStateDTO:
        s = self.agent.state
        return AgentStateDTO(
            name="deeplob",
            enabled=self.cfg.enabled,
            position=s.position,
            cash=s.cash,
            realized_pnl=s.realized_pnl,
            unrealized_pnl=s.unrealized_pnl,
            total_pnl=s.total_pnl,
            fills=s.fills,
            gross_qty=s.gross_traded_qty,
            open_order_id=s.open_order_id,
            open_order_side=("bid" if s.open_order_side == Side.Bid else "ask")
            if s.open_order_side is not None
            else None,
            open_order_price=s.open_order_price,
            open_order_qty=s.open_order_qty,
            cost_basis=s.cost_basis,
            mid=mid,
            avg_slippage=self.avg_slippage,
        )


class _MarketMakerSlot:
    """Manages one MarketMakerAgent: reconcile fills, decide_all, execute."""

    def __init__(self, cfg: MarketMakerDriverConfig) -> None:
        self.cfg = cfg
        self.agent = MarketMakerAgent(cfg.to_agent_config())
        self._own_ids: set[int] = set()
        self._next_id: int = cfg.id_offset
        # Slippage as adverse selection: mid at quote time vs mid at fill time.
        self._mid_at_submit: dict[int, float] = {}
        self._total_slippage: float = 0.0
        self._slippage_fills: int = 0

    def reset(self) -> None:
        self.agent = MarketMakerAgent(self.cfg.to_agent_config())
        self._own_ids.clear()
        self._next_id = self.cfg.id_offset
        self._mid_at_submit.clear()
        self._total_slippage = 0.0
        self._slippage_fills = 0

    @property
    def avg_slippage(self) -> float:
        return self._total_slippage / self._slippage_fills if self._slippage_fills else 0.0

    def step(
        self,
        *,
        t: float,
        engine: Engine,
        best_bid: int | None,
        best_ask: int | None,
        mid: float | None,
        trades: list[TradeDTO],
        trade_maker_ids: list[int],
        forecast: ForecastDTO | None,  # unused — MM is non-directional
    ) -> None:
        self._reconcile_fills(trades, trade_maker_ids, mid=mid)
        self._check_orders_alive(engine)
        self.agent.mark_to_mid(mid)

        actions = self.agent.decide_all(t=t, mid=mid, best_bid=best_bid, best_ask=best_ask)
        for action in actions:
            self._execute(action, engine=engine, t=t, mid=mid)

    def _execute(self, action: AgentAction, *, engine: Engine, t: float, mid: float | None) -> None:
        if action.kind is AgentActionKind.NOOP:
            return
        if action.kind is AgentActionKind.CANCEL:
            cid = action.cancel_id
            if cid is None:
                return
            if engine.cancel(cid):
                self.agent.on_order_gone(cid)
                self._mid_at_submit.pop(cid, None)
            return
        if action.kind is AgentActionKind.SUBMIT:
            assert action.side is not None and action.price is not None and action.qty is not None
            oid = self._next_id
            self._next_id += 1
            try:
                result = engine.submit(action.side, action.price, action.qty, id=oid)
            except Exception:
                log.warning("MM submit failed id=%d side=%s price=%d", oid, action.side, action.price)
                return
            self._own_ids.add(result.order_id)
            if mid is not None:
                self._mid_at_submit[result.order_id] = mid
            self.agent.record_submitted(
                side=action.side,
                order_id=result.order_id,
                price=action.price,
                t=t,
            )
            for trade in result.trades:
                self._record_slippage(result.order_id, mid)
                self.agent.on_fill(action.side, trade.price, trade.qty, result.order_id)

    def _reconcile_fills(
        self, trades: list[TradeDTO], maker_ids: list[int], *, mid: float | None
    ) -> None:
        s = self.agent.state
        if not trades:
            return
        for trade, maker_id in zip(trades, maker_ids, strict=True):
            if maker_id == s.bid_order_id:
                self._record_slippage(maker_id, mid)
                self.agent.on_fill(Side.Bid, trade.price, trade.qty, maker_id)
            elif maker_id == s.ask_order_id:
                self._record_slippage(maker_id, mid)
                self.agent.on_fill(Side.Ask, trade.price, trade.qty, maker_id)

    def _record_slippage(self, order_id: int, current_mid: float | None) -> None:
        """Adverse selection: mid moved from quote time to fill time."""
        ref_mid = self._mid_at_submit.pop(order_id, None)
        if ref_mid is not None and current_mid is not None:
            self._total_slippage += abs(current_mid - ref_mid)
            self._slippage_fills += 1

    def _check_orders_alive(self, engine: Engine) -> None:
        s = self.agent.state
        if s.bid_order_id is not None and not engine.contains(s.bid_order_id):
            self.agent.on_order_gone(s.bid_order_id)
        if s.ask_order_id is not None and not engine.contains(s.ask_order_id):
            self.agent.on_order_gone(s.ask_order_id)

    def snapshot(self, mid: float | None) -> AgentStateDTO:
        s = self.agent.state
        return AgentStateDTO(
            name="market_maker",
            enabled=self.cfg.enabled,
            position=s.position,
            cash=s.cash,
            realized_pnl=s.realized_pnl,
            unrealized_pnl=s.unrealized_pnl,
            total_pnl=s.total_pnl,
            fills=s.fills,
            gross_qty=s.gross_traded_qty,
            open_order_id=None,
            open_order_side=None,
            open_order_price=None,
            open_order_qty=None,
            cost_basis=s.cost_basis,
            mid=mid,
            avg_slippage=self.avg_slippage,
        )


# ---------------------------------------------------------------------------
# Public driver
# ---------------------------------------------------------------------------


class AgentDriver:
    """Coordinates all active agent slots for one simulation."""

    def __init__(self, slots: list[_DeepLOBSlot | _MarketMakerSlot]) -> None:
        self._slots = slots

    def step(
        self,
        *,
        t: float,
        engine: Engine,
        best_bid: int | None,
        best_ask: int | None,
        mid: float | None,
        trades: list[TradeDTO],
        trade_maker_ids: list[int],
        forecast: ForecastDTO | None,
    ) -> None:
        for slot in self._slots:
            slot.step(
                t=t,
                engine=engine,
                best_bid=best_bid,
                best_ask=best_ask,
                mid=mid,
                trades=trades,
                trade_maker_ids=trade_maker_ids,
                forecast=forecast,
            )

    def snapshots(self, mid: float | None) -> list[AgentStateDTO]:
        return [slot.snapshot(mid) for slot in self._slots]

    def reset(self) -> None:
        """Clear all agent state after a generator switch / engine reset."""
        for slot in self._slots:
            slot.reset()
