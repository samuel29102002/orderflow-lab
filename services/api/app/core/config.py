from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

GeneratorName = Literal["poisson", "hawkes", "queue_reactive"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="ORDERFLOW_",
        extra="ignore",
    )

    env: str = Field(default="dev")
    database_url: str = Field(
        default="postgresql+psycopg://orderflow:orderflow@localhost:5432/orderflow",
    )
    redis_url: str = Field(default="redis://localhost:6379/0")

    # ---- live simulation -------------------------------------------------

    sim_tick_hz: float = Field(default=20.0, description="broadcast frames per second")
    sim_speed: float = Field(default=1.0, description="simulator seconds per wall-clock second")
    sim_depth_levels: int = Field(default=10, description="levels per side sent in snapshots")
    sim_trade_buffer: int = Field(default=200, description="max trades buffered per frame")
    sim_seed: int = Field(default=42)

    # ---- generator selection ---------------------------------------------

    sim_generator: GeneratorName = Field(default="poisson")

    # Shared microstructure knobs (used by all generators).
    sim_mid0: float = Field(default=10_000.0)
    sim_mu: float = Field(default=10_000.0)
    sim_kappa: float = Field(default=1.5)
    sim_sigma: float = Field(default=4.0)
    sim_offset_mean: float = Field(default=3.0)
    sim_qty_mean: float = Field(default=10.0)

    # Poisson-specific.
    sim_lambda_rate: float = Field(default=80.0, description="Poisson arrival rate λ")

    # Hawkes-specific.
    sim_hawkes_mu: float = Field(default=10.0, description="baseline intensity per side")
    sim_hawkes_alpha_self: float = Field(default=0.6)
    sim_hawkes_alpha_cross: float = Field(default=0.15)
    sim_hawkes_beta: float = Field(default=1.0)

    # Queue-reactive-specific.
    sim_qr_base_lambda: float = Field(default=80.0)
    sim_qr_baseline_spread: int = Field(default=2)
    sim_qr_rate_sensitivity: float = Field(default=1.0)
    sim_qr_offset_sensitivity: float = Field(default=0.75)
    sim_qr_imbalance_sensitivity: float = Field(default=0.35)

    # ---- forecaster ------------------------------------------------------

    forecast_model_path: str = Field(
        default="../../research/artifacts/deeplob.pt",
        description="checkpoint for the DeepLOB forecaster; relative paths resolve from services/api",
    )
    forecast_enabled: bool = Field(default=True)

    # ---- agent (DeepLOB-driven trader) -----------------------------------

    agent_enabled: bool = Field(default=True)
    agent_threshold: float = Field(
        default=0.70,
        description="minimum winning-class probability required to submit",
    )
    agent_base_clip: int = Field(default=5, description="default lots per submission")
    agent_max_pos: int = Field(default=50, description="hard cap on |position|")
    agent_risk_aversion: float = Field(
        default=1.5,
        description="γ exponent in the Almgren-Chriss inventory penalty",
    )
    agent_place_cooldown_s: float = Field(
        default=0.10,
        description="minimum sim-seconds between successive submissions",
    )

    # ---- storage (TimescaleDB sink) --------------------------------------

    storage_enabled: bool = Field(
        default=True,
        description="write trades and PnL snapshots to TimescaleDB",
    )
    storage_pnl_interval_s: float = Field(
        default=5.0,
        description="seconds between agent PnL snapshots written to the DB",
    )

    # ---- HTTP / WS -------------------------------------------------------

    cors_origins: list[str] = Field(
        default_factory=lambda: ["http://localhost:3000", "http://127.0.0.1:3000"]
    )


settings = Settings()
