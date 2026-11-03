/** @vitest-environment jsdom */
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { EntityPicker } from "./EntityPicker";

let root: Root;
let host: HTMLDivElement;
const options = [
  { id: "channel-1", label: "Primary", detail: "openai · 已启用" },
  { id: "channel-2", label: "Backup", detail: "claude · 已启用" },
];

beforeEach(() => {
  vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true);
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});

afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.unstubAllGlobals();
});

it("searches by display name and returns stable ids for selected entities", async () => {
  const onChange = vi.fn();
  await act(async () => root.render(<EntityPicker label="渠道" value={[]} options={options} onChange={onChange} />));
  const search = host.querySelector<HTMLInputElement>('input[type="search"]')!;
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!.call(search, "Backup");
    search.dispatchEvent(new Event("input", { bubbles: true }));
  });
  expect(host.textContent).toContain("Backup");
  expect(host.textContent).not.toContain("Primary");
  await act(async () => host.querySelector<HTMLInputElement>('input[type="checkbox"]')!.click());
  expect(onChange).toHaveBeenCalledWith(["channel-2"]);
});

it("preserves unavailable ids so users can remove stale selections", async () => {
  const onChange = vi.fn();
  await act(async () => root.render(<EntityPicker label="渠道" value={["deleted-id"]} options={options} onChange={onChange} />));
  expect(host.textContent).toContain("不可用项目");
  await act(async () => host.querySelector<HTMLButtonElement>('button[aria-label="移除渠道 不可用项目"]')!.click());
  expect(onChange).toHaveBeenCalledWith([]);
});
