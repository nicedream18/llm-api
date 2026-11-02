/** @vitest-environment jsdom */
import { act, type ReactNode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { DashboardPage } from "./DashboardPage";
import { RequestChart } from "./RequestChart";
import { KnowledgePage } from "./KnowledgePage";
import { SoftwarePage } from "./SoftwarePage";
import { McpManager } from "./McpManager";
import { WikiManager } from "./WikiManager";

let host: HTMLDivElement; let root: Root;
const onError = vi.fn();
const response = (data: unknown, status = 200) => new Response(JSON.stringify({ data, info: status >= 400 ? "服务暂不可用" : "" }), { status });
const button = (name: string) => Array.from(host.querySelectorAll("button")).find(item => item.textContent?.trim() === name)!;
const control = (label: string) => Array.from(host.querySelectorAll("label")).find(item => item.textContent?.startsWith(label))!.querySelector<HTMLInputElement | HTMLTextAreaElement>("input,textarea")!;
async function input(element: HTMLInputElement | HTMLTextAreaElement, value: string) {
  await act(async () => {
    const prototype = element instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
    Object.getOwnPropertyDescriptor(prototype, "value")!.set!.call(element, value);
    element.dispatchEvent(new Event("input", { bubbles: true }));
  });
}
async function mount(element: ReactNode, fetcher: ReturnType<typeof vi.fn> = vi.fn(() => Promise.resolve(response([])))) {
  vi.stubGlobal("fetch", fetcher); await act(async () => root.render(element)); return fetcher;
}
beforeEach(() => { vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true); host = document.createElement("div"); document.body.append(host); root = createRoot(host); onError.mockClear(); });
afterEach(async () => { await act(async () => root.unmount()); host.remove(); vi.unstubAllGlobals(); vi.restoreAllMocks(); vi.useRealTimers(); window.location.hash = ""; });

const stats = { total_requests: 20, total_tokens: 30500, total_errors: 2, avg_duration_ms: 123.5 };
const dashboardData = (path: string) => path === "/api/v1/dashboard" ? stats : path.includes("/analytics?") ? { items: [{ group: "2026-11-02", requests: 20, errors: 2 }] }
  : path === "/api/v1/channels" ? [{ id: "c", name: "Primary", type: "openai", status: 1, models: ["chat"] }]
  : path.includes("/logs?") ? [{ id: "success", status_code: 200 }, { id: "failure", model: "chat", status_code: 429, error_message: "限流" }]
  : [{ id: "approval", tool_id: "deploy", principal_id: "reviewer", created_at: "2026-11-02" }];

it("dashboard labels cumulative metrics honestly and links to actionable failures and approvals", async () => {
  const fetcher = vi.fn((path: string) => Promise.resolve(response(dashboardData(path))));
  await mount(<DashboardPage onError={onError} />, fetcher);
  expect(host.querySelector(".metric-grid")?.textContent).toContain("10.0%");
  expect(host.querySelector(".metric-grid")?.textContent).toContain("124");
  expect(host.textContent).toContain("当前保留日志累计");
  expect(host.textContent).toContain("最近 20 条请求记录中的错误");
  expect(host.querySelectorAll(".chart-bars li")).toHaveLength(7);
  expect(host.textContent).toContain("HTTP 429"); expect(host.textContent).toContain("deploy");
  expect(host.querySelector('a[href="#/software?view=approvals"]')).not.toBeNull();
  expect(host.textContent).toContain("启用状态不代表连接测试结果");
  const query = new URL(fetcher.mock.calls.find(([path]) => path.includes("analytics?"))![0], "http://test").searchParams;
  expect(query.get("timezone")).toBe("UTC"); expect(query.get("group_by")).toBe("day");
  const start = new Date(query.get("start")!); const end = new Date(query.get("end")!);
  expect(start.getUTCHours()).toBe(0); expect(end.getTime() - start.getTime()).toBeGreaterThanOrEqual(6 * 86400000);
  expect(end.getTime() - start.getTime()).toBeLessThan(7 * 86400000);
});

it("dashboard shows onboarding and undefined rates for no requests", async () => {
  await mount(<DashboardPage onError={onError} />, vi.fn((path: string) => Promise.resolve(response(path === "/api/v1/dashboard" ? { ...stats, total_requests: 0, total_tokens: 0, total_errors: 0 } : path.includes("analytics?") ? { items: [] } : []))));
  expect(host.textContent).toContain("完成三个步骤"); expect(host.querySelector(".metric-grid")?.textContent).not.toContain("NaN");
  expect(host.querySelectorAll(".onboarding-panel li")).toHaveLength(3);
  expect(host.querySelector(".metric-grid")?.textContent).toContain("—");
  expect(host.textContent).toContain("该范围没有请求数据");
});

it("dashboard separates loading and a partial failure and retries that section", async () => {
  let finish!: (value: Response) => void; let attempts = 0;
  const fetcher = vi.fn((path: string) => path === "/api/v1/dashboard" ? new Promise<Response>(resolve => { finish = resolve; })
    : Promise.resolve(path.includes("analytics?") && ++attempts === 1 ? response(null, 503) : response(dashboardData(path))));
  await mount(<DashboardPage onError={onError} />, fetcher);
  expect(host.querySelector(".metric-grid")?.getAttribute("aria-busy")).toBe("true");
  expect(host.textContent).toContain("趋势加载失败"); expect(host.textContent).toContain("Primary");
  await act(async () => button("重试趋势").click());
  expect(host.querySelector('[aria-label="请求趋势"]')).not.toBeNull();
  await act(async () => finish(response(stats)));
  expect(host.querySelector(".metric-grid")?.getAttribute("aria-busy")).toBe("false");
});

it("refreshing the dashboard updates the end of its time range", async () => {
  vi.useFakeTimers(); vi.setSystemTime(new Date("2026-11-02T12:00:00Z"));
  const fetcher = vi.fn((path: string) => Promise.resolve(response(dashboardData(path))));
  await mount(<DashboardPage onError={onError} />, fetcher);
  vi.setSystemTime(new Date("2026-11-03T13:00:00Z"));
  await act(async () => button("刷新概览").click());
  const requests = fetcher.mock.calls.filter(([path]) => path.includes("analytics?"));
  expect(new URL(requests.at(-1)![0], "http://test").searchParams.get("end")).toBe("2026-11-03T13:00:00.000Z");
});

it("chart exposes exact request/error counts and handles zero without invalid heights", async () => {
  await mount(<RequestChart items={[{ group: "2026-11-01", requests: 0, errors: 0 }, { group: "2026-11-02", requests: 1000, errors: 20 }]} />);
  expect(host.querySelector('li[title="2026-11-02：请求 1000，错误 20"]')).not.toBeNull();
  expect(host.querySelectorAll(".chart-bar")[0]!.getAttribute("style")).toContain("height: 0%");
  expect(host.querySelectorAll(".chart-error")[1]!.getAttribute("style")).toContain("height: 2%");
  expect(host.textContent).toContain("20 次错误"); expect(host.innerHTML).not.toContain("NaN");
});

it("chart has an explicit empty state and bounds dense displays", async () => {
  await mount(<RequestChart items={[]} />); expect(host.textContent).toContain("该范围没有请求数据");
  await act(async () => root.render(<RequestChart items={Array.from({ length: 50 }, (_, i) => ({ group: String(i), requests: i + 1, errors: 0 }))} />));
  expect(host.querySelectorAll(".chart-bars li")).toHaveLength(48);
  expect(host.querySelector(".chart-bars li")?.getAttribute("title")).toContain("2：请求 3");
});

it("knowledge search filters description and new KB selects the upload destination", async () => {
  const rows = [{ id: "a", name: "Engineering", description: "Runbooks", doc_count: 2, chunk_count: 5 }];
  const fetcher = vi.fn((_path: string, init?: RequestInit) => Promise.resolve(response(init?.method === "POST" ? { id: "b", name: "Research" } : [...rows, { id: "b", name: "Research", doc_count: 0, chunk_count: 0 }])));
  await mount(<KnowledgePage onError={onError} />, fetcher);
  await input(host.querySelector('input[type="search"]')!, "Runbooks"); expect(host.querySelectorAll(".kb-card")).toHaveLength(1);
  await input(host.querySelector('input[type="search"]')!, "missing"); expect(host.textContent).toContain("没有匹配的知识库");
  await act(async () => button("＋ 创建知识库").click()); await input(control("知识库名称"), "Research");
  await act(async () => host.querySelector("form")!.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true })));
  expect(fetcher).toHaveBeenCalledWith("/api/v1/kb", expect.objectContaining({ method: "POST", body: '{"name":"Research"}' }));
  expect(host.querySelector("select")?.value).toBe("b"); expect(host.querySelector('[role="dialog"]')).toBeNull();
});

it("knowledge list failure is retryable and does not look like an empty library", async () => {
  await mount(<KnowledgePage onError={onError} />, vi.fn().mockResolvedValueOnce(response(null, 503)).mockResolvedValue(response([])));
  expect(host.textContent).toContain("知识库加载失败"); expect(host.textContent).not.toContain("建立你的第一个知识库");
  await act(async () => button("重试").click()); expect(host.textContent).toContain("建立你的第一个知识库");
});

const instance = { id: "s1", name: "Disabled HTTP", connector_type: "http", enabled: false, config: { base_url: "https://example.test" } };
const tool = { id: "tool1", name: "lookup", description: "Lookup item", enabled: true, risk_level: "low" };
function softwareData(path: string) {
  return path === "/api/v1/software/instances" ? [instance] : path === "/api/v1/software/tools" ? [tool] : path.includes("/approvals?") ? [{ id: "approval", tool_id: tool.id, arguments: { query: "example" }, created_at: "2026-11-02" }] : [];
}
it("software separates tabs and editing a disabled connector preserves its status", async () => {
  const fetcher = vi.fn((path: string, init?: RequestInit) => Promise.resolve(response(init?.method === "PUT" ? instance : softwareData(path))));
  await mount(<SoftwarePage onError={onError} />, fetcher);
  expect(host.querySelector(".software-debug")).not.toBeNull();
  expect(host.querySelector(".tool-select")?.getAttribute("aria-pressed")).toBe("true");
  await act(async () => button("连接器").click()); expect(host.querySelector(".software-debug")).toBeNull();
  await act(async () => button("编辑").click()); expect(host.querySelector('[role="dialog"]')).not.toBeNull();
  await act(async () => button("保存实例").click());
  expect(fetcher).toHaveBeenCalledWith("/api/v1/software/instances/s1", expect.objectContaining({ method: "PUT", body: expect.stringContaining('"enabled":false') }));
  expect(host.querySelector('[role="dialog"]')).toBeNull();
});

it("software rejects invalid config without a request and retains the editor", async () => {
  const fetcher = vi.fn((path: string) => Promise.resolve(response(softwareData(path))));
  await mount(<SoftwarePage onError={onError} />, fetcher);
  await act(async () => button("＋ 添加连接器").click()); await input(control("实例名称"), "New connector"); await input(control("配置 JSON"), "[]");
  await act(async () => button("创建实例").click());
  expect(onError).toHaveBeenCalledWith("实例配置必须是 JSON 对象"); expect(fetcher).toHaveBeenCalledTimes(4);
  expect(host.querySelector('[role="dialog"]')).not.toBeNull();
});

it("software guards a pending approval decision against repeated clicks", async () => {
  let finish!: (value: Response) => void;
  const fetcher = vi.fn((path: string, init?: RequestInit) => init?.method === "POST" ? new Promise<Response>(resolve => { finish = resolve; }) : Promise.resolve(response(softwareData(path))));
  await mount(<SoftwarePage onError={onError} />, fetcher);
  await act(async () => button("待审批1").click());
  await act(async () => { button("批准并执行").click(); button("批准并执行").click(); });
  expect(fetcher.mock.calls.filter(([, init]) => init?.method === "POST")).toHaveLength(1);
  expect(button("拒绝").disabled).toBe(true);
  await act(async () => finish(response({ status: "succeeded" })));
});

it("software failed loads are retryable and discovery only requests a dry-run installation", async () => {
  let failed = true;
  const fetcher = vi.fn((path: string, init?: RequestInit) => Promise.resolve(failed ? response(null, 503) : response(init?.method === "POST" ? { status: "planned", command: ["pip", "install", "ruff"] } : softwareData(path))));
  await mount(<SoftwarePage onError={onError} />, fetcher);
  expect(host.textContent).toContain("工具数据加载失败"); expect(host.textContent).not.toContain("暂无工具");
  failed = false; await act(async () => button("重试").click());
  await act(async () => button("本机发现").click()); await input(host.querySelector('[aria-label="安装包名"]')!, "ruff");
  await act(async () => button("生成安装计划").click());
  expect(fetcher).toHaveBeenCalledWith("/api/v1/software/install", expect.objectContaining({ body: '{"package":"ruff","manager":"pip","dry_run":true}' }));
  expect(host.textContent).toContain("已生成安装计划");
});

it("software previews and imports only selected OpenAPI operations", async () => {
  const fetcher = vi.fn((path: string) => Promise.resolve(response(path.endsWith("/preview") ? { openapi: "3.1.0", tool_count: 2, tools: [{ name: "read", risk_level: "low" }, { name: "write", risk_level: "high" }] } : path.endsWith("/import") ? { instance: { name: "Orders" }, tools: [tool] } : softwareData(path))));
  await mount(<SoftwarePage onError={onError} />, fetcher);
  await act(async () => button("OpenAPI 导入").click()); await input(control("实例名称"), "Orders"); await input(control("OpenAPI JSON"), '{"openapi":"3.1.0"}');
  await act(async () => button("预览操作").click()); await act(async () => host.querySelectorAll<HTMLInputElement>('.operation-row input')[1]!.click());
  await act(async () => button("导入所选（1）").click());
  expect(fetcher).toHaveBeenCalledWith("/api/v1/software/openapi/import", expect.objectContaining({ body: '{"name":"Orders","spec":{"openapi":"3.1.0"},"tools":["read"]}' }));
  expect(host.textContent).toContain("已导入 1 个操作");
});

it("MCP tools fail independently of audit and can be retried before a call", async () => {
  let reads = 0;
  const fetcher = vi.fn((path: string) => Promise.resolve(path === "/api/v1/mcp/tools" ? ++reads === 1 ? response(null, 503) : response({ tools: [{ name: "lookup", description: "Find items" }] }) : path.endsWith("/call") ? response({ content: "ok" }) : response([])));
  await mount(<McpManager onError={onError} />, fetcher);
  expect(host.textContent).toContain("工具加载失败"); expect(host.textContent).not.toContain("暂无可用工具");
  await act(async () => button("重试工具").click()); await act(async () => button("调用工具").click());
  expect(fetcher).toHaveBeenCalledWith("/api/v1/mcp/tools/lookup/call", expect.objectContaining({ method: "POST", body: '{"arguments":{}}' }));
  expect(host.textContent).toContain('"content": "ok"');
});

it("MCP rejects non-object arguments without invoking a tool", async () => {
  const fetcher = vi.fn((path: string) => Promise.resolve(response(path.endsWith("/tools") ? { tools: [{ name: "lookup" }] } : [])));
  await mount(<McpManager onError={onError} />, fetcher); await input(control("JSON 参数"), "[]");
  await act(async () => button("调用工具").click());
  expect(onError).toHaveBeenCalledWith("参数必须是 JSON 对象"); expect(fetcher).toHaveBeenCalledTimes(2);
});

it("Wiki distinguishes initial loading, project failure and an empty project list", async () => {
  let finish!: (value: Response) => void;
  const fetcher = vi.fn().mockImplementationOnce(() => new Promise<Response>(resolve => { finish = resolve; })).mockResolvedValue(response([]));
  await mount(<WikiManager onError={onError} />, fetcher);
  expect(host.textContent).toContain("正在加载 Wiki 项目"); expect(host.textContent).not.toContain("创建一个项目");
  await act(async () => finish(response(null, 503))); expect(host.textContent).toContain("Wiki 项目加载失败");
  await act(async () => button("重试").click()); expect(host.textContent).toContain("创建一个项目");
  expect(host.querySelector('[role="alert"]')).toBeNull();
});

it("approval deep links enter the queue directly without showing the debug form", async () => {
  window.location.hash = "#/software?view=approvals";
  await mount(<SoftwarePage onError={onError} />, vi.fn((path: string) => Promise.resolve(response(softwareData(path)))));
  expect(button("批准并执行")).toBeDefined();
  expect(host.querySelector(".software-debug")).toBeNull();
});
