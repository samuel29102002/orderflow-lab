"""CSV/Parquet historical L2 data replay generator.

Feeds a recorded order book file tick-by-tick into the engine, enabling
backtesting agents (e.g. DeepLOB) against real historical flash crashes.

Expected columns (case-insensitive):
    timestamp   — Unix seconds (float) or ISO8601 string
    side        — "bid"/"buy" or "ask"/"sell" (case-insensitive)
    price       — integer tick price
    qty         — integer quantity
    order_type  — optional; ignored if missing
"""

from __future__ import annotations

import itertools
from pathlib import Path
from typing import Iterator

import pandas as pd

from orderflow_engine import Side

from ..events import LimitOrderEvent
from .base import BookState, FlowGenerator

_SIDE_MAP: dict[str, Side] = {
    "bid": Side.Bid,
    "buy": Side.Bid,
    "ask": Side.Ask,
    "sell": Side.Ask,
}

_ID_COUNTER = itertools.count(3_000_000_000)


class CSVReplayGenerator(FlowGenerator):
    """Replay a CSV or Parquet L2 data file tick-by-tick.

    Parameters
    ----------
    path:
        Path to a ``.csv`` or ``.parquet`` file.
    symbol:
        Unused by the engine today; reserved for multi-instrument support.
    speed_multiplier:
        Scale factor applied to inter-event dt (1.0 = realtime).  Has no
        effect when the downstream loop drives timing itself.
    """

    name = "csv_replay"

    def __init__(
        self,
        path: str,
        symbol: str = "SIM",
        speed_multiplier: float = 1.0,
    ) -> None:
        self.path = Path(path)
        self.symbol = symbol
        self.speed_multiplier = speed_multiplier
        self._iter: Iterator[LimitOrderEvent] = self._load()

    # ------------------------------------------------------------------

    def _load(self) -> Iterator[LimitOrderEvent]:
        p = self.path
        if p.suffix.lower() == ".parquet":
            df = pd.read_parquet(p)
        elif p.suffix.lower() in {".csv", ".tsv", ".gz"}:
            df = pd.read_csv(p)
        else:
            raise ValueError(f"Unsupported file type: {p.suffix!r}. Use .csv or .parquet")

        df.columns = [c.lower() for c in df.columns]

        required = {"side", "price", "qty"}
        missing = required - set(df.columns)
        if missing:
            raise ValueError(
                f"File {p.name!r} is missing required columns: {missing}. "
                f"Available: {list(df.columns)}"
            )

        has_ts = "timestamp" in df.columns
        t0 = 0.0

        for i, row in enumerate(df.itertuples(index=False)):
            side_raw = str(getattr(row, "side", "")).strip().lower()
            side = _SIDE_MAP.get(side_raw)
            if side is None:
                continue

            try:
                price = int(float(getattr(row, "price")))
                qty = int(float(getattr(row, "qty")))
            except (ValueError, TypeError):
                continue

            if price <= 0 or qty <= 0:
                continue

            if has_ts:
                raw_ts = getattr(row, "timestamp")
                try:
                    t = float(pd.Timestamp(raw_ts).timestamp()) if isinstance(raw_ts, str) else float(raw_ts)
                except Exception:
                    t = t0 + i * 0.001
            else:
                t = t0 + i * 0.001

            yield LimitOrderEvent(
                timestamp=t,
                id=next(_ID_COUNTER),
                side=side,
                price=price,
                qty=qty,
            )

    # ------------------------------------------------------------------

    def __next__(self) -> LimitOrderEvent:
        try:
            return next(self._iter)
        except StopIteration:
            raise

    def observe(self, state: BookState) -> None:
        pass
