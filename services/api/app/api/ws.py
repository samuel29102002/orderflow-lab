"""WebSocket endpoint for the live simulation stream."""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.services.broadcaster import Broadcaster
from app.services.simulation import Simulation

log = logging.getLogger(__name__)

router = APIRouter()


@router.websocket("/ws/stream")
async def stream(ws: WebSocket) -> None:
    """Push live book snapshots + trades at the simulation tick rate."""
    broadcaster: Broadcaster = ws.app.state.broadcaster
    simulation: Simulation = ws.app.state.simulation

    await ws.accept()

    # Greet the client with sim metadata so it can render a header.
    await ws.send_text(simulation.hello().model_dump_json())

    client = await broadcaster.connect(ws)
    pump_task = asyncio.create_task(broadcaster.pump(client), name="ws-pump")

    try:
        # Keep the coroutine alive until the client disconnects; we also
        # drain any incoming messages so the TCP read loop stays healthy.
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        pass
    except Exception:
        log.exception("ws stream error")
    finally:
        pump_task.cancel()
        try:
            await pump_task
        except (asyncio.CancelledError, Exception):
            pass
        await broadcaster.disconnect(ws)
