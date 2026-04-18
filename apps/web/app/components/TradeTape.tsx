"use client";

import { useEffect, useRef, useState } from "react";

import type { Trade } from "../lib/types";

interface Props {
  trades: Trade[];
}

function fmtTs(t: number): string {
  // sim-time → "mm:ss.ms" relative to sim start
  const s = Math.floor(t);
  const ms = Math.floor((t - s) * 1000);
  const mm = Math.floor(s / 60)
    .toString()
    .padStart(2, "0");
  const ss = (s % 60).toString().padStart(2, "0");
  return `${mm}:${ss}.${ms.toString().padStart(3, "0")}`;
}

/**
 * Flashes any newly-arrived trade row for ~320ms. We key on ``seq`` so the
 * flash follows the row as older trades scroll down the tape.
 */
function useFreshSeqs(trades: Trade[]): Set<number> {
  const lastTopRef = useRef<number>(-1);
  const [fresh, setFresh] = useState<Set<number>>(new Set());

  useEffect(() => {
    if (trades.length === 0) return;
    const currentTop = trades[0].seq;
    if (currentTop === lastTopRef.current) return;

    const newSeqs = new Set<number>();
    for (const t of trades) {
      if (t.seq > lastTopRef.current) newSeqs.add(t.seq);
      else break;
    }
    lastTopRef.current = currentTop;
    if (newSeqs.size === 0) return;

    setFresh(newSeqs);
    const timer = window.setTimeout(() => setFresh(new Set()), 340);
    return () => window.clearTimeout(timer);
  }, [trades]);

  return fresh;
}

export function TradeTape({ trades }: Props) {
  const fresh = useFreshSeqs(trades);

  return (
    <section className="flex min-h-0 flex-col border border-zinc-800 bg-black">
      <header className="flex items-baseline justify-between border-b border-zinc-800 px-3 py-2">
        <h2 className="text-[10px] font-semibold uppercase tracking-[0.18em] text-zinc-500">
          Trade Tape
        </h2>
        <span className="font-mono text-[10px] tabular-nums text-zinc-600">{trades.length}</span>
      </header>

      <div className="grid grid-cols-[auto_auto_1fr_auto] gap-x-3 border-b border-zinc-800 px-3 py-1 text-[10px] uppercase tracking-[0.14em] text-zinc-600">
        <span>time</span>
        <span>side</span>
        <span className="text-right">price</span>
        <span className="text-right">qty</span>
      </div>

      <ul className="flex-1 overflow-hidden">
        {trades.length === 0 ? (
          <li className="px-3 py-2 text-[11px] text-zinc-600">waiting for fills…</li>
        ) : (
          trades.map((t) => {
            const buyerInit = t.taker_side === "bid";
            const dir = buyerInit ? "▲" : "▼";
            const sideColor = buyerInit ? "text-emerald-400" : "text-rose-400";
            const flashCls = fresh.has(t.seq)
              ? buyerInit
                ? "flash-up"
                : "flash-down"
              : "";
            return (
              <li
                key={t.seq}
                className={`grid grid-cols-[auto_auto_1fr_auto] gap-x-3 border-b border-zinc-900 px-3 py-0.5 font-mono text-xs tabular-nums ${flashCls}`}
              >
                <span className="text-zinc-500">{fmtTs(t.ts)}</span>
                <span className={sideColor}>{dir}</span>
                <span className={`${sideColor} text-right`}>{t.price.toLocaleString()}</span>
                <span className="text-right text-zinc-300">{t.qty}</span>
              </li>
            );
          })
        )}
      </ul>
    </section>
  );
}
