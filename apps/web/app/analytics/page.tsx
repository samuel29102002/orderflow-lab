"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { API_URL } from "../lib/config";

// ─── Types ────────────────────────────────────────────────────────────────────

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

// ─── Per-agent chart row ───────────────────────────────────────────────────────

interface PnlChartRow {
  t: number;
  label: string;
  realized_pnl: number | undefined;
  unrealized_pnl: number | undefined;
}

// ─── Risk metric results ───────────────────────────────────────────────────────

interface RiskMetrics {
  sharpe: number;
  maxDrawdown: number;       // expressed as a positive percentage, e.g. 3.42
  timeInMarket: number;      // percentage 0–100
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

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

function fmtPct(v: number, digits = 2): string {
  if (!Number.isFinite(v)) return "—";
  return `${v.toFixed(digits)}%`;
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

// ─── Risk computation ─────────────────────────────────────────────────────────

/**
 * Compute annualised Sharpe, max drawdown and time-in-market
 * from the raw PnlPoint array for a single agent.
 */
function computeRiskMetrics(points: PnlPoint[]): RiskMetrics {
  if (points.length < 2) {
    return { sharpe: NaN, maxDrawdown: NaN, timeInMarket: NaN };
  }

  // Sort ascending by time
  const sorted = [...points].sort(
    (a, b) => new Date(a.time).getTime() - new Date(b.time).getTime(),
  );

  // Daily returns from total_pnl differences (tick-level, treat as "period returns")
  const pnlValues = sorted.map((p) => p.total_pnl);
  const returns: number[] = [];
  for (let i = 1; i < pnlValues.length; i++) {
    returns.push(pnlValues[i] - pnlValues[i - 1]);
  }

  const n = returns.length;
  const mean = returns.reduce((s, r) => s + r, 0) / n;
  const variance = returns.reduce((s, r) => s + (r - mean) ** 2, 0) / n;
  const std = Math.sqrt(variance);
  // Annualise: assume ~252 trading days worth of ticks scaled proportionally
  const sharpe = std === 0 ? NaN : (mean / std) * Math.sqrt(252);

  // Max drawdown: peak-to-trough on cumulative total_pnl
  let peak = -Infinity;
  let maxDD = 0;
  for (const v of pnlValues) {
    if (v > peak) peak = v;
    const dd = peak - v;
    if (dd > maxDD) maxDD = dd;
  }
  // Express as percentage of the peak magnitude (avoid div by zero)
  const maxDrawdown =
    Math.abs(peak) > 1e-10 ? (maxDD / Math.abs(peak)) * 100 : NaN;

  // Time in market: fraction of ticks where position != 0
  const inMarket = sorted.filter((p) => p.position !== 0).length;
  const timeInMarket = (inMarket / sorted.length) * 100;

  return { sharpe, maxDrawdown, timeInMarket };
}

// ─── Custom Tooltip ──────────────────────────────────────────────────────────

interface TooltipPayloadItem {
  dataKey: string;
  value: number;
  color: string;
}

interface CustomTooltipProps {
  active?: boolean;
  label?: string;
  payload?: TooltipPayloadItem[];
}

function PnlTooltip({ active, label, payload }: CustomTooltipProps) {
  if (!active || !payload || payload.length === 0) return null;

  const realized = payload.find((p) => p.dataKey === "realized_pnl");
  const unrealized = payload.find((p) => p.dataKey === "unrealized_pnl");

  return (
    <div
      style={{
        backgroundColor: "#09090b",
        border: "1px solid #27272a",
        borderRadius: 0,
        fontFamily: "monospace",
        fontSize: 11,
        padding: "8px 12px",
        lineHeight: "1.7",
      }}
    >
      <div style={{ color: "#71717a", marginBottom: 4 }}>{label}</div>
      {realized && (
        <div style={{ color: "#34d399" }}>
          realized&nbsp;&nbsp;
          <span style={{ color: "#d4d4d8" }}>{fmtNum(realized.value, 4)}</span>
        </div>
      )}
      {unrealized && (
        <div style={{ color: "#71717a" }}>
          unrealized&nbsp;
          <span style={{ color: "#d4d4d8" }}>{fmtNum(unrealized.value, 4)}</span>
        </div>
      )}
      {realized && unrealized && (
        <div style={{ color: "#52525b", marginTop: 4 }}>
          total&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;
          <span style={{ color: "#e4e4e7" }}>
            {fmtNum(realized.value + unrealized.value, 4)}
          </span>
        </div>
      )}
    </div>
  );
}

// ─── Stat card ────────────────────────────────────────────────────────────────

interface StatCardProps {
  label: string;
  value: string;
  valueClass?: string;
}

function StatCard({ label, value, valueClass = "text-zinc-100" }: StatCardProps) {
  return (
    <div className="flex flex-col gap-1.5 border border-zinc-800 bg-black px-5 py-4">
      <span
        className={`font-mono text-2xl tabular-nums leading-none ${valueClass}`}
      >
        {value}
      </span>
      <span className="text-[10px] uppercase tracking-[0.22em] text-zinc-500">
        {label}
      </span>
    </div>
  );
}

// ─── Tab type ─────────────────────────────────────────────────────────────────

type Tab = "pnl" | "risk";

// ─── Page ─────────────────────────────────────────────────────────────────────

export default function AnalyticsPage() {
  const [pnl, setPnl] = useState<PnlPoint[] | null>(null);
  const [ratios, setRatios] = useState<RatiosResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<Tab>("pnl");
  const [selectedAgent, setSelectedAgent] = useState<string>("deeplob");

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
          // Default to first agent returned
          if (ratioData.agents.length > 0) {
            setSelectedAgent((prev) => {
              const names = ratioData.agents.map((a) => a.agent_name);
              return names.includes(prev) ? prev : names[0];
            });
          }
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

  // ── PnL chart data for the selected agent ────────────────────────────────
  const pnlChartData: PnlChartRow[] = useMemo(() => {
    if (!pnl) return [];
    const agentPoints = pnl.filter((p) => p.agent_name === selectedAgent);
    return agentPoints
      .map((p) => ({
        t: new Date(p.time).getTime(),
        label: fmtTime(new Date(p.time).getTime()),
        realized_pnl: Number.isFinite(p.realized_pnl) ? p.realized_pnl : undefined,
        unrealized_pnl: Number.isFinite(p.unrealized_pnl)
          ? p.unrealized_pnl
          : undefined,
      }))
      .filter((r) => Number.isFinite(r.t))
      .sort((a, b) => a.t - b.t);
  }, [pnl, selectedAgent]);

  // ── Risk metrics per-agent ────────────────────────────────────────────────
  const riskByAgent = useMemo(() => {
    if (!pnl) return {} as Record<string, RiskMetrics>;
    const agentNames = [...new Set(pnl.map((p) => p.agent_name))];
    const result: Record<string, RiskMetrics> = {};
    for (const name of agentNames) {
      result[name] = computeRiskMetrics(pnl.filter((p) => p.agent_name === name));
    }
    return result;
  }, [pnl]);

  const agentNames: string[] = ratios
    ? ratios.agents.map((a) => a.agent_name)
    : [];

  const loading = pnl === null || ratios === null;

  const maxPeriods = ratios
    ? ratios.agents.reduce((m, a) => Math.max(m, a.n_periods), 0)
    : 0;
  const notEnoughData = ratios !== null && maxPeriods < 10;

  const currentRisk: RiskMetrics | null = riskByAgent[selectedAgent] ?? null;

  return (
    <main className="min-h-screen bg-black text-zinc-100">
      {/* ── Top nav ──────────────────────────────────────────────────────────── */}
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
        <div className="mx-auto flex max-w-6xl flex-col gap-0 px-4 py-6">
          {error && (
            <div className="mb-4 border border-rose-900 bg-black px-3 py-2 font-mono text-[11px] text-rose-400">
              Error: {error}
            </div>
          )}

          {notEnoughData && (
            <div className="mb-4 border border-zinc-800 bg-black px-3 py-2 text-[11px] text-zinc-500">
              Collecting data — check back after the simulation has run for ~1 minute.
            </div>
          )}

          {/* ── Agent selector ──────────────────────────────────────────────── */}
          {agentNames.length > 1 && (
            <div className="mb-4 flex items-center gap-2">
              <span className="text-[10px] uppercase tracking-[0.18em] text-zinc-600">
                Agent
              </span>
              {agentNames.map((name) => (
                <button
                  key={name}
                  onClick={() => setSelectedAgent(name)}
                  className={[
                    "px-3 py-1 text-[10px] uppercase tracking-[0.18em] transition-colors",
                    selectedAgent === name
                      ? "border border-zinc-100 text-zinc-100"
                      : "border border-zinc-800 text-zinc-600 hover:text-zinc-400",
                  ].join(" ")}
                >
                  {agentDisplayName(name)}
                </button>
              ))}
            </div>
          )}

          {/* ── Tab nav ─────────────────────────────────────────────────────── */}
          <div className="mb-0 flex border-b border-zinc-800">
            {(
              [
                { id: "pnl", label: "PnL Curve" },
                { id: "risk", label: "Risk Metrics" },
              ] as { id: Tab; label: string }[]
            ).map((tab) => (
              <button
                key={tab.id}
                onClick={() => setActiveTab(tab.id)}
                className={[
                  "px-4 py-2 text-[11px] uppercase tracking-[0.18em] transition-colors",
                  activeTab === tab.id
                    ? "border-b-2 border-zinc-100 text-zinc-100"
                    : "border-b-2 border-transparent text-zinc-600 hover:text-zinc-400",
                ].join(" ")}
              >
                {tab.label}
              </button>
            ))}
          </div>

          {/* ── Tab 1: PnL Curve ────────────────────────────────────────────── */}
          {activeTab === "pnl" && (
            <section className="border border-t-0 border-zinc-800 bg-black">
              <div className="flex items-center justify-between border-b border-zinc-800 px-3 py-2">
                <span className="text-[10px] uppercase tracking-[0.22em] text-zinc-500">
                  PnL Curve · {agentDisplayName(selectedAgent)} · 1h
                </span>
                <span className="font-mono text-[10px] tabular-nums text-zinc-600">
                  {pnlChartData.length} points
                </span>
              </div>

              <div className="h-80 w-full px-2 py-3">
                <ResponsiveContainer width="100%" height="100%">
                  <AreaChart
                    data={pnlChartData}
                    margin={{ top: 8, right: 16, bottom: 8, left: 0 }}
                  >
                    <defs>
                      <linearGradient
                        id="gradRealized"
                        x1="0"
                        y1="0"
                        x2="0"
                        y2="1"
                      >
                        <stop
                          offset="5%"
                          stopColor="#34d399"
                          stopOpacity={0.15}
                        />
                        <stop
                          offset="95%"
                          stopColor="#34d399"
                          stopOpacity={0}
                        />
                      </linearGradient>
                      <linearGradient
                        id="gradUnrealized"
                        x1="0"
                        y1="0"
                        x2="0"
                        y2="1"
                      >
                        <stop
                          offset="5%"
                          stopColor="#71717a"
                          stopOpacity={0.12}
                        />
                        <stop
                          offset="95%"
                          stopColor="#71717a"
                          stopOpacity={0}
                        />
                      </linearGradient>
                    </defs>

                    <CartesianGrid
                      stroke="#27272a"
                      strokeDasharray="0"
                      vertical={false}
                    />
                    <XAxis
                      dataKey="label"
                      tick={{
                        fill: "#52525b",
                        fontSize: 10,
                        fontFamily: "monospace",
                      }}
                      stroke="#3f3f46"
                      minTickGap={48}
                    />
                    <YAxis
                      tick={{
                        fill: "#52525b",
                        fontSize: 10,
                        fontFamily: "monospace",
                      }}
                      stroke="#3f3f46"
                      width={64}
                      domain={["auto", "auto"]}
                    />
                    <Tooltip content={<PnlTooltip />} />

                    {/* Unrealized — dashed zinc, rendered first (behind) */}
                    <Area
                      type="monotone"
                      dataKey="unrealized_pnl"
                      name="Unrealized"
                      stroke="#71717a"
                      strokeWidth={1.5}
                      strokeDasharray="4 3"
                      fill="url(#gradUnrealized)"
                      dot={false}
                      isAnimationActive={false}
                      connectNulls
                    />

                    {/* Realized — solid emerald */}
                    <Area
                      type="monotone"
                      dataKey="realized_pnl"
                      name="Realized"
                      stroke="#34d399"
                      strokeWidth={1.5}
                      fill="url(#gradRealized)"
                      dot={false}
                      isAnimationActive={false}
                      connectNulls
                    />
                  </AreaChart>
                </ResponsiveContainer>
              </div>

              {/* Legend */}
              <div className="flex items-center gap-6 border-t border-zinc-800 px-4 py-2">
                <div className="flex items-center gap-2">
                  <span
                    style={{
                      display: "inline-block",
                      width: 20,
                      height: 1.5,
                      backgroundColor: "#34d399",
                    }}
                  />
                  <span className="text-[10px] uppercase tracking-[0.18em] text-zinc-500">
                    Realized
                  </span>
                </div>
                <div className="flex items-center gap-2">
                  <svg width={20} height={4}>
                    <line
                      x1={0}
                      y1={2}
                      x2={20}
                      y2={2}
                      stroke="#71717a"
                      strokeWidth={1.5}
                      strokeDasharray="4 3"
                    />
                  </svg>
                  <span className="text-[10px] uppercase tracking-[0.18em] text-zinc-500">
                    Unrealized
                  </span>
                </div>
              </div>
            </section>
          )}

          {/* ── Tab 2: Risk Metrics ─────────────────────────────────────────── */}
          {activeTab === "risk" && (
            <section className="border border-t-0 border-zinc-800 bg-black">
              <div className="border-b border-zinc-800 px-3 py-2 text-[10px] uppercase tracking-[0.22em] text-zinc-500">
                Risk Metrics · {agentDisplayName(selectedAgent)} · 1h
              </div>

              {/* Stat cards */}
              <div className="grid grid-cols-3 gap-px bg-zinc-800 p-px">
                <StatCard
                  label="Sharpe Ratio (annualised)"
                  value={fmtNum(currentRisk?.sharpe ?? NaN, 3)}
                  valueClass={
                    currentRisk
                      ? ratioClass(currentRisk.sharpe)
                      : "text-zinc-500"
                  }
                />
                <StatCard
                  label="Max Drawdown"
                  value={
                    currentRisk ? fmtPct(currentRisk.maxDrawdown, 2) : "—"
                  }
                  valueClass={
                    currentRisk && Number.isFinite(currentRisk.maxDrawdown)
                      ? currentRisk.maxDrawdown > 5
                        ? "text-rose-400"
                        : "text-zinc-100"
                      : "text-zinc-500"
                  }
                />
                <StatCard
                  label="Time in Market"
                  value={
                    currentRisk ? fmtPct(currentRisk.timeInMarket, 1) : "—"
                  }
                />
              </div>

              {/* Methodology note */}
              <div className="border-t border-zinc-800 px-4 py-3 text-[10px] leading-relaxed text-zinc-600">
                Sharpe: (mean_tick_return / std_tick_return) * sqrt(252) &nbsp;·&nbsp;
                Drawdown: peak-to-trough on cumulative PnL &nbsp;·&nbsp;
                Time-in-market: ticks with open position / total ticks
              </div>

              {/* Per-agent ratio table (all agents) */}
              {ratios && ratios.agents.length > 0 && (
                <>
                  <div className="border-t border-zinc-800 px-3 py-2 text-[10px] uppercase tracking-[0.22em] text-zinc-500">
                    All Agents
                  </div>
                  <table className="w-full border-collapse">
                    <thead>
                      <tr className="border-b border-zinc-800 text-[10px] uppercase tracking-[0.22em] text-zinc-500">
                        <th className="px-3 py-2 text-left font-semibold">
                          Agent
                        </th>
                        <th className="px-3 py-2 text-right font-semibold">
                          Sharpe (server)
                        </th>
                        <th className="px-3 py-2 text-right font-semibold">
                          Max DD
                        </th>
                        <th className="px-3 py-2 text-right font-semibold">
                          Time in Mkt
                        </th>
                        <th className="px-3 py-2 text-right font-semibold">
                          Mean PnL
                        </th>
                        <th className="px-3 py-2 text-right font-semibold">
                          Vol
                        </th>
                      </tr>
                    </thead>
                    <tbody>
                      {ratios.agents.map((a) => {
                        const risk = riskByAgent[a.agent_name];
                        return (
                          <tr
                            key={a.agent_name}
                            className="border-b border-zinc-900"
                          >
                            <td className="px-3 py-2 text-[11px] uppercase tracking-[0.18em] text-zinc-300">
                              {agentDisplayName(a.agent_name)}
                            </td>
                            <td
                              className={`px-3 py-2 text-right font-mono text-sm tabular-nums ${ratioClass(a.sharpe)}`}
                            >
                              {fmtNum(a.sharpe, 3)}
                            </td>
                            <td className="px-3 py-2 text-right font-mono text-sm tabular-nums text-zinc-300">
                              {risk ? fmtPct(risk.maxDrawdown, 2) : "—"}
                            </td>
                            <td className="px-3 py-2 text-right font-mono text-sm tabular-nums text-zinc-300">
                              {risk ? fmtPct(risk.timeInMarket, 1) : "—"}
                            </td>
                            <td
                              className={`px-3 py-2 text-right font-mono text-sm tabular-nums ${ratioClass(a.mean_pnl_per_period)}`}
                            >
                              {fmtNum(a.mean_pnl_per_period, 4)}
                            </td>
                            <td className="px-3 py-2 text-right font-mono text-sm tabular-nums text-zinc-300">
                              {fmtNum(a.pnl_volatility, 4)}
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </>
              )}
            </section>
          )}
        </div>
      )}
    </main>
  );
}
