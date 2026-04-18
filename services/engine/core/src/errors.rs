//! Engine error type.

use core::fmt;

use crate::types::OrderId;

#[derive(Copy, Clone, Debug, Eq, PartialEq)]
pub enum EngineError {
    DuplicateOrderId(OrderId),
    UnknownOrderId(OrderId),
    ZeroQty,
    ZeroPrice,
}

impl fmt::Display for EngineError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::DuplicateOrderId(id) => write!(f, "duplicate order id: {id}"),
            Self::UnknownOrderId(id) => write!(f, "unknown order id: {id}"),
            Self::ZeroQty => write!(f, "order quantity must be > 0"),
            Self::ZeroPrice => write!(f, "order price must be > 0"),
        }
    }
}

impl std::error::Error for EngineError {}
