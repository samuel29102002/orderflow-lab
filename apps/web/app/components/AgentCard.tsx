"use client";

import type { AgentState } from "../lib/types";

interface Props {
  agent: AgentState | null;
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

function Cell({
  label,
  children,
  sub,
}: {
  label: string;
  children: React.ReactNode;
  sub?: React.ReactNode;
}) {
  return (
    <div className="flex flex-col justify-center px-4 py-1.5">
      <span className="text-[9px] font-semibold uppercase tracking-[0.22em] text-zinc-500">
        {label}
      </span>
      <span className="font-mono text-sm font-semibold leading-tight tabular-nums">
        {children}
      </span>
      {sub != null ? (
        <span className="mt-0.5 font-mono text-[9px] uppercase tracking-[0.14em] tabular-nums text-zinc-600">
          {sub}
        </span>
      ) : null}
    </div>
  );
}

/**
 * Live P&L card for the DeepLOB-driven trader. Grid-based layout with 1px
 * dividers between cells, no shadows, no rounded corners. Mono digits so
 * PnL numerals align as they tick.
 */
export function AgentCard({ agent }: Props) {
  if (agent == null || !agent.enabled) {
    return (
      <div className="flex items-center gap-2 border border-zinc-800 bg-black px-3 py-1.5 text-[10px] uppercase tracking-[0.18em] text-zinc-600">
        <span className="inline-block h-1.5 w-1.5 bg-zinc-700" />
        Agent · off
      </div>
    );
  }

  const total = agent.total_pnl;
  const totalCls = pnlClass(total);

  const position = agent.position;
  const posCls =
    position > 0
      ? "text-emerald-300"
      : position < 0
        ? "text-rose-300"
        : "text-zinc-400";

  const openLabel =
    agent.open_order_id != null && agent.open_order_side != null
      ? `${agent.open_order_side === "bid" ? "BID" : "ASK"} ${agent.open_order_price?.toLocaleString() ?? "—"} × ${agent.open_order_qty ?? 0}`
      : "—";

  return (
    <div className="grid grid-cols-3 divide-x divide-zinc-800 border border-zinc-800 bg-black">
      <Cell
        label="Agent PnL"
        sub={
          <>
            r:{fmtPnl(agent.realized_pnl)} · u:{fmtPnl(agent.unrealized_pnl)}
          </>
        }
      >
        <span className={totalCls}>{fmtPnl(total)}</span>
      </Cell>

      <Cell label="Pos" sub={`fills ${agent.fills} · qty ${agent.gross_qty}`}>
        <span className={posCls}>{position > 0 ? `+${position}` : position}</span>
      </Cell>

      <Cell
        label="Resting"
        sub={`cost ${agent.cost_basis > 0 ? agent.cost_basis.toFixed(2) : "—"}`}
      >
        <span className="text-zinc-200">{openLabel}</span>
      </Cell>
    </div>
  );
}
