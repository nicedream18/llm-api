/** @vitest-environment jsdom */
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { KnowledgePage } from "./App";

let host: HTMLDivElement;
let root: Root;
const onError = vi.fn();
const response = (data: unknown, status = 200) => new Response(JSON.stringify({ data, info: status >= 400 ? "刷新失败" : "" }), { status });
const kbs = [{ id: "a", name: "First", doc_count: 0, chunk_count: 0 }, { id: "b", name: "Second", doc_count: 0, chunk_count: 0 }];
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
});

async function selectKb(id: string) {
  await act(async () => {
    const select = host.querySelector("select")!;
    select.value = id;
    select.dispatchEvent(new Event("change", { bubbles: true }));
  });
}

it("captures a real change event before await and allows uploading the same file again", async () => {
  let finish!: (response: Response) => void;
  const fetcher = vi.fn((path: string, init?: RequestInit) => init?.method === "POST"
    ? new Promise<Response>(resolve => { finish = resolve; }) : Promise.resolve(response(kbs)));
  vi.stubGlobal("fetch", fetcher);
  await act(async () => root.render(<KnowledgePage onError={onError} />));
  await selectKb("a");
  const input = host.querySelector<HTMLInputElement>('input[type="file"]')!;
  const file = new File(["contents"], "guide.md", { type: "text/markdown" });
  Object.defineProperty(input, "files", { configurable: true, value: [file] });
  const clear = vi.spyOn(input, "value", "set");
  await act(async () => input.dispatchEvent(new Event("change", { bubbles: true })));
  expect(fetcher.mock.calls.at(-1)?.[0]).toBe("/api/v1/kb/a/documents/upload");
  expect((fetcher.mock.calls.at(-1)?.[1]?.body as FormData).get("file")).toBe(file);
  // Changing the destination while upload is pending must not reassign it.
  await selectKb("b");
  await act(async () => finish(response({ id: "doc" })));
  expect(clear).toHaveBeenCalledWith("");
  expect(onError).not.toHaveBeenCalled();
  expect(fetcher.mock.calls.filter(call => call[0] === "/api/v1/kb")).toHaveLength(2);
  await act(async () => input.dispatchEvent(new Event("change", { bubbles: true })));
  expect(fetcher.mock.calls.at(-1)?.[0]).toBe("/api/v1/kb/b/documents/upload");
  await act(async () => finish(response({ id: "doc-2" })));
  expect(clear).toHaveBeenCalledTimes(2);
  expect(onError).not.toHaveBeenCalled();
});

it("reports refresh failure separately after a successful upload", async () => {
  let reads = 0;
  const fetcher = vi.fn((_path: string, init?: RequestInit) => Promise.resolve(
    init?.method === "POST" ? response({ id: "doc" }) : ++reads === 1 ? response(kbs) : response(null, 503)));
  vi.stubGlobal("fetch", fetcher);
  await act(async () => root.render(<KnowledgePage onError={onError} />));
  await selectKb("a");
  const input = host.querySelector<HTMLInputElement>('input[type="file"]')!;
  Object.defineProperty(input, "files", { configurable: true, value: [new File(["x"], "guide.md")] });
  const clear = vi.spyOn(input, "value", "set");
  await act(async () => input.dispatchEvent(new Event("change", { bubbles: true })));
  expect(clear).toHaveBeenCalledWith("");
  expect(onError).toHaveBeenCalledExactlyOnceWith("刷新失败");
  expect(fetcher.mock.calls.filter(call => call[1]?.method === "POST")).toHaveLength(1);
});

it("keeps the selection and reports an upload failure without refreshing", async () => {
  const fetcher = vi.fn((_path: string, init?: RequestInit) => init?.method === "POST"
    ? Promise.reject(new Error("上传失败")) : Promise.resolve(response(kbs)));
  vi.stubGlobal("fetch", fetcher);
  await act(async () => root.render(<KnowledgePage onError={onError} />));
  await selectKb("a");
  const input = host.querySelector<HTMLInputElement>('input[type="file"]')!;
  Object.defineProperty(input, "files", { configurable: true, value: [new File(["x"], "guide.md")] });
  const clear = vi.spyOn(input, "value", "set");
  await act(async () => input.dispatchEvent(new Event("change", { bubbles: true })));
  expect(clear).not.toHaveBeenCalled();
  expect(onError).toHaveBeenCalledExactlyOnceWith("上传失败");
  expect(fetcher.mock.calls).toHaveLength(2);
});
