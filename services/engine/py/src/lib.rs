//! PyO3 bindings for the Orderflow Lab matching engine.
//!
//! Exposes `Side`, `NewOrder`, `Trade`, `ResidentOrder`, `ModifyOutcome`, and
//! `OrderBook` as Python classes. The module is importable as
//! `orderflow_engine`.

#![deny(unsafe_op_in_unsafe_fn)]

use orderbook_core as core;
use pyo3::exceptions::{PyKeyError, PyValueError};
use pyo3::prelude::*;

// ----- Side ---------------------------------------------------------------

#[pyclass(eq, eq_int, frozen, hash, name = "Side", module = "orderflow_engine")]
#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash)]
pub enum Side {
    Bid,
    Ask,
}

#[pymethods]
impl Side {
    fn __repr__(&self) -> &'static str {
        match self {
            Side::Bid => "Side.Bid",
            Side::Ask => "Side.Ask",
        }
    }

    fn __str__(&self) -> &'static str {
        match self {
            Side::Bid => "bid",
            Side::Ask => "ask",
        }
    }
}

impl From<Side> for core::Side {
    fn from(s: Side) -> Self {
        match s {
            Side::Bid => core::Side::Bid,
            Side::Ask => core::Side::Ask,
        }
    }
}

impl From<core::Side> for Side {
    fn from(s: core::Side) -> Self {
        match s {
            core::Side::Bid => Side::Bid,
            core::Side::Ask => Side::Ask,
        }
    }
}

// ----- NewOrder -----------------------------------------------------------

#[pyclass(frozen, get_all, name = "NewOrder", module = "orderflow_engine")]
#[derive(Clone, Copy, Debug)]
pub struct NewOrder {
    pub id: u64,
    pub side: Side,
    pub price: u64,
    pub qty: u64,
}

#[pymethods]
impl NewOrder {
    #[new]
    fn py_new(id: u64, side: Side, price: u64, qty: u64) -> Self {
        Self { id, side, price, qty }
    }

    fn __repr__(&self) -> String {
        format!(
            "NewOrder(id={}, side={}, price={}, qty={})",
            self.id,
            self.side.__repr__(),
            self.price,
            self.qty,
        )
    }
}

impl From<NewOrder> for core::NewOrder {
    fn from(o: NewOrder) -> Self {
        core::NewOrder { id: o.id, side: o.side.into(), price: o.price, qty: o.qty }
    }
}

// ----- Trade --------------------------------------------------------------

#[pyclass(frozen, get_all, name = "Trade", module = "orderflow_engine")]
#[derive(Clone, Copy, Debug)]
pub struct Trade {
    pub seq: u64,
    pub maker_id: u64,
    pub taker_id: u64,
    pub taker_side: Side,
    pub price: u64,
    pub qty: u64,
}

#[pymethods]
impl Trade {
    fn __repr__(&self) -> String {
        format!(
            "Trade(seq={}, maker_id={}, taker_id={}, taker_side={}, price={}, qty={})",
            self.seq,
            self.maker_id,
            self.taker_id,
            self.taker_side.__repr__(),
            self.price,
            self.qty,
        )
    }
}

impl From<core::Trade> for Trade {
    fn from(t: core::Trade) -> Self {
        Trade {
            seq: t.seq,
            maker_id: t.maker_id,
            taker_id: t.taker_id,
            taker_side: t.taker_side.into(),
            price: t.price,
            qty: t.qty,
        }
    }
}

// ----- ResidentOrder ------------------------------------------------------

#[pyclass(frozen, get_all, name = "ResidentOrder", module = "orderflow_engine")]
#[derive(Clone, Copy, Debug)]
pub struct ResidentOrder {
    pub id: u64,
    pub qty: u64,
    pub seq: u64,
}

#[pymethods]
impl ResidentOrder {
    fn __repr__(&self) -> String {
        format!("ResidentOrder(id={}, qty={}, seq={})", self.id, self.qty, self.seq)
    }
}

impl From<core::ResidentOrder> for ResidentOrder {
    fn from(o: core::ResidentOrder) -> Self {
        Self { id: o.id, qty: o.qty, seq: o.seq }
    }
}

// ----- ModifyOutcome ------------------------------------------------------

#[pyclass(frozen, get_all, name = "ModifyOutcome", module = "orderflow_engine")]
#[derive(Clone, Debug)]
pub struct ModifyOutcome {
    pub canceled_qty: u64,
    pub submitted_qty: u64,
    pub trades: Vec<Trade>,
}

#[pymethods]
impl ModifyOutcome {
    fn __repr__(&self) -> String {
        format!(
            "ModifyOutcome(canceled_qty={}, submitted_qty={}, trades=<{} trades>)",
            self.canceled_qty,
            self.submitted_qty,
            self.trades.len(),
        )
    }
}

// ----- OrderBook ----------------------------------------------------------

#[pyclass(name = "OrderBook", module = "orderflow_engine")]
pub struct OrderBook {
    inner: core::OrderBook,
}

#[pymethods]
impl OrderBook {
    #[new]
    fn py_new() -> Self {
        Self { inner: core::OrderBook::new() }
    }

    fn submit(&mut self, order: &NewOrder) -> PyResult<Vec<Trade>> {
        let trades = self.inner.submit((*order).into()).map_err(to_py_err)?;
        Ok(trades.into_iter().map(Into::into).collect())
    }

    fn cancel(&mut self, id: u64) -> PyResult<u64> {
        self.inner.cancel(id).map_err(to_py_err)
    }

    fn modify(&mut self, id: u64, new_price: u64, new_qty: u64) -> PyResult<ModifyOutcome> {
        let outcome = self.inner.modify(id, new_price, new_qty).map_err(to_py_err)?;
        match outcome {
            core::CommandOutcome::Modify { canceled_qty, submitted_qty, trades } => {
                Ok(ModifyOutcome {
                    canceled_qty,
                    submitted_qty,
                    trades: trades.into_iter().map(Into::into).collect(),
                })
            }
            _ => unreachable!("modify always returns CommandOutcome::Modify"),
        }
    }

    fn best_bid(&self) -> Option<u64> { self.inner.best_bid() }
    fn best_ask(&self) -> Option<u64> { self.inner.best_ask() }
    fn spread(&self) -> Option<u64> { self.inner.spread() }
    fn contains(&self, id: u64) -> bool { self.inner.contains(id) }

    fn __len__(&self) -> usize { self.inner.len() }

    #[getter]
    fn is_empty(&self) -> bool { self.inner.is_empty() }

    fn total_qty(&self, side: Side) -> u64 { self.inner.total_qty(side.into()) }

    fn level_qty(&self, side: Side, price: u64) -> u64 {
        self.inner.level_qty(side.into(), price)
    }

    fn level_prices(&self, side: Side) -> Vec<u64> {
        self.inner.level_prices(side.into())
    }

    fn level_orders(&self, side: Side, price: u64) -> Vec<ResidentOrder> {
        self.inner.level_orders(side.into(), price).into_iter().map(Into::into).collect()
    }

    fn __repr__(&self) -> String {
        format!(
            "OrderBook(len={}, best_bid={:?}, best_ask={:?})",
            self.inner.len(),
            self.inner.best_bid(),
            self.inner.best_ask(),
        )
    }
}

fn to_py_err(e: core::EngineError) -> PyErr {
    match e {
        core::EngineError::UnknownOrderId(id) => {
            PyKeyError::new_err(format!("unknown order id: {id}"))
        }
        core::EngineError::DuplicateOrderId(id) => {
            PyValueError::new_err(format!("duplicate order id: {id}"))
        }
        core::EngineError::ZeroQty => PyValueError::new_err("order quantity must be > 0"),
        core::EngineError::ZeroPrice => PyValueError::new_err("order price must be > 0"),
    }
}

#[pymodule]
fn orderflow_engine(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add("__version__", env!("CARGO_PKG_VERSION"))?;
    m.add_class::<Side>()?;
    m.add_class::<NewOrder>()?;
    m.add_class::<Trade>()?;
    m.add_class::<ResidentOrder>()?;
    m.add_class::<ModifyOutcome>()?;
    m.add_class::<OrderBook>()?;
    Ok(())
}
