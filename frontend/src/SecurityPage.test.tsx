/** @vitest-environment jsdom */
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { SecurityPage } from "./SecurityPage";

let host: HTMLDivElement; let root: Root; const onError = vi.fn();
const response = (data: unknown, status = 200) => new Response(JSON.stringify({ data, detail: status >= 400 ? "保存被拒绝" : "", code: "0000", info: "" }), { status });
const policy = { enabled: true, mode: "audit", scan_unicode: true, scan_network: true, scan_tools: true, scan_response: false, redact_secrets: false, block_on_critical: true, fail_closed: true, capabilities: { stream_response_scan: false, binary_attachment_scan: false } };
const builtin = { id: "builtin-1", rule_id: "credential_test", name: "Credential", category: "credentials", severity: "high", action: "warn", enabled: 1, description: "Company detector" };
const custom = { id: "custom-1", name: "Company domain", pattern: "example\.com", category: "domain", severity: "medium", action: "warn", enabled: 1, description: "Company" };
const defaults = (path: string) => path.endsWith("/settings") ? { ...policy } : path.endsWith("/builtin") ? [builtin] : path.endsWith("/custom") ? [custom] : path.includes("/findings?") ? [{ id: "f", log_id: "log-1", title: "Detected credential", severity: "high", action: "redact", phase: "request", location: "$.password", evidence_masked: "[REDACTED]" }] : { id: "log-1", request_body: "[REDACTED]" };
const button = (name: string) => Array.from(host.querySelectorAll("button")).find(item => item.textContent?.trim() === name)!;
const tab = (name: string) => Array.from(host.querySelectorAll<HTMLButtonElement>('[role="tab"]')).find(item => item.textContent?.includes(name))!;
const labelControl = (name: string) => Array.from(host.querySelectorAll("label")).find(item => item.textContent?.startsWith(name))!.querySelector<HTMLInputElement | HTMLSelectElement>("input,select")!;
const setValue = async (control: HTMLInputElement | HTMLSelectElement, value: string) => act(async () => { const prototype = control instanceof HTMLSelectElement ? HTMLSelectElement.prototype : HTMLInputElement.prototype; Object.getOwnPropertyDescriptor(prototype, "value")!.set!.call(control, value); control.dispatchEvent(new Event(control instanceof HTMLSelectElement ? "change" : "input", { bubbles: true })); });
const submit = async (selector: string) => act(async () => host.querySelector<HTMLFormElement>(selector)!.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true })));
async function mount(fetcher: ReturnType<typeof vi.fn<(path: string, init?: RequestInit) => Promise<Response>>> = vi.fn((path: string, _init?: RequestInit) => Promise.resolve(response(defaults(path))))) { vi.stubGlobal("fetch", fetcher); await act(async () => root.render(<SecurityPage onError={onError} />)); return fetcher; }
beforeEach(() => { vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true); host = document.createElement("div"); document.body.append(host); root = createRoot(host); onError.mockReset(); });
afterEach(async () => { await act(async () => root.unmount()); host.remove(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });

it("keeps policy drafts across tabs and saves only changed settings", async () => {
  let current = { ...policy }; const fetcher = vi.fn((path: string, init?: RequestInit) => { if (path.endsWith("/settings") && init?.method === "PUT") current = { ...current, ...JSON.parse(init.body as string) }; return Promise.resolve(response(path.endsWith("/settings") ? current : defaults(path))); });
  await mount(fetcher); await act(async () => labelControl("密钥自动脱敏").click()); await act(async () => tab("内置规则").click());
  expect(host.textContent).toContain("1 项策略修改未保存"); await act(async () => button("保存安全策略").click());
  const saved = fetcher.mock.calls.find(([, init]) => init?.method === "PUT")!; expect(JSON.parse(saved[1]!.body as string)).toEqual({ redact_secrets: true }); expect(host.textContent).toContain("安全策略已保存");
});

it("retains policy edits when saving fails", async () => {
  await mount(vi.fn((path: string, init?: RequestInit) => Promise.resolve(init?.method === "PUT" ? response(null, 422) : response(defaults(path)))));
  await act(async () => labelControl("普通响应扫描").click()); expect(host.textContent).toContain("流式请求将在连接上游前被拒绝"); await submit("#security-policy-form");
  expect(onError).toHaveBeenCalledWith("保存被拒绝"); expect((labelControl("普通响应扫描") as HTMLInputElement).checked).toBe(true); expect(host.textContent).toContain("1 项策略修改未保存");
});

it("filters and paginates builtin rules without reloading settings", async () => {
  const rows = Array.from({ length: 12 }, (_, index) => ({ ...builtin, id: `builtin-${index}`, rule_id: `rule-${index}`, name: index === 11 ? "Special detector" : `Rule ${index}` }));
  const fetcher = await mount(vi.fn((path: string) => Promise.resolve(response(path.endsWith("/builtin") ? rows : defaults(path))))); await act(async () => tab("内置规则").click());
  expect(host.querySelectorAll(".security-table tbody tr")).toHaveLength(10); await act(async () => button("下一页").click()); expect(host.textContent).toContain("Special detector");
  await setValue(host.querySelector<HTMLInputElement>('[aria-label="搜索内置规则"]')!, "Special"); expect(host.querySelectorAll(".security-table tbody tr")).toHaveLength(1); expect(fetcher.mock.calls.filter(([path]) => path.endsWith("/settings"))).toHaveLength(1);
});

it("keeps a failed custom rule editor open and opens finding details", async () => {
  let failPost = true; const fetcher = await mount(vi.fn((path: string, init?: RequestInit) => Promise.resolve(failPost && init?.method === "POST" ? response(null, 422) : response(defaults(path)))));
  await act(async () => tab("自定义规则").click()); await act(async () => button("添加自定义规则").click()); await setValue(labelControl("规则名称"), "Retry"); await setValue(labelControl("匹配模式"), "private"); await submit(".security-rule-form"); expect(host.querySelector('[role="dialog"]')).not.toBeNull(); expect(host.textContent).toContain("规则未保存");
  failPost = false; await submit(".security-rule-form"); expect(host.querySelector('.security-rule-drawer')).toBeNull(); await act(async () => tab("安全发现").click()); await act(async () => button("查看请求").click()); expect(fetcher.mock.calls.some(([path]) => path === "/api/v1/logs/log-1")).toBe(true); expect(host.textContent).toContain("[REDACTED]");
});

it("saves editable builtin metadata without sending the detector", async () => {
  const fetcher = await mount(); await act(async () => tab("内置规则").click()); await act(async () => host.querySelector<HTMLButtonElement>('[aria-label="编辑 Credential"]')!.click()); await setValue(labelControl("规则名称"), "Company credential"); await setValue(labelControl("严重度"), "critical"); await submit(".security-rule-form");
  const call = fetcher.mock.calls.find(([path, init]) => path.endsWith("/builtin/builtin-1") && init?.method === "PUT")!; const body = JSON.parse(call[1]!.body as string); expect(body).toMatchObject({ name: "Company credential", severity: "critical" }); expect(body).not.toHaveProperty("pattern");
});
