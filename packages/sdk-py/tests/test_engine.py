"""Behaviour tests for the :class:`Engine` wrapper."""

from __future__ import annotations

import pytest

from orderflow_sdk import Engine, Side
from orderflow_sdk.events import LimitOrderEvent


def test_submit_auto_allocates_monotonic_ids() -> None:
    eng = Engine()
    r1 = eng.submit(Side.Bid, price=100, qty=5)
    r2 = eng.submit(Side.Bid, price=99, qty=3)
    assert r1.order_id == 1
    assert r2.order_id == 2
    assert r1.trades == []
    assert len(eng) == 2


def test_explicit_id_is_respected_and_advances_counter() -> None:
    eng = Engine()
    r = eng.submit(Side.Ask, price=101, qty=4, id=42)
    assert r.order_id == 42
    # Next auto id should be 43 via apply_limit keeping the counter consistent.
    evt = LimitOrderEvent(timestamp=0.0, id=43, side=Side.Bid, price=100, qty=1)
    eng.apply_limit(evt)
    r2 = eng.submit(Side.Ask, price=102, qty=1)
    assert r2.order_id == 44


def test_submit_crosses_and_returns_trades() -> None:
    eng = Engine()
    eng.submit(Side.Ask, price=100, qty=5)
    eng.submit(Side.Ask, price=101, qty=5)
    r = eng.submit(Side.Bid, price=101, qty=7)
    # Sweeps level 100 fully, then 2@101.
    assert [(t.price, t.qty) for t in r.trades] == [(100, 5), (101, 2)]
    assert eng.best_ask() == 101
    assert eng.best_bid() is None


def test_cancel_and_modify() -> None:
    eng = Engine()
    r = eng.submit(Side.Bid, price=99, qty=10)
    assert eng.cancel(r.order_id) == 10
    assert not eng.contains(r.order_id)

    r2 = eng.submit(Side.Bid, price=98, qty=6)
    outcome = eng.modify(r2.order_id, price=98, qty=4)
    # Amend-down: partial cancel, nothing re-submitted, no trades.
    assert outcome.canceled_qty == 2
    assert outcome.submitted_qty == 0
    assert outcome.trades == []


def test_depth_and_mid() -> None:
    eng = Engine()
    eng.submit(Side.Bid, price=100, qty=5)
    eng.submit(Side.Bid, price=99, qty=3)
    eng.submit(Side.Ask, price=101, qty=4)
    eng.submit(Side.Ask, price=102, qty=7)

    assert eng.depth(Side.Bid) == [(100, 5), (99, 3)]
    assert eng.depth(Side.Ask) == [(101, 4), (102, 7)]
    assert eng.mid() == pytest.approx(100.5)
    assert eng.spread() == 1


def test_unknown_id_raises_keyerror() -> None:
    eng = Engine()
    with pytest.raises(KeyError):
        eng.cancel(999)
