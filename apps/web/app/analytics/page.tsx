"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { API_URL } from "../lib/config";

interface PnlPoint {
  time: string;
  agent_name: string;
  total_pnl: number;
  realized_pnl: number;
  unrealized_pnl: number;
  position: number;
}

interface RatioEntry {
  agent_name: string;
  sharpe: number;
  information_ratio: number;
  mean_pnl_per_period: number;
  pnl_volatility: number;
  n_periods: number;
}

interface RatiosResponse {
  hours: number;
  agents: RatioEntry[];
}

interface ChartRow {
  t: number;
  label: string;
  deeplob?: number;
  market_maker?: number;
}

const AGENT_COLORS: Record<string, string> = {
  deeplob: "#38bdf8", // sky-400
  market_maker: "#34d399", // emerald-400
};

function fmtTime(ts: number): string {
  const d = new Date(ts);
  const hh = String(d.getHours()).padStart(2, "0");
  const mm = String(d.getMinutes()).padStart(2, "0");
  const ss = String(d.getSeconds()).padStart(2, "0");
  return `${hh}:${mm}:${ss}`;
}

function fmtNum(v: number, digits = 4): string {
  if (!Number.isFinite(v)) return "—";
  return v.toFixed(digits);
}

function ratioClass(v: number): string {
  if (!Number.isFinite(v)) return "text-zinc-500";
  if (v > 0) return "text-emerald-400";
  if (v < 0) return "text-rose-400";
  return "text-zinc-400";
}

function agentDisplayName(name: string): string {
  if (name === "deeplob") return "DeepLOB";
  if (name === "market_maker") return "Market Maker";
  return name;
}

export default function AnalyticsPage() {
  const [pnl, setPnl] = useState<PnlPoint[] | null>(null);
  const [ratios, setRatios] = useState<RatiosResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function fetchAll() {
      try {
        const [pnlRes, ratioRes] = await Promise.all([
          fetch(`${API_URL}/analytics/pnl?hours=1`),
          fetch(`${API_URL}/analytics/ratios?hours=1`),
        ]);
        if (!pnlRes.ok || !ratioRes.ok) {
          throw new Error(`HTTP ${pnlRes.status}/${ratioRes.status}`);
        }
        const pnlData = (await pnlRes.json()) as PnlPoint[];
        const ratioData = (await ratioRes.json()) as RatiosResponse;
        if (!cancelled) {
          setPnl(pnlData);
          setRatios(ratioData);
          setError(null);
        }
      } catch (e) {
        if (!cancelled) {
          setError(e instanceof Error ? e.message : String(e));
        }
      }
    }

    fetchAll();
    const id = setInterval(fetchAll, 30_000);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, []);

  const chartData: ChartRow[] = useMemo(() => {
    if (!pnl) return [];
    const byTime = new Map<number, ChartRow>();
    for (const p of pnl) {
      const t = new Date(p.time).getTime();
      if (!Number.isFinite(t)) continue;
      let row = byTime.get(t);
      if (!row) {
        row = { t, label: fmtTime(t) };
        byTime.set(t, row);
      }
      if (p.agent_name === "deeplob") row.deeplob = p.total_pnl;
      else if (p.agent_name === "market_maker") row.market_maker = p.total_pnl;
    }
    return Array.from(byTime.values()).sort((a, b) => a.t - b.t);
  }, [pnl]);

  const loading = pnl === null || ratios === null;

  const maxPeriods = ratios
    ? ratios.agents.reduce((m, a) => Math.max(m, a.n_periods), 0)
    : 0;
  const notEnoughData = ratios !== null && maxPeriods < 10;

  return (
    <main className="min-h-screen bg-black text-zinc-100">
      <div className="flex items-center justify-between border-b border-zinc-800 bg-black px-4 py-2">
        <div className="flex items-center gap-3">
          <Link
            href="/lab"
            className="text-[10px] uppercase tracking-[0.18em] text-zinc-600 transition-colors hover:text-zinc-300"
          >
            ← Lab
          </Link>
          <span className="text-[10px] font-semibold uppercase tracking-[0.22em] text-zinc-500">
            Analytics
          </span>
        </div>
        <span className="text-[10px] uppercase tracking-[0.18em] text-zinc-600">
          window · 1h · refresh 30s
        </span>
      </div>

      {loading ? (
        <div className="flex min-h-[60vh] items-center justify-center text-[11px] uppercase tracking-[0.22em] text-zinc-600">
          Loading...
        </div>
      ) : (
        <div className="mx-auto flex max-w-6xl flex-col gap-6 px-4 py-6">
          {error && (
            <div className="border border-rose-900 bg-black px-3 py-2 font-mono text-[11px] text-rose-400">
              Error: {error}
            </div>
          )}

          {notEnoughData && (
            <div className="border border-zinc-800 bg-black px-3 py-2 text-[11px] text-zinc-500">
              Collecting data — check back after the simulation has run for ~1 minute.
            </div>
          )}

          {/* Cumulative PnL chart */}
          <section className="border border-zinc-800 bg-black">
            <div className="flex items-center justify-between border-b border-zinc-800 px-3 py-2">
              <span className="text-[10px] uppercase tracking-[0.22em] text-zinc-500">
                Cumulative PnL · 1h
              </span>
              <span className="font-mono text-[10px] tabular-nums text-zinc-600">
                {chartData.length} points
              </span>
            </div>
            <div className="h-80 w-full px-2 py-3">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={chartData} margin={{ top: 8, right: 16, bottom: 8, left: 0 }}>
                  <CartesianGrid stroke="#27272a" strokeDasharray="0" vertical={false} />
                  <XAxis
                    dataKey="label"
                    tick={{ fill: "#52525b", fontSize: 10, fontFamily: "monospace" }}
                    stroke="#3f3f46"
                    minTickGap={48}
                  />
                  <YAxis
                    tick={{ fill: "#52525b", fontSize: 10, fontFamily: "monospace" }}
                    stroke="#3f3f46"
                    width={60}
                    domain={["auto", "auto"]}
                  />
                  <Tooltip
                    contentStyle={{
                      backgroundColor: "#000",
                      border: "1px solid #27272a",
                      borderRadius: 0,
                      fontFamily: "monospace",
                      fontSize: 11,
                    }}
                    labelStyle={{ color: "#a1a1aa" }}
                    itemStyle={{ color: "#e4e4e7" }}
                  />
                  <Legend
                    wrapperStyle={{
                      fontSize: 10,
                      fontFamily: "monospace",
                      textTransform: "uppercase",
                      letterSpacing: "0.18em",
                      color: "#71717a",
                    }}
                  />
                  <Line
                    type="monotone"
                    dataKey="deeplob"
                    name="DeepLOB"
                    stroke={AGENT_COLORS.deeplob}
                    strokeWidth={1.5}
                    dot={false}
                    isAnimationActive={false}
                    connectNulls
                  />
                  <Line
                    type="monotone"
                    dataKey="market_maker"
                    name="Market Maker"
                    stroke={AGENT_COLORS.market_maker}
                    strokeWidth={1.5}
                    dot={false}
                    isAnimationActive={false}
                    connectNulls
                  />
                </LineChart>
              </ResponsiveContainer>
            </div>
          </section>

          {/* Ratio table */}
          <section className="border border-zinc-800 bg-black">
            <div className="border-b border-zinc-800 px-3 py-2 text-[10px] uppercase tracking-[0.22em] text-zinc-500">
              Performance Ratios
            </div>
            <table className="w-full border-collapse">
              <thead>
                <tr className="border-b border-zinc-800 text-[10px] uppercase tracking-[0.22em] text-zinc-500">
                  <th className="px-3 py-2 text-left font-semibold">Agent</th>
                  <th className="px-3 py-2 text-right font-semibold">Sharpe</th>
                  <th className="px-3 py-2 text-right font-semibold">Info Ratio</th>
                  <th className="px-3 py-2 text-right font-semibold">Mean PnL</th>
                  <th className="px-3 py-2 text-right font-semibold">Vol</th>
                  <th className="px-3 py-2 text-right font-semibold">N</th>
                </tr>
              </thead>
              <tbody>
                {ratios!.agents.length === 0 ? (
                  <tr>
                    <td
                      colSpan={6}
                      className="px-3 py-4 text-center text-[11px] text-zinc-600"
                    >
                      No ratio data available.
                    </td>
                  </tr>
                ) : (
                  ratios!.agents.map((a) => (
                    <tr key={a.agent_name} className="border-b border-zinc-900">
                      <td className="px-3 py-2 text-[11px] uppercase tracking-[0.18em] text-zinc-300">
                        {agentDisplayName(a.agent_name)}
                      </td>
                      <td
                        className={`px-3 py-2 text-right font-mono text-sm tabular-nums ${ratioClass(a.sharpe)}`}
                      >
                        {fmtNum(a.sharpe, 3)}
                      </td>
                      <td
                        className={`px-3 py-2 text-right font-mono text-sm tabular-nums ${ratioClass(a.information_ratio)}`}
                      >
                        {fmtNum(a.information_ratio, 3)}
                      </td>
                      <td
                        className={`px-3 py-2 text-right font-mono text-sm tabular-nums ${ratioClass(a.mean_pnl_per_period)}`}
                      >
                        {fmtNum(a.mean_pnl_per_period, 4)}
                      </td>
                      <td className="px-3 py-2 text-right font-mono text-sm tabular-nums text-zinc-300">
                        {fmtNum(a.pnl_volatility, 4)}
                      </td>
                      <td className="px-3 py-2 text-right font-mono text-sm tabular-nums text-zinc-500">
                        {a.n_periods}
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </section>
        </div>
      )}
    </main>
  );
}
