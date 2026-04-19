"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { API_URL } from "../lib/config";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface CommandResult {
  ok: boolean;
  message: string;
}

interface Command {
  id: string;
  label: string;
  description: string;
  run: () => Promise<CommandResult>;
}

interface Props {
  onResult: (result: CommandResult) => void;
}

// ---------------------------------------------------------------------------
// API helpers
// ---------------------------------------------------------------------------

async function switchGenerator(type: "hawkes" | "poisson"): Promise<CommandResult> {
  const res = await fetch(`${API_URL}/sim/generator`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ type }),
  });
  if (!res.ok) {
    const detail = await res.text().catch(() => "");
    return { ok: false, message: `switch failed: ${res.status} ${detail}` };
  }
  return { ok: true, message: `generator switched to ${type.toUpperCase()}` };
}

async function clearDb(): Promise<CommandResult> {
  // Try POST first; fall back to DELETE if the backend uses that verb.
  const res = await fetch(`${API_URL}/analytics/clear`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
  });
  if (!res.ok) {
    const detail = await res.text().catch(() => "");
    return { ok: false, message: `clear-db failed: ${res.status} ${detail}` };
  }
  return { ok: true, message: "analytics database cleared" };
}

async function exportParquet(): Promise<CommandResult> {
  const res = await fetch(`${API_URL}/analytics/export`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
  });
  if (!res.ok) {
    const detail = await res.text().catch(() => "");
    return { ok: false, message: `export failed: ${res.status} ${detail}` };
  }
  let path = "";
  try {
    const json = await res.json();
    path = json.path ?? json.file ?? JSON.stringify(json);
  } catch {
    path = "(no path returned)";
  }
  return { ok: true, message: `exported → ${path}` };
}

// ---------------------------------------------------------------------------
// Commands registry
// ---------------------------------------------------------------------------

function buildCommands(): Command[] {
  return [
    {
      id: "switch-hawkes",
      label: "/switch hawkes",
      description: "set generator to Hawkes process",
      run: () => switchGenerator("hawkes"),
    },
    {
      id: "switch-poisson",
      label: "/switch poisson",
      description: "set generator to Poisson process",
      run: () => switchGenerator("poisson"),
    },
    {
      id: "clear-db",
      label: "/clear-db",
      description: "delete all analytics data",
      run: clearDb,
    },
    {
      id: "export-parquet",
      label: "/export-parquet",
      description: "export analytics to parquet file",
      run: exportParquet,
    },
  ];
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function CommandPalette({ onResult }: Props) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState(0);
  const [running, setRunning] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const commands = buildCommands();

  const filtered = query.trim()
    ? commands.filter(
        (c) =>
          c.label.toLowerCase().includes(query.toLowerCase()) ||
          c.description.toLowerCase().includes(query.toLowerCase()),
      )
    : commands;

  // Clamp selection when filtered list changes
  useEffect(() => {
    setSelected((s) => Math.min(s, Math.max(filtered.length - 1, 0)));
  }, [filtered.length]);

  // CMD+K / Ctrl+K open/close
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === "k") {
        e.preventDefault();
        setOpen((prev) => {
          if (!prev) {
            setQuery("");
            setSelected(0);
          }
          return !prev;
        });
      }
      if (e.key === "Escape") {
        setOpen(false);
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, []);

  // Focus input when palette opens
  useEffect(() => {
    if (open) {
      // Next tick so the element is mounted
      requestAnimationFrame(() => inputRef.current?.focus());
    }
  }, [open]);

  const execute = useCallback(
    async (cmd: Command) => {
      if (running) return;
      setRunning(true);
      setOpen(false);
      try {
        const result = await cmd.run();
        onResult(result);
      } catch (err) {
        onResult({
          ok: false,
          message: err instanceof Error ? err.message : String(err),
        });
      } finally {
        setRunning(false);
        setQuery("");
        setSelected(0);
      }
    },
    [running, onResult],
  );

  const onKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setSelected((s) => Math.min(s + 1, filtered.length - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setSelected((s) => Math.max(s - 1, 0));
    } else if (e.key === "Enter") {
      e.preventDefault();
      const cmd = filtered[selected];
      if (cmd) void execute(cmd);
    } else if (e.key === "Escape") {
      setOpen(false);
    }
  };

  if (!open) return null;

  return (
    // Backdrop
    <div
      className="fixed inset-0 z-50 bg-black/80"
      onMouseDown={(e) => {
        // Close when clicking outside the panel
        if (e.target === e.currentTarget) setOpen(false);
      }}
    >
      {/* Panel */}
      <div className="mx-auto mt-[20vh] w-[600px] border border-zinc-800 bg-[#000000]">
        {/* Input row */}
        <div className="flex items-center border-b border-zinc-800 px-3">
          <span className="mr-2 font-mono text-xs text-zinc-600">{">"}</span>
          <input
            ref={inputRef}
            type="text"
            value={query}
            onChange={(e) => {
              setQuery(e.target.value);
              setSelected(0);
            }}
            onKeyDown={onKeyDown}
            placeholder="type a command…"
            spellCheck={false}
            autoCorrect="off"
            autoCapitalize="off"
            className="w-full bg-transparent py-3 font-mono text-sm text-zinc-100 placeholder-zinc-600 outline-none"
          />
          <span className="ml-2 font-mono text-[10px] text-zinc-700">ESC</span>
        </div>

        {/* Results list */}
        {filtered.length > 0 ? (
          <ul role="listbox" className="max-h-60 overflow-y-auto py-1">
            {filtered.map((cmd, i) => (
              <li
                key={cmd.id}
                role="option"
                aria-selected={i === selected}
                onMouseEnter={() => setSelected(i)}
                onMouseDown={(e) => {
                  e.preventDefault();
                  void execute(cmd);
                }}
                className={[
                  "flex cursor-pointer items-baseline gap-3 px-3 py-2 transition-colors",
                  i === selected ? "bg-zinc-900" : "bg-transparent",
                ].join(" ")}
              >
                <span className="font-mono text-sm text-zinc-100">{cmd.label}</span>
                <span className="font-mono text-xs text-zinc-500">{cmd.description}</span>
              </li>
            ))}
          </ul>
        ) : (
          <div className="px-3 py-3 font-mono text-xs text-zinc-600">no commands match</div>
        )}

        {/* Footer hint */}
        <div className="flex items-center gap-4 border-t border-zinc-800 px-3 py-1.5">
          <span className="font-mono text-[10px] text-zinc-700">↑↓ navigate</span>
          <span className="font-mono text-[10px] text-zinc-700">↵ run</span>
          <span className="ml-auto font-mono text-[10px] text-zinc-700">⌘K toggle</span>
        </div>
      </div>
    </div>
  );
}
