"""DeepLOB agent unit tests — decide logic, AC sizing, PnL bookkeeping."""

from __future__ import annotations

import pytest
from orderflow_engine import Side
from orderflow_sdk.agents import (
    AgentActionKind,
    DeepLOBAgent,
    DeepLOBAgentConfig,
    ForecastSignal,
)


def _sig(direction: str, probs: tuple[float, float, float], ready: bool = True) -> ForecastSignal:
    return ForecastSignal(direction=direction, probs=probs, model_ready=ready)


# ---- decide ----------------------------------------------------------------


def test_noop_until_model_ready() -> None:
    agent = DeepLOBAgent()
    action = agent.decide(
        t=1.0,
        best_bid=99,
        best_ask=101,
        signal=_sig("flat", (0.1, 0.8, 0.1), ready=False),
    )
    assert action.kind is AgentActionKind.NOOP


def test_buy_on_high_up_signal_joins_best_bid() -> None:
    agent = DeepLOBAgent(DeepLOBAgentConfig(threshold=0.7, base_clip=5, max_pos=50))
    action = agent.decide(
        t=1.0,
        best_bid=99,
        best_ask=101,
        signal=_sig("up", (0.1, 0.1, 0.8)),
    )
    assert action.kind is AgentActionKind.SUBMIT
    assert action.side is Side.Bid
    assert action.price == 99
    assert action.qty == 5


def test_sell_on_high_down_signal_joins_best_ask() -> None:
    agent = DeepLOBAgent(DeepLOBAgentConfig(threshold=0.7, base_clip=5, max_pos=50))
    action = agent.decide(
        t=1.0,
        best_bid=99,
        best_ask=101,
        signal=_sig("down", (0.85, 0.10, 0.05)),
    )
    assert action.kind is AgentActionKind.SUBMIT
    assert action.side is Side.Ask
    assert action.price == 101


def test_low_confidence_emits_noop() -> None:
    agent = DeepLOBAgent(DeepLOBAgentConfig(threshold=0.7))
    # Top class is only 0.60 — below threshold.
    action = agent.decide(t=1.0, best_bid=99, best_ask=101, signal=_sig("up", (0.2, 0.2, 0.6)))
    assert action.kind is AgentActionKind.NOOP


def test_cooldown_blocks_immediate_resubmit() -> None:
    agent = DeepLOBAgent(DeepLOBAgentConfig(threshold=0.7, place_cooldown_s=0.2))
    agent.record_submitted(order_id=1, side=Side.Bid, price=99, qty=5, t=1.00)
    agent.on_fill(Side.Bid, price=99, qty=5)  # clears open order
    # 0.05s later — still within the 0.2s cooldown.
    action = agent.decide(t=1.05, best_bid=99, best_ask=101, signal=_sig("up", (0.1, 0.1, 0.8)))
    assert action.kind is AgentActionKind.NOOP
    assert action.reason == "cooldown"


def test_cancel_when_signal_disagrees_with_resting_side() -> None:
    agent = DeepLOBAgent()
    agent.record_submitted(order_id=1, side=Side.Bid, price=99, qty=5, t=1.0)
    action = agent.decide(t=2.0, best_bid=99, best_ask=101, signal=_sig("down", (0.8, 0.1, 0.1)))
    assert action.kind is AgentActionKind.CANCEL
    assert action.cancel_id == 1


def test_cancel_when_best_price_moves_away() -> None:
    agent = DeepLOBAgent()
    agent.record_submitted(order_id=1, side=Side.Bid, price=99, qty=5, t=1.0)
    action = agent.decide(t=2.0, best_bid=100, best_ask=102, signal=_sig("up", (0.1, 0.1, 0.8)))
    assert action.kind is AgentActionKind.CANCEL
    assert action.cancel_id == 1


def test_hold_when_resting_already_matches_intent() -> None:
    agent = DeepLOBAgent()
    agent.record_submitted(order_id=1, side=Side.Bid, price=99, qty=5, t=1.0)
    action = agent.decide(t=2.0, best_bid=99, best_ask=101, signal=_sig("up", (0.1, 0.1, 0.8)))
    assert action.kind is AgentActionKind.NOOP
    assert action.reason == "already resting"


# ---- AC sizing -------------------------------------------------------------


def test_ac_penalty_shrinks_clip_as_position_grows() -> None:
    cfg = DeepLOBAgentConfig(base_clip=10, max_pos=20, risk_aversion=1.0, threshold=0.7)
    agent = DeepLOBAgent(cfg)
    # pos = 0 → full clip
    agent.state.position = 0
    assert agent._scaled_clip(Side.Bid) == 10
    # pos = 10 → half-loaded, linear taper at γ=1 → clip ≈ 5
    agent.state.position = 10
    assert agent._scaled_clip(Side.Bid) == 5
    # pos = 20 → at limit → zero add
    agent.state.position = 20
    assert agent._scaled_clip(Side.Bid) == 0


def test_ac_lets_reducing_side_trade_full_size() -> None:
    cfg = DeepLOBAgentConfig(base_clip=10, max_pos=20, risk_aversion=2.0)
    agent = DeepLOBAgent(cfg)
    agent.state.position = 15  # long
    # Selling = reducing |pos|. Full clip allowed, hard-capped by headroom.
    assert agent._scaled_clip(Side.Ask) == 10  # clip is 10, headroom to short = 20+15 = 35


def test_hard_cap_never_exceeds_max_pos() -> None:
    cfg = DeepLOBAgentConfig(base_clip=100, max_pos=20, risk_aversion=0.0)
    agent = DeepLOBAgent(cfg)
    # γ=0 disables the AC penalty (penalty = max(0, 1 - x^0) = max(0, 0) = 0 for any |pos|>0).
    # So adding is blocked the moment we hold inventory.
    agent.state.position = 10
    assert agent._scaled_clip(Side.Bid) == 0
    # Reducing still uses full base clip, capped by headroom = max_pos + pos = 30.
    assert agent._scaled_clip(Side.Ask) == 30


# ---- PnL bookkeeping -------------------------------------------------------


def test_realized_pnl_on_roundtrip() -> None:
    agent = DeepLOBAgent()
    agent.on_fill(Side.Bid, price=100, qty=10)
    assert agent.state.position == 10
    assert agent.state.cost_basis == 100.0
    assert agent.state.cash == -1000.0
    assert agent.state.realized_pnl == 0.0
    # Sell the lot 2 ticks higher.
    agent.on_fill(Side.Ask, price=102, qty=10)
    assert agent.state.position == 0
    assert agent.state.realized_pnl == pytest.approx(20.0)  # 10 * 2 ticks
    assert agent.state.cash == pytest.approx(20.0)


def test_unrealized_marks_inventory_to_mid() -> None:
    agent = DeepLOBAgent()
    agent.on_fill(Side.Bid, price=100, qty=10)
    agent.mark_to_mid(101.5)
    assert agent.state.unrealized_pnl == pytest.approx(15.0)
    agent.mark_to_mid(98.0)
    assert agent.state.unrealized_pnl == pytest.approx(-20.0)


def test_flip_through_zero_resets_cost_basis() -> None:
    agent = DeepLOBAgent()
    agent.on_fill(Side.Bid, price=100, qty=5)  # long 5 @ 100
    agent.on_fill(Side.Ask, price=103, qty=8)  # sell 8 — closes 5, flips to short 3 @ 103
    assert agent.state.position == -3
    assert agent.state.realized_pnl == pytest.approx(5 * (103 - 100))
    assert agent.state.cost_basis == pytest.approx(103.0)


def test_fill_clears_open_order_bookkeeping() -> None:
    agent = DeepLOBAgent()
    agent.record_submitted(order_id=42, side=Side.Bid, price=100, qty=5, t=1.0)
    assert agent.state.open_order_id == 42
    agent.on_fill(Side.Bid, price=100, qty=5)
    assert agent.state.open_order_id is None
