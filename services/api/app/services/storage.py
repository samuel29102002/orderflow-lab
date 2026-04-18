"""Async TimescaleDB sink for simulation frames.

Design
------
The sink owns a bounded :class:`asyncio.Queue` and a background drain task.
:meth:`PostgresSink.on_snapshot` enqueues a frame without blocking — the
simulation hot-path is never stalled by DB I/O.  If the queue is full (the
DB is too slow to keep up) the oldest frame is silently dropped; the queue
holds the most-recent state.

PnL snapshots are written at most once every ``pnl_interval_s`` seconds
(default 5 s).  All trades from each snapshot are written every tick.

Usage::

    sink = PostgresSink(pool, pnl_interval_s=5.0)
    await sink.start()                  # spawns drain task
    # ... simulation runs ...
    await sink.stop()                   # drains remaining items, closes task
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone

from psycopg_pool import AsyncConnectionPool

from app.domain.schemas import BookSnapshot

log = logging.getLogger(__name__)

_INSERT_TRADE = """
INSERT INTO trades (time, seq, price, qty, taker_side, sim_t)
VALUES (%(time)s, %(seq)s, %(price)s, %(qty)s, %(taker_side)s, %(sim_t)s)
"""

_INSERT_PNL = """
INSERT INTO agent_pnl
    (time, agent_name, position, realized_pnl, unrealized_pnl, total_pnl, fills, avg_slippage)
VALUES
    (%(time)s, %(agent_name)s, %(position)s, %(realized_pnl)s,
     %(unrealized_pnl)s, %(total_pnl)s, %(fills)s, %(avg_slippage)s)
"""


class PostgresSink:
    """Buffers simulation frames and writes them to TimescaleDB asynchronously."""

    def __init__(
        self,
        pool: AsyncConnectionPool,
        *,
        pnl_interval_s: float = 5.0,
        queue_size: int = 256,
    ) -> None:
        self._pool = pool
        self._pnl_interval = pnl_interval_s
        self._queue: asyncio.Queue[BookSnapshot] = asyncio.Queue(maxsize=queue_size)
        self._drain_task: asyncio.Task[None] | None = None
        self._last_pnl_flush: float = 0.0

    # ---- lifecycle --------------------------------------------------------

    async def start(self) -> None:
        self._drain_task = asyncio.create_task(self._drain(), name="storage-drain")
        log.info("PostgresSink started (pnl_interval=%.1fs)", self._pnl_interval)

    async def stop(self) -> None:
        if self._drain_task is None:
            return
        # Drain remaining items with a brief grace period.
        try:
            await asyncio.wait_for(self._queue.join(), timeout=5.0)
        except asyncio.TimeoutError:
            pass
        self._drain_task.cancel()
        try:
            await self._drain_task
        except (asyncio.CancelledError, Exception):
            pass
        self._drain_task = None
        log.info("PostgresSink stopped")

    # ---- hot-path enqueue (non-blocking) ----------------------------------

    def on_snapshot(self, frame: BookSnapshot) -> None:
        """Enqueue a frame; drops the oldest if the queue is full."""
        if self._queue.full():
            try:
                self._queue.get_nowait()
                self._queue.task_done()
            except asyncio.QueueEmpty:
                pass
        try:
            self._queue.put_nowait(frame)
        except asyncio.QueueFull:
            pass

    # ---- drain loop -------------------------------------------------------

    async def _drain(self) -> None:
        while True:
            frame = await self._queue.get()
            try:
                await self._write(frame)
            except Exception:
                log.exception("storage write error (frame seq=%d)", frame.seq)
            finally:
                self._queue.task_done()

    async def _write(self, frame: BookSnapshot) -> None:
        now = datetime.now(tz=timezone.utc)
        now_wall = time.monotonic()

        async with self._pool.connection() as conn:
            async with conn.cursor() as cur:
                # --- trades (every tick) ---
                if frame.trades:
                    trade_rows = [
                        {
                            "time": now,
                            "seq": t.seq,
                            "price": t.price,
                            "qty": t.qty,
                            "taker_side": t.taker_side,
                            "sim_t": t.ts,
                        }
                        for t in frame.trades
                    ]
                    await cur.executemany(_INSERT_TRADE, trade_rows)

                # --- PnL snapshot (every pnl_interval_s) ---
                if frame.agents and now_wall - self._last_pnl_flush >= self._pnl_interval:
                    pnl_rows = [
                        {
                            "time": now,
                            "agent_name": a.name,
                            "position": a.position,
                            "realized_pnl": a.realized_pnl,
                            "unrealized_pnl": a.unrealized_pnl,
                            "total_pnl": a.total_pnl,
                            "fills": a.fills,
                            "avg_slippage": a.avg_slippage,
                        }
                        for a in frame.agents
                    ]
                    await cur.executemany(_INSERT_PNL, pnl_rows)
                    self._last_pnl_flush = now_wall

            await conn.commit()
