import { Fragment, type ReactNode } from "react";

/**
 * Tiny, dependency-free renderer for the subset the assistant uses: paragraphs, bullet/numbered lists,
 * **bold**, `code` and http(s)/tel/mailto links. It builds React elements (never raw HTML), so model
 * output cannot inject markup or script.
 */
const INLINE = /(\*\*[^*]+\*\*|`[^`]+`|https?:\/\/[^\s)<]+|\bmailto:[^\s)<]+|\+\d[\d ()-]{7,}\d)/g;

function safeHref(token: string): string | null {
  if (/^https?:\/\//i.test(token) || /^mailto:/i.test(token)) return token;
  if (/^\+\d/.test(token)) return `tel:${token.replace(/[^\d+]/g, "")}`;
  return null;
}

export function renderInline(text: string): ReactNode[] {
  const parts = text.split(INLINE);
  return parts.map((part, i) => {
    if (!part) return null;
    if (part.startsWith("**") && part.endsWith("**")) return <strong key={i}>{part.slice(2, -2)}</strong>;
    if (part.startsWith("`") && part.endsWith("`")) return <code key={i}>{part.slice(1, -1)}</code>;
    const href = safeHref(part);
    if (href) {
      return (
        <a key={i} href={href} target="_blank" rel="noopener noreferrer nofollow">
          {part}
        </a>
      );
    }
    return <Fragment key={i}>{part}</Fragment>;
  });
}

export function Markdown({ text }: { text: string }) {
  const blocks: ReactNode[] = [];
  const lines = text.replace(/\r\n/g, "\n").split("\n");
  let list: { ordered: boolean; items: string[] } | null = null;
  let para: string[] = [];

  const flushPara = () => {
    if (para.length) blocks.push(<p key={blocks.length}>{renderInline(para.join(" "))}</p>);
    para = [];
  };
  const flushList = () => {
    if (!list) return;
    const Tag = list.ordered ? "ol" : "ul";
    blocks.push(
      <Tag key={blocks.length}>
        {list.items.map((it, i) => (
          <li key={i}>{renderInline(it)}</li>
        ))}
      </Tag>,
    );
    list = null;
  };

  for (const raw of lines) {
    const line = raw.trimEnd();
    const bullet = /^\s*[-*•]\s+(.*)$/.exec(line);
    const numbered = /^\s*\d+[.)]\s+(.*)$/.exec(line);
    if (bullet || numbered) {
      flushPara();
      const ordered = !!numbered;
      if (list && list.ordered !== ordered) flushList();
      list ??= { ordered, items: [] };
      list.items.push((bullet ?? numbered)![1]);
    } else if (!line.trim()) {
      flushPara();
      flushList();
    } else {
      flushList();
      para.push(line.trim());
    }
  }
  flushPara();
  flushList();
  return <>{blocks}</>;
}
