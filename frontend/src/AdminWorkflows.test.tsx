/** @vitest-environment jsdom */
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { ChannelManager } from "./ChannelManager";
import { ApiKeyManager } from "./ApiKeyManager";
import { RoutingManager } from "./RoutingManager";
import { LogManager } from "./LogManager";
import { App } from "./App";
import { PageBoundary } from "./navigation";
import { get } from "./api";

const payload = (data: unknown, status = 200) => new Response(JSON.stringify({ data, info: status >= 400 ? "权限不足" : "", code: "0000" }), { status });
const channel = { id: "c", name: "Primary", type: "openai", base_url: "https://example.test/v1", api_key: "mask****", api_keys: [{ id: "k" }], models: ["chat"], status: 1, priority: 1, weight: 2, config: { endpoints: ["/v1/chat/completions"], timeout: 10 } };
let root: Root; let host: HTMLDivElement; const onError = vi.fn();
beforeEach(() => { vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true); host = document.createElement("div"); document.body.append(host); root = createRoot(host); onError.mockClear(); window.location.hash = ""; });
afterEach(async () => { await act(async () => root.unmount()); host.remove(); vi.unstubAllGlobals(); vi.restoreAllMocks(); });
const button = (name: string) => Array.from(host.querySelectorAll("button")).find(item => item.textContent?.trim() === name)!;
const labelledButton = (name: string) => host.querySelector<HTMLButtonElement>(`button[aria-label="${name}"]`)!;
const setControlValue = (control: HTMLInputElement | HTMLSelectElement, value: string) => {
  const prototype = control instanceof HTMLSelectElement ? HTMLSelectElement.prototype : HTMLInputElement.prototype;
  Object.getOwnPropertyDescriptor(prototype, "value")?.set?.call(control, value);
  control.dispatchEvent(new Event(control instanceof HTMLSelectElement ? "change" : "input", { bubbles: true }));
};
const submit = async (selector: string) => act(async () => { host.querySelector(selector)!.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true })); });
async function mount(element: React.ReactNode, fetcher: ReturnType<typeof vi.fn>) { vi.stubGlobal("fetch", fetcher); await act(async () => root.render(element)); }

it("edits channel without resending nested keys or masked secrets and clears capabilities", async () => {
  const fetcher = vi.fn((path: string, _init?: RequestInit) => Promise.resolve(payload(path === "/api/v1/channels" ? [channel] : { success: true })));
  await mount(<ChannelManager onError={onError} />, fetcher);
  await act(async () => labelledButton("编辑渠道 Primary").click());
  await act(async () => host.querySelector<HTMLInputElement>('fieldset input[type="checkbox"]')!.click());
  await submit("form.channel-form");
  const update = fetcher.mock.calls.find(call => (call[1] as RequestInit)?.method === "PUT")!;
  const data = JSON.parse((update[1] as RequestInit).body as string);
  expect(data).not.toHaveProperty("api_keys"); expect(data.api_key).toBeNull(); expect(data.config).toEqual({ timeout: 10 });
});

it("probes draft and preserves one-key edit while testing selected key", async () => {
  const fetcher = vi.fn((path: string, _init?: RequestInit) => Promise.resolve(payload(path.endsWith("/api-keys") ? [{ id: "k", name: "Extra", api_key: "mask****", status: 1, weight: 2 }] : path === "/api/v1/channels" ? [channel] : { success: true })));
  await mount(<ChannelManager onError={onError} />, fetcher);
  await act(async () => button("新增渠道").click());
  await act(async () => button("测试连接").click()); expect(host.textContent).toContain("测试通过");
  expect(host.querySelector('[role="dialog"] [role="status"]')?.textContent).toContain("草稿测试通过");
  await act(async () => labelledButton("关闭渠道编辑").click());
  await act(async () => { labelledButton("更多操作 Primary").click(); });
  await act(async () => button("管理多 Key").click());
  await act(async () => button("测试 Key Extra").click());
  expect(fetcher).toHaveBeenCalledWith("/api/v1/channels/c/api-keys/k/test", expect.anything());
  await act(async () => button("编辑 Key Extra").click());
  await submit(".key-manager form");
  expect(fetcher).toHaveBeenCalledWith("/api/v1/channels/c/api-keys/k", expect.objectContaining({ method: "PUT", body: expect.stringContaining('"api_key":null') }));
});

it("rejects invalid import and does not delete when confirmation is cancelled", async () => {
  vi.spyOn(window, "confirm").mockReturnValue(false);
  const fetcher = vi.fn((_path: string, _init?: RequestInit) => Promise.resolve(payload([channel])));
  await mount(<ChannelManager onError={onError} />, fetcher);
  await act(async () => button("导入").click());
  await act(async () => button("预览导入").click()); expect(onError).toHaveBeenCalled();
  await act(async () => labelledButton("关闭渠道导入").click());
  await act(async () => { labelledButton("更多操作 Primary").click(); });
  await act(async () => button("删除渠道").click());
  expect(fetcher).toHaveBeenCalledTimes(1);
});

it("filters channel rows and opens the accessible editor drawer", async () => {
  const paused = { ...channel, id: "paused", name: "Paused", type: "claude", status: 0, models: ["vision"] };
  const fetcher = vi.fn((_path: string, _init?: RequestInit) => Promise.resolve(payload([channel, paused])));
  await mount(<ChannelManager onError={onError} />, fetcher);
  expect(host.querySelectorAll(".channel-table tbody tr")).toHaveLength(2);
  await act(async () => setControlValue(host.querySelector<HTMLInputElement>('input[type="search"]')!, "Primary"));
  expect(host.querySelectorAll(".channel-table tbody tr")).toHaveLength(1);
  expect(host.textContent).not.toContain("Paused");
  await act(async () => setControlValue(host.querySelector<HTMLInputElement>('input[type="search"]')!, ""));
  await act(async () => setControlValue(host.querySelector<HTMLSelectElement>('select[aria-label="状态筛选"]')!, "false"));
  expect(host.querySelectorAll(".channel-table tbody tr")).toHaveLength(1);
  expect(host.textContent).toContain("Paused");
  await act(async () => button("新增渠道").click());
  expect(host.querySelector('[role="dialog"][aria-labelledby="channel-drawer-title"]')).not.toBeNull();
  expect(host.textContent).toContain("新增渠道");
});

it("filters access keys and closes its editor drawer with Escape", async () => {
  const rows = [
    { id: "k1", name: "Production", key: "sk-mask1", status: 1, allowed_models: ["gpt-4o"], allowed_channels: [], quota_limit: 100, quota_used: 12, expires_at: null },
    { id: "k2", name: "Disabled", key: "sk-mask2", status: 0, allowed_models: ["claude-sonnet"], allowed_channels: [], quota_limit: 0, quota_used: 0, expires_at: null },
  ];
  const fetcher = vi.fn((_path: string, _init?: RequestInit) => Promise.resolve(payload(rows)));
  await mount(<ApiKeyManager onError={onError} />, fetcher);
  expect(host.querySelectorAll(".access-key-page tbody tr")).toHaveLength(2);
  await act(async () => setControlValue(host.querySelector<HTMLInputElement>('input[type="search"]')!, "Production"));
  expect(host.querySelectorAll(".access-key-page tbody tr")).toHaveLength(1);
  await act(async () => setControlValue(host.querySelector<HTMLInputElement>('input[type="search"]')!, ""));
  await act(async () => setControlValue(host.querySelector<HTMLSelectElement>('select[aria-label="访问密钥状态"]')!, "false"));
  expect(host.querySelectorAll(".access-key-page tbody tr")).toHaveLength(1);
  await act(async () => labelledButton("编辑密钥 Disabled").click());
  expect(host.querySelector('[role="dialog"][aria-labelledby="key-drawer-title"]')).not.toBeNull();
  await act(async () => window.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true })));
  expect(host.querySelector('[role="dialog"][aria-labelledby="key-drawer-title"]')).toBeNull();
});

it("shows a list error separately from loading and retries without losing the page", async () => {
  const fetcher = vi.fn().mockResolvedValueOnce(payload(null, 403)).mockResolvedValue(payload([]));
  await mount(<ApiKeyManager onError={onError} />, fetcher);
  expect(host.querySelector('[role="alert"]')?.textContent).toContain("加载失败");
  expect(host.textContent).not.toContain("正在加载访问密钥");
  await act(async () => button("重试").click());
  expect(host.querySelector('[role="alert"]')).toBeNull();
  expect(host.textContent).toContain("还没有访问密钥");
});

it("filters route groups and saves through the route editor drawer", async () => {
  const row = { id: "team", updated_at: "now", enabled: true, strategy: "weighted", channels: ["c1"], api_key_ids: [], models: ["gpt-4o"], endpoints: [], max_concurrent: 10, retry_budget: 2, unknown_quota: "allow" };
  const fetcher = vi.fn((path: string, init?: RequestInit) => Promise.resolve(payload(path.endsWith("/groups") ? [row] : init?.method === "PUT" ? {} : { candidates: [], reason: "no_capacity" })));
  await mount(<RoutingManager onError={onError} />, fetcher);
  await act(async () => button("编辑").click());
  expect(host.querySelector('[role="dialog"][aria-labelledby="route-drawer-title"]')).not.toBeNull();
  await submit("form.route-editor-form");
  expect(fetcher).toHaveBeenCalledWith("/api/v1/routing/groups/team", expect.objectContaining({ method: "PUT" }));
  expect(host.querySelector('[role="dialog"][aria-labelledby="route-drawer-title"]')).toBeNull();
});

it("filters request logs by status and opens trace details in a drawer", async () => {
  const fetcher = vi.fn((path: string) => Promise.resolve(payload(path.includes("logs?page") ? [{ id: "ok", model: "gpt-4o", status_code: 200, duration_ms: 20 }, { id: "bad", model: "claude", status_code: 500, duration_ms: 90 }] : path.includes("attempts") ? [{ attempt_no: 1 }] : path.includes("findings") ? [] : { request_id: "trace-ok" })));
  await mount(<LogManager onError={onError} />, fetcher);
  expect(host.querySelectorAll(".logs-page tbody tr")).toHaveLength(2);
  await act(async () => setControlValue(host.querySelector<HTMLSelectElement>('select[aria-label="筛选 HTTP 状态"]')!, "500"));
  expect(host.querySelectorAll(".logs-page tbody tr")).toHaveLength(1);
  await act(async () => setControlValue(host.querySelector<HTMLSelectElement>('select[aria-label="筛选 HTTP 状态"]')!, ""));
  await act(async () => labelledButton("查看日志 ok").click());
  expect(host.querySelector('[role="dialog"][aria-labelledby="log-detail-title"]')).not.toBeNull();
  expect(host.textContent).toContain("trace-ok");
});

it("renders grouped navigation and persists theme and sidebar preferences", async () => {
  localStorage.clear();
  const fetcher = vi.fn((path: string, _init?: RequestInit) => Promise.resolve(payload(path.endsWith("/auth/session") ? { authenticated: true } : {})));
  await mount(<App />, fetcher);
  expect(host.querySelectorAll(".nav-group")).toHaveLength(4);
  expect(host.querySelectorAll('.app-nav a[aria-current="page"]')).toHaveLength(1);
  await act(async () => labelledButton("切换到深色模式").click());
  expect(document.documentElement.dataset.theme).toBe("dark");
  expect(localStorage.getItem("waliapi-admin-theme")).toBe("dark");
  await act(async () => labelledButton("收起侧栏").click());
  expect(host.querySelector(".shell")?.classList.contains("sidebar-collapsed")).toBe(true);
  expect(localStorage.getItem("waliapi-admin-sidebar")).toBe("collapsed");
});

it("does not reset quota or rotate an existing access key on ordinary edits", async () => {
  const row = { id: "a", name: "Client", key: "mask****", status: 1, quota_limit: 100, quota_used: 90, allowed_models: ["chat"], allowed_channels: [], expires_at: null };
  const fetcher = vi.fn((_path: string, _init?: RequestInit) => Promise.resolve(payload([row])));
  await mount(<ApiKeyManager onError={onError} />, fetcher);
  await act(async () => labelledButton("编辑密钥 Client").click()); await submit("form");
  const body = JSON.parse((fetcher.mock.calls.find(call => (call[1] as RequestInit)?.method === "PUT")![1] as RequestInit).body as string);
  expect(body).not.toHaveProperty("quota_used"); expect(body).not.toHaveProperty("key"); expect(body.expires_at).toBeNull();
});

it("edits server route rows without server metadata and previews without mutation", async () => {
  const row = { id: "team", updated_at: "now", enabled: true, strategy: "weighted", channels: [], api_key_ids: [], models: [], endpoints: [], max_concurrent: 10, retry_budget: 2, unknown_quota: "allow" };
  const fetcher = vi.fn((path: string, _init?: RequestInit) => Promise.resolve(payload(path.endsWith("/groups") ? [row] : { candidates: [], reason: "no_capacity" })));
  await mount(<RoutingManager onError={onError} />, fetcher);
  await act(async () => labelledButton("编辑路由 team").click()); await submit("form.route-editor-form");
  const body = JSON.parse((fetcher.mock.calls.find(call => (call[1] as RequestInit)?.method === "PUT")![1] as RequestInit).body as string);
  expect(body).not.toHaveProperty("updated_at"); expect(body).not.toHaveProperty("id");
  await submit("form.route-preview"); expect(host.textContent).toContain("no_capacity");
});

it("loads log detail with attempts and findings and reports forbidden reads", async () => {
  const fetcher = vi.fn((path: string, _init?: RequestInit) => Promise.resolve(payload(path.includes("logs?page") ? [{ id: "l", model: "chat" }] : path.includes("attempts") ? [{ attempt_no: 2 }] : path.includes("findings") ? [{ risk: "low" }] : { request_id: "execution" })));
  await mount(<LogManager onError={onError} />, fetcher);
  await act(async () => labelledButton("查看日志 l").click());
  expect(host.textContent).toContain("execution"); expect(host.textContent).toContain("attempt_no"); expect(host.textContent).toContain("risk");
  fetcher.mockImplementation(() => Promise.resolve(payload(null, 403)));
  await act(async () => button("刷新").click()); expect(onError).toHaveBeenCalledWith("权限不足");
});

it("keeps hash navigation, unknown route recovery and expired-session login", async () => {
  window.location.hash = "#/missing";
  const fetcher = vi.fn((_path: string, _init?: RequestInit) => Promise.resolve(payload(_path.endsWith("/auth/session") ? { authenticated: true } : [])));
  await mount(<App />, fetcher); expect(host.textContent).toContain("没有找到这个页面");
  await act(async () => { window.location.hash = "#/channels"; window.dispatchEvent(new Event("hashchange")); });
  expect(host.querySelector('[aria-current="page"]')?.textContent).toBe("渠道");
  await act(async () => { window.location.hash = "#/software?view=approvals"; window.dispatchEvent(new Event("hashchange")); });
  expect(host.textContent).toContain("待审批调用");
  expect(host.textContent).not.toContain("没有找到这个页面");
  expect(labelledButton("退出登录")).not.toBeNull();
  await act(async () => window.dispatchEvent(new Event("admin-session-expired")));
  expect(host.textContent).toContain("欢迎回来");
});

it("isolates render failures with an accessible recovery link", async () => {
  vi.spyOn(console, "error").mockImplementation(() => {});
  function Broken(): React.ReactNode { throw new Error("broken"); }
  await mount(<PageBoundary><Broken /></PageBoundary>, vi.fn());
  expect(host.querySelector('[role="alert"]')?.textContent).toContain("页面暂时无法显示");
  expect(host.querySelector('a')?.getAttribute("href")).toBe("#/dashboard");
});

it("handles non-JSON errors and validation details without logging out on forbidden", async () => {
  const expired = vi.fn(); window.addEventListener("admin-session-expired", expired);
  vi.stubGlobal("fetch", vi.fn().mockResolvedValueOnce(new Response("oops", { status: 502 })).mockResolvedValueOnce(new Response(JSON.stringify({ detail: [{ loc: ["body", "name"], msg: "Required" }] }), { status: 422 })).mockResolvedValueOnce(payload(null, 403)).mockResolvedValueOnce(payload(null, 401)));
  await expect(get("/api/v1/test")).rejects.toThrow("HTTP 502");
  await expect(get("/api/v1/test")).rejects.toThrow("body.name: Required");
  await expect(get("/api/v1/test")).rejects.toThrow("权限不足"); expect(expired).not.toHaveBeenCalled();
  await expect(get("/api/v1/test")).rejects.toThrow(); expect(expired).toHaveBeenCalledOnce();
  window.removeEventListener("admin-session-expired", expired);
});
