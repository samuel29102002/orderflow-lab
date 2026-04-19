"use client";

import { useState } from "react";

import type { AgentState } from "../lib/types";

interface Props {
  agents: AgentState[];
}

function SlippageBadge({ slippage }: { slippage: number }) {
  const abs = Math.abs(slippage);
  const cls =
    abs < 0.1
      ? "bg-emerald-950 text-emerald-400 border border-emerald-800"
      : abs <= 1.0
        ? "bg-yellow-950 text-yellow-400 border border-yellow-800"
        : "bg-red-950 text-red-400 border border-red-800";
  return (
    <span
      className={`inline-block px-1.5 py-px font-mono text-[9px] tabular-nums leading-tight ${cls}`}
    >
      {abs.toFixed(3)}
    </span>
  );
}

function SideBadge({ side }: { side: "BUY" | "SELL" | null }) {
  if (side === "BUY")
    return (
      <span className="inline-block border border-emerald-800 bg-emerald-950 px-1.5 py-px font-mono text-[9px] leading-tight text-emerald-400">
        BUY
      </span>
    );
  if (side === "SELL")
    return (
      <span className="inline-block border border-rose-800 bg-rose-950 px-1.5 py-px font-mono text-[9px] leading-tight text-rose-400">
        SELL
      </span>
    );
  return (
    <span className="inline-block border border-zinc-700 bg-zinc-900 px-1.5 py-px font-mono text-[9px] leading-tight text-zinc-500">
      —
    </span>
  );
}

function inferSide(agent: AgentState): "BUY" | "SELL" | null {
  if (agent.open_order_side === "bid") return "BUY";
  if (agent.open_order_side === "ask") return "SELL";
  if (agent.position > 0) return "BUY";
  if (agent.position < 0) return "SELL";
  return null;
}

export function ExecutionSidebar({ agents }: Props) {
  const [collapsed, setCollapsed] = useState(false);
  const rows = agents
    .filter((a) => a.enabled && a.fills > 0)
    .sort((a, b) => b.fills - a.fills)
    .slice(0, 5);

  return (
    <aside
      className={`flex flex-col border-l border-zinc-800 bg-black transition-all duration-200 ${collapsed ? "w-8" : "w-[220px]"}`}
    >
      <div className="flex h-8 items-center justify-between border-b border-zinc-800 px-2">
        {!collapsed && (
          <span className="select-none font-mono text-[10px] font-semibold uppercase tracking-widest text-zinc-500">
            Executions
          </span>
        )}
        <button
          onClick={() => setCollapsed((c) => !c)}
          className={`flex h-5 w-5 items-center justify-center border border-zinc-800 bg-black font-mono text-[10px] text-zinc-500 transition-colors hover:border-zinc-600 hover:text-zinc-300 ${collapsed ? "mx-auto" : "ml-auto"}`}
          aria-label={collapsed ? "Expand" : "Collapse"}
        >
          {collapsed ? "›" : "‹"}
        </button>
      </div>

      {!collapsed && (
        <div className="flex min-h-0 flex-1 flex-col overflow-hidden">
          <div className="grid grid-cols-[1fr_auto] gap-x-2 border-b border-zinc-800 px-2 py-1">
            <span className="font-mono text-[9px] uppercase tracking-[0.14em] text-zinc-600">
              Agent / Side
            </span>
            <span className="text-right font-mono text-[9px] uppercase tracking-[0.14em] text-zinc-600">
              Slip
            </span>
          </div>

          <ul className="flex-1 overflow-y-auto">
            {rows.length === 0 ? (
              <li className="px-2 py-2 font-mono text-[10px] text-zinc-600">no fills yet…</li>
            ) : (
              rows.map((agent) => {
                const side = inferSide(agent);
                const price =
                  agent.cost_basis > 0
                    ? agent.cost_basis.toLocaleString(undefined, {
                        minimumFractionDigits: 1,
                        maximumFractionDigits: 1,
                      })
                    : "—";
                return (
                  <li key={agent.name} className="border-b border-zinc-900 px-2 py-1.5">
                    <div className="flex items-center justify-between gap-1">
                      <span
                        className="truncate font-mono text-[10px] text-zinc-300"
                        title={agent.name}
                      >
                        {agent.name}
                      </span>
                      <SlippageBadge slippage={agent.avg_slippage} />
                    </div>
                    <div className="mt-0.5 flex items-center gap-1.5">
                      <SideBadge side={side} />
                      <span className="font-mono text-[10px] tabular-nums text-zinc-400">
                        {price}
                      </span>
                      <span className="ml-auto font-mono text-[9px] tabular-nums text-zinc-500">
                        ×{agent.gross_qty}
                      </span>
                    </div>
                  </li>
                );
              })
            )}
          </ul>

          <div className="border-t border-zinc-800 px-2 py-1">
            <span className="font-mono text-[9px] tabular-nums text-zinc-600">
              {rows.length} / {agents.filter((a) => a.enabled).length} agents
            </span>
          </div>
        </div>
      )}
    </aside>
  );
}
