import type { ReactNode } from "react";

type InlineToken = { kind: "text" | "code" | "strong" | "em" | "link" | "image"; value: string; target?: string };

function inlineTokens(source: string): InlineToken[] {
  const pattern = /(!?)\[([^\]]*)\]\(([^\s)]+)(?:\s+"[^"]*")?\)|\*\*([^*]+)\*\*|`([^`]+)`|\*([^*]+)\*/g;
  const tokens: InlineToken[] = [];
  let cursor = 0;
  for (const match of source.matchAll(pattern)) {
    const index = match.index ?? 0;
    if (index > cursor) tokens.push({ kind: "text", value: source.slice(cursor, index) });
    if (match[2] !== undefined) {
      tokens.push({ kind: match[1] ? "image" : "link", value: match[2], target: match[3] });
    } else if (match[4] !== undefined) tokens.push({ kind: "strong", value: match[4] });
    else if (match[5] !== undefined) tokens.push({ kind: "code", value: match[5] });
    else if (match[6] !== undefined) tokens.push({ kind: "em", value: match[6] });
    cursor = index + match[0].length;
  }
  if (cursor < source.length) tokens.push({ kind: "text", value: source.slice(cursor) });
  return tokens;
}

function safeLink(target: string, attachmentPrefix: string): boolean {
  if (target.startsWith(attachmentPrefix) && /^[A-Za-z0-9-]+$/.test(target.slice(attachmentPrefix.length))) return true;
  try {
    const url = new URL(target);
    return url.protocol === "https:" || url.protocol === "http:" || url.protocol === "mailto:";
  } catch {
    return false;
  }
}

function inline(source: string, attachmentPrefix: string): ReactNode[] {
  return inlineTokens(source).map((token, index) => {
    if (token.kind === "code") return <code key={index}>{token.value}</code>;
    if (token.kind === "strong") return <strong key={index}>{token.value}</strong>;
    if (token.kind === "em") return <em key={index}>{token.value}</em>;
    if (token.kind === "link" && token.target && safeLink(token.target, attachmentPrefix)) {
      const external = /^https?:/i.test(token.target);
      return <a key={index} href={token.target} {...(external ? { target: "_blank", rel: "noopener noreferrer" } : {})}>{token.value}</a>;
    }
    if (token.kind === "image" && token.target?.startsWith(attachmentPrefix) && !token.target.startsWith("//")) {
      return <img key={index} src={token.target} alt={token.value} loading="lazy" />;
    }
    return <span key={index}>{token.value}</span>;
  });
}

export function renderWikiMarkdown(source: string, attachmentPrefix: string): ReactNode {
  const lines = source.split(/\r?\n/);
  const blocks: ReactNode[] = [];
  let index = 0;
  while (index < lines.length) {
    const line = lines[index];
    if (!line.trim()) { index += 1; continue; }
    const fence = line.match(/^```\s*([\w-]*)\s*$/);
    if (fence) {
      const code: string[] = [];
      index += 1;
      while (index < lines.length && !/^```\s*$/.test(lines[index])) code.push(lines[index++]);
      if (index < lines.length) index += 1;
      blocks.push(<pre key={`block-${blocks.length}`}><code className={fence[1] ? `language-${fence[1]}` : undefined}>{code.join("\n")}</code></pre>);
      continue;
    }
    const heading = line.match(/^(#{1,6})\s+(.+)$/);
    if (heading) {
      const level = heading[1].length;
      const children = inline(heading[2], attachmentPrefix);
      const key = `block-${blocks.length}`;
      if (level === 1) blocks.push(<h1 key={key}>{children}</h1>);
      else if (level === 2) blocks.push(<h2 key={key}>{children}</h2>);
      else if (level === 3) blocks.push(<h3 key={key}>{children}</h3>);
      else if (level === 4) blocks.push(<h4 key={key}>{children}</h4>);
      else if (level === 5) blocks.push(<h5 key={key}>{children}</h5>);
      else blocks.push(<h6 key={key}>{children}</h6>);
      index += 1;
      continue;
    }
    if (/^\s*[-*]\s+/.test(line)) {
      const items: ReactNode[] = [];
      while (index < lines.length && /^\s*[-*]\s+/.test(lines[index])) {
        items.push(<li key={`item-${items.length}`}>{inline(lines[index].replace(/^\s*[-*]\s+/, ""), attachmentPrefix)}</li>);
        index += 1;
      }
      blocks.push(<ul key={`block-${blocks.length}`}>{items}</ul>);
      continue;
    }
    const paragraph = [line];
    index += 1;
    while (index < lines.length && lines[index].trim() && !/^(#{1,6})\s+/.test(lines[index]) && !/^```/.test(lines[index]) && !/^\s*[-*]\s+/.test(lines[index])) paragraph.push(lines[index++]);
    blocks.push(<p key={`block-${blocks.length}`}>{paragraph.map((part, lineIndex) => <span key={lineIndex}>{lineIndex > 0 && <br />}{inline(part, attachmentPrefix)}</span>)}</p>);
  }
  return <div className="wiki-markdown">{blocks}</div>;
}
