/** @vitest-environment jsdom */
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { ProviderSyncPanel } from "./ProviderSyncPanel";

const state = {
  settings: { enabled: false, quota_interval: 300, models_interval: 21600 },
  snapshots: {
    quota: { fetched_at: null, error_code: "provider_error", payload: { status: "stale", windows: [
      { window: "daily", unit: "tokens", remaining: "500", limit: "1000", currency: null, reset_at: null },
      { window: "monthly", unit: "currency", remaining: "1.125", limit: "5", currency: "USD", reset_at: "2026-12-01" },
    ] } }, models: { payload: { models: ["model-a"] } },
  }, jobs: [{ id: "job", kind: "quota", status: "pending", attempts: 1 }],
};
const response = (data: unknown, status = 200) => new Response(JSON.stringify({ data, info: "拒绝访问" }), { status });
let root: Root;
let host: HTMLDivElement;
const onError = vi.fn();
beforeEach(() => { vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true); host = document.createElement("div"); document.body.appendChild(host); root = createRoot(host); onError.mockClear(); });
afterEach(async () => { await act(async () => root.unmount()); host.remove(); vi.unstubAllGlobals(); });
const button = (name: string) => Array.from(host.querySelectorAll("button")).find(item => item.textContent === name)!;
async function mount(fetcher: ReturnType<typeof vi.fn>) { vi.stubGlobal("fetch", fetcher); await act(async () => root.render(<ProviderSyncPanel accountId="a" onError={onError} onClose={() => {}} />)); }

it("renders separate quota windows, last-good warning, models and durable jobs", async () => {
  await mount(vi.fn().mockResolvedValue(response(state)));
  expect(host.textContent).toContain("配额：stale"); expect(host.textContent).toContain("保留上次有效快照");
  expect(host.querySelectorAll("tbody tr")).toHaveLength(2); expect(host.textContent).toContain("USD");
  expect(host.textContent).toContain("1.125"); expect(host.textContent).toContain("model-a"); expect(host.textContent).toContain("quota：pending");
  expect(host.querySelector<HTMLInputElement>('input[type="checkbox"]')!.checked).toBe(false);
});

it("enqueues manual synchronization and explicitly opts in to scheduling", async () => {
  const fetcher = vi.fn().mockImplementation(() => Promise.resolve(response(state)));
  await mount(fetcher);
  await act(async () => button("提交配额和模型同步").click());
  expect(fetcher).toHaveBeenCalledWith("/api/v1/providers/a/sync", expect.objectContaining({ method: "POST", body: "{}" }));
  expect(host.textContent).toContain("同步任务已提交");
  await act(async () => host.querySelector<HTMLInputElement>('input[type="checkbox"]')!.click());
  await act(async () => host.querySelector("form")!.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true })));
  expect(fetcher).toHaveBeenCalledWith("/api/v1/providers/a/sync/settings", expect.objectContaining({ method: "PUT", body: JSON.stringify({ enabled: true, quota_interval: 300, models_interval: 21600 }) }));
  expect(host.textContent).toContain("同步设置已保存");
});

it("reports rejected actions and permits retry", async () => {
  const fetcher = vi.fn().mockImplementation(() => Promise.resolve(response(state)));
  await mount(fetcher); fetcher.mockImplementationOnce(() => Promise.resolve(response(null, 403)));
  await act(async () => button("提交配额和模型同步").click());
  expect(onError).toHaveBeenCalledWith("拒绝访问"); expect(button("提交配额和模型同步").disabled).toBe(false);
});

it("ignores a late response after switching accounts", async () => {
  let resolveOld!: (value: Response) => void;
  const fetcher = vi.fn().mockImplementationOnce(() => new Promise<Response>(resolve => { resolveOld = resolve; })).mockResolvedValue(response({ ...state, snapshots: {} }));
  await mount(fetcher);
  await act(async () => root.render(<ProviderSyncPanel accountId="b" onError={onError} onClose={() => {}} />));
  await act(async () => resolveOld(response(state)));
  expect(host.textContent).not.toContain("model-a"); expect(host.textContent).toContain("配额：unknown");
});
