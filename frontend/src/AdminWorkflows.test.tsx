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
const button = (name: string) => Array.from(host.querySelectorAll("button")).find(item => item.textContent === name)!;
const submit = async (selector: string) => act(async () => { host.querySelector(selector)!.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true })); });
async function mount(element: React.ReactNode, fetcher: ReturnType<typeof vi.fn>) { vi.stubGlobal("fetch", fetcher); await act(async () => root.render(element)); }

it("edits channel without resending nested keys or masked secrets and clears capabilities", async () => {
  const fetcher = vi.fn((path: string, _init?: RequestInit) => Promise.resolve(payload(path === "/api/v1/channels" ? [channel] : { success: true })));
  await mount(<ChannelManager onError={onError} />, fetcher);
  await act(async () => button("编辑 Primary").click());
  await act(async () => host.querySelector<HTMLInputElement>('fieldset input[type="checkbox"]')!.click());
  await submit("form.channel-form");
  const update = fetcher.mock.calls.find(call => (call[1] as RequestInit)?.method === "PUT")!;
  const data = JSON.parse((update[1] as RequestInit).body as string);
  expect(data).not.toHaveProperty("api_keys"); expect(data.api_key).toBeNull(); expect(data.config).toEqual({ timeout: 10 });
});

it("probes draft and preserves one-key edit while testing selected key", async () => {
  const fetcher = vi.fn((path: string, _init?: RequestInit) => Promise.resolve(payload(path.endsWith("/api-keys") ? [{ id: "k", name: "Extra", api_key: "mask****", status: 1, weight: 2 }] : path === "/api/v1/channels" ? [channel] : { success: true })));
  await mount(<ChannelManager onError={onError} />, fetcher);
  await act(async () => button("测试当前草稿").click()); expect(host.textContent).toContain("草稿测试通过");
  await act(async () => button("管理多 Key Primary").click());
  await act(async () => button("测试 Key Extra").click());
  expect(fetcher).toHaveBeenCalledWith("/api/v1/channels/c/api-keys/k/test", expect.anything());
  await act(async () => button("编辑 Key Extra").click());
  await submit("section.panel form");
  expect(fetcher).toHaveBeenCalledWith("/api/v1/channels/c/api-keys/k", expect.objectContaining({ method: "PUT", body: expect.stringContaining('"api_key":null') }));
});

it("rejects invalid import and does not delete when confirmation is cancelled", async () => {
  vi.spyOn(window, "confirm").mockReturnValue(false);
  const fetcher = vi.fn((_path: string, _init?: RequestInit) => Promise.resolve(payload([channel])));
  await mount(<ChannelManager onError={onError} />, fetcher);
  await act(async () => button("预览导入").click()); expect(onError).toHaveBeenCalled();
  await act(async () => button("删除 Primary").click());
  expect(fetcher).toHaveBeenCalledTimes(1);
});

it("does not reset quota or rotate an existing access key on ordinary edits", async () => {
  const row = { id: "a", name: "Client", key: "mask****", status: 1, quota_limit: 100, quota_used: 90, allowed_models: ["chat"], allowed_channels: [], expires_at: null };
  const fetcher = vi.fn((_path: string, _init?: RequestInit) => Promise.resolve(payload([row])));
  await mount(<ApiKeyManager onError={onError} />, fetcher);
  await act(async () => button("编辑密钥 Client").click()); await submit("form");
  const body = JSON.parse((fetcher.mock.calls.find(call => (call[1] as RequestInit)?.method === "PUT")![1] as RequestInit).body as string);
  expect(body).not.toHaveProperty("quota_used"); expect(body).not.toHaveProperty("key"); expect(body.expires_at).toBeNull();
});

it("edits server route rows without server metadata and previews without mutation", async () => {
  const row = { id: "team", updated_at: "now", enabled: true, strategy: "weighted", channels: [], api_key_ids: [], models: [], endpoints: [], max_concurrent: 10, retry_budget: 2, unknown_quota: "allow" };
  const fetcher = vi.fn((path: string, _init?: RequestInit) => Promise.resolve(payload(path.endsWith("/groups") ? [row] : { candidates: [], reason: "no_capacity" })));
  await mount(<RoutingManager onError={onError} />, fetcher);
  await act(async () => button("编辑路由 team").click()); await submit("form");
  const body = JSON.parse((fetcher.mock.calls.find(call => (call[1] as RequestInit)?.method === "PUT")![1] as RequestInit).body as string);
  expect(body).not.toHaveProperty("updated_at"); expect(body).not.toHaveProperty("id");
  await submit("form:last-of-type"); expect(host.textContent).toContain("no_capacity");
});

it("loads log detail with attempts and findings and reports forbidden reads", async () => {
  const fetcher = vi.fn((path: string, _init?: RequestInit) => Promise.resolve(payload(path.includes("logs?page") ? [{ id: "l", model: "chat" }] : path.includes("attempts") ? [{ attempt_no: 2 }] : path.includes("findings") ? [{ risk: "low" }] : { request_id: "execution" })));
  await mount(<LogManager onError={onError} />, fetcher);
  await act(async () => button("查看日志 l").click());
  expect(host.textContent).toContain("execution"); expect(host.textContent).toContain("attempt_no"); expect(host.textContent).toContain("risk");
  fetcher.mockImplementation(() => Promise.resolve(payload(null, 403)));
  await act(async () => button("刷新日志").click()); expect(onError).toHaveBeenCalledWith("权限不足");
});

it("keeps hash navigation, unknown route recovery and expired-session login", async () => {
  window.location.hash = "#/missing";
  const fetcher = vi.fn((_path: string, _init?: RequestInit) => Promise.resolve(payload(_path.endsWith("/auth/session") ? { authenticated: true } : [])));
  await mount(<App />, fetcher); expect(host.textContent).toContain("没有找到这个页面");
  await act(async () => { window.location.hash = "#/channels"; window.dispatchEvent(new Event("hashchange")); });
  expect(host.querySelector('[aria-current="page"]')?.textContent).toBe("渠道");
  await act(async () => window.dispatchEvent(new Event("admin-session-expired")));
  expect(host.textContent).toContain("管理员登录");
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
