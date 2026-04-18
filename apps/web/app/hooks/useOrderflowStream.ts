"use client";

import { useEffect, useRef, useState } from "react";

import { PRICE_SERIES_LENGTH, TRADE_TAPE_LENGTH, WS_URL } from "../lib/config";
import type {
  AgentState,
  BookSnapshot,
  ConnectionStatus,
  Forecast,
  Hello,
  StreamMessage,
  Trade,
} from "../lib/types";

export interface PricePoint {
  seq: number;
  sim_t: number;
  mid: number;
}

export interface StreamState {
  status: ConnectionStatus;
  hello: Hello | null;
  snapshot: BookSnapshot | null;
  trades: Trade[];
  priceSeries: PricePoint[];
  forecast: Forecast | null;
  agents: AgentState[];
  framesPerSec: number;
  droppedConnections: number;
}

/**
 * Subscribe to the FastAPI `/ws/stream` firehose.
 *
 * Reconnects with a capped exponential backoff. Keeps:
 * - the most recent full book snapshot (drives the order-book panel)
 * - a ring-buffered trade tape (drives the trades list)
 * - a ring-buffered mid-price series (drives the chart)
 * - an observed frame rate so the UI can surface stream health
 */
export function useOrderflowStream(url: string = WS_URL): StreamState {
  const [status, setStatus] = useState<ConnectionStatus>("idle");
  const [hello, setHello] = useState<Hello | null>(null);
  const [snapshot, setSnapshot] = useState<BookSnapshot | null>(null);
  const [trades, setTrades] = useState<Trade[]>([]);
  const [priceSeries, setPriceSeries] = useState<PricePoint[]>([]);
  const [forecast, setForecast] = useState<Forecast | null>(null);
  const [agents, setAgents] = useState<AgentState[]>([]);
  const [framesPerSec, setFramesPerSec] = useState<number>(0);
  const [droppedConnections, setDroppedConnections] = useState<number>(0);

  const wsRef = useRef<WebSocket | null>(null);
  const reconnectRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const frameWindowRef = useRef<number[]>([]);

  useEffect(() => {
    let cancelled = false;
    let attempt = 0;

    const connect = () => {
      if (cancelled) return;
      setStatus("connecting");
      const ws = new WebSocket(url);
      wsRef.current = ws;

      ws.onopen = () => {
        attempt = 0;
        setStatus("open");
      };

      ws.onmessage = (evt) => {
        const msg: StreamMessage = JSON.parse(evt.data as string);
        if (msg.type === "hello") {
          setHello(msg);
          return;
        }
        if (msg.type === "simulation_reset") {
          setTrades([]);
          setPriceSeries([]);
          setAgents([]);
          return;
        }
        if (msg.type === "generator_changed") {
          setHello((prev) =>
            prev
              ? { ...prev, generator: msg.generator, sim_params: msg.sim_params }
              : prev,
          );
          return;
        }
        // snapshot
        setSnapshot(msg);
        setForecast(msg.forecast ?? null);
        setAgents(msg.agents ?? []);

        if (msg.trades.length > 0) {
          setTrades((prev) => {
            const next = [...msg.trades.slice().reverse(), ...prev];
            return next.length > TRADE_TAPE_LENGTH
              ? next.slice(0, TRADE_TAPE_LENGTH)
              : next;
          });
        }

        if (msg.mid != null) {
          const point: PricePoint = {
            seq: msg.seq,
            sim_t: msg.sim_t,
            mid: msg.mid,
          };
          setPriceSeries((prev) => {
            const next = prev.length >= PRICE_SERIES_LENGTH ? prev.slice(1) : prev.slice();
            next.push(point);
            return next;
          });
        }

        const now = performance.now();
        const window = frameWindowRef.current;
        window.push(now);
        while (window.length > 0 && now - window[0] > 1000) window.shift();
        setFramesPerSec(window.length);
      };

      ws.onclose = () => {
        if (wsRef.current === ws) wsRef.current = null;
        if (cancelled) return;
        setStatus("closed");
        setDroppedConnections((n) => n + 1);
        attempt += 1;
        const delay = Math.min(5000, 250 * 2 ** Math.min(attempt, 4));
        reconnectRef.current = setTimeout(connect, delay);
      };

      ws.onerror = () => {
        // onclose will fire after this; let the reconnect path handle it.
        try {
          ws.close();
        } catch {
          /* noop */
        }
      };
    };

    connect();

    return () => {
      cancelled = true;
      if (reconnectRef.current) clearTimeout(reconnectRef.current);
      if (wsRef.current) {
        try {
          wsRef.current.close();
        } catch {
          /* noop */
        }
        wsRef.current = null;
      }
    };
  }, [url]);

  return {
    status,
    hello,
    snapshot,
    trades,
    priceSeries,
    forecast,
    agents,
    framesPerSec,
    droppedConnections,
  };
}
