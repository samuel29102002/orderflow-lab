//! Property-based tests for the matching engine.
//!
//! Four invariants, each checked over randomly generated command sequences:
//!   1. No self-cross: `best_bid < best_ask` whenever both sides are populated.
//!   2. FIFO priority: within each level, resting-order seqs are strictly
//!      increasing (oldest at the front).
//!   3. Quantity conservation: `submitted == resting + canceled + 2 * traded`
//!      across a full run (each trade consumes the same qty from maker and
//!      taker, hence the factor of 2).
//!   4. Determinism: applying the same command stream to two fresh books
//!      produces identical outcomes and identical book state.

use orderbook_core::{
    Command, CommandOutcome, NewOrder, OrderBook, OrderId, Price, Qty, Side,
};
use proptest::prelude::*;

const MAX_ID: OrderId = 32;
const MAX_PRICE: Price = 10;
const MAX_QTY: Qty = 8;
const MAX_CMDS: usize = 80;

fn side_st() -> impl Strategy<Value = Side> {
    prop_oneof![Just(Side::Bid), Just(Side::Ask)]
}

fn new_order_st() -> impl Strategy<Value = NewOrder> {
    (0u64..MAX_ID, side_st(), 1u64..=MAX_PRICE, 1u64..=MAX_QTY)
        .prop_map(|(id, side, price, qty)| NewOrder { id, side, price, qty })
}

fn command_st() -> impl Strategy<Value = Command> {
    // Weighted so Limit dominates and cancel/modify fire often enough to
    // exercise those paths without starving the book.
    prop_oneof![
        8 => new_order_st().prop_map(Command::Limit),
        3 => (0u64..MAX_ID).prop_map(|id| Command::Cancel { id }),
        2 => (0u64..MAX_ID, 1u64..=MAX_PRICE, 1u64..=MAX_QTY)
                .prop_map(|(id, np, nq)| Command::Modify { id, new_price: np, new_qty: nq }),
    ]
}

fn commands_st() -> impl Strategy<Value = Vec<Command>> {
    prop::collection::vec(command_st(), 0..=MAX_CMDS)
}

fn assert_no_self_cross(book: &OrderBook) -> Result<(), TestCaseError> {
    if let (Some(bid), Some(ask)) = (book.best_bid(), book.best_ask()) {
        prop_assert!(bid < ask, "self-cross: best_bid={bid} best_ask={ask}");
    }
    Ok(())
}

fn assert_fifo_seqs(book: &OrderBook) -> Result<(), TestCaseError> {
    for side in [Side::Bid, Side::Ask] {
        for price in book.level_prices(side) {
            let orders = book.level_orders(side, price);
            for pair in orders.windows(2) {
                prop_assert!(
                    pair[0].seq < pair[1].seq,
                    "FIFO violated at {}@{}: seqs {} !< {}",
                    side,
                    price,
                    pair[0].seq,
                    pair[1].seq,
                );
            }
        }
    }
    Ok(())
}

proptest! {
    // (1) + (2): both structural invariants hold after every single command.
    #[test]
    fn invariants_hold_after_every_command(cmds in commands_st()) {
        let mut book = OrderBook::new();
        for cmd in cmds {
            let _ = book.apply(cmd);
            assert_no_self_cross(&book)?;
            assert_fifo_seqs(&book)?;
        }
    }

    // (3) Quantity conservation.
    //
    //     submitted = resting + canceled + 2 * traded
    //
    // Derivation: each unit of a successful submit ends up as (a) filled
    // immediately as taker, (b) resting on book, (c) canceled, or (d) filled
    // later as maker. Each trade consumes the same qty from both sides, so
    // (a) + (d) = 2 * trade_qty. Modify is tracked via its canceled_qty
    // (in-place amend-down) and submitted_qty (cancel-replace leg).
    #[test]
    fn quantity_conservation(cmds in commands_st()) {
        let mut book = OrderBook::new();
        let mut submitted: u128 = 0;
        let mut canceled: u128 = 0;
        let mut traded: u128 = 0;
        for cmd in &cmds {
            match book.apply(*cmd) {
                Ok(CommandOutcome::Limit { trades }) => {
                    if let Command::Limit(new) = cmd {
                        submitted += u128::from(new.qty);
                    }
                    traded += trades.iter().map(|t| u128::from(t.qty)).sum::<u128>();
                }
                Ok(CommandOutcome::Cancel { qty }) => {
                    canceled += u128::from(qty);
                }
                Ok(CommandOutcome::Modify { canceled_qty, submitted_qty, trades }) => {
                    canceled += u128::from(canceled_qty);
                    submitted += u128::from(submitted_qty);
                    traded += trades.iter().map(|t| u128::from(t.qty)).sum::<u128>();
                }
                Err(_) => {}
            }
        }
        let resting = u128::from(book.total_qty(Side::Bid)) + u128::from(book.total_qty(Side::Ask));
        prop_assert_eq!(
            submitted,
            resting + canceled + 2 * traded,
            "conservation failed: submitted={} resting={} canceled={} traded={}",
            submitted, resting, canceled, traded,
        );
    }

    // (4) Determinism: applying the same commands twice yields identical
    //     outcomes and identical book state.
    #[test]
    fn determinism(cmds in commands_st()) {
        let mut book_a = OrderBook::new();
        let mut book_b = OrderBook::new();
        let outs_a: Vec<_> = cmds.iter().copied().map(|c| book_a.apply(c)).collect();
        let outs_b: Vec<_> = cmds.iter().copied().map(|c| book_b.apply(c)).collect();
        prop_assert_eq!(outs_a, outs_b);
        prop_assert!(book_a == book_b, "book state diverged between runs");
    }

    // A convenience invariant: every id the engine reports as "contained"
    // is actually a resident on the side the book says it is.
    #[test]
    fn index_is_consistent_with_levels(cmds in commands_st()) {
        let mut book = OrderBook::new();
        for cmd in cmds {
            let _ = book.apply(cmd);
            // Every visible order corresponds to a contained id; no duplicates.
            let mut seen = std::collections::HashSet::new();
            for side in [Side::Bid, Side::Ask] {
                for price in book.level_prices(side) {
                    for order in book.level_orders(side, price) {
                        prop_assert!(book.contains(order.id), "order {} visible but !contains", order.id);
                        prop_assert!(seen.insert(order.id), "duplicate id {} on book", order.id);
                    }
                }
            }
            prop_assert_eq!(seen.len(), book.len());
        }
    }
}
