/** @vitest-environment jsdom */
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { SecurityPage } from "./SecurityPage";

let host: HTMLDivElement; let root: Root;
const onError = vi.fn();
const response = (data: unknown, status = 200) => new Response(JSON.stringify({ data, detail: status >= 400 ? "保存被拒绝" : "" }), { status });
const policy = { enabled: true, mode: "audit", scan_unicode: true, scan_network: true, scan_tools: true, scan_response: false, redact_secrets: false, block_on_critical: true, fail_closed: true, capabilities: { stream_response_scan: false, binary_attachment_scan: false } };
const builtin = { id: "builtin-1", rule_id: "credential_test", name: "Credential", category: "credentials", severity: "high", action: "warn", enabled: 1, description: "Company detector" };
const custom = { id: "custom-1", name: "Company domain", pattern: "example.com", category: "domain", severity: "medium", action: "allow", enabled: 1, rule_type: "whitelist", match_type: "literal", description: "Company" };
const button = (name: string) => Array.from(host.querySelectorAll("button")).find(item => item.textContent?.trim() === name)!;
const control = (name: string) => Array.from(host.querySelectorAll("label")).find(item => item.textContent?.startsWith(name))!.querySelector<HTMLInputElement | HTMLSelectElement>("input,select")!;
async function fill(name: string, value: string) { await act(async () => { const element = control(name); const prototype = element instanceof HTMLSelectElement ? HTMLSelectElement.prototype : HTMLInputElement.prototype; Object.getOwnPropertyDescriptor(prototype, "value")!.set!.call(element, value); element.dispatchEvent(new Event(element instanceof HTMLSelectElement ? "change" : "input", { bubbles: true })); }); }
const submit = async (selector: string) => act(async () => { host.querySelector(selector)!.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true })); });
const defaults = (path: string) => path.endsWith("/settings") ? { ...policy } : path.endsWith("/builtin") ? [builtin] : path.endsWith("/custom") ? [custom] : path.includes("/findings?") ? [{ id: "f", log_id: "log-1", title: "Detected credential", severity: "high", action: "redact", phase: "request", location: "$.password", evidence_masked: "[REDACTED]" }] : { id: "log-1", request_body: "[REDACTED]" };
async function mount(fetcher = vi.fn((path: string, _init?: RequestInit) => Promise.resolve(response(defaults(path))))) { vi.stubGlobal("fetch", fetcher); await act(async () => root.render(<SecurityPage onError={onError} />)); return fetcher; }
beforeEach(() => { vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true); host = document.createElement("div"); document.body.append(host); root = createRoot(host); onError.mockReset(); });
afterEach(async () => { await act(async () => root.unmount()); host.remove(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });

it("persists independent redaction, reloads settings and explains the streaming restriction", async () => {
  let current = { ...policy };
  const fetcher = vi.fn((path: string, init?: RequestInit) => {
    if (path.endsWith("/settings") && init?.method === "PUT") current = { ...current, ...JSON.parse(init.body as string) };
    return Promise.resolve(response(path.endsWith("/settings") ? current : defaults(path)));
  });
  await mount(fetcher);
  await act(async () => control("密钥自动脱敏").click());
  await act(async () => control("普通响应扫描").click());
  expect(host.textContent).toContain("流式请求将在连接上游前被拒绝");
  await submit("form");
  const saved = fetcher.mock.calls.find(([, init]) => init?.method === "PUT")!;
  expect(JSON.parse(saved[1]!.body as string)).toMatchObject({ redact_secrets: true, scan_response: true });
  expect(JSON.parse(saved[1]!.body as string)).not.toHaveProperty("capabilities");
  expect(host.textContent).toContain("安全策略已保存");
  expect((control("密钥自动脱敏") as HTMLInputElement).checked).toBe(true);
});

it("does not claim success when settings saving fails", async () => {
  await mount(vi.fn((path: string, init?: RequestInit) => Promise.resolve(init?.method === "PUT" ? response(null, 422) : response(defaults(path)))));
  await submit("form");
  expect(onError).toHaveBeenCalledWith("保存被拒绝");
  expect(host.textContent).not.toContain("安全策略已保存");
});

it("creates a whitelist with literal allow semantics", async () => {
  const fetcher = await mount();
  await act(async () => button("添加自定义规则").click());
  await fill("规则名称", "Safe API"); await fill("规则类型", "whitelist"); await fill("规则类别", "domain"); await fill("匹配模式", "api.example.com");
  expect((control("处置动作") as HTMLSelectElement).disabled).toBe(true);
  expect(host.querySelector('[value="regex"]')).toBeNull();
  await submit('[role="dialog"] form');
  const call = fetcher.mock.calls.find(([, init]) => init?.method === "POST")!;
  expect(JSON.parse(call[1]!.body as string)).toMatchObject({ rule_type: "whitelist", match_type: "literal", action: "allow", pattern: "api.example.com" });
  expect(host.querySelector('[role="dialog"]')).toBeNull();
});

it("edits builtin metadata without modifying detectors and confirms resets", async () => {
  const fetcher = await mount(); const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
  await act(async () => button("编辑 Credential").click());
  await fill("规则名称", "Company credential"); await fill("严重度", "critical");
  await submit('[role="dialog"] form');
  const call = fetcher.mock.calls.find(([path, init]) => path.endsWith("/builtin/builtin-1") && init?.method === "PUT")!;
  expect(JSON.parse(call[1]!.body as string)).toMatchObject({ name: "Company credential", severity: "critical" });
  expect(JSON.parse(call[1]!.body as string)).not.toHaveProperty("pattern");
  await act(async () => button("恢复默认规则").click());
  expect(fetcher.mock.calls.some(([path]) => path.endsWith("/reset"))).toBe(false);
  confirm.mockReturnValue(true); await act(async () => button("恢复默认规则").click());
  expect(fetcher.mock.calls.some(([path]) => path.endsWith("/reset"))).toBe(true);
});

it("partially toggles custom rules, confirms deletion and opens linked request logs", async () => {
  const fetcher = await mount(); vi.spyOn(window, "confirm").mockReturnValue(true);
  const row = Array.from(host.querySelectorAll("tr")).find(item => item.textContent?.includes("Company domain"))!;
  await act(async () => Array.from(row.querySelectorAll("button")).find(item => item.textContent === "停用")!.click());
  const toggle = fetcher.mock.calls.find(([path, init]) => path.endsWith("/custom/custom-1") && init?.method === "PUT")!;
  expect(JSON.parse(toggle[1]!.body as string)).toEqual({ enabled: 0 });
  await act(async () => button("删除 Company domain").click());
  expect(fetcher.mock.calls.some(([, init]) => init?.method === "DELETE")).toBe(true);
  await act(async () => button("查看请求").click());
  expect(fetcher.mock.calls.some(([path]) => path === "/api/v1/logs/log-1")).toBe(true);
  expect(host.querySelector('[role="dialog"]')?.textContent).toContain("[REDACTED]");
});

it("recovers from loading failure and keeps failed editors open", async () => {
  let failLoad = true;
  await mount(vi.fn((path: string, init?: RequestInit) => Promise.resolve(failLoad || init?.method === "POST" ? response(null, 503) : response(defaults(path)))));
  expect(host.textContent).toContain("保存被拒绝");
  failLoad = false; await act(async () => button("重试加载").click());
  await act(async () => button("添加自定义规则").click());
  await fill("规则名称", "Retry"); await fill("匹配模式", "private");
  await submit('[role="dialog"] form');
  expect(host.querySelector('[role="dialog"]')).not.toBeNull();
  expect(host.textContent).not.toContain("规则已保存");
});
