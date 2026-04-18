"use client";

import type { AgentState } from "../lib/types";

interface Props {
  agents: AgentState[];
}

function fmtPnl(v: number): string {
  const sign = v >= 0 ? "+" : "−";
  return `${sign}${Math.abs(v).toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
}

function pnlClass(v: number): string {
  if (v > 0.005) return "text-emerald-400";
  if (v < -0.005) return "text-rose-400";
  return "text-zinc-400";
}

function posClass(p: number): string {
  if (p > 0) return "text-emerald-300";
  if (p < 0) return "text-rose-300";
  return "text-zinc-400";
}

function AgentLabel({ name }: { name: string }) {
  const display = name === "deeplob" ? "DeepLOB" : name === "market_maker" ? "MM" : name;
  return (
    <span className="text-[9px] font-semibold uppercase tracking-[0.22em] text-zinc-500">
      {display}
    </span>
  );
}

function AgentRow({ agent }: { agent: AgentState }) {
  const total = agent.total_pnl;
  const pos = agent.position;

  return (
    <div className="flex items-center divide-x divide-zinc-800">
      {/* Name */}
      <div className="flex w-20 flex-col justify-center px-3 py-1.5">
        <AgentLabel name={agent.name} />
      </div>

      {/* PnL */}
      <div className="flex flex-col justify-center px-3 py-1.5">
        <span className="text-[9px] font-semibold uppercase tracking-[0.22em] text-zinc-600">
          PnL
        </span>
        <span className={`font-mono text-sm font-semibold leading-tight tabular-nums ${pnlClass(total)}`}>
          {fmtPnl(total)}
        </span>
        <span className="mt-0.5 font-mono text-[9px] uppercase tracking-[0.14em] tabular-nums text-zinc-600">
          r:{fmtPnl(agent.realized_pnl)} · u:{fmtPnl(agent.unrealized_pnl)}
        </span>
      </div>

      {/* Position */}
      <div className="flex flex-col justify-center px-3 py-1.5">
        <span className="text-[9px] font-semibold uppercase tracking-[0.22em] text-zinc-600">
          Pos
        </span>
        <span className={`font-mono text-sm font-semibold leading-tight tabular-nums ${posClass(pos)}`}>
          {pos > 0 ? `+${pos}` : pos}
        </span>
        <span className="mt-0.5 font-mono text-[9px] uppercase tracking-[0.14em] tabular-nums text-zinc-600">
          fills {agent.fills}
        </span>
      </div>

      {/* Slippage */}
      <div className="flex flex-col justify-center px-3 py-1.5">
        <span className="text-[9px] font-semibold uppercase tracking-[0.22em] text-zinc-600">
          Slip
        </span>
        <span className="font-mono text-sm font-semibold leading-tight tabular-nums text-zinc-300">
          {agent.avg_slippage.toFixed(2)}
        </span>
      </div>
    </div>
  );
}

/**
 * Compact leaderboard showing every active agent's PnL and position.
 * One row per agent, divider between rows, no shadows, no rounded corners.
 */
export function AgentLeaderboard({ agents }: Props) {
  const active = agents.filter((a) => a.enabled);

  if (active.length === 0) {
    return (
      <div className="flex items-center gap-2 border border-zinc-800 bg-black px-3 py-1.5 text-[10px] uppercase tracking-[0.18em] text-zinc-600">
        <span className="inline-block h-1.5 w-1.5 bg-zinc-700" />
        Agents · off
      </div>
    );
  }

  return (
    <div className="divide-y divide-zinc-800 border border-zinc-800 bg-black">
      {active.map((agent) => (
        <AgentRow key={agent.name} agent={agent} />
      ))}
    </div>
  );
}
