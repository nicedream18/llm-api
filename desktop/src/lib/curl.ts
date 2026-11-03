// ────────────────────────────────────────────────────────────────────────────
// curl 工具：构建（渠道 → curl）与解析（curl → 渠道表单字段）。
//
// 两个方向共用同一套 shell 词法：
//  - buildChannelCurl：把渠道配置渲染成可直接执行的 curl 命令（多行 `\` 续行），
//    用于渠道列表「复制测试 curl」。
//  - parseCurlCommand / parseCurlToChannel：把用户粘贴的 curl 命令还原为
//    method / URL / headers / body，再推导协议、Base URL、API Key 与模型，
//    用于新建渠道表单的「从 curl 导入」。
// ────────────────────────────────────────────────────────────────────────────

import type { ChannelProtocol, ChannelEndpoint } from "../types";

// ─── shell 词法：把命令串切成参数 token（处理引号 / $'...' / 续行符）──────

function tokenize(input: string): string[] {
  const tokens: string[] = [];
  let i = 0;
  const n = input.length;
  const escapeMap: Record<string, string> = { n: "\n", t: "\t", r: "\r", "'": "'", '"': '"', "\\": "\\" };
  while (i < n) {
    // 跳过空白（含续行符 \ + 换行）
    while (i < n && /\s/.test(input[i])) i++;
    if (i >= n) break;
    // 行尾续行符：跳过 `\` + 换行，继续视作空白
    if (input[i] === "\\" && input[i + 1] === "\n") { i += 2; continue; }
    let tok = "";
    while (i < n && !/[\s]/.test(input[i])) {
      const c = input[i];
      if (c === "'") {
        // 单引号：字面量，直到下一个 '
        i++;
        while (i < n && input[i] !== "'") tok += input[i++];
        i++; // 闭合引号
      } else if (c === '"') {
        // 双引号：支持 \" \\ 转义
        i++;
        while (i < n && input[i] !== '"') {
          if (input[i] === "\\" && i + 1 < n && (input[i + 1] === '"' || input[i + 1] === "\\")) {
            tok += input[i + 1];
            i += 2;
          } else {
            tok += input[i++];
          }
        }
        i++; // 闭合引号
      } else if (c === "$" && input[i + 1] === "'") {
        // $'...'：ANSI-C 引用，处理 \n \t 等转义
        i += 2;
        while (i < n && input[i] !== "'") {
          if (input[i] === "\\" && i + 1 < n) {
            tok += escapeMap[input[i + 1]] ?? input[i + 1];
            i += 2;
          } else {
            tok += input[i++];
          }
        }
        i++; // 闭合引号
      } else if (c === "\\" && i + 1 < n) {
        // 反斜杠转义单个字符
        tok += input[i + 1];
        i += 2;
      } else {
        tok += input[i++];
      }
    }
    tokens.push(tok);
  }
  return tokens;
}

// ─── curl 命令解析 ──────────────────────────────────────────────────────────

export interface ParsedCurl {
  method: string;
  url: string;
  headers: { name: string; value: string }[];
  body: string | null;
}

const VALUE_FLAGS = new Set([
  "-X", "--request", "-H", "--header", "-d", "--data", "--data-raw", "--data-binary",
  "--data-urlencode", "--json", "-u", "--user", "--url", "-F", "--form", "-o", "--output",
  "-A", "--user-agent", "-e", "--referer", "-b", "--cookie", "-m", "--max-time",
  "--connect-timeout", "--retry",
]);

/** 解析 curl 命令为结构化请求；非 curl 形态 / 缺 URL 返回 null。 */
export function parseCurlCommand(input: string): ParsedCurl | null {
  const trimmed = input.trim().replace(/^curl\b/i, "");
  if (!trimmed) return null;
  const tokens = tokenize(trimmed);
  let url = "";
  let method = "POST";
  const headers: { name: string; value: string }[] = [];
  const datas: string[] = [];
  for (let i = 0; i < tokens.length; i++) {
    const t = tokens[i];
    if (!t) continue;
    if (t === "--") continue;
    if (t.startsWith("-") && t.length > 1) {
      // 形如 -H'X: 1' 的粘连写法：flag 与值已被 tokenizer 合成一个 token，
      // 这里兜底按前缀拆开（如 "-HAuthorization: x"）。
      const shortAttached = t.match(/^-(X|H|d|u)$/) ? null : t.match(/^-(X|H|d)(.+)$/s);
      if (shortAttached) {
        const flag = `-${shortAttached[1]}`;
        const rest = shortAttached[2];
        if (flag === "-X") method = rest.toUpperCase();
        else if (flag === "-H") {
          const idx = rest.indexOf(":");
          if (idx > 0) headers.push({ name: rest.slice(0, idx).trim().toLowerCase(), value: rest.slice(idx + 1).trim() });
        } else datas.push(rest);
        continue;
      }
      if (t === "-X" || t === "--request") method = (tokens[++i] || "POST").toUpperCase();
      else if (t === "-H" || t === "--header") {
        const h = tokens[++i];
        if (h) {
          const idx = h.indexOf(":");
          if (idx > 0) headers.push({ name: h.slice(0, idx).trim().toLowerCase(), value: h.slice(idx + 1).trim() });
        }
      } else if (t === "--json") {
        const d = tokens[++i];
        if (d) { headers.push({ name: "content-type", value: "application/json" }); datas.push(d); }
      } else if (t === "-d" || t === "--data" || t === "--data-raw" || t === "--data-binary" || t === "--data-urlencode") {
        const d = tokens[++i];
        if (d) datas.push(d);
      } else if (t === "--url") {
        const u = tokens[++i];
        if (u && !url) url = u;
      } else if (VALUE_FLAGS.has(t)) {
        i++; // 消费掉参数值，忽略不关心的 flag
      }
      continue;
    }
    if (!url) url = t;
  }
  if (!url || !/^https?:\/\//i.test(url)) return null;
  return {
    method,
    url,
    headers,
    body: datas.length > 0 ? datas[datas.length - 1] : null,
  };
}

// ─── curl → 渠道表单字段 ────────────────────────────────────────────────────

export interface CurlChannelParseResult {
  protocol: ChannelProtocol;
  baseUrl: string;
  apiKey: string;
  model: string | null;
  endpoint: ChannelEndpoint | null;
}

// URL 路径后缀 → 协议 + 端点（顺序敏感：更长的前缀优先匹配）。
const ENDPOINT_SUFFIXES: [suffix: string, protocol: ChannelProtocol, endpoint: ChannelEndpoint][] = [
  ["/chat/completions", "openai", "chat_completions"],
  ["/responses", "openai", "responses"],
  ["/messages/count_tokens", "anthropic", "count_tokens"],
  ["/messages", "anthropic", "messages"],
  ["/api/chat", "ollama", "api_chat"],
];

/** 从 curl 命令推导渠道表单所需的协议 / Base URL / Key / 模型。无法解析返回 null。 */
export function parseCurlToChannel(input: string): CurlChannelParseResult | null {
  const parsed = parseCurlCommand(input);
  if (!parsed) return null;

  const headerMap = new Map(parsed.headers.map(h => [h.name, h.value]));
  const urlPath = parsed.url.split("?")[0].replace(/\/+$/, "");
  const lowerPath = urlPath.toLowerCase();

  // 1) 协议识别：先按路径后缀，再用鉴权头修正。
  let protocol: ChannelProtocol = "openai";
  let endpoint: ChannelEndpoint | null = null;
  for (const [suffix, proto, ep] of ENDPOINT_SUFFIXES) {
    if (lowerPath.endsWith(suffix)) { protocol = proto; endpoint = ep; break; }
  }
  if (protocol !== "ollama" && (headerMap.has("x-api-key") || headerMap.has("anthropic-version"))) {
    protocol = "anthropic";
  }

  // 2) Base URL：剥掉端点路径后缀（路径可能多段，如 /messages/count_tokens）。
  let baseUrl = urlPath;
  if (endpoint) {
    const matched = ENDPOINT_SUFFIXES.find(([s]) => lowerPath.endsWith(s));
    if (matched) baseUrl = urlPath.slice(0, urlPath.length - matched[0].length);
  }
  baseUrl = baseUrl.replace(/\/+$/, "");
  if (!baseUrl || !/^https?:\/\//i.test(baseUrl)) return null;

  // 3) API Key：x-api-key 优先，其次 Authorization: Bearer xxx。
  const xKey = headerMap.get("x-api-key");
  const authHeader = headerMap.get("authorization");
  const bearer = authHeader?.match(/^Bearer\s+(.+)$/i)?.[1]?.trim() ?? "";
  const apiKey = (xKey?.trim() || bearer) ?? "";

  // 4) 模型：body JSON 的 model 字段。
  let model: string | null = null;
  if (parsed.body) {
    try {
      const json = JSON.parse(parsed.body);
      if (typeof json?.model === "string" && json.model.trim()) model = json.model.trim();
    } catch { /* body 非 JSON 时忽略 */ }
  }

  return { protocol, baseUrl, apiKey, model, endpoint };
}

// ─── 渠道 → curl 命令 ───────────────────────────────────────────────────────

export interface ChannelCurlInput {
  protocol: string;
  baseUrl: string;
  models: string[];
  apiKey: string;
  extraHeaders?: { name: string; value: string }[];
}

const CURL_FALLBACK_MODELS: Record<string, string> = {
  openai: "gpt-4o-mini",
  anthropic: "claude-sonnet-4-5",
  ollama: "llama3",
};

/** 渠道配置 → 可直接执行的测试 curl（多行 `\` 续行，单引号安全转义）。 */
export function buildChannelCurl(opts: ChannelCurlInput): string {
  const proto = opts.protocol === "anthropic" ? "anthropic" : opts.protocol === "ollama" ? "ollama" : "openai";
  const base = opts.baseUrl.trim().replace(/\/+$/, "");
  const url = proto === "openai" ? `${base}/chat/completions`
    : proto === "anthropic" ? `${base}/messages`
    : `${base}/api/chat`;
  const model = opts.models[0] || CURL_FALLBACK_MODELS[proto];
  // shell 单引号转义：' → '\''
  const esc = (s: string) => s.replace(/'/g, `'\\''`);

  const lines: string[] = [`curl -X POST '${esc(url)}'`];
  lines.push(`  -H 'Content-Type: application/json'`);
  if (opts.apiKey) {
    if (proto === "anthropic") lines.push(`  -H 'x-api-key: ${esc(opts.apiKey)}'`);
    else lines.push(`  -H 'Authorization: Bearer ${esc(opts.apiKey)}'`);
  }
  if (proto === "anthropic") lines.push(`  -H 'anthropic-version: 2023-06-01'`);
  for (const h of opts.extraHeaders ?? []) {
    if (h.name.trim()) lines.push(`  -H '${esc(h.name)}: ${esc(h.value)}'`);
  }
  const message = { role: "user", content: "hi" };
  const body = proto === "anthropic"
    ? { model, max_tokens: 16, messages: [message] }
    : proto === "ollama"
      ? { model, messages: [message], stream: false }
      : { model, max_tokens: 16, messages: [message] };
  lines.push(`  -d '${esc(JSON.stringify(body))}'`);
  return lines.join(" \\\n");
}
