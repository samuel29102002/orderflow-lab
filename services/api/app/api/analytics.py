"""Analytics REST API: historical PnL series and strategy performance ratios.

Endpoints
---------
GET /analytics/pnl
    Returns time-series of cumulative PnL for every agent over the last
    ``hours`` hours, sampled from the ``agent_pnl`` hypertable.

GET /analytics/ratios
    Computes Sharpe Ratio and Information Ratio for every agent over the
    last ``hours`` hours of simulation.

Sharpe Ratio
~~~~~~~~~~~~
::
    sharpe(agent) = mean(ΔPnL) / std(ΔPnL) × √(periods_per_year)

where ``ΔPnL`` is the first-difference of ``total_pnl`` over consecutive
5-second snapshots, and ``periods_per_year = 365 × 24 × 720 = 6_307_200``
(there are 720 five-second periods in an hour).

Information Ratio
~~~~~~~~~~~~~~~~~
::
    IR(agent_A vs agent_B) = mean(ΔPnL_A − ΔPnL_B) / std(ΔPnL_A − ΔPnL_B) × √N

IR measures how consistently agent_A outperforms the other agent
(tracking error).  When only one agent has data IR is returned as 0.
"""

from __future__ import annotations

import math
import statistics
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

router = APIRouter(prefix="/analytics", tags=["analytics"])

_PNL_INTERVAL_S = 5  # must match PostgresSink.pnl_interval_s


# ---- wire types -----------------------------------------------------------


class PnLPoint(BaseModel):
    time: str
    agent_name: str
    total_pnl: float
    realized_pnl: float
    unrealized_pnl: float
    position: int


class AgentRatios(BaseModel):
    agent_name: str
    sharpe: float
    information_ratio: float
    mean_pnl_per_period: float
    pnl_volatility: float
    n_periods: int


class RatiosResponse(BaseModel):
    hours: int
    agents: list[AgentRatios]


# ---- helpers --------------------------------------------------------------


def _sharpe(returns: list[float]) -> float:
    if len(returns) < 2:
        return 0.0
    mu = statistics.mean(returns)
    sigma = statistics.stdev(returns)
    if sigma == 0.0:
        return 0.0
    periods_per_year = 365 * 24 * 3600 / _PNL_INTERVAL_S
    return mu / sigma * math.sqrt(periods_per_year)


def _information_ratio(returns_a: list[float], returns_b: list[float]) -> float:
    n = min(len(returns_a), len(returns_b))
    if n < 2:
        return 0.0
    active = [a - b for a, b in zip(returns_a[-n:], returns_b[-n:])]
    mu = statistics.mean(active)
    sigma = statistics.stdev(active)
    if sigma == 0.0:
        return 0.0
    periods_per_year = 365 * 24 * 3600 / _PNL_INTERVAL_S
    return mu / sigma * math.sqrt(periods_per_year)


# ---- endpoints ------------------------------------------------------------


@router.get("/pnl", response_model=list[PnLPoint])
async def get_pnl_history(request: Request, hours: int = 1) -> list[PnLPoint]:
    """Return cumulative PnL time-series for all agents over the last N hours."""
    sink = getattr(request.app.state, "storage", None)
    if sink is None:
        raise HTTPException(status_code=503, detail="storage not available")

    query = """
        SELECT
            time AT TIME ZONE 'UTC' AS time,
            agent_name,
            total_pnl,
            realized_pnl,
            unrealized_pnl,
            position
        FROM agent_pnl
        WHERE time >= NOW() - INTERVAL '1 hour' * %(hours)s
        ORDER BY agent_name, time
    """
    rows: list[dict[str, Any]] = []
    async with sink._pool.connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(query, {"hours": hours})
            cols = [d.name for d in cur.description]  # type: ignore[union-attr]
            async for row in cur:
                d = dict(zip(cols, row))
                d["time"] = d["time"].isoformat()
                rows.append(d)

    return [PnLPoint(**r) for r in rows]


@router.get("/ratios", response_model=RatiosResponse)
async def get_ratios(request: Request, hours: int = 1) -> RatiosResponse:
    """Compute Sharpe and Information Ratio for every agent over the last N hours."""
    sink = getattr(request.app.state, "storage", None)
    if sink is None:
        raise HTTPException(status_code=503, detail="storage not available")

    query = """
        SELECT agent_name, total_pnl
        FROM agent_pnl
        WHERE time >= NOW() - INTERVAL '1 hour' * %(hours)s
        ORDER BY agent_name, time
    """
    series: dict[str, list[float]] = {}
    async with sink._pool.connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(query, {"hours": hours})
            async for row in cur:
                agent, pnl = row[0], float(row[1])
                series.setdefault(agent, []).append(pnl)

    # First-difference each agent's PnL series to get period returns.
    returns: dict[str, list[float]] = {
        name: [b - a for a, b in zip(pnls, pnls[1:])]
        for name, pnls in series.items()
    }

    agent_names = list(returns.keys())
    result: list[AgentRatios] = []

    for name, rets in returns.items():
        sr = _sharpe(rets)

        # IR vs every other agent (average if multiple).
        other_names = [n for n in agent_names if n != name]
        if other_names:
            irs = [_information_ratio(rets, returns[n]) for n in other_names]
            ir = sum(irs) / len(irs)
        else:
            ir = 0.0

        result.append(
            AgentRatios(
                agent_name=name,
                sharpe=round(sr, 4),
                information_ratio=round(ir, 4),
                mean_pnl_per_period=round(statistics.mean(rets), 6) if rets else 0.0,
                pnl_volatility=round(statistics.stdev(rets), 6) if len(rets) > 1 else 0.0,
                n_periods=len(rets),
            )
        )

    return RatiosResponse(hours=hours, agents=result)
