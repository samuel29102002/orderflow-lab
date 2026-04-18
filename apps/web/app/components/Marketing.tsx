// Server components powering the landing page at `/`. Kept in one file so
// the marketing surface is easy to scan and restyle in one pass.

import Link from "next/link";

export function MarketingHeader() {
  return (
    <header className="sticky top-0 z-10 flex items-center justify-between border-b border-zinc-800 bg-black/80 px-6 py-3 backdrop-blur-md sm:px-10 md:px-16">
      <Link href="/" className="flex items-center gap-2.5">
        <span className="inline-block h-2 w-2 bg-emerald-400 shadow-dot text-emerald-400" aria-hidden />
        <span className="text-sm font-semibold tracking-tight">
          Orderflow <span className="text-zinc-500">Lab</span>
        </span>
      </Link>
      <nav className="flex items-center gap-6 text-[10px] uppercase tracking-[0.18em]">
        <a href="#architecture" className="text-zinc-500 transition-colors hover:text-zinc-200">
          Architecture
        </a>
        <a href="#benchmarks" className="text-zinc-500 transition-colors hover:text-zinc-200">
          Benchmarks
        </a>
        <a href="#stack" className="text-zinc-500 transition-colors hover:text-zinc-200">
          Stack
        </a>
        <Link
          href="/lab"
          className="border border-zinc-700 px-3 py-1.5 font-semibold text-zinc-200 transition-colors hover:border-sky-500 hover:text-sky-300"
        >
          Live Lab →
        </Link>
      </nav>
    </header>
  );
}

export function HeroSection() {
  return (
    <section className="relative overflow-hidden border-b border-zinc-800">
      {/* Grid-lattice background cue, intentionally quiet. */}
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0 opacity-[0.06]"
        style={{
          backgroundImage:
            "linear-gradient(to right, #3f3f46 1px, transparent 1px), linear-gradient(to bottom, #3f3f46 1px, transparent 1px)",
          backgroundSize: "56px 56px",
        }}
      />
      <div className="relative mx-auto flex max-w-5xl flex-col items-start gap-8 px-6 py-24 sm:px-10 md:px-16 md:py-32">
        <span className="border border-zinc-800 px-2.5 py-1 text-[10px] uppercase tracking-[0.22em] text-zinc-400">
          Market Microstructure · Execution · Deep Learning
        </span>
        <h1 className="text-4xl font-semibold leading-[1.05] tracking-tight sm:text-5xl md:text-6xl">
          A self-contained
          <br />
          <span className="text-zinc-400">limit-order-book lab</span>
          <br />
          that actually trades.
        </h1>
        <p className="max-w-2xl text-base leading-relaxed text-zinc-400 sm:text-lg">
          A 2M-ops/sec Rust matching engine, a PyTorch DeepLOB price-move
          classifier, and an Almgren-Chriss trading agent — stitched together
          into one live WebSocket firehose and rendered in a terminal-grade
          dashboard.
        </p>
        <div className="flex flex-wrap items-center gap-3 pt-2">
          <Link
            href="/lab"
            className="group flex items-center gap-2 border border-zinc-100 bg-zinc-100 px-5 py-2.5 text-sm font-semibold uppercase tracking-[0.18em] text-black transition-colors hover:border-sky-400 hover:bg-sky-400"
          >
            Launch Live Lab
            <span className="font-mono transition-transform group-hover:translate-x-0.5">→</span>
          </Link>
          <a
            href="#architecture"
            className="border border-zinc-800 px-5 py-2.5 text-sm font-semibold uppercase tracking-[0.18em] text-zinc-300 transition-colors hover:border-zinc-600 hover:text-zinc-100"
          >
            How it works
          </a>
        </div>
      </div>
    </section>
  );
}

function ArchCard({
  index,
  title,
  subtitle,
  body,
  metrics,
}: {
  index: string;
  title: string;
  subtitle: string;
  body: string;
  metrics: { label: string; value: string }[];
}) {
  return (
    <article className="grid grid-rows-[auto_1fr_auto] gap-6 border border-zinc-800 bg-black p-6">
      <header className="flex items-baseline justify-between">
        <span className="font-mono text-[10px] uppercase tracking-[0.22em] text-zinc-600">
          {index}
        </span>
        <span className="text-[10px] uppercase tracking-[0.18em] text-zinc-500">
          {subtitle}
        </span>
      </header>
      <div className="flex flex-col gap-3">
        <h3 className="text-xl font-semibold tracking-tight text-zinc-100">{title}</h3>
        <p className="text-sm leading-relaxed text-zinc-400">{body}</p>
      </div>
      <dl className="grid grid-cols-2 divide-x divide-zinc-800 border-t border-zinc-800 pt-4">
        {metrics.map((m) => (
          <div key={m.label} className="flex flex-col gap-1 px-3 first:pl-0">
            <dt className="text-[10px] uppercase tracking-[0.18em] text-zinc-600">{m.label}</dt>
            <dd className="font-mono text-sm font-semibold tabular-nums text-zinc-100">
              {m.value}
            </dd>
          </div>
        ))}
      </dl>
    </article>
  );
}

export function ArchitectureSection() {
  return (
    <section id="architecture" className="border-b border-zinc-800 px-6 py-24 sm:px-10 md:px-16">
      <div className="mx-auto max-w-6xl">
        <div className="mb-14 flex items-baseline justify-between border-b border-zinc-800 pb-4">
          <div className="flex items-baseline gap-4">
            <span className="font-mono text-[10px] uppercase tracking-[0.22em] text-zinc-600">
              01
            </span>
            <h2 className="text-2xl font-semibold tracking-tight sm:text-3xl">
              System Architecture
            </h2>
          </div>
          <span className="hidden text-[10px] uppercase tracking-[0.18em] text-zinc-500 sm:block">
            Engine · Model · Agent
          </span>
        </div>

        <div className="grid grid-cols-1 gap-px bg-zinc-800 md:grid-cols-3">
          <ArchCard
            index="01"
            subtitle="Matching Engine"
            title="Rust core with PyO3 bindings"
            body="Price-time priority book over BTreeMap<Price, VecDeque<Order>>. Every submit, cancel, and modify round-trips through PyO3 into Python without copies. L2 depth, resident-order inspection, and fill attribution via maker_id are all first-class."
            metrics={[
              { label: "Throughput", value: "2M ops/s" },
              { label: "Tests", value: "22 passing" },
            ]}
          />
          <ArchCard
            index="02"
            subtitle="DeepLOB Forecaster"
            title="CNN + GRU classifier"
            body="Three convolutional stages collapse the 40-feature LOB row into a single channel, then a GRU(32) reads a 50-step window. Three-class head: down / flat / up over a ten-step horizon. Trained on Hawkes-generated data with class-weighted cross-entropy."
            metrics={[
              { label: "Params", value: "13.7k" },
              { label: "CPU inference", value: "0.6 ms" },
            ]}
          />
          <ArchCard
            index="03"
            subtitle="Execution Agent"
            title="DeepLOB-signal trader"
            body="Joins best bid/ask on high-conviction forecasts. Asymmetric Almgren-Chriss sizing — the clip shrinks as |pos| grows but stays full-size when reducing. VWAP cost basis, flip-through-zero handling, and live realised + unrealised P&L."
            metrics={[
              { label: "Risk control", value: "γ = 1.5" },
              { label: "Reserved IDs", value: "≥ 1e9" },
            ]}
          />
        </div>
      </div>
    </section>
  );
}

function BenchCell({
  label,
  value,
  unit,
  sub,
}: {
  label: string;
  value: string;
  unit: string;
  sub: string;
}) {
  return (
    <div className="flex flex-col gap-3 border border-zinc-800 bg-black p-6">
      <span className="text-[10px] uppercase tracking-[0.22em] text-zinc-500">{label}</span>
      <div className="flex items-baseline gap-2">
        <span className="font-mono text-4xl font-semibold tabular-nums text-zinc-100">
          {value}
        </span>
        <span className="font-mono text-xs uppercase tracking-[0.18em] text-zinc-500">
          {unit}
        </span>
      </div>
      <span className="text-[11px] leading-relaxed text-zinc-500">{sub}</span>
    </div>
  );
}

export function BenchmarksSection() {
  return (
    <section id="benchmarks" className="border-b border-zinc-800 bg-black px-6 py-24 sm:px-10 md:px-16">
      <div className="mx-auto max-w-6xl">
        <div className="mb-14 flex items-baseline justify-between border-b border-zinc-800 pb-4">
          <div className="flex items-baseline gap-4">
            <span className="font-mono text-[10px] uppercase tracking-[0.22em] text-zinc-600">
              02
            </span>
            <h2 className="text-2xl font-semibold tracking-tight sm:text-3xl">
              Performance
            </h2>
          </div>
          <span className="hidden text-[10px] uppercase tracking-[0.18em] text-zinc-500 sm:block">
            Benchmarks · Coverage · Latency
          </span>
        </div>

        <div className="grid grid-cols-2 gap-px bg-zinc-800 md:grid-cols-4">
          <BenchCell
            label="Engine throughput"
            value="2.0M"
            unit="ops / sec"
            sub="Submit + match on M2 laptop, single core, release build."
          />
          <BenchCell
            label="Data collection"
            value="688×"
            unit="real-time"
            sub="30 sim-minutes of Hawkes flow + labels produced in 2.6 s."
          />
          <BenchCell
            label="Forecast latency"
            value="0.6"
            unit="ms / tick"
            sub="CPU inference on a 50 × 40 window; no GPU required."
          />
          <BenchCell
            label="Broadcast rate"
            value="20"
            unit="Hz"
            sub="Per-client bounded queue; slowest client drops oldest frame."
          />
        </div>

        <p className="mt-8 max-w-3xl text-sm leading-relaxed text-zinc-500">
          Every metric above is reproducible from the repo — no external data
          feed, no paid infra, and no GPU. The whole pipeline fits on a single
          laptop and boots in under a minute.
        </p>
      </div>
    </section>
  );
}

function StackRow({
  layer,
  tech,
  role,
}: {
  layer: string;
  tech: string;
  role: string;
}) {
  return (
    <div className="grid grid-cols-[120px_1fr_2fr] items-baseline gap-6 border-b border-zinc-800 px-1 py-4 last:border-b-0">
      <span className="text-[10px] uppercase tracking-[0.22em] text-zinc-600">{layer}</span>
      <span className="font-mono text-sm font-semibold tabular-nums text-zinc-100">{tech}</span>
      <span className="text-sm leading-relaxed text-zinc-400">{role}</span>
    </div>
  );
}

export function StackSection() {
  return (
    <section id="stack" className="border-b border-zinc-800 px-6 py-24 sm:px-10 md:px-16">
      <div className="mx-auto max-w-5xl">
        <div className="mb-14 flex items-baseline justify-between border-b border-zinc-800 pb-4">
          <div className="flex items-baseline gap-4">
            <span className="font-mono text-[10px] uppercase tracking-[0.22em] text-zinc-600">
              03
            </span>
            <h2 className="text-2xl font-semibold tracking-tight sm:text-3xl">Stack</h2>
          </div>
          <span className="hidden text-[10px] uppercase tracking-[0.18em] text-zinc-500 sm:block">
            One repo · four runtimes
          </span>
        </div>

        <div className="border border-zinc-800 bg-black px-5 py-3">
          <StackRow
            layer="Engine"
            tech="Rust 2024 · maturin · PyO3"
            role="Matching book, flow generators, deterministic replay."
          />
          <StackRow
            layer="Gateway"
            tech="FastAPI · asyncio · uvicorn"
            role="Tick loop, pub-sub broadcaster, agent driver, REST control plane."
          />
          <StackRow
            layer="ML"
            tech="PyTorch 2 · pandas · parquet"
            role="DeepLOB CNN+GRU classifier trained on self-generated Hawkes data."
          />
          <StackRow
            layer="Client"
            tech="Next.js 15 · Tailwind v4 · lightweight-charts"
            role="WebSocket firehose, ring-buffered state, terminal-style UI."
          />
        </div>
      </div>
    </section>
  );
}

export function MarketingFooter() {
  return (
    <footer className="border-t border-zinc-800 bg-black px-6 py-8 sm:px-10 md:px-16">
      <div className="mx-auto flex max-w-6xl flex-col items-start justify-between gap-4 text-[10px] uppercase tracking-[0.18em] text-zinc-600 sm:flex-row sm:items-center">
        <span>Orderflow Lab · Built solo · No affiliations</span>
        <span className="font-mono text-zinc-700">
          Rust · PyO3 · FastAPI · PyTorch · Next.js 15
        </span>
      </div>
    </footer>
  );
}
