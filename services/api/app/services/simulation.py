"""Live simulation loop, generator factory, and snapshot builder.

The :class:`Simulation` is an async task that owns the Rust :class:`Engine`,
drives a pluggable :class:`FlowGenerator` forward by wall-clock time, and
publishes a :class:`BookSnapshot` to a pub-sub broadcaster at a fixed
``tick_hz``.

Design notes
------------

* **Decoupled rates.** The flow generator advances according to its own
  simulation clock. The tick loop advances the sim clock by
  ``wall_dt * sim_speed`` each frame and consumes every event whose
  ``timestamp`` falls inside the window. This keeps flow density matched to
  the generator, independent of how fast we broadcast.
* **Reactive generators.** Before consuming events each tick we call
  :meth:`FlowGenerator.observe` with the latest :class:`BookState`. That
  gives queue-reactive (HLR-style) generators a fresh view of the book
  without having to instrument the hot path.
* **Hot-swap.** :meth:`switch_generator` rebuilds only the generator — the
  engine keeps its state, so the book doesn't reset when a user toggles
  between Poisson / Hawkes / Queue-Reactive.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from orderflow_sdk import Engine, Side, engine_version
from orderflow_sdk.flow import (
    BookState,
    FlowConfig,
    FlowGenerator,
    HawkesConfig,
    HawkesFlowGenerator,
    PoissonFlowGenerator,
    QueueReactiveConfig,
    QueueReactiveFlowGenerator,
)

from app.core.config import GeneratorName, Settings
from app.domain.schemas import (
    AgentStateDTO,
    BookSnapshot,
    ForecastDTO,
    GeneratorChanged,
    Hello,
    Level,
    SimulationReset,
    TradeDTO,
)
from app.services.agent_driver import AgentDriver
from app.services.forecast import Forecaster

if TYPE_CHECKING:
    from app.services.broadcaster import Broadcaster
    from app.services.storage import PostgresSink

log = logging.getLogger(__name__)


AVAILABLE_GENERATORS: tuple[GeneratorName, ...] = ("poisson", "hawkes", "queue_reactive")


# ---- factories ------------------------------------------------------------


def _poisson_from_settings(settings: Settings) -> PoissonFlowGenerator:
    cfg = FlowConfig(
        seed=settings.sim_seed,
        lambda_rate=settings.sim_lambda_rate,
        mid0=settings.sim_mid0,
        mu=settings.sim_mu,
        kappa=settings.sim_kappa,
        sigma=settings.sim_sigma,
        offset_mean=settings.sim_offset_mean,
        qty_mean=settings.sim_qty_mean,
    )
    return PoissonFlowGenerator(cfg)


def _hawkes_from_settings(settings: Settings) -> HawkesFlowGenerator:
    cfg = HawkesConfig(
        seed=settings.sim_seed,
        mu_bid=settings.sim_hawkes_mu,
        mu_ask=settings.sim_hawkes_mu,
        alpha_self=settings.sim_hawkes_alpha_self,
        alpha_cross=settings.sim_hawkes_alpha_cross,
        beta=settings.sim_hawkes_beta,
        mid0=settings.sim_mid0,
        mu=settings.sim_mu,
        kappa=settings.sim_kappa,
        sigma=settings.sim_sigma,
        offset_mean=settings.sim_offset_mean,
        qty_mean=settings.sim_qty_mean,
    )
    return HawkesFlowGenerator(cfg)


def _queue_reactive_from_settings(settings: Settings) -> QueueReactiveFlowGenerator:
    cfg = QueueReactiveConfig(
        seed=settings.sim_seed,
        base_lambda=settings.sim_qr_base_lambda,
        baseline_spread=settings.sim_qr_baseline_spread,
        rate_sensitivity=settings.sim_qr_rate_sensitivity,
        offset_sensitivity=settings.sim_qr_offset_sensitivity,
        imbalance_sensitivity=settings.sim_qr_imbalance_sensitivity,
        mid0=settings.sim_mid0,
        mu=settings.sim_mu,
        kappa=settings.sim_kappa,
        sigma=settings.sim_sigma,
        offset_mean=settings.sim_offset_mean,
        qty_mean=settings.sim_qty_mean,
    )
    return QueueReactiveFlowGenerator(cfg)


_GENERATOR_FACTORIES: dict[GeneratorName, callable] = {
    "poisson": _poisson_from_settings,
    "hawkes": _hawkes_from_settings,
    "queue_reactive": _queue_reactive_from_settings,
}


def build_generator(name: GeneratorName, settings: Settings) -> FlowGenerator:
    try:
        factory = _GENERATOR_FACTORIES[name]
    except KeyError as exc:
        raise ValueError(f"unknown generator: {name!r}") from exc
    return factory(settings)


def sim_params_for(name: GeneratorName, settings: Settings) -> dict[str, float | int]:
    """The knobs the UI should display for a given generator."""
    shared = {
        "mu_price": settings.sim_mu,
        "kappa": settings.sim_kappa,
        "sigma": settings.sim_sigma,
        "offset_mean": settings.sim_offset_mean,
        "qty_mean": settings.sim_qty_mean,
        "seed": settings.sim_seed,
    }
    if name == "poisson":
        return {**shared, "lambda": settings.sim_lambda_rate}
    if name == "hawkes":
        return {
            **shared,
            "mu_baseline": settings.sim_hawkes_mu,
            "alpha_self": settings.sim_hawkes_alpha_self,
            "alpha_cross": settings.sim_hawkes_alpha_cross,
            "beta": settings.sim_hawkes_beta,
        }
    return {
        **shared,
        "base_lambda": settings.sim_qr_base_lambda,
        "baseline_spread": settings.sim_qr_baseline_spread,
        "rate_sens": settings.sim_qr_rate_sensitivity,
        "offset_sens": settings.sim_qr_offset_sensitivity,
        "imbalance_sens": settings.sim_qr_imbalance_sensitivity,
    }


# ---- simulation service ---------------------------------------------------


@dataclass(slots=True)
class SimulationConfig:
    settings: Settings
    tick_hz: float
    sim_speed: float
    depth_levels: int
    trade_buffer: int
    generator_name: GeneratorName
    forecaster: Forecaster | None = None
    agent_driver: AgentDriver | None = None
    storage: "PostgresSink | None" = None


class Simulation:
    """Owns the engine, generator, and broadcast cadence."""

    def __init__(self, cfg: SimulationConfig, broadcaster: "Broadcaster") -> None:
        self.cfg = cfg
        self.broadcaster = broadcaster
        self.engine = Engine()
        self._generator_name: GeneratorName = cfg.generator_name
        self._generator: FlowGenerator = build_generator(cfg.generator_name, cfg.settings)
        self._pending = next(self._generator)
        self._sim_t: float = 0.0
        self._frame_seq: int = 0
        self._task: asyncio.Task[None] | None = None
        self._stop = asyncio.Event()
        self._lock = asyncio.Lock()
        self._forecaster: Forecaster | None = cfg.forecaster
        self._agent_driver: AgentDriver | None = cfg.agent_driver
        self._storage: "PostgresSink | None" = cfg.storage

    # ---- lifecycle --------------------------------------------------------

    def start(self) -> None:
        if self._task is not None:
            return
        self._task = asyncio.create_task(self._run(), name="simulation-loop")
        log.info(
            "simulation started: tick_hz=%s speed=%s generator=%s",
            self.cfg.tick_hz,
            self.cfg.sim_speed,
            self._generator_name,
        )

    async def stop(self) -> None:
        if self._task is None:
            return
        self._stop.set()
        self._task.cancel()
        try:
            await self._task
        except (asyncio.CancelledError, Exception):
            pass
        self._task = None
        log.info("simulation stopped")

    # ---- control ---------------------------------------------------------

    @property
    def generator_name(self) -> GeneratorName:
        return self._generator_name

    async def switch_generator(self, name: GeneratorName) -> GeneratorChanged:
        """Replace the active generator and reset the engine book.

        A full reset is required because each generator allocates order IDs
        starting from 1.  If the engine kept stale orders from the previous
        generator, the new generator would emit duplicate IDs causing the Rust
        engine to raise on ``apply_limit``, which crashes the simulation loop.

        Reset sequence (all under the sim lock so the tick loop is paused):
        1. Fresh :class:`Engine` — no stale resting orders, ID space is clean.
        2. New generator with its clock advanced to ``_sim_t`` so the first
           event lands in the next tick window rather than flooding this one.
        3. Agent driver reset — clears order-ID sets and agent state so fill
           reconciliation doesn't try to match phantom order IDs.

        A :class:`SimulationReset` is broadcast first so clients can clear
        their price-series and trade-tape before the new stream begins.
        """
        if name not in _GENERATOR_FACTORIES:
            raise ValueError(f"unknown generator: {name!r}")

        async with self._lock:
            # 1. Fresh engine — clears all resting orders and ID history.
            self.engine = Engine()

            # 2. New generator with clock aligned to current sim time.
            new_gen = build_generator(name, self.cfg.settings)
            new_gen.t = self._sim_t  # type: ignore[attr-defined]
            self._generator = new_gen
            self._pending = next(new_gen)
            self._generator_name = name

            # 3. Clear agent state so fill reconciliation starts clean.
            if self._agent_driver is not None:
                self._agent_driver.reset()

        log.info("generator switched to %s (engine + agents reset)", name)

        # Notify clients to clear UI before the new stream begins.
        await self.broadcaster.publish(SimulationReset())

        changed = GeneratorChanged(
            generator=name,
            sim_params=sim_params_for(name, self.cfg.settings),
        )
        await self.broadcaster.publish(changed)
        return changed

    # ---- hello snapshot (sent on connect) ---------------------------------

    def hello(self) -> Hello:
        return Hello(
            engine_version=engine_version,
            tick_hz=self.cfg.tick_hz,
            depth_levels=self.cfg.depth_levels,
            generator=self._generator_name,
            available_generators=list(AVAILABLE_GENERATORS),
            sim_params=sim_params_for(self._generator_name, self.cfg.settings),
        )

    # ---- main loop --------------------------------------------------------

    async def _run(self) -> None:
        interval = 1.0 / self.cfg.tick_hz
        next_tick = asyncio.get_running_loop().time()

        try:
            while not self._stop.is_set():
                now = asyncio.get_running_loop().time()
                self._sim_t += interval * self.cfg.sim_speed

                async with self._lock:
                    self._generator.observe(self._build_book_state())
                    trades, maker_ids = self._consume_events_until(self._sim_t)
                    frame = self._build_snapshot(trades, maker_ids)

                await self.broadcaster.publish(frame)
                if self._storage is not None:
                    self._storage.on_snapshot(frame)

                next_tick += interval
                sleep_for = next_tick - now
                if sleep_for > 0:
                    await asyncio.sleep(sleep_for)
                else:
                    next_tick = asyncio.get_running_loop().time() + interval
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("simulation loop crashed")
            raise

    # ---- event consumption -----------------------------------------------

    def _consume_events_until(self, horizon: float) -> tuple[list[TradeDTO], list[int]]:
        """Advance the book to ``horizon`` and return (trades, maker_ids).

        The parallel ``maker_ids`` list is how the :class:`AgentDriver`
        attributes fills back to its own resting orders; it's intentionally
        kept off the wire DTO.
        """
        trades: list[TradeDTO] = []
        maker_ids: list[int] = []
        buf_cap = self.cfg.trade_buffer
        apply = self.engine.apply_limit

        while self._pending.timestamp <= horizon:
            evt = self._pending
            for t in apply(evt):
                if len(trades) < buf_cap:
                    trades.append(
                        TradeDTO(
                            seq=t.seq,
                            price=t.price,
                            qty=t.qty,
                            taker_side="bid" if t.taker_side == Side.Bid else "ask",
                            ts=evt.timestamp,
                        )
                    )
                    maker_ids.append(t.maker_id)
            self._pending = next(self._generator)

        return trades, maker_ids

    # ---- snapshot / book state builders ----------------------------------

    def _build_book_state(self) -> BookState:
        eng = self.engine
        bb = eng.best_bid()
        ba = eng.best_ask()
        bid_top_qty = eng.depth(Side.Bid)[0][1] if bb is not None else 0
        ask_top_qty = eng.depth(Side.Ask)[0][1] if ba is not None else 0
        return BookState(
            t=self._sim_t,
            best_bid=bb,
            best_ask=ba,
            spread=eng.spread(),
            mid=eng.mid(),
            bid_top_qty=bid_top_qty,
            ask_top_qty=ask_top_qty,
        )

    def _build_snapshot(
        self, trades: list[TradeDTO], maker_ids: list[int]
    ) -> BookSnapshot:
        self._frame_seq += 1
        eng = self.engine
        depth = self.cfg.depth_levels

        raw_bids = eng.depth(Side.Bid)[:depth]
        raw_asks = eng.depth(Side.Ask)[:depth]
        bids = [Level(price=p, qty=q) for p, q in raw_bids]
        asks = [Level(price=p, qty=q) for p, q in raw_asks]

        forecast_dto: ForecastDTO | None = None
        if self._forecaster is not None:
            # Feed the model the *full-depth* top-K view the API broadcasts.
            self._forecaster.push_snapshot(raw_bids, raw_asks, eng.mid())
            r = self._forecaster.predict()
            forecast_dto = ForecastDTO(
                direction=r.direction,
                probs=r.probs,
                horizon_steps=r.horizon_steps,
                model_ready=r.model_ready,
            )

        agents_dto: list[AgentStateDTO] | None = None
        if self._agent_driver is not None:
            # Step all agents *after* the forecast is ready but still under
            # the sim lock, so every action is applied against a consistent
            # book snapshot. The driver reconciles any fills that happened
            # during this tick and may itself submit new orders.
            self._agent_driver.step(
                t=self._sim_t,
                engine=eng,
                best_bid=eng.best_bid(),
                best_ask=eng.best_ask(),
                mid=eng.mid(),
                trades=trades,
                trade_maker_ids=maker_ids,
                forecast=forecast_dto,
            )
            agents_dto = self._agent_driver.snapshots(eng.mid())

        return BookSnapshot(
            seq=self._frame_seq,
            ts_wall=time.time(),
            sim_t=self._sim_t,
            best_bid=eng.best_bid(),
            best_ask=eng.best_ask(),
            mid=eng.mid(),
            spread=eng.spread(),
            resting=len(eng),
            bids=bids,
            asks=asks,
            trades=trades,
            forecast=forecast_dto,
            agents=agents_dto,
        )
