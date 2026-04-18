//! Orderflow Lab matching engine core.
//!
//! Deterministic continuous-double-auction limit order book with price-time
//! (FIFO) priority. Integer arithmetic only — prices in ticks, quantities in
//! lots. See [`order_book::OrderBook`] for the public surface.

#![deny(unsafe_op_in_unsafe_fn)]

mod errors;
mod order_book;
mod types;

pub use errors::EngineError;
pub use order_book::OrderBook;
pub use types::{
    Command, CommandOutcome, NewOrder, OrderId, Price, Qty, ResidentOrder, Seq, Side, Trade,
};

/// Crate version, pulled from Cargo metadata.
pub const VERSION: &str = env!("CARGO_PKG_VERSION");

pub fn version() -> &'static str {
    VERSION
}
