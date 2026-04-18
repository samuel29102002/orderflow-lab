"""Stateful convenience wrapper around the Rust :class:`OrderBook`."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from orderflow_engine import (
    ModifyOutcome,
    NewOrder,
    OrderBook,
    ResidentOrder,
    Side,
    Trade,
)

from .events import LimitOrderEvent


@dataclass(frozen=True, slots=True)
class SubmitResult:
    """Return value for :meth:`Engine.submit` — keeps the assigned id handy."""

    order_id: int
    trades: list[Trade]


class Engine:
    """High-level order entry on top of :class:`orderflow_engine.OrderBook`.

    Allocates monotonically increasing order ids so callers can submit orders
    without tracking ids themselves, while still supporting explicit ids for
    deterministic replay.
    """

    def __init__(self, *, start_id: int = 1) -> None:
        self._book = OrderBook()
        self._next_id = start_id

    # ---- order entry ------------------------------------------------------

    def submit(
        self,
        side: Side,
        price: int,
        qty: int,
        *,
        id: int | None = None,
    ) -> SubmitResult:
        oid = id if id is not None else self._allocate_id()
        trades = self._book.submit(NewOrder(oid, side, price, qty))
        return SubmitResult(order_id=oid, trades=trades)

    def cancel(self, order_id: int) -> int:
        return self._book.cancel(order_id)

    def modify(self, order_id: int, price: int, qty: int) -> ModifyOutcome:
        return self._book.modify(order_id, price, qty)

    def apply_limit(self, event: LimitOrderEvent) -> list[Trade]:
        """Dispatch a :class:`LimitOrderEvent` from a flow generator."""
        self._next_id = max(self._next_id, event.id + 1)
        return self._book.submit(
            NewOrder(event.id, event.side, event.price, event.qty)
        )

    def apply_many(self, events: Iterable[LimitOrderEvent]) -> int:
        """Apply a batch, returning the total number of trades produced."""
        total = 0
        submit = self._book.submit
        for evt in events:
            self._next_id = max(self._next_id, evt.id + 1)
            total += len(
                submit(NewOrder(evt.id, evt.side, evt.price, evt.qty))
            )
        return total

    # ---- inspection -------------------------------------------------------

    @property
    def book(self) -> OrderBook:
        return self._book

    def best_bid(self) -> int | None:
        return self._book.best_bid()

    def best_ask(self) -> int | None:
        return self._book.best_ask()

    def spread(self) -> int | None:
        return self._book.spread()

    def mid(self) -> float | None:
        b, a = self._book.best_bid(), self._book.best_ask()
        if b is None or a is None:
            return None
        return (b + a) / 2.0

    def depth(self, side: Side) -> list[tuple[int, int]]:
        """Price-level depth on one side, sorted best→worst."""
        prices = self._book.level_prices(side)
        return [(p, self._book.level_qty(side, p)) for p in prices]

    def level_orders(self, side: Side, price: int) -> list[ResidentOrder]:
        return self._book.level_orders(side, price)

    def contains(self, order_id: int) -> bool:
        return self._book.contains(order_id)

    def __len__(self) -> int:
        return len(self._book)

    def __repr__(self) -> str:
        return (
            f"Engine(len={len(self._book)}, "
            f"best_bid={self._book.best_bid()}, "
            f"best_ask={self._book.best_ask()})"
        )

    # ---- internals --------------------------------------------------------

    def _allocate_id(self) -> int:
        oid = self._next_id
        self._next_id += 1
        return oid
