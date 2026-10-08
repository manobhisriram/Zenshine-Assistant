import { readEvents } from "./sse";
import type { PublicConfig, StreamEvent } from "./types";

const BASE = (import.meta.env.VITE_API_BASE_URL as string | undefined)?.replace(/\/$/, "") ?? "";
const API_KEY = import.meta.env.VITE_API_KEY as string | undefined;
const TENANT = (import.meta.env.VITE_TENANT as string | undefined) || undefined;

export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
    public code: string,
    public retryAfter?: number,
  ) {
    super(message);
  }
}

function headers(): Record<string, string> {
  const h: Record<string, string> = { "Content-Type": "application/json" };
  if (API_KEY) h["X-API-Key"] = API_KEY;
  return h;
}

async function failure(res: Response): Promise<ApiError> {
  let code = "http_error";
  let message = "Something went wrong. Please try again.";
  try {
    const j = await res.json();
    code = j?.error?.code ?? code;
    message = j?.error?.message ?? message;
  } catch {
    /* non-JSON error body */
  }
  const retry = Number(res.headers.get("Retry-After"));
  return new ApiError(message, res.status, code, Number.isFinite(retry) && retry > 0 ? retry : undefined);
}

export async function fetchConfig(signal?: AbortSignal): Promise<PublicConfig> {
  const q = TENANT ? `?tenant=${encodeURIComponent(TENANT)}` : "";
  const res = await fetch(`${BASE}/v1/config${q}`, { signal });
  if (!res.ok) throw await failure(res);
  return res.json();
}

export async function* streamChat(
  message: string,
  sessionId: string | null,
  signal: AbortSignal,
): AsyncGenerator<StreamEvent> {
  const res = await fetch(`${BASE}/v1/chat/stream`, {
    method: "POST",
    headers: headers(),
    body: JSON.stringify({ message, session_id: sessionId ?? undefined, tenant: TENANT }),
    signal,
  });
  if (!res.ok || !res.body) throw await failure(res);
  yield* readEvents(res.body);
}

export async function sendFeedback(sessionId: string, messageId: string, rating: "up" | "down"): Promise<void> {
  await fetch(`${BASE}/v1/feedback`, {
    method: "POST",
    headers: headers(),
    body: JSON.stringify({ session_id: sessionId, message_id: messageId, rating }),
  }).catch(() => undefined);
}

export async function resetSession(sessionId: string): Promise<void> {
  await fetch(`${BASE}/v1/sessions/${encodeURIComponent(sessionId)}${TENANT ? `?tenant=${TENANT}` : ""}`, {
    method: "DELETE",
    headers: headers(),
  }).catch(() => undefined);
}
