// Thin client for the FastAPI control plane (generator hot-swap, etc.).

import { API_URL } from "./config";
import type { GeneratorName } from "./types";

export interface GeneratorResponse {
  generator: GeneratorName;
  available: GeneratorName[];
  sim_params: Record<string, number>;
}

export async function setGenerator(name: GeneratorName): Promise<GeneratorResponse> {
  const res = await fetch(`${API_URL}/control/generator`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name }),
  });
  if (!res.ok) {
    const detail = await res.text().catch(() => "");
    throw new Error(`setGenerator(${name}) failed: ${res.status} ${detail}`);
  }
  return (await res.json()) as GeneratorResponse;
}
