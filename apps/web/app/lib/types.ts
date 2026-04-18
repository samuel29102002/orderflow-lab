// Wire types — mirrors services/api/app/domain/schemas.py.

export type Side = "bid" | "ask";

export type GeneratorName = "poisson" | "hawkes" | "queue_reactive";

export interface Level {
  price: number;
  qty: number;
}

export interface Trade {
  seq: number;
  price: number;
  qty: number;
  taker_side: Side;
  ts: number;
}

export type ForecastDirection = "down" | "flat" | "up";

export interface Forecast {
  direction: ForecastDirection;
  probs: [number, number, number]; // [p_down, p_flat, p_up]
  horizon_steps: number;
  model_ready: boolean;
}

export interface AgentState {
  name: string;
  enabled: boolean;
  position: number;
  cash: number;
  realized_pnl: number;
  unrealized_pnl: number;
  total_pnl: number;
  fills: number;
  gross_qty: number;
  open_order_id: number | null;
  open_order_side: Side | null;
  open_order_price: number | null;
  open_order_qty: number | null;
  cost_basis: number;
  mid: number | null;
  avg_slippage: number;
}

export interface BookSnapshot {
  type: "snapshot";
  seq: number;
  ts_wall: number;
  sim_t: number;
  best_bid: number | null;
  best_ask: number | null;
  mid: number | null;
  spread: number | null;
  resting: number;
  bids: Level[];
  asks: Level[];
  trades: Trade[];
  forecast: Forecast | null;
  agents: AgentState[] | null;
}

export interface Hello {
  type: "hello";
  engine_version: string;
  tick_hz: number;
  depth_levels: number;
  generator: GeneratorName;
  available_generators: GeneratorName[];
  sim_params: Record<string, number>;
}

export interface GeneratorChanged {
  type: "generator_changed";
  generator: GeneratorName;
  sim_params: Record<string, number>;
}

export interface SimulationReset {
  type: "simulation_reset";
}

export type StreamMessage = BookSnapshot | Hello | GeneratorChanged | SimulationReset;

export type ConnectionStatus = "idle" | "connecting" | "open" | "closed";
