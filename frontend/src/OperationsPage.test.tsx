/** @vitest-environment jsdom */
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { OperationsPage } from "./OperationsPage";

let root: Root; let host: HTMLDivElement;
const onError = vi.fn();
const report = { start: "2026-11-01T00:00:00Z", end: "2026-11-02T00:00:00Z", timezone: "Asia/Shanghai", group_by: "day", items: [{ group: "2026-11-01", requests: 3, errors: 1, attempts: 4, total_tokens: 50, unknown_usage: 1, estimated_usage: 2, unknown_price: 1, costs: { USD: "0.125", EUR: "0.02" }, latency_p50: 50, latency_p95: 100, latency_p99: 100, first_token_p95: 25 }] };
const response = (data: unknown, status = 200) => new Response(JSON.stringify({ data, info: "权限不足" }), { status });
const button = (name: string) => Array.from(host.querySelectorAll("button")).find(item => item.textContent === name)!;
beforeEach(() => { vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true); host = document.createElement("div"); document.body.appendChild(host); root = createRoot(host); onError.mockClear(); });
afterEach(async () => { await act(async () => root.unmount()); host.remove(); vi.unstubAllGlobals(); });
async function mount(fetcher: ReturnType<typeof vi.fn>) { vi.stubGlobal("fetch", fetcher); await act(async () => root.render(<OperationsPage onError={onError} />)); }

it("renders separate currencies and unknown counters and drills into the selected date", async () => {
  const fetcher = vi.fn((path: string) => Promise.resolve(response(path.includes("/analytics?") ? report : path.includes("/events/query?") ? { total: 1, items: [{ id: "one", request_id: "trace", kind: "attempt", outcome: "failed", total_tokens: null, usage_source: "unknown", pricing_status: "missing_price", cost: null }] } : [])));
  await mount(fetcher);
  expect(host.textContent).toContain("USD 0.125；EUR 0.02"); expect(host.textContent).toContain("1 / 2 / 1"); expect(host.textContent).toContain("50 / 100 / 100 ms");
  await act(async () => button("查看明细 2026-11-01").click());
  expect(fetcher).toHaveBeenCalledWith(expect.stringContaining("/events/query?"), expect.objectContaining({ body: expect.stringContaining('"bucket":"2026-11-01"') }));
  expect(host.textContent).toContain("trace"); expect(host.textContent).toContain("missing_price");
});

it("acknowledges alerts and requires explicit rule creation", async () => {
  const fetcher = vi.fn((path: string, _init?: RequestInit) => Promise.resolve(response(path.includes("/analytics?") ? report : path === "/api/v1/operations/alerts" ? [{ id: "alert", message: "Failure rate high", severity: "warning", status: "open" }] : [])));
  await mount(fetcher);
  expect(fetcher.mock.calls.every(call => !(call[1] as RequestInit | undefined)?.method)).toBe(true);
  await act(async () => button("确认告警").click());
  expect(fetcher).toHaveBeenCalledWith("/api/v1/operations/alerts/alert/acknowledge", expect.objectContaining({ method: "POST" }));
  await act(async () => host.querySelectorAll("form")[1]!.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true })));
  expect(fetcher).toHaveBeenCalledWith("/api/v1/operations/alerts/rules/failure-rate", expect.objectContaining({ method: "PUT" }));
  expect(host.textContent).toContain("告警规则已保存并启用");
});

it("reports authorization errors without rendering fabricated statistics", async () => {
  const fetcher = vi.fn((path: string) => Promise.resolve(path.includes("/analytics?") ? response(null, 403) : response([])));
  await mount(fetcher); expect(onError).toHaveBeenCalledWith("权限不足"); expect(host.querySelectorAll("tbody tr")).toHaveLength(0);
  expect(button("查询统计").disabled).toBe(false);
});
