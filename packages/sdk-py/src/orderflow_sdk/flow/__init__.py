"""Synthetic order-flow generators.

Three generators are exposed:

* :class:`PoissonFlowGenerator` — homogeneous Poisson + OU mid-price (MVP).
* :class:`HawkesFlowGenerator` — bivariate self- and cross-exciting Hawkes
  process that produces bursty, clustered flow.
* :class:`QueueReactiveFlowGenerator` — state-reactive Poisson whose rate /
  side / aggressiveness depend on the top-of-book.
"""

from .base import BookState, FlowGenerator, MarketContext, MarketContextConfig
from .csv_replay import CSVReplayGenerator
from .hawkes import HawkesConfig, HawkesFlowGenerator
from .poisson import FlowConfig, PoissonFlowGenerator
from .queue_reactive import QueueReactiveConfig, QueueReactiveFlowGenerator

__all__ = [
    "BookState",
    "CSVReplayGenerator",
    "FlowConfig",
    "FlowGenerator",
    "HawkesConfig",
    "HawkesFlowGenerator",
    "MarketContext",
    "MarketContextConfig",
    "PoissonFlowGenerator",
    "QueueReactiveConfig",
    "QueueReactiveFlowGenerator",
]
