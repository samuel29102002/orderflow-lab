// Client-side config. Keep defaults pointing at the local dev FastAPI.

export const WS_URL: string =
  process.env.NEXT_PUBLIC_WS_URL ?? "ws://127.0.0.1:8000/ws/stream";

export const API_URL: string =
  process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000";

export const TRADE_TAPE_LENGTH = 80;
export const PRICE_SERIES_LENGTH = 600;
