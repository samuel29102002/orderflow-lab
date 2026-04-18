//! Public value types for the matching engine.
//!
//! All prices and quantities are integers (ticks and lots). Callers own the
//! conversion to/from human units — the engine never sees floats. This keeps
//! arithmetic deterministic and bit-exact across runs.

use core::fmt;

/// Stable identifier for an order, assigned by the caller.
pub type OrderId = u64;

/// Price, expressed in ticks.
pub type Price = u64;

/// Quantity, expressed in lots.
pub type Qty = u64;

/// Monotonic sequence number. Assigned by the book for time priority and
/// for ordering trades in the output stream.
pub type Seq = u64;

/// Side of the book.
#[derive(Copy, Clone, Debug, Eq, PartialEq, Hash)]
pub enum Side {
    Bid,
    Ask,
}

impl Side {
    #[inline]
    pub fn opposite(self) -> Self {
        match self {
            Side::Bid => Side::Ask,
            Side::Ask => Side::Bid,
        }
    }
}

impl fmt::Display for Side {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(match self {
            Side::Bid => "bid",
            Side::Ask => "ask",
        })
    }
}

/// A new limit order. The engine assigns the time-priority sequence internally;
/// callers supply only the logical fields.
#[derive(Copy, Clone, Debug, Eq, PartialEq)]
pub struct NewOrder {
    pub id: OrderId,
    pub side: Side,
    pub price: Price,
    pub qty: Qty,
}

/// A single trade between a resting maker and an incoming taker.
/// Fills are always at the maker's price (price-time priority).
#[derive(Copy, Clone, Debug, Eq, PartialEq)]
pub struct Trade {
    pub seq: Seq,
    pub maker_id: OrderId,
    pub taker_id: OrderId,
    pub taker_side: Side,
    pub price: Price,
    pub qty: Qty,
}

/// Command applied to the book. Useful as a replayable event type.
#[derive(Copy, Clone, Debug, Eq, PartialEq)]
pub enum Command {
    Limit(NewOrder),
    Cancel { id: OrderId },
    Modify { id: OrderId, new_price: Price, new_qty: Qty },
}

/// Outcome of applying a [`Command`]. Each variant carries enough data for
/// conservation accounting (submitted = resting + canceled + 2 * traded).
#[derive(Clone, Debug, Eq, PartialEq)]
pub enum CommandOutcome {
    Limit {
        trades: Vec<Trade>,
    },
    Cancel {
        qty: Qty,
    },
    /// Either an in-place amend (priority preserved) or a cancel-replace
    /// (priority lost, may cross the spread).
    ///
    /// * `canceled_qty` — lots removed from the book by this modify
    ///   (either the in-place reduction, or the old remaining qty on
    ///   cancel-replace).
    /// * `submitted_qty` — lots submitted as the replacement leg
    ///   (0 for in-place; `new_qty` for cancel-replace).
    /// * `trades` — fills produced by the replacement leg.
    Modify {
        canceled_qty: Qty,
        submitted_qty: Qty,
        trades: Vec<Trade>,
    },
}

/// Snapshot of one resting order, for inspection and tests.
#[derive(Copy, Clone, Debug, Eq, PartialEq)]
pub struct ResidentOrder {
    pub id: OrderId,
    pub qty: Qty,
    pub seq: Seq,
}
