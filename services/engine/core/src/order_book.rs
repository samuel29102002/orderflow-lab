//! Continuous-double-auction limit order book with price-time (FIFO) priority.
//!
//! Design notes
//! ------------
//! * Each side is a `BTreeMap<Price, VecDeque<RestingOrder>>`. BTreeMap gives
//!   deterministic ordered iteration for best-price lookup; VecDeque gives
//!   O(1) push-back (insertion) and pop-front (fill) — the hot operations
//!   that FIFO priority demands.
//! * An `index: HashMap<OrderId, Location>` maps order id -> (side, price)
//!   for O(1) cancellation lookup. Removal within a level is O(level-depth)
//!   via linear scan; acceptable for v0 and for property testing. A linked
//!   list per level is a future optimization.
//! * A monotonic `next_seq` counter is the source of time priority and of
//!   trade sequence numbers. Given the same command stream, every Trade
//!   emitted is identical byte-for-byte — the determinism property the
//!   downstream replay pipeline relies on.
//! * No floating-point anywhere. Prices and quantities are `u64`.

use std::collections::{BTreeMap, HashMap, VecDeque};

use crate::errors::EngineError;
use crate::types::{
    Command, CommandOutcome, NewOrder, OrderId, Price, Qty, ResidentOrder, Seq, Side, Trade,
};

#[derive(Copy, Clone, Debug, Eq, PartialEq)]
struct RestingOrder {
    id: OrderId,
    qty: Qty,
    seq: Seq,
}

#[derive(Copy, Clone, Debug, Eq, PartialEq)]
struct Location {
    side: Side,
    price: Price,
}

type Levels = BTreeMap<Price, VecDeque<RestingOrder>>;

#[derive(Debug, Default, Eq, PartialEq)]
pub struct OrderBook {
    bids: Levels,
    asks: Levels,
    index: HashMap<OrderId, Location>,
    next_seq: Seq,
}

impl OrderBook {
    pub fn new() -> Self {
        Self::default()
    }

    // ------- Inspection -------

    pub fn best_bid(&self) -> Option<Price> {
        self.bids.keys().next_back().copied()
    }

    pub fn best_ask(&self) -> Option<Price> {
        self.asks.keys().next().copied()
    }

    pub fn spread(&self) -> Option<Price> {
        Some(self.best_ask()? - self.best_bid()?)
    }

    pub fn contains(&self, id: OrderId) -> bool {
        self.index.contains_key(&id)
    }

    /// Number of resting orders across both sides.
    pub fn len(&self) -> usize {
        self.index.len()
    }

    pub fn is_empty(&self) -> bool {
        self.index.is_empty()
    }

    /// Total resting quantity on a side.
    pub fn total_qty(&self, side: Side) -> Qty {
        self.side(side)
            .values()
            .flat_map(|lvl| lvl.iter())
            .map(|o| o.qty)
            .sum()
    }

    /// Sum of quantities at a single price level.
    pub fn level_qty(&self, side: Side, price: Price) -> Qty {
        self.side(side)
            .get(&price)
            .map(|lvl| lvl.iter().map(|o| o.qty).sum())
            .unwrap_or(0)
    }

    /// Prices on a side, in market-priority order (bids desc, asks asc).
    pub fn level_prices(&self, side: Side) -> Vec<Price> {
        match side {
            Side::Bid => self.bids.keys().rev().copied().collect(),
            Side::Ask => self.asks.keys().copied().collect(),
        }
    }

    /// Orders at a given level in FIFO order (oldest first).
    pub fn level_orders(&self, side: Side, price: Price) -> Vec<ResidentOrder> {
        self.side(side)
            .get(&price)
            .map(|lvl| {
                lvl.iter()
                    .map(|o| ResidentOrder { id: o.id, qty: o.qty, seq: o.seq })
                    .collect()
            })
            .unwrap_or_default()
    }

    // ------- Dispatch -------

    pub fn apply(&mut self, cmd: Command) -> Result<CommandOutcome, EngineError> {
        match cmd {
            Command::Limit(order) => self.submit(order).map(|trades| CommandOutcome::Limit { trades }),
            Command::Cancel { id } => self.cancel(id).map(|qty| CommandOutcome::Cancel { qty }),
            Command::Modify { id, new_price, new_qty } => {
                self.modify(id, new_price, new_qty)
            }
        }
    }

    // ------- Core operations -------

    /// Submit a new limit order. Crosses against the opposite side in
    /// price-time priority; any remainder rests on the book.
    pub fn submit(&mut self, order: NewOrder) -> Result<Vec<Trade>, EngineError> {
        if order.qty == 0 {
            return Err(EngineError::ZeroQty);
        }
        if order.price == 0 {
            return Err(EngineError::ZeroPrice);
        }
        if self.index.contains_key(&order.id) {
            return Err(EngineError::DuplicateOrderId(order.id));
        }

        let mut trades = Vec::new();
        let remaining = self.match_against_opposite(
            order.side,
            order.id,
            order.price,
            order.qty,
            &mut trades,
        );

        if remaining > 0 {
            let seq = self.next_seq;
            self.next_seq += 1;
            let resting = RestingOrder { id: order.id, qty: remaining, seq };
            self.side_mut(order.side)
                .entry(order.price)
                .or_default()
                .push_back(resting);
            self.index.insert(order.id, Location { side: order.side, price: order.price });
        }

        Ok(trades)
    }

    /// Cancel a resting order. Returns the quantity removed from the book.
    pub fn cancel(&mut self, id: OrderId) -> Result<Qty, EngineError> {
        let loc = self.index.remove(&id).ok_or(EngineError::UnknownOrderId(id))?;
        let book = self.side_mut(loc.side);
        let level = book.get_mut(&loc.price).expect("index/level consistency");
        let pos = level.iter().position(|o| o.id == id).expect("index/order consistency");
        let removed = level.remove(pos).expect("valid position");
        if level.is_empty() {
            book.remove(&loc.price);
        }
        Ok(removed.qty)
    }

    /// Modify an existing order.
    ///
    /// * If `new_price == current price` AND `new_qty <= current qty`, the
    ///   order is amended in place and keeps its place in the FIFO queue
    ///   (exchanges call this an "amend-down"). The reduction is reported
    ///   as `canceled_qty` for conservation accounting.
    /// * Otherwise the order is canceled and a fresh limit is submitted
    ///   with the new parameters. The new leg may cross the spread and
    ///   produce trades; it starts at the back of its target level.
    pub fn modify(
        &mut self,
        id: OrderId,
        new_price: Price,
        new_qty: Qty,
    ) -> Result<CommandOutcome, EngineError> {
        if new_qty == 0 {
            return Err(EngineError::ZeroQty);
        }
        if new_price == 0 {
            return Err(EngineError::ZeroPrice);
        }
        let loc = *self.index.get(&id).ok_or(EngineError::UnknownOrderId(id))?;
        let current_qty = self
            .side(loc.side)
            .get(&loc.price)
            .and_then(|lvl| lvl.iter().find(|o| o.id == id))
            .map(|o| o.qty)
            .expect("index/order consistency");

        if new_price == loc.price && new_qty <= current_qty {
            let level = self.side_mut(loc.side).get_mut(&loc.price).expect("level consistency");
            let resting = level.iter_mut().find(|o| o.id == id).expect("order consistency");
            resting.qty = new_qty;
            return Ok(CommandOutcome::Modify {
                canceled_qty: current_qty - new_qty,
                submitted_qty: 0,
                trades: Vec::new(),
            });
        }

        // Cancel-replace: loses priority; replacement may cross.
        let canceled_qty = self.cancel(id)?;
        let trades = self.submit(NewOrder { id, side: loc.side, price: new_price, qty: new_qty })?;
        Ok(CommandOutcome::Modify { canceled_qty, submitted_qty: new_qty, trades })
    }

    /// Modify only the quantity of a resting order, preserving its price.
    ///
    /// Priority rules:
    /// * `new_qty < current qty` — amend in place; order keeps its FIFO position (amend-down).
    /// * `new_qty > current qty` — cancel and re-insert at back of level (loses priority).
    /// * `new_qty == 0` — cancel entirely.
    pub fn modify_order(
        &mut self,
        id: OrderId,
        new_qty: Qty,
    ) -> Result<CommandOutcome, EngineError> {
        if new_qty == 0 {
            return self.cancel(id).map(|qty| CommandOutcome::Cancel { qty });
        }
        let loc = *self.index.get(&id).ok_or(EngineError::UnknownOrderId(id))?;
        self.modify(id, loc.price, new_qty)
    }

    // ------- Matching -------

    /// Drain the opposite side at prices that cross `limit_price`, consuming
    /// the taker's `remaining` quantity in price-then-time order. Returns
    /// the unfilled taker quantity.
    fn match_against_opposite(
        &mut self,
        taker_side: Side,
        taker_id: OrderId,
        limit_price: Price,
        mut remaining: Qty,
        trades: &mut Vec<Trade>,
    ) -> Qty {
        let opposite = taker_side.opposite();

        while remaining > 0 {
            let best_price = match opposite {
                Side::Bid => self.bids.keys().next_back().copied(),
                Side::Ask => self.asks.keys().next().copied(),
            };
            let Some(best_price) = best_price else {
                break;
            };
            let crosses = match taker_side {
                Side::Bid => limit_price >= best_price,
                Side::Ask => limit_price <= best_price,
            };
            if !crosses {
                break;
            }

            // Split-borrow `self` so we can mutate both the level and next_seq.
            let Self { bids, asks, index, next_seq, .. } = &mut *self;
            let book: &mut Levels = match opposite {
                Side::Bid => bids,
                Side::Ask => asks,
            };
            let level = book.get_mut(&best_price).expect("level iteration consistency");

            while remaining > 0 {
                let Some(front) = level.front_mut() else {
                    break;
                };
                let match_qty = remaining.min(front.qty);
                let seq = *next_seq;
                *next_seq += 1;
                trades.push(Trade {
                    seq,
                    maker_id: front.id,
                    taker_id,
                    taker_side,
                    price: best_price,
                    qty: match_qty,
                });
                front.qty -= match_qty;
                remaining -= match_qty;
                if front.qty == 0 {
                    let filled = level.pop_front().expect("non-empty");
                    index.remove(&filled.id);
                }
            }

            if level.is_empty() {
                book.remove(&best_price);
            }
        }

        remaining
    }

    // ------- Internal helpers -------

    #[inline]
    fn side(&self, side: Side) -> &Levels {
        match side {
            Side::Bid => &self.bids,
            Side::Ask => &self.asks,
        }
    }

    #[inline]
    fn side_mut(&mut self, side: Side) -> &mut Levels {
        match side {
            Side::Bid => &mut self.bids,
            Side::Ask => &mut self.asks,
        }
    }
}
