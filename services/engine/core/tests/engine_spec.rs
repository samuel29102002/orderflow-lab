//! Hand-crafted behavioral tests for the matching engine.
//!
//! Broad invariants are exercised by `tests/properties.rs`; this file nails
//! down the semantics of each individual operation with fixed scripts.

use orderbook_core::{
    Command, CommandOutcome, EngineError, NewOrder, OrderBook, OrderId, Price, Qty, Side,
};

fn lim(id: OrderId, side: Side, price: Price, qty: Qty) -> NewOrder {
    NewOrder { id, side, price, qty }
}

// ---------- Submit / resting ----------

#[test]
fn rests_when_no_cross() {
    let mut book = OrderBook::new();
    let trades = book.submit(lim(1, Side::Bid, 10, 5)).unwrap();
    assert!(trades.is_empty());
    assert_eq!(book.best_bid(), Some(10));
    assert_eq!(book.best_ask(), None);
    assert_eq!(book.level_qty(Side::Bid, 10), 5);
    assert!(book.contains(1));
}

#[test]
fn best_bid_ask_and_spread() {
    let mut book = OrderBook::new();
    assert_eq!(book.spread(), None);
    book.submit(lim(1, Side::Bid, 9, 5)).unwrap();
    book.submit(lim(2, Side::Ask, 11, 5)).unwrap();
    assert_eq!(book.best_bid(), Some(9));
    assert_eq!(book.best_ask(), Some(11));
    assert_eq!(book.spread(), Some(2));
}

// ---------- Crossing behavior ----------

#[test]
fn fills_at_maker_price_not_taker_price() {
    let mut book = OrderBook::new();
    book.submit(lim(1, Side::Ask, 10, 5)).unwrap();
    // Taker willing to pay up to 15; fills at the resting maker price (10).
    let trades = book.submit(lim(2, Side::Bid, 15, 3)).unwrap();
    assert_eq!(trades.len(), 1);
    assert_eq!(trades[0].price, 10);
    assert_eq!(trades[0].qty, 3);
    assert_eq!(trades[0].taker_side, Side::Bid);
}

#[test]
fn partial_fill_rests_remainder_on_taker_side() {
    let mut book = OrderBook::new();
    book.submit(lim(1, Side::Ask, 10, 3)).unwrap();
    let trades = book.submit(lim(2, Side::Bid, 10, 5)).unwrap();
    assert_eq!(trades.len(), 1);
    assert_eq!(trades[0].qty, 3);
    assert_eq!(book.level_qty(Side::Ask, 10), 0);
    assert_eq!(book.level_qty(Side::Bid, 10), 2);
    assert!(!book.contains(1));
    assert!(book.contains(2));
}

#[test]
fn taker_walks_multiple_price_levels_up_to_limit() {
    let mut book = OrderBook::new();
    book.submit(lim(1, Side::Ask, 10, 2)).unwrap();
    book.submit(lim(2, Side::Ask, 11, 2)).unwrap();
    book.submit(lim(3, Side::Ask, 12, 2)).unwrap();
    // Buyer willing to pay up to 11; must not touch the 12 level.
    let trades = book.submit(lim(4, Side::Bid, 11, 10)).unwrap();
    assert_eq!(trades.len(), 2);
    assert_eq!((trades[0].price, trades[0].qty), (10, 2));
    assert_eq!((trades[1].price, trades[1].qty), (11, 2));
    assert_eq!(book.level_qty(Side::Ask, 12), 2);
    // Remainder (10 - 4 = 6) rests at 11 as a bid.
    assert_eq!(book.level_qty(Side::Bid, 11), 6);
    assert_eq!(book.best_bid(), Some(11));
    assert_eq!(book.best_ask(), Some(12));
}

// ---------- FIFO / time priority ----------

#[test]
fn fifo_within_same_price_level() {
    let mut book = OrderBook::new();
    book.submit(lim(1, Side::Ask, 10, 5)).unwrap();
    book.submit(lim(2, Side::Ask, 10, 5)).unwrap();
    let trades = book.submit(lim(3, Side::Bid, 10, 8)).unwrap();
    assert_eq!(trades.len(), 2);
    assert_eq!(trades[0].maker_id, 1);
    assert_eq!(trades[0].qty, 5);
    assert_eq!(trades[1].maker_id, 2);
    assert_eq!(trades[1].qty, 3);
    assert_eq!(book.level_qty(Side::Ask, 10), 2);
}

#[test]
fn trade_seqs_are_monotonically_increasing() {
    let mut book = OrderBook::new();
    book.submit(lim(1, Side::Ask, 10, 1)).unwrap();
    book.submit(lim(2, Side::Ask, 10, 1)).unwrap();
    book.submit(lim(3, Side::Ask, 10, 1)).unwrap();
    let trades = book.submit(lim(4, Side::Bid, 10, 3)).unwrap();
    let seqs: Vec<_> = trades.iter().map(|t| t.seq).collect();
    assert!(seqs.windows(2).all(|w| w[0] < w[1]), "trade seqs not monotonic: {seqs:?}");
}

// ---------- Errors ----------

#[test]
fn cancel_unknown_errors() {
    let mut book = OrderBook::new();
    assert_eq!(book.cancel(99), Err(EngineError::UnknownOrderId(99)));
}

#[test]
fn duplicate_id_rejected() {
    let mut book = OrderBook::new();
    book.submit(lim(1, Side::Bid, 10, 5)).unwrap();
    assert_eq!(
        book.submit(lim(1, Side::Bid, 11, 5)),
        Err(EngineError::DuplicateOrderId(1))
    );
}

#[test]
fn zero_qty_rejected() {
    let mut book = OrderBook::new();
    assert_eq!(book.submit(lim(1, Side::Bid, 10, 0)), Err(EngineError::ZeroQty));
}

#[test]
fn zero_price_rejected() {
    let mut book = OrderBook::new();
    assert_eq!(book.submit(lim(1, Side::Bid, 0, 5)), Err(EngineError::ZeroPrice));
}

#[test]
fn modify_unknown_errors() {
    let mut book = OrderBook::new();
    assert_eq!(book.modify(99, 10, 5), Err(EngineError::UnknownOrderId(99)));
}

// ---------- Cancel ----------

#[test]
fn cancel_removes_order_and_collapses_empty_level() {
    let mut book = OrderBook::new();
    book.submit(lim(1, Side::Bid, 10, 5)).unwrap();
    assert_eq!(book.cancel(1).unwrap(), 5);
    assert!(!book.contains(1));
    assert_eq!(book.best_bid(), None);
    assert_eq!(book.level_qty(Side::Bid, 10), 0);
}

// ---------- Modify ----------

#[test]
fn amend_down_preserves_priority_and_reports_canceled_delta() {
    let mut book = OrderBook::new();
    book.submit(lim(1, Side::Bid, 10, 10)).unwrap();
    book.submit(lim(2, Side::Bid, 10, 10)).unwrap();

    let outcome = book.modify(1, 10, 4).unwrap();
    assert_eq!(
        outcome,
        CommandOutcome::Modify { canceled_qty: 6, submitted_qty: 0, trades: Vec::new() }
    );

    // Taker sells 3 at 10 — order 1 still has queue priority.
    let trades = book.submit(lim(3, Side::Ask, 10, 3)).unwrap();
    assert_eq!(trades.len(), 1);
    assert_eq!(trades[0].maker_id, 1);
    assert_eq!(trades[0].qty, 3);
    // Order 1 has 1 left; order 2 untouched at 10.
    assert_eq!(book.level_qty(Side::Bid, 10), 1 + 10);
}

#[test]
fn modify_price_change_loses_priority() {
    let mut book = OrderBook::new();
    book.submit(lim(1, Side::Bid, 10, 5)).unwrap();
    book.submit(lim(2, Side::Bid, 10, 5)).unwrap();

    // Move order 1 up to 11 (no opposite side — rests).
    let out_up = book.modify(1, 11, 5).unwrap();
    assert_eq!(
        out_up,
        CommandOutcome::Modify { canceled_qty: 5, submitted_qty: 5, trades: Vec::new() }
    );
    assert_eq!(book.level_qty(Side::Bid, 11), 5);

    // Move it back to 10 — now sits behind order 2.
    book.modify(1, 10, 5).unwrap();
    let trades = book.submit(lim(3, Side::Ask, 10, 6)).unwrap();
    assert_eq!(trades[0].maker_id, 2);
    assert_eq!(trades[0].qty, 5);
    assert_eq!(trades[1].maker_id, 1);
    assert_eq!(trades[1].qty, 1);
}

#[test]
fn modify_qty_up_at_same_price_loses_priority() {
    let mut book = OrderBook::new();
    book.submit(lim(1, Side::Bid, 10, 5)).unwrap();
    book.submit(lim(2, Side::Bid, 10, 5)).unwrap();
    book.modify(1, 10, 10).unwrap(); // qty up — cancel-replace
    let trades = book.submit(lim(3, Side::Ask, 10, 7)).unwrap();
    assert_eq!(trades[0].maker_id, 2);
    assert_eq!(trades[0].qty, 5);
    assert_eq!(trades[1].maker_id, 1);
    assert_eq!(trades[1].qty, 2);
}

#[test]
fn modify_can_cross_immediately() {
    let mut book = OrderBook::new();
    book.submit(lim(1, Side::Bid, 8, 5)).unwrap();
    book.submit(lim(2, Side::Ask, 10, 5)).unwrap();
    let outcome = book.modify(1, 10, 5).unwrap();
    match outcome {
        CommandOutcome::Modify { canceled_qty, submitted_qty, trades } => {
            assert_eq!(canceled_qty, 5);
            assert_eq!(submitted_qty, 5);
            assert_eq!(trades.len(), 1);
            assert_eq!(trades[0].maker_id, 2);
            assert_eq!(trades[0].qty, 5);
        }
        other => panic!("expected Modify outcome, got {other:?}"),
    }
    assert!(book.is_empty());
}

// ---------- Determinism (fixed script) ----------

#[test]
fn determinism_on_fixed_script() {
    let script: Vec<Command> = vec![
        Command::Limit(lim(1, Side::Bid, 10, 5)),
        Command::Limit(lim(2, Side::Ask, 12, 3)),
        Command::Limit(lim(3, Side::Bid, 12, 2)), // crosses
        Command::Cancel { id: 1 },
        Command::Modify { id: 2, new_price: 11, new_qty: 4 }, // price change
        Command::Limit(lim(4, Side::Ask, 11, 4)),
    ];
    let run = |cmds: &[Command]| {
        let mut book = OrderBook::new();
        let outs: Vec<_> = cmds.iter().copied().map(|c| book.apply(c)).collect();
        (book, outs)
    };
    let (book_a, outs_a) = run(&script);
    let (book_b, outs_b) = run(&script);
    assert_eq!(outs_a, outs_b);
    assert_eq!(book_a, book_b);
}
