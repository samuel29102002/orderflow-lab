"use client";

import { useState } from "react";

import { setGenerator } from "../lib/control";
import type {
  BookSnapshot,
  ConnectionStatus,
  GeneratorName,
  Hello,
} from "../lib/types";

interface Props {
  status: ConnectionStatus;
  hello: Hello | null;
  snapshot: BookSnapshot | null;
  framesPerSec: number;
  droppedConnections: number;
}

function statusTone(s: ConnectionStatus): { label: string; dot: string; text: string } {
  switch (s) {
    case "open":
      return { label: "LIVE", dot: "bg-emerald-400 text-emerald-400 shadow-dot", text: "text-emerald-300" };
    case "connecting":
      return { label: "CONNECTING", dot: "bg-amber-400 animate-pulse", text: "text-amber-300" };
    case "closed":
      return { label: "RECONNECTING", dot: "bg-rose-500 animate-pulse", text: "text-rose-300" };
    default:
      return { label: "IDLE", dot: "bg-zinc-600", text: "text-zinc-500" };
  }
}

const GEN_LABEL: Record<GeneratorName, string> = {
  poisson: "POISSON",
  hawkes: "HAWKES",
  queue_reactive: "QUEUE-R",
};

const GEN_TONE: Record<GeneratorName, string> = {
  poisson: "border-sky-500/60 text-sky-300",
  hawkes: "border-fuchsia-500/60 text-fuchsia-300",
  queue_reactive: "border-amber-500/60 text-amber-300",
};

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-baseline gap-1.5">
      <span className="text-[10px] uppercase tracking-[0.14em] text-zinc-600">{label}</span>
      <span className="font-mono text-xs tabular-nums text-zinc-200">{value}</span>
    </div>
  );
}

function GeneratorToggle({
  active,
  available,
  onSelect,
  pending,
}: {
  active: GeneratorName | null;
  available: GeneratorName[];
  onSelect: (name: GeneratorName) => void;
  pending: GeneratorName | null;
}) {
  return (
    <div className="flex items-center border border-zinc-800 bg-black">
      {available.map((name, i) => {
        const isActive = active === name;
        const isPending = pending === name;
        return (
          <button
            key={name}
            type="button"
            onClick={() => !isActive && onSelect(name)}
            disabled={isActive || isPending}
            className={[
              "px-2.5 py-1 text-[10px] font-semibold uppercase tracking-[0.18em] transition-colors",
              i > 0 ? "border-l border-zinc-800" : "",
              isActive
                ? `${GEN_TONE[name]} bg-zinc-950`
                : "text-zinc-500 hover:bg-zinc-950 hover:text-zinc-200",
              isPending ? "animate-pulse" : "",
            ].join(" ")}
            aria-pressed={isActive}
            title={`switch to ${GEN_LABEL[name]}`}
          >
            {GEN_LABEL[name]}
          </button>
        );
      })}
    </div>
  );
}

function fmt(v: number | undefined, d = 2): string {
  if (v == null) return "—";
  return Number.isInteger(v) ? String(v) : v.toFixed(d);
}

function ParamRow({
  generator,
  params,
}: {
  generator: GeneratorName | null;
  params: Record<string, number>;
}) {
  if (generator === "hawkes") {
    return (
      <>
        <Stat label="μ" value={fmt(params.mu_baseline, 1)} />
        <Stat label="α_self" value={fmt(params.alpha_self)} />
        <Stat label="α_cross" value={fmt(params.alpha_cross)} />
        <Stat label="β" value={fmt(params.beta)} />
      </>
    );
  }
  if (generator === "queue_reactive") {
    return (
      <>
        <Stat label="λ₀" value={fmt(params.base_lambda, 0)} />
        <Stat label="s₀" value={fmt(params.baseline_spread, 0)} />
        <Stat label="rate_s" value={fmt(params.rate_sens)} />
        <Stat label="off_s" value={fmt(params.offset_sens)} />
        <Stat label="imb_s" value={fmt(params.imbalance_sens)} />
      </>
    );
  }
  // poisson default
  return (
    <>
      <Stat label="λ" value={fmt(params.lambda, 0)} />
      <Stat label="κ" value={fmt(params.kappa)} />
      <Stat label="σ" value={fmt(params.sigma)} />
      <Stat label="seed" value={fmt(params.seed, 0)} />
    </>
  );
}

export function StatusBar({
  status,
  hello,
  snapshot,
  framesPerSec,
  droppedConnections,
}: Props) {
  const tone = statusTone(status);
  const generator = hello?.generator ?? null;
  const available = hello?.available_generators ?? [];
  const params = hello?.sim_params ?? {};
  const [pending, setPending] = useState<GeneratorName | null>(null);
  const [error, setError] = useState<string | null>(null);

  const onSelect = async (name: GeneratorName) => {
    setPending(name);
    setError(null);
    try {
      await setGenerator(name);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setPending(null);
    }
  };

  return (
    <header className="flex flex-wrap items-center gap-x-6 gap-y-2 border-b border-zinc-800 bg-black px-4 py-2">
      <div className="flex items-center gap-3">
        <span className={`inline-block h-2 w-2 ${tone.dot}`} aria-hidden />
        <h1 className="text-sm font-semibold tracking-tight">
          Orderflow <span className="text-zinc-500">Lab</span>
        </h1>
        <span className={`text-[10px] font-semibold uppercase tracking-[0.18em] ${tone.text}`}>
          {tone.label}
        </span>
        {generator && (
          <span
            className={`border px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-[0.14em] ${GEN_TONE[generator]} bg-black`}
            title="active flow generator"
          >
            {GEN_LABEL[generator]}
          </span>
        )}
      </div>

      <div className="flex flex-wrap items-center gap-x-5 gap-y-1">
        <Stat label="engine" value={hello?.engine_version ?? "—"} />
        <Stat label="tick" value={hello ? `${hello.tick_hz.toFixed(0)} Hz` : "—"} />
        <Stat label="frames/s" value={framesPerSec.toString()} />
        <Stat label="seq" value={snapshot?.seq != null ? snapshot.seq.toString() : "—"} />
        <Stat
          label="sim_t"
          value={snapshot?.sim_t != null ? `${snapshot.sim_t.toFixed(1)}s` : "—"}
        />
        <Stat label="resting" value={snapshot?.resting != null ? snapshot.resting.toString() : "—"} />
        {droppedConnections > 0 && (
          <Stat label="reconnects" value={droppedConnections.toString()} />
        )}
      </div>

      <div className="ml-auto flex flex-wrap items-center gap-x-4 gap-y-1 text-[11px]">
        <ParamRow generator={generator} params={params} />
        {available.length > 0 && (
          <GeneratorToggle
            active={generator}
            available={available}
            onSelect={onSelect}
            pending={pending}
          />
        )}
        {error && (
          <span className="text-[10px] text-rose-400" title={error}>
            switch failed
          </span>
        )}
      </div>
    </header>
  );
}
