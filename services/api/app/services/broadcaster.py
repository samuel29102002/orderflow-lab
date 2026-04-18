"""Fan-out of simulation frames to connected WebSocket clients.

Design
------
Each client gets its own bounded :class:`asyncio.Queue`. The simulation loop
calls :meth:`publish` once per frame; broadcast is a non-blocking enqueue on
every queue. Slow clients whose queue is full get the oldest frame dropped
(we keep the freshest state) so one stalled tab can't back-pressure the
simulation.

A per-client consumer task drains the queue and writes to the socket.
When the socket dies the task exits and :meth:`disconnect` cleans up.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field

from fastapi import WebSocket
from pydantic import BaseModel

from app.domain.schemas import AgentStateDTO, BookSnapshot

log = logging.getLogger(__name__)


@dataclass(slots=True)
class _Client:
    ws: WebSocket
    queue: asyncio.Queue[str] = field(default_factory=lambda: asyncio.Queue(maxsize=8))
    dropped: int = 0


class Broadcaster:
    """Owns a set of connected clients and fans out frames."""

    def __init__(self) -> None:
        self._clients: dict[int, _Client] = {}
        self._lock = asyncio.Lock()
        # Latest agent state seen on any published frame. Kept so /health
        # and debugging hooks can surface PnL without having to keep their
        # own subscription; the websocket itself still gets the state via
        # the normal ``BookSnapshot`` fan-out.
        self._latest_agent: AgentStateDTO | None = None

    # ---- client lifecycle -------------------------------------------------

    async def connect(self, ws: WebSocket) -> _Client:
        client = _Client(ws=ws)
        async with self._lock:
            self._clients[id(ws)] = client
        log.info("client connected: %s (total=%d)", ws.client, len(self._clients))
        return client

    async def disconnect(self, ws: WebSocket) -> None:
        async with self._lock:
            client = self._clients.pop(id(ws), None)
        if client is not None:
            log.info(
                "client disconnected: %s (total=%d, dropped=%d)",
                ws.client,
                len(self._clients),
                client.dropped,
            )

    @property
    def client_count(self) -> int:
        return len(self._clients)

    # ---- fan-out ----------------------------------------------------------

    async def publish(self, frame: BaseModel) -> None:
        """Serialise once, enqueue on every client."""
        if isinstance(frame, BookSnapshot) and frame.agents:
            self._latest_agent = frame.agents[0]
        if not self._clients:
            return
        payload = frame.model_dump_json()
        for client in list(self._clients.values()):
            self._enqueue(client, payload)

    @property
    def latest_agent_state(self) -> AgentStateDTO | None:
        """The most recently broadcast agent state, if any."""
        return self._latest_agent

    def _enqueue(self, client: _Client, payload: str) -> None:
        q = client.queue
        if q.full():
            try:
                q.get_nowait()  # drop oldest
            except asyncio.QueueEmpty:  # pragma: no cover
                pass
            client.dropped += 1
        q.put_nowait(payload)

    # ---- per-client consumer ---------------------------------------------

    async def pump(self, client: _Client) -> None:
        """Drain a client's queue and write to its socket until the connection dies."""
        ws = client.ws
        try:
            while True:
                payload = await client.queue.get()
                await ws.send_text(payload)
        except Exception as exc:  # WebSocketDisconnect, ConnectionClosed, etc.
            log.debug("pump exiting for %s: %s", ws.client, exc)
