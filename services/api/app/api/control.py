"""Control-plane HTTP endpoints (generator switching, etc.)."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from app.services.simulation import AVAILABLE_GENERATORS, Simulation

router = APIRouter(prefix="/control", tags=["control"])

GeneratorName = Literal["poisson", "hawkes", "queue_reactive"]


class GeneratorRequest(BaseModel):
    name: GeneratorName


class GeneratorResponse(BaseModel):
    generator: GeneratorName
    available: list[str]
    sim_params: dict[str, float | int]


@router.get("/generator", response_model=GeneratorResponse)
async def get_generator(request: Request) -> GeneratorResponse:
    simulation: Simulation = request.app.state.simulation
    hello = simulation.hello()
    return GeneratorResponse(
        generator=hello.generator,
        available=hello.available_generators,
        sim_params=hello.sim_params,
    )


@router.post("/generator", response_model=GeneratorResponse)
async def set_generator(payload: GeneratorRequest, request: Request) -> GeneratorResponse:
    simulation: Simulation = request.app.state.simulation
    if payload.name not in AVAILABLE_GENERATORS:
        raise HTTPException(status_code=400, detail=f"unknown generator: {payload.name}")
    await simulation.switch_generator(payload.name)
    hello = simulation.hello()
    return GeneratorResponse(
        generator=hello.generator,
        available=hello.available_generators,
        sim_params=hello.sim_params,
    )
