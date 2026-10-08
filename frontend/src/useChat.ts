import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, resetSession, sendFeedback, streamChat } from "./api";
import type { ChatMessage } from "./types";

const SESSION_KEY = "zs.session";
const uid = () => (globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random()}`).replace(/-/g, "");

function loadSession(): string | null {
  try {
    return sessionStorage.getItem(SESSION_KEY);
  } catch {
    return null;
  }
}
function saveSession(id: string | null) {
  try {
    if (id) sessionStorage.setItem(SESSION_KEY, id);
    else sessionStorage.removeItem(SESSION_KEY);
  } catch {
    /* storage unavailable (private mode) */
  }
}

function friendly(err: unknown, phone?: string): string {
  if (err instanceof ApiError) {
    if (err.status === 429) return `You're sending messages quickly. Please wait ${err.retryAfter ?? 30}s and try again.`;
    if (err.status === 503) return `The assistant is temporarily unavailable.${phone ? ` Please call ${phone}.` : ""}`;
    return err.message;
  }
  return `Connection problem. Please check your network and try again.${phone ? ` Or call ${phone}.` : ""}`;
}

export function useChat(phone?: string) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const session = useRef<string | null>(loadSession());
  const abort = useRef<AbortController | null>(null);

  useEffect(() => () => abort.current?.abort(), []);

  const patch = useCallback((id: string, fn: (m: ChatMessage) => ChatMessage) => {
    setMessages((all) => all.map((m) => (m.id === id ? fn(m) : m)));
  }, []);

  const send = useCallback(
    async (text: string) => {
      const content = text.trim();
      if (!content || busy) return;
      setError(null);
      setBusy(true);
      const botId = uid();
      setMessages((all) => [
        ...all,
        { id: uid(), role: "user", content },
        { id: botId, role: "assistant", content: "", status: "streaming" },
      ]);
      const controller = new AbortController();
      abort.current = controller;
      try {
        for await (const ev of streamChat(content, session.current, controller.signal)) {
          switch (ev.event) {
            case "meta":
              session.current = ev.data.session_id;
              saveSession(ev.data.session_id);
              patch(botId, (m) => ({ ...m, messageId: ev.data.message_id }));
              break;
            case "delta":
              patch(botId, (m) => ({ ...m, content: m.content + ev.data.text, tool: null }));
              break;
            case "tool":
              patch(botId, (m) => ({ ...m, tool: ev.data.status === "running" ? ev.data.name : null }));
              break;
            case "sources":
              patch(botId, (m) => ({ ...m, sources: ev.data.sources }));
              break;
            case "done":
              patch(botId, (m) => ({ ...m, status: "done", tool: null }));
              break;
            case "error":
              patch(botId, (m) => ({ ...m, status: "error", tool: null }));
              setError(ev.data.message);
              break;
          }
        }
        patch(botId, (m) => (m.status === "streaming" ? { ...m, status: m.content ? "done" : "error" } : m));
      } catch (err) {
        if (controller.signal.aborted) {
          patch(botId, (m) => ({ ...m, status: "stopped", tool: null }));
        } else {
          patch(botId, (m) => ({ ...m, status: "error", tool: null }));
          setError(friendly(err, phone));
        }
      } finally {
        abort.current = null;
        setBusy(false);
      }
    },
    [busy, patch, phone],
  );

  const stop = useCallback(() => abort.current?.abort(), []);

  const rate = useCallback(
    (id: string, rating: "up" | "down") => {
      const msg = messages.find((m) => m.id === id);
      if (!msg?.messageId || !session.current || msg.rating) return;
      patch(id, (m) => ({ ...m, rating }));
      void sendFeedback(session.current, msg.messageId, rating);
    },
    [messages, patch],
  );

  const reset = useCallback(() => {
    abort.current?.abort();
    if (session.current) void resetSession(session.current);
    session.current = null;
    saveSession(null);
    setMessages([]);
    setError(null);
  }, []);

  return { messages, busy, error, send, stop, rate, reset };
}
