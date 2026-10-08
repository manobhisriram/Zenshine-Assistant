import { type FormEvent, type KeyboardEvent, useEffect, useRef, useState } from "react";
import { fetchConfig } from "./api";
import { Markdown } from "./markdown";
import type { ChatMessage, PublicConfig } from "./types";
import { useChat } from "./useChat";

const TOOL_LABEL: Record<string, string> = {
  calculate_quote: "Calculating your quote…",
  request_callback: "Submitting your callback request…",
};

function Bubble({ m, onRate }: { m: ChatMessage; onRate: (id: string, r: "up" | "down") => void }) {
  const [showSources, setShowSources] = useState(false);
  const isBot = m.role === "assistant";
  return (
    <div className={`row ${isBot ? "bot" : "user"}`}>
      <div className={`bubble ${m.status === "error" ? "bubble-error" : ""}`}>
        {m.content ? <Markdown text={m.content} /> : null}
        {m.status === "streaming" && !m.content && (
          <span className="typing" aria-label="Assistant is typing">
            <i /><i /><i />
          </span>
        )}
        {m.tool && <p className="tool">{TOOL_LABEL[m.tool] ?? "Working…"}</p>}
        {m.status === "stopped" && <p className="muted">Stopped.</p>}
        {isBot && m.status === "done" && (
          <div className="meta">
            <button className={`icon ${m.rating === "up" ? "on" : ""}`} aria-label="Helpful" onClick={() => onRate(m.id, "up")} disabled={!!m.rating}>👍</button>
            <button className={`icon ${m.rating === "down" ? "on" : ""}`} aria-label="Not helpful" onClick={() => onRate(m.id, "down")} disabled={!!m.rating}>👎</button>
            {!!m.sources?.length && (
              <button className="link" onClick={() => setShowSources((s) => !s)} aria-expanded={showSources}>
                {showSources ? "Hide" : "Show"} sources ({m.sources.length})
              </button>
            )}
          </div>
        )}
        {showSources && (
          <ul className="sources">
            {m.sources?.map((s) => (
              <li key={s.id}>{s.question}</li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

export default function App() {
  const [config, setConfig] = useState<PublicConfig | null>(null);
  const [configError, setConfigError] = useState(false);
  const chat = useChat(config?.contact.phone);
  const [draft, setDraft] = useState("");
  const endRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const max = config?.limits.max_message_chars ?? 1200;

  useEffect(() => {
    const c = new AbortController();
    fetchConfig(c.signal).then(setConfig).catch(() => !c.signal.aborted && setConfigError(true));
    return () => c.abort();
  }, []);

  useEffect(() => {
    endRef.current?.scrollIntoView?.({ behavior: "smooth", block: "end" });
  }, [chat.messages, chat.error]);

  const submit = (e?: FormEvent) => {
    e?.preventDefault();
    if (!draft.trim() || chat.busy) return;
    void chat.send(draft);
    setDraft("");
    inputRef.current?.focus();
  };
  const onKey = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      submit();
    }
  };

  const empty = chat.messages.length === 0;
  const phone = config?.contact.phone;

  return (
    <div className="app">
      <header className="header">
        <div className="logo" aria-hidden>✦</div>
        <div className="title">
          <h1>{config?.brand.name ?? "Assistant"}</h1>
          <p>{config?.brand.tagline ?? ""}</p>
        </div>
        {phone && (
          <a className="call" href={`tel:${phone.replace(/[^\d+]/g, "")}`}>
            Call us
          </a>
        )}
        {!empty && (
          <button className="ghost" onClick={chat.reset} aria-label="Start a new conversation">
            New chat
          </button>
        )}
      </header>

      <main className="thread" aria-live="polite" aria-busy={chat.busy}>
        {configError && empty && <div className="banner">We couldn't reach the assistant. Please try again shortly.</div>}
        {empty && config && (
          <section className="welcome">
            <h2>{config.ui.welcome_title}</h2>
            <p>{config.ui.welcome_body}</p>
            <div className="chips">
              {config.ui.suggestions.map((s) => (
                <button key={s} className="chip" onClick={() => void chat.send(s)} disabled={chat.busy}>
                  {s}
                </button>
              ))}
            </div>
          </section>
        )}
        {chat.messages.map((m) => (
          <Bubble key={m.id} m={m} onRate={chat.rate} />
        ))}
        {chat.error && (
          <div className="banner" role="alert">
            {chat.error}
          </div>
        )}
        <div ref={endRef} />
      </main>

      <form className="composer" onSubmit={submit}>
        <textarea
          ref={inputRef}
          value={draft}
          onChange={(e) => setDraft(e.target.value.slice(0, max))}
          onKeyDown={onKey}
          placeholder="Ask about services, pricing or bookings…"
          rows={1}
          aria-label="Message"
          maxLength={max}
        />
        {chat.busy ? (
          <button type="button" className="send stop" onClick={chat.stop} aria-label="Stop generating">■</button>
        ) : (
          <button type="submit" className="send" disabled={!draft.trim()} aria-label="Send message">➤</button>
        )}
      </form>
      <footer className="footer">{(config?.ui.disclaimer ?? "").replace("{phone}", phone ?? "our team")}</footer>
    </div>
  );
}
