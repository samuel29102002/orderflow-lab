"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";

import { AgentLeaderboard } from "../components/AgentLeaderboard";
import { CommandPalette } from "../components/CommandPalette";
import { ExecutionSidebar } from "../components/ExecutionSidebar";
import type { CommandResult } from "../components/CommandPalette";
import { OrderBookPanel } from "../components/OrderBookPanel";
import { PriceChart } from "../components/PriceChart";
import { StatusBar } from "../components/StatusBar";
import { TradeTape } from "../components/TradeTape";
import { useOrderflowStream } from "../hooks/useOrderflowStream";

const TOAST_DURATION_MS = 3500;

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

  const [toast, setToast] = useState<CommandResult | null>(null);
  const toastTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const handleCommandResult = useCallback((result: CommandResult) => {
    if (toastTimer.current) clearTimeout(toastTimer.current);
    setToast(result);
    toastTimer.current = setTimeout(() => setToast(null), TOAST_DURATION_MS);
  }, []);

  // Clean up timer on unmount
  useEffect(() => {
    return () => {
      if (toastTimer.current) clearTimeout(toastTimer.current);
    };
  }, []);

  return (
    <main className="flex h-screen w-screen flex-col overflow-hidden bg-black text-[var(--foreground)]">
      <CommandPalette onResult={handleCommandResult} />

      {/* Command palette toast */}
      {toast && (
        <div
          className={[
            "fixed bottom-8 left-1/2 z-40 -translate-x-1/2",
            "border font-mono text-xs px-4 py-2",
            toast.ok
              ? "border-emerald-800 bg-black text-emerald-300"
              : "border-rose-800 bg-black text-rose-300",
          ].join(" ")}
          role="status"
          aria-live="polite"
        >
          {toast.ok ? "ok" : "err"} {toast.message}
        </div>
      )}

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

      <div className="flex min-h-0 flex-1">
        <div className="grid min-h-0 flex-1 grid-cols-[320px_minmax(0,1fr)_320px] gap-px bg-zinc-800">
          <OrderBookPanel snapshot={snapshot} depth={depth} />
          <PriceChart series={priceSeries} forecast={forecast} />
          <TradeTape trades={trades} />
        </div>
        <ExecutionSidebar agents={agents} />
      </div>

      <footer className="border-t border-zinc-800 bg-black px-4 py-1.5 text-[10px] uppercase tracking-[0.18em] text-zinc-600">
        Rust engine · PyO3 bridge · FastAPI WS · Next.js 15 · Tailwind v4
      </footer>
    </main>
  );
}
