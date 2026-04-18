"use client";

import Link from "next/link";

import { AgentLeaderboard } from "../components/AgentLeaderboard";
import { OrderBookPanel } from "../components/OrderBookPanel";
import { PriceChart } from "../components/PriceChart";
import { StatusBar } from "../components/StatusBar";
import { TradeTape } from "../components/TradeTape";
import { useOrderflowStream } from "../hooks/useOrderflowStream";

export default function LabPage() {
  const {
    status,
    hello,
    snapshot,
    trades,
    priceSeries,
    forecast,
    agents,
    framesPerSec,
    droppedConnections,
  } = useOrderflowStream();

  const depth = hello?.depth_levels ?? 10;

  return (
    <main className="flex h-screen w-screen flex-col overflow-hidden bg-black text-[var(--foreground)]">
      <StatusBar
        status={status}
        hello={hello}
        snapshot={snapshot}
        framesPerSec={framesPerSec}
        droppedConnections={droppedConnections}
      />

      <div className="flex items-center justify-between border-b border-zinc-800 bg-black px-4 py-1.5">
        <div className="flex items-center gap-3">
          <Link
            href="/"
            className="text-[10px] uppercase tracking-[0.18em] text-zinc-600 transition-colors hover:text-zinc-300"
          >
            ← Home
          </Link>
          <span className="text-[10px] font-semibold uppercase tracking-[0.22em] text-zinc-500">
            DeepLOB Trader
          </span>
          <Link
            href="/analytics"
            className="text-[10px] uppercase tracking-[0.18em] text-zinc-600 transition-colors hover:text-zinc-300"
          >
            Analytics →
          </Link>
        </div>
        <AgentLeaderboard agents={agents} />
      </div>

      <div className="grid min-h-0 flex-1 grid-cols-[320px_minmax(0,1fr)_320px] gap-px bg-zinc-800">
        <OrderBookPanel snapshot={snapshot} depth={depth} />
        <PriceChart series={priceSeries} forecast={forecast} />
        <TradeTape trades={trades} />
      </div>

      <footer className="border-t border-zinc-800 bg-black px-4 py-1.5 text-[10px] uppercase tracking-[0.18em] text-zinc-600">
        Rust engine · PyO3 bridge · FastAPI WS · Next.js 15 · Tailwind v4
      </footer>
    </main>
  );
}
