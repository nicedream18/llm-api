/** @vitest-environment jsdom */
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { SettingsPage } from "./SettingsPage";

let root: Root;
let host: HTMLDivElement;
const onError = vi.fn();
const payload = (data: unknown) => new Response(JSON.stringify({ data, code: "0000", info: "" }), { status: 200 });
const datasets: Record<string, unknown> = {
  "/api/v1/platform/prompts": [],
  "/api/v1/platform/config": [],
  "/api/v1/access/grants": [],
  "/api/v1/api-keys": [{ id: "key-uuid", name: "Production", key: "masked-token", status: 1 }],
  "/api/v1/mcp/tools": { tools: [] },
  "/api/v1/kb": [{ id: "kb-uuid", name: "Engineering Docs", doc_count: 3, chunk_count: 10 }],
  "/api/v1/wiki/projects": [],
  "/api/v1/software/tools": [],
  "/api/v1/auth/sessions": [],
  "/api/v1/administration/diagnostics": {},
  "/api/v1/administration/audit?limit=50&offset=0": [],
};

beforeEach(() => {
  vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true);
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  onError.mockClear();
});

afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

it("creates grants by selecting readable names while submitting stable ids", async () => {
  const fetcher = vi.fn((path: string, init?: RequestInit) => Promise.resolve(payload(init?.method === "POST" ? { id: "grant" } : datasets[path] ?? [])));
  vi.stubGlobal("fetch", fetcher);
  await act(async () => root.render(<SettingsPage onError={onError} />));

  expect(host.textContent).toContain("Production");
  expect(host.textContent).not.toContain("key-uuid");
  const radios = host.querySelectorAll<HTMLInputElement>('input[type="radio"]');
  await act(async () => radios[0]!.click());
  const resourceType = Array.from(host.querySelectorAll("label")).find(label => label.textContent?.startsWith("资源类型"))!.querySelector("select")!;
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, "value")!.set!.call(resourceType, "kb");
    resourceType.dispatchEvent(new Event("change", { bubbles: true }));
  });
  const resourceRadios = host.querySelectorAll<HTMLFieldSetElement>(".settings-grant-form .entity-picker")[1]!.querySelectorAll<HTMLInputElement>('input[type="radio"]');
  const docsOption = resourceRadios[1]!;
  await act(async () => docsOption.click());
  await act(async () => host.querySelector<HTMLFormElement>("form.settings-grant-form")!.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true })));

  expect(fetcher).toHaveBeenCalledWith("/api/v1/access/grants", expect.objectContaining({
    method: "POST",
    body: JSON.stringify({ principal_type: "api_key", principal_id: "key-uuid", resource_type: "kb", resource_id: "kb-uuid", action: "execute" }),
  }));
  expect(onError).not.toHaveBeenCalled();
});
