/** @vitest-environment jsdom */
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { codeSamples, LandingPage } from "./LandingPage";

let host: HTMLDivElement;
let root: Root;
const writeText = vi.fn();
const findButton = (label: string) => Array.from(document.querySelectorAll("button")).find(button => button.getAttribute("aria-label") === label)!;
const select = async (label: string) => {
  const item = Array.from(host.querySelectorAll(".ant-segmented-item")).find(element => element.textContent === label)!;
  await act(async () => (item.querySelector("input") as HTMLInputElement).click());
};

beforeEach(async () => {
  vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true);
  vi.stubGlobal("ResizeObserver", class { observe() {} unobserve() {} disconnect() {} });
  Object.defineProperty(window, "matchMedia", { configurable: true, value: vi.fn().mockImplementation(query => ({ matches: false, media: query, addListener() {}, removeListener() {}, addEventListener() {}, removeEventListener() {}, dispatchEvent() { return true; } })) });
  Object.defineProperty(navigator, "clipboard", { configurable: true, value: { writeText } });
  writeText.mockReset().mockResolvedValue(undefined);
  host = document.createElement("div"); document.body.append(host); root = createRoot(host);
  await act(async () => root.render(<LandingPage />));
});
afterEach(async () => { await act(async () => root.unmount()); host.remove(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });

it("presents public product content, valid section links and the existing console", () => {
  expect(host.querySelector("h1")?.textContent).toBe("让灵感，快一步成为产品。");
  expect(host.querySelectorAll("h1")).toHaveLength(1);
  expect(host.querySelector('a[href="/admin/"]')).not.toBeNull();
  for (const link of host.querySelectorAll<HTMLAnchorElement>('a[href^="#"]')) {
    expect(host.querySelector(link.getAttribute("href")!), link.textContent || "section link").not.toBeNull();
  }
  expect(host.textContent).toContain("交互演示");
  expect(host.textContent).toContain("示例数据");
});

it("switches the product preview without making live or fabricated API requests", async () => {
  const fetcher = vi.spyOn(globalThis, "fetch");
  await select("安全审计");
  expect(host.querySelector('[aria-label="把安全放在转发之前"]')?.textContent).toContain("[REDACTED]");
  expect(host.textContent).toContain("凭证已替换");
  await select("知识检索");
  expect(host.textContent).toContain("让答案，来自你的知识。");
  expect(fetcher).not.toHaveBeenCalled();
});

it("copies the selected language and resets stale success after switching", async () => {
  await act(async () => findButton("复制示例代码").click());
  expect(writeText).toHaveBeenLastCalledWith(codeSamples.Python);
  expect(findButton("代码已复制")).toBeDefined();
  await select("cURL");
  expect(host.querySelector('[aria-label="cURL 接入示例"]')?.textContent).toContain("curl http://localhost:9900/v1/chat/completions");
  await act(async () => findButton("复制示例代码").click());
  expect(writeText).toHaveBeenLastCalledWith(codeSamples.cURL);
  await select("Node.js");
  expect(findButton("复制示例代码")).toBeDefined();
  expect(host.querySelector('[aria-label="Node.js 接入示例"]')?.textContent).toContain("process.env.WALIAPI_API_KEY");
});

it("reports clipboard rejection without showing success", async () => {
  writeText.mockRejectedValueOnce(new Error("permission denied"));
  await act(async () => findButton("复制示例代码").click());
  expect(host.querySelector('[role="alert"]')?.textContent).toContain("复制失败");
  expect(findButton("代码已复制")).toBeUndefined();
});

it("opens and closes the mobile navigation and expands useful answers", async () => {
  await act(async () => { findButton("打开导航菜单").click(); await vi.dynamicImportSettled(); });
  const mobile = document.querySelector('[aria-label="移动导航"]')!;
  expect(mobile).not.toBeNull();
  await act(async () => mobile.querySelector<HTMLAnchorElement>('a[href="#features"]')!.click());
  expect(document.querySelector('.ant-drawer-open')).toBeNull();
  const question = Array.from(host.querySelectorAll('[role="button"]')).find(element => element.textContent?.includes("这是一个托管的 AI 服务吗？")) as HTMLElement;
  await act(async () => question.click());
  expect(host.textContent).toContain("你需要准备运行环境、数据库和上游模型凭证");
});
