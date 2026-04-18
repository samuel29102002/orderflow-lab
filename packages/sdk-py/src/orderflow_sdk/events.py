"""Event dataclasses emitted by flow generators.

These are pure-Python structures so generator code stays independent of the
PyO3 extension and can be unit-tested without the Rust wheel installed.
"""

from __future__ import annotations

from dataclasses import dataclass

from orderflow_engine import Side


@dataclass(frozen=True, slots=True)
class LimitOrderEvent:
    """A single limit-order arrival."""

    timestamp: float
    id: int
    side: Side
    price: int
    qty: int
