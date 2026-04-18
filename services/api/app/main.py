from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from pathlib import Path

from app import __version__
from app.api.analytics import router as analytics_router
from app.api.control import router as control_router
from app.api.ws import router as ws_router
from app.core.config import settings
from app.infra.db import create_pool
from app.services.agent_driver import (
    AgentDriver,
    AgentDriverConfig,
    MarketMakerDriverConfig,
    _DeepLOBSlot,
    _MarketMakerSlot,
)
from app.services.broadcaster import Broadcaster
from app.services.forecast import Forecaster
from app.services.simulation import Simulation, SimulationConfig
from app.services.storage import PostgresSink

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def _build_forecaster() -> Forecaster | None:
    if not settings.forecast_enabled:
        return None
    raw = Path(settings.forecast_model_path)
    path = raw if raw.is_absolute() else (Path(__file__).resolve().parent.parent / raw).resolve()
    return Forecaster(path)


def _build_agent_driver() -> AgentDriver | None:
    if not settings.agent_enabled:
        return None
    slots = [
        _DeepLOBSlot(
            AgentDriverConfig(
                enabled=True,
                threshold=settings.agent_threshold,
                base_clip=settings.agent_base_clip,
                max_pos=settings.agent_max_pos,
                risk_aversion=settings.agent_risk_aversion,
                place_cooldown_s=settings.agent_place_cooldown_s,
            )
        ),
        _MarketMakerSlot(MarketMakerDriverConfig()),
    ]
    return AgentDriver(slots)


def _build_simulation(broadcaster: Broadcaster, storage: PostgresSink | None) -> Simulation:
    cfg = SimulationConfig(
        settings=settings,
        tick_hz=settings.sim_tick_hz,
        sim_speed=settings.sim_speed,
        depth_levels=settings.sim_depth_levels,
        trade_buffer=settings.sim_trade_buffer,
        generator_name=settings.sim_generator,
        forecaster=_build_forecaster(),
        agent_driver=_build_agent_driver(),
        storage=storage,
    )
    return Simulation(cfg, broadcaster)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # --- storage (optional; degrades gracefully if DB is unreachable) ---
    storage: PostgresSink | None = None
    if settings.storage_enabled:
        try:
            pool = await create_pool(settings.database_url)
            storage = PostgresSink(pool, pnl_interval_s=settings.storage_pnl_interval_s)
            await storage.start()
            app.state.storage = storage
        except Exception:
            logging.getLogger(__name__).exception(
                "TimescaleDB unavailable — storage disabled"
            )

    broadcaster = Broadcaster()
    simulation = _build_simulation(broadcaster, storage)
    app.state.broadcaster = broadcaster
    app.state.simulation = simulation
    simulation.start()

    try:
        yield
    finally:
        await simulation.stop()
        if storage is not None:
            await storage.stop()
            await storage._pool.close()


def create_app() -> FastAPI:
    app = FastAPI(
        title="Orderflow Lab API",
        version=__version__,
        description="Gateway for the Orderflow Lab market microstructure simulator.",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(ws_router)
    app.include_router(control_router)
    app.include_router(analytics_router)

    @app.get("/health", tags=["meta"])
    async def health() -> dict[str, object]:
        clients = 0
        generator = ""
        agent: dict[str, object] | None = None
        broadcaster: Broadcaster | None = getattr(app.state, "broadcaster", None)
        simulation: Simulation | None = getattr(app.state, "simulation", None)
        if broadcaster is not None:
            clients = broadcaster.client_count
            state = broadcaster.latest_agent_state
            if state is not None:
                agent = {
                    "position": state.position,
                    "realized_pnl": state.realized_pnl,
                    "unrealized_pnl": state.unrealized_pnl,
                    "total_pnl": state.total_pnl,
                    "fills": state.fills,
                    "avg_slippage": state.avg_slippage,
                }
        if simulation is not None:
            generator = simulation.generator_name
        return {
            "status": "ok",
            "version": __version__,
            "env": settings.env,
            "ws_clients": clients,
            "generator": generator,
            "agent": agent,
        }

    return app


app = create_app()
