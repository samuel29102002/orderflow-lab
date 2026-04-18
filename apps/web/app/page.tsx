// Marketing / portfolio landing page — served at `/` by the Next.js App Router.
// The live dashboard lives at `/lab`.

import Link from "next/link";

import {
  ArchitectureSection,
  BenchmarksSection,
  HeroSection,
  MarketingFooter,
  MarketingHeader,
  StackSection,
} from "./components/Marketing";

export const metadata = {
  title: "Orderflow Lab — Rust matching engine · DeepLOB forecaster · Live trader",
  description:
    "A self-contained market-microstructure simulator: a 2M-ops/sec Rust matching engine, a PyTorch DeepLOB price-move classifier, and an Almgren-Chriss trading agent, all wired into one live WebSocket dashboard.",
};

export default function LandingPage() {
  return (
    <main className="min-h-screen bg-black text-[var(--foreground)]">
      <MarketingHeader />
      <HeroSection />
      <ArchitectureSection />
      <BenchmarksSection />
      <StackSection />
      <section className="border-t border-zinc-800 px-6 py-20 sm:px-10 md:px-16">
        <div className="mx-auto flex max-w-5xl flex-col items-center gap-6 text-center">
          <h2 className="text-2xl font-semibold tracking-tight sm:text-3xl">
            See the whole stack running in one tab.
          </h2>
          <p className="max-w-2xl text-sm leading-relaxed text-zinc-400">
            The Live Lab boots the Rust engine, attaches the Hawkes flow
            generator, warms up the DeepLOB forecaster, and starts the trading
            agent — then streams every frame over a single WebSocket.
          </p>
          <Link
            href="/lab"
            className="group flex items-center gap-3 border border-zinc-700 bg-black px-6 py-3 text-sm font-semibold uppercase tracking-[0.18em] text-zinc-100 transition-colors hover:border-sky-500 hover:text-sky-300"
          >
            Launch Live Lab
            <span className="font-mono text-zinc-500 transition-colors group-hover:text-sky-300">
              →
            </span>
          </Link>
        </div>
      </section>
      <MarketingFooter />
    </main>
  );
}
