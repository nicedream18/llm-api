/** @vitest-environment jsdom */
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { ProviderManager } from "./ProviderManager";

const account = { id: "a1", provider: "codex", name: "Work account", status: "active", priority: 1, enabled: true, tags: ["work"], group_name: "Team", auth_status: "active", health_status: "healthy" };
const payload = (data: unknown, status = 200) => new Response(JSON.stringify({ data, info: status >= 400 ? "拒绝访问" : "", code: status >= 400 ? "error" : "0000" }), { status });
let root: Root;
let host: HTMLDivElement;
const onError = vi.fn();
beforeEach(() => {
  vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true);
  host = document.createElement("div"); document.body.appendChild(host); root = createRoot(host); onError.mockClear();
});
afterEach(async () => { await act(async () => root.unmount()); host.remove(); vi.unstubAllGlobals(); });
const button = (name: string) => Array.from(host.querySelectorAll("button")).find(item => item.textContent === name)!;
async function mount(fetcher: ReturnType<typeof vi.fn>) { vi.stubGlobal("fetch", fetcher); await act(async () => { root.render(<ProviderManager onError={onError} />); }); }

it("shows independent account states and requests server-side next page", async () => {
  const fetcher = vi.fn().mockImplementation(() => Promise.resolve(payload({ items: [account], total: 26, limit: 25, offset: 0 })));
  await mount(fetcher);
  expect(host.textContent).toContain("Work account"); expect(host.textContent).toContain("已启用 · active · healthy");
  await act(async () => button("下一页").click());
  expect(fetcher).toHaveBeenLastCalledWith(expect.stringContaining("offset=25"), expect.anything());
  await act(async () => host.querySelector("form")!.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true })));
  expect(fetcher).toHaveBeenLastCalledWith(expect.stringContaining("offset=0"), expect.anything());
});

it("reports bulk partial failures and clears selection after refresh", async () => {
  const fetcher = vi.fn((path: string) => Promise.resolve(path.endsWith("/bulk") ? payload({ results: [{ id: "a1", success: true }, { id: "missing", success: false, error: "not_found" }] }) : payload({ items: [account], total: 1, limit: 25, offset: 0 })));
  await mount(fetcher);
  expect(button("批量停用").disabled).toBe(true);
  await act(async () => host.querySelector<HTMLInputElement>('input[aria-label="选择 Work account"]')!.click());
  await act(async () => button("批量停用").click());
  expect(fetcher).toHaveBeenCalledWith("/api/v1/providers/bulk", expect.objectContaining({ body: JSON.stringify({ account_ids: ["a1"], operation: "enabled", enabled: false }) }));
  expect(host.textContent).toContain("成功 1 项，失败 1 项"); expect(button("批量停用").disabled).toBe(true);
});

it("cancels archive without a write and restores archived accounts explicitly", async () => {
  const confirm = vi.fn().mockReturnValue(false); vi.spyOn(window, "confirm").mockImplementation(confirm);
  const fetcher = vi.fn().mockImplementation(() => Promise.resolve(payload({ items: [account], total: 1, limit: 25, offset: 0 })));
  await mount(fetcher);
  await act(async () => button("归档").click());
  expect(confirm).toHaveBeenCalledOnce(); expect(fetcher).toHaveBeenCalledTimes(1);
  fetcher.mockImplementation(() => Promise.resolve(payload({ items: [{ ...account, archived_at: "2026-11-02", enabled: false }], total: 1, limit: 25, offset: 0 })));
  await act(async () => button("刷新").click());
  expect(button("恢复（需重新授权）")).toBeDefined();
  await act(async () => button("恢复（需重新授权）").click());
  expect(fetcher).toHaveBeenCalledWith("/api/v1/providers/a1/operations", expect.objectContaining({ body: JSON.stringify({ operation: "restore" }) }));
  vi.restoreAllMocks();
});

it("surfaces permission errors and provides a retry", async () => {
  const fetcher = vi.fn().mockImplementationOnce(() => Promise.resolve(payload(null, 403))).mockImplementation(() => Promise.resolve(payload({ items: [], total: 0, limit: 25, offset: 0 })));
  await mount(fetcher); expect(onError).toHaveBeenCalledWith("拒绝访问");
  await act(async () => button("刷新").click()); expect(host.textContent).toContain("没有符合条件的账号");
});

it("edits through structured inputs, retaining unknown connection settings", async () => {
  const existing = { ...account, client_config: { client_id: "public", timeout_seconds: 25 }, model_mapping: { chat: "upstream" } };
  const fetcher = vi.fn((path: string, init?: RequestInit) => Promise.resolve(payload(path.includes("/accounts?") ? { items: [existing], total: 1, limit: 25, offset: 0 } : init?.method === "PUT" ? existing : {})));
  await mount(fetcher); await act(async () => button("编辑").click());
  await act(async () => host.querySelector("form.provider-form")!.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true })));
  expect(fetcher).toHaveBeenCalledWith("/api/v1/providers/a1", expect.objectContaining({ method: "PUT", body: expect.stringContaining('"timeout_seconds":25') }));
  expect(host.textContent).toContain("账号与分组标签已保存");
});
