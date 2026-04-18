"""Wire schemas for the live simulation stream.

These Pydantic models define the JSON shape clients see on the WebSocket.
Prices and quantities stay as integers (ticks / lots) — the UI formats them.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class Level(BaseModel):
    """One price level in the book."""

    price: int
    qty: int


class TradeDTO(BaseModel):
    """A single executed trade."""

    seq: int
    price: int
    qty: int
    taker_side: Literal["bid", "ask"]
    ts: float = Field(description="simulation time of the trade, in seconds")


class ForecastDTO(BaseModel):
    """DeepLOB next-move classifier output for the current frame."""

    direction: Literal["down", "flat", "up"]
    probs: tuple[float, float, float] = Field(
        description="(p_down, p_flat, p_up)",
    )
    horizon_steps: int = Field(
        description="prediction horizon in snapshots; at tick_hz=20, 10 steps = 500ms",
    )
    model_ready: bool = Field(
        description="false if no checkpoint is loaded or the rolling window hasn't filled yet",
    )


class AgentStateDTO(BaseModel):
    """Live state of one trading agent.

    All monetary values are in *tick units* (price × qty), matching the
    integer tick/lot convention used throughout the simulator. PnL is split
    into realised (closed trades, VWAP-based) and unrealised (open inventory
    marked to current mid).
    """

    name: str = Field(default="agent", description="agent identifier for the leaderboard")
    enabled: bool
    position: int = Field(description="net inventory; positive = long, negative = short")
    cash: float = Field(description="running cash balance in tick-units")
    realized_pnl: float
    unrealized_pnl: float
    total_pnl: float
    fills: int = Field(description="count of fills received")
    gross_qty: int = Field(description="sum of |qty| across all fills")
    open_order_id: int | None
    open_order_side: Literal["bid", "ask"] | None
    open_order_price: int | None
    open_order_qty: int | None
    cost_basis: float = Field(description="VWAP of current inventory, in ticks")
    mid: float | None = Field(description="mark-to-mid reference used for unrealised PnL")
    avg_slippage: float = Field(
        default=0.0,
        description="mean |fill_price - mid_at_submit| across all fills; 0 if no fills yet",
    )


class BookSnapshot(BaseModel):
    """A single broadcast frame.

    - ``bids`` are ordered best → worst (highest price first).
    - ``asks`` are ordered best → worst (lowest price first).
    - ``trades`` holds fills that occurred since the previous frame.
    """

    type: Literal["snapshot"] = "snapshot"
    seq: int = Field(description="monotonic frame counter")
    ts_wall: float = Field(description="server wall-clock when frame was built, unix seconds")
    sim_t: float = Field(description="simulator time in seconds")
    best_bid: int | None
    best_ask: int | None
    mid: float | None
    spread: int | None
    resting: int = Field(description="total resting orders across both sides")
    bids: list[Level]
    asks: list[Level]
    trades: list[TradeDTO]
    forecast: ForecastDTO | None = None
    agents: list[AgentStateDTO] | None = None


class Hello(BaseModel):
    """First message sent to a newly connected client."""

    type: Literal["hello"] = "hello"
    engine_version: str
    tick_hz: float
    depth_levels: int
    generator: Literal["poisson", "hawkes", "queue_reactive"]
    available_generators: list[str]
    sim_params: dict[str, float | int]


class GeneratorChanged(BaseModel):
    """Broadcast when the active generator is hot-swapped."""

    type: Literal["generator_changed"] = "generator_changed"
    generator: Literal["poisson", "hawkes", "queue_reactive"]
    sim_params: dict[str, float | int]


class SimulationReset(BaseModel):
    """Broadcast immediately before a generator switch.

    Clients should clear their UI state (price series, trade tape, agent PnL)
    when they receive this message, because the engine book is being reset and
    new order-IDs start from the beginning.
    """

    type: Literal["simulation_reset"] = "simulation_reset"
