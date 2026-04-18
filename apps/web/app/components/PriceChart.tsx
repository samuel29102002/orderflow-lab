"use client";

import {
  ColorType,
  LineSeries,
  createChart,
  type IChartApi,
  type ISeriesApi,
  type LineData,
  type UTCTimestamp,
} from "lightweight-charts";
import { useEffect, useRef } from "react";

import type { PricePoint } from "../hooks/useOrderflowStream";
import type { Forecast, ForecastDirection } from "../lib/types";

interface Props {
  series: PricePoint[];
  forecast: Forecast | null;
}

const CHART_BG = "#000000";
const GRID = "#18181b"; // zinc-900
const AXIS = "#52525b"; // zinc-600
const LINE = "#38bdf8"; // sky-400

const DIR_STYLE: Record<ForecastDirection, { label: string; glyph: string; cls: string }> = {
  up: {
    label: "UP",
    glyph: "▲",
    cls: "border-emerald-500/60 bg-emerald-500/5 text-emerald-300",
  },
  down: {
    label: "DOWN",
    glyph: "▼",
    cls: "border-rose-500/60 bg-rose-500/5 text-rose-300",
  },
  flat: {
    label: "FLAT",
    glyph: "─",
    cls: "border-zinc-700 bg-zinc-950 text-zinc-300",
  },
};

function ForecastBadge({ forecast }: { forecast: Forecast | null }) {
  if (forecast == null) {
    return (
      <span className="border border-zinc-800 px-2 py-0.5 text-[10px] uppercase tracking-[0.14em] text-zinc-600">
        Forecast · off
      </span>
    );
  }

  if (!forecast.model_ready) {
    return (
      <span
        className="border border-zinc-700 bg-zinc-950 px-2 py-0.5 text-[10px] uppercase tracking-[0.14em] text-zinc-400"
        title="checkpoint not loaded or window still warming up"
      >
        AI · warming
      </span>
    );
  }

  const dir = DIR_STYLE[forecast.direction];
  const [pDown, pFlat, pUp] = forecast.probs;
  const active = forecast.direction === "up" ? pUp : forecast.direction === "down" ? pDown : pFlat;
  const horizonMs = Math.round(forecast.horizon_steps * 50);

  return (
    <span
      className={`flex items-center gap-1.5 border px-2 py-0.5 text-[10px] uppercase tracking-[0.14em] ${dir.cls}`}
      title={`down ${(pDown * 100).toFixed(0)}% · flat ${(pFlat * 100).toFixed(0)}% · up ${(pUp * 100).toFixed(0)}% · horizon ${horizonMs}ms`}
    >
      <span className="text-sm leading-none">{dir.glyph}</span>
      <span className="font-semibold">AI · {dir.label}</span>
      <span className="font-mono text-[9px] tabular-nums opacity-80">{(active * 100).toFixed(0)}%</span>
      <span className="font-mono text-[9px] opacity-60">+{horizonMs}ms</span>
    </span>
  );
}

export function PriceChart({ series, forecast }: Props) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const lineRef = useRef<ISeriesApi<"Line"> | null>(null);

  // init once
  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;

    const chart = createChart(el, {
      layout: {
        background: { type: ColorType.Solid, color: CHART_BG },
        textColor: AXIS,
        fontFamily: "var(--font-mono), ui-monospace, monospace",
        fontSize: 11,
      },
      grid: {
        vertLines: { color: GRID },
        horzLines: { color: GRID },
      },
      rightPriceScale: {
        borderColor: GRID,
        scaleMargins: { top: 0.1, bottom: 0.1 },
      },
      timeScale: {
        borderColor: GRID,
        timeVisible: true,
        secondsVisible: true,
      },
      crosshair: { mode: 0 },
      autoSize: true,
    });

    const line = chart.addSeries(LineSeries, {
      color: LINE,
      lineWidth: 1,
      priceLineVisible: true,
      priceLineWidth: 1,
      priceLineColor: LINE,
      priceLineStyle: 2,
      lastValueVisible: true,
      priceFormat: { type: "price", precision: 2, minMove: 0.5 },
    });

    chartRef.current = chart;
    lineRef.current = line;

    const ro = new ResizeObserver(() => chart.applyOptions({}));
    ro.observe(el);

    return () => {
      ro.disconnect();
      chart.remove();
      chartRef.current = null;
      lineRef.current = null;
    };
  }, []);

  // push data on each series update — setData is O(n) but n<=600, negligible
  useEffect(() => {
    const line = lineRef.current;
    if (!line) return;

    const data: LineData[] = series.map((p) => ({
      // sim_t is seconds-since-start; the chart wants a UTCTimestamp. Fake it
      // by pretending sim_t is seconds-since-epoch; the axis labels will just
      // read like a monotonic timer which is what we want.
      time: p.sim_t as UTCTimestamp,
      value: p.mid,
    }));

    line.setData(data);
  }, [series]);

  return (
    <section className="flex min-h-0 flex-col border border-zinc-800 bg-black">
      <header className="flex items-center justify-between gap-3 border-b border-zinc-800 px-3 py-2">
        <h2 className="text-[10px] font-semibold uppercase tracking-[0.18em] text-zinc-500">
          Mid-Price
        </h2>
        <div className="flex items-center gap-2">
          <ForecastBadge forecast={forecast} />
          <span className="font-mono text-[10px] text-zinc-600 tabular-nums">{series.length} pts</span>
        </div>
      </header>
      <div ref={containerRef} className="min-h-0 flex-1" />
    </section>
  );
}
