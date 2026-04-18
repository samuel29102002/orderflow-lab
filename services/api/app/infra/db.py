"""Async psycopg connection pool and DDL bootstrap for TimescaleDB.

Call :func:`create_pool` at startup (before the simulation begins) to open
the pool and ensure the hypertables exist.  Call :meth:`AsyncConnectionPool.close`
at shutdown.

Hypertables
-----------
``trades``
    One row per executed trade.  Partitioned by ``time`` so TimescaleDB can
    evict old chunks automatically.

``agent_pnl``
    One row per 5-second PnL snapshot per agent.  Used by the analytics
    API to compute Sharpe and Information Ratio over a rolling window.
"""

from __future__ import annotations

import logging

from psycopg_pool import AsyncConnectionPool

log = logging.getLogger(__name__)

# DDL is idempotent — safe to re-run on every start.
_DDL = """
CREATE TABLE IF NOT EXISTS trades (
    time        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    seq         BIGINT,
    price       INTEGER,
    qty         INTEGER,
    taker_side  TEXT,
    sim_t       DOUBLE PRECISION
);

CREATE TABLE IF NOT EXISTS agent_pnl (
    time            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    agent_name      TEXT        NOT NULL,
    position        INTEGER,
    realized_pnl    DOUBLE PRECISION,
    unrealized_pnl  DOUBLE PRECISION,
    total_pnl       DOUBLE PRECISION,
    fills           INTEGER,
    avg_slippage    DOUBLE PRECISION
);
"""

# TimescaleDB hypertable creation — tolerates the table already being a
# hypertable (if_not_exists => TRUE).
_HYPERTABLES = """
SELECT create_hypertable('trades',    'time', if_not_exists => TRUE);
SELECT create_hypertable('agent_pnl', 'time', if_not_exists => TRUE);
"""


def _plain_dsn(sqlalchemy_url: str) -> str:
    """Strip the SQLAlchemy dialect prefix so psycopg can use it directly."""
    return sqlalchemy_url.replace("postgresql+psycopg://", "postgresql://", 1)


async def create_pool(database_url: str) -> AsyncConnectionPool:
    """Open an async psycopg pool and bootstrap the hypertables.

    Parameters
    ----------
    database_url
        Either a plain ``postgresql://`` URL or the SQLAlchemy
        ``postgresql+psycopg://`` variant (prefix is stripped automatically).
    """
    dsn = _plain_dsn(database_url)
    pool = AsyncConnectionPool(conninfo=dsn, open=False, min_size=1, max_size=4)
    await pool.open()

    async with pool.connection() as conn:
        await conn.execute(_DDL)
        try:
            await conn.execute(_HYPERTABLES)
        except Exception as exc:
            # TimescaleDB may not be available in plain Postgres test envs;
            # log a warning rather than crash.
            log.warning("hypertable creation skipped: %s", exc)
        await conn.commit()

    log.info("TimescaleDB pool ready (%s)", dsn.split("@")[-1])
    return pool
