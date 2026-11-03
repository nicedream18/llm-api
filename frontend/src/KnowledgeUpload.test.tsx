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

class FetchBackedUploadXhr {
  upload: { onprogress: ((event: ProgressEvent) => void) | null } = { onprogress: null };
  onload: (() => void) | null = null;
  onerror: (() => void) | null = null;
  status = 0;
  responseText = "";
  withCredentials = false;
  private path = "";

  open(_method: string, path: string) { this.path = path; }
  setRequestHeader() {}
  send(body: FormData) {
    this.upload.onprogress?.({ lengthComputable: true, loaded: 5, total: 10 } as ProgressEvent);
    void globalThis.fetch(this.path, { method: "POST", body }).then(async response => {
      this.status = response.status;
      this.responseText = await response.text();
      this.onload?.();
    }).catch(() => this.onerror?.());
  }
}

beforeEach(() => {
  vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true);
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  onError.mockClear();
  vi.stubGlobal("XMLHttpRequest", FetchBackedUploadXhr);
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
  const processingDoc = { id: "doc", kb_id: "a", name: "guide.md", status: "pending", chunk_count: 0, total_tokens: 0, task_id: "task", task_status: "pending", task_progress: 0 };
  const fetcher = vi.fn((path: string, init?: RequestInit) => init?.method === "POST"
    ? new Promise<Response>(resolve => { finish = resolve; }) : Promise.resolve(path.endsWith("/documents") ? response([processingDoc]) : response(kbs)));
  vi.stubGlobal("fetch", fetcher);
  await act(async () => root.render(<KnowledgePage onError={onError} />));
  await selectKb("a");
  const input = host.querySelector<HTMLInputElement>('input[type="file"]')!;
  const file = new File(["contents"], "guide.md", { type: "text/markdown" });
  Object.defineProperty(input, "files", { configurable: true, value: [file] });
  const clear = vi.spyOn(input, "value", "set");
  await act(async () => input.dispatchEvent(new Event("change", { bubbles: true })));
  expect(host.querySelector('[role="progressbar"][aria-label="文件上传进度"]')?.getAttribute("aria-valuenow")).toBe("50");
  expect(host.textContent).toContain("正在传输文件");
  expect(fetcher.mock.calls.at(-1)?.[0]).toBe("/api/v1/kb/a/documents/upload");
  expect((fetcher.mock.calls.at(-1)?.[1]?.body as FormData).get("file")).toBe(file);
  // Changing the destination while upload is pending must not reassign it.
  await selectKb("b");
  await act(async () => finish(response({ id: "doc" })));
  expect(host.textContent).toContain("正在等待后台建立索引");
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
  const fetcher = vi.fn((path: string, init?: RequestInit) => Promise.resolve(
    init?.method === "POST" ? response({ id: "doc" }) : path === "/api/v1/kb" ? ++reads === 1 ? response(kbs) : response(null, 503) : response([])));
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
    ? Promise.resolve(new Response(JSON.stringify({ data: null, info: "上传失败" }), { status: 500 })) : Promise.resolve(response(kbs)));
  vi.stubGlobal("fetch", fetcher);
  await act(async () => root.render(<KnowledgePage onError={onError} />));
  await selectKb("a");
  const input = host.querySelector<HTMLInputElement>('input[type="file"]')!;
  Object.defineProperty(input, "files", { configurable: true, value: [new File(["x"], "guide.md")] });
  const clear = vi.spyOn(input, "value", "set");
  await act(async () => input.dispatchEvent(new Event("change", { bubbles: true })));
  expect(clear).not.toHaveBeenCalled();
  expect(onError).toHaveBeenCalledExactlyOnceWith("上传失败");
  expect(fetcher.mock.calls.filter(call => call[1]?.method === "POST")).toHaveLength(1);
});

it("shows a failed indexing reason and retries the stored upload after configuration is fixed", async () => {
  let reads = 0;
  const failed = { id: "doc-1", kb_id: "a", name: "guide.md", status: "error", chunk_count: 0, total_tokens: 0,
    error_message: "Knowledge task failed", task_id: "task-1", task_status: "failed", task_error_message: "No channel supports model: text-embedding-3-small" };
  const pending = { ...failed, status: "pending", error_message: null, task_status: "pending", task_error_message: null, task_progress: 0 };
  const fetcher = vi.fn((path: string, init?: RequestInit) => Promise.resolve(
    init?.method === "POST" ? response(pending)
      : path === "/api/v1/kb" ? response(kbs)
        : path.endsWith("/documents") ? response([++reads === 1 ? failed : pending])
          : response([])));
  vi.stubGlobal("fetch", fetcher);
  await act(async () => root.render(<KnowledgePage onError={onError} />));
  await selectKb("a");
  expect(host.textContent).toContain("处理失败");
  expect(host.textContent).toContain("text-embedding-3-small");
  expect(host.querySelector('a[href="#/channels"]')).not.toBeNull();
  await act(async () => Array.from(host.querySelectorAll("button")).find(button => button.textContent === "修复配置后重试")!.click());
  expect(fetcher).toHaveBeenCalledWith("/api/v1/kb/a/documents/doc-1/retry", expect.objectContaining({ method: "POST", body: "{}" }));
  expect(host.textContent).toContain("排队处理中");
  expect(onError).not.toHaveBeenCalled();
});
