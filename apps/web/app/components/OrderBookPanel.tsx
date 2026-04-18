"use client";

import { useEffect, useRef, useState } from "react";

import type { BookSnapshot, Level } from "../lib/types";

interface Props {
  snapshot: BookSnapshot | null;
  depth: number;
}

type FlashKind = "up" | "down" | null;

function fmtPrice(p: number): string {
  return p.toLocaleString("en-US");
}

function fmtQty(q: number): string {
  return q.toLocaleString("en-US");
}

/**
 * Tracks per-price qty deltas across snapshots and returns a Map<price,
 * flash> that components can read to tint rows whose qty moved up or down.
 * We key on price so the flash survives row reordering on reprice.
 */
function useLevelFlashes(levels: Level[] | undefined): Map<number, FlashKind> {
  const prevRef = useRef<Map<number, number>>(new Map());
  const [flashes, setFlashes] = useState<Map<number, FlashKind>>(new Map());

  useEffect(() => {
    if (!levels) return;
    const next = new Map<number, number>();
    const diff = new Map<number, FlashKind>();

    for (const lvl of levels) {
      next.set(lvl.price, lvl.qty);
      const prev = prevRef.current.get(lvl.price);
      if (prev === undefined) {
        // New level — a fresh bid/ask appearing counts as an "up" in size.
        diff.set(lvl.price, "up");
      } else if (lvl.qty > prev) {
        diff.set(lvl.price, "up");
      } else if (lvl.qty < prev) {
        diff.set(lvl.price, "down");
      }
    }

    prevRef.current = next;
    if (diff.size === 0) return;
    setFlashes(diff);
    // Clear after the animation runs so the next tick's flash can reuse
    // the same price (CSS animation must restart).
    const timer = window.setTimeout(() => setFlashes(new Map()), 340);
    return () => window.clearTimeout(timer);
  }, [levels]);

  return flashes;
}

function Row({
  level,
  maxQty,
  tone,
  flash,
}: {
  level: Level;
  maxQty: number;
  tone: "bid" | "ask";
  flash: FlashKind;
}) {
  const pct = maxQty > 0 ? Math.min(100, (level.qty / maxQty) * 100) : 0;
  const barColor = tone === "bid" ? "bg-emerald-500/10" : "bg-rose-500/10";
  const priceColor = tone === "bid" ? "text-emerald-300" : "text-rose-300";
  const origin = tone === "bid" ? "right-0" : "left-0";
  const flashCls = flash === "up" ? "flash-up" : flash === "down" ? "flash-down" : "";
  return (
    <div
      className={`relative grid grid-cols-[1fr_1fr] items-center px-3 py-0.5 font-mono text-xs tabular-nums ${flashCls}`}
    >
      <span
        aria-hidden
        className={`absolute top-0 bottom-0 ${origin} ${barColor}`}
        style={{ width: `${pct}%` }}
      />
      {tone === "bid" ? (
        <>
          <span className={`relative text-right ${priceColor}`}>{fmtPrice(level.price)}</span>
          <span className="relative text-right text-zinc-300">{fmtQty(level.qty)}</span>
        </>
      ) : (
        <>
          <span className="relative text-right text-zinc-300">{fmtQty(level.qty)}</span>
          <span className={`relative text-right ${priceColor}`}>{fmtPrice(level.price)}</span>
        </>
      )}
    </div>
  );
}

function Empty({ depth }: { depth: number }) {
  return (
    <div className="flex items-center justify-center py-2 text-[11px] text-zinc-600">
      waiting for {depth} levels…
    </div>
  );
}

export function OrderBookPanel({ snapshot, depth }: Props) {
  const bids = snapshot?.bids;
  const asks = snapshot?.asks;
  const bidFlashes = useLevelFlashes(bids);
  const askFlashes = useLevelFlashes(asks);

  const bidsList = bids ?? [];
  const asksList = asks ?? [];
  const maxQty = Math.max(
    1,
    ...bidsList.map((l) => l.qty),
    ...asksList.map((l) => l.qty),
  );

  // Render asks worst→best (top of column = deep ask, bottom = best ask)
  const asksRender = asksList.slice(0, depth).slice().reverse();
  const bidsRender = bidsList.slice(0, depth);

  const spread = snapshot?.spread ?? null;
  const mid = snapshot?.mid ?? null;

  return (
    <section className="flex min-h-0 flex-col border border-zinc-800 bg-black">
      <header className="flex items-baseline justify-between border-b border-zinc-800 px-3 py-2">
        <h2 className="text-[10px] font-semibold uppercase tracking-[0.18em] text-zinc-500">
          Order Book
        </h2>
        <span className="font-mono text-[10px] text-zinc-600 tabular-nums">top {depth}</span>
      </header>

      <div className="grid grid-cols-[1fr_1fr] border-b border-zinc-800 px-3 py-1 text-[10px] uppercase tracking-[0.14em] text-zinc-600">
        <span className="text-right">qty</span>
        <span className="text-right">ask</span>
      </div>

      <div className="flex flex-col">
        {asksRender.length > 0 ? (
          asksRender.map((l) => (
            <Row
              key={`a-${l.price}`}
              level={l}
              maxQty={maxQty}
              tone="ask"
              flash={askFlashes.get(l.price) ?? null}
            />
          ))
        ) : (
          <Empty depth={depth} />
        )}
      </div>

      <div className="flex items-center justify-between border-y border-zinc-800 bg-zinc-950 px-3 py-2 font-mono tabular-nums">
        <span className="text-[10px] uppercase tracking-[0.18em] text-zinc-500 font-sans">mid</span>
        <span className="text-sm font-semibold text-zinc-100">
          {mid != null ? mid.toFixed(1) : "—"}
        </span>
        <span className="text-[10px] uppercase tracking-[0.18em] text-zinc-500 font-sans">spread</span>
        <span className="text-xs text-amber-300">{spread ?? "—"}</span>
      </div>

      <div className="flex flex-col">
        {bidsRender.length > 0 ? (
          bidsRender.map((l) => (
            <Row
              key={`b-${l.price}`}
              level={l}
              maxQty={maxQty}
              tone="bid"
              flash={bidFlashes.get(l.price) ?? null}
            />
          ))
        ) : (
          <Empty depth={depth} />
        )}
      </div>

      <div className="grid grid-cols-[1fr_1fr] border-t border-zinc-800 px-3 py-1 text-[10px] uppercase tracking-[0.14em] text-zinc-600">
        <span className="text-right">bid</span>
        <span className="text-right">qty</span>
      </div>
    </section>
  );
}
