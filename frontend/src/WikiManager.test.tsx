/** @vitest-environment jsdom */
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";
import { WikiManager } from "./WikiManager";

function payload(data: unknown, status = 200) {
  return new Response(JSON.stringify({ code: status >= 400 ? "error" : "ok", info: status >= 400 ? "error" : "", data }), { status });
}

describe("Wiki manager workflow", () => {
  let root: Root | undefined;
  let host: HTMLDivElement | undefined;

  afterEach(() => {
    root?.unmount();
    host?.remove();
    vi.unstubAllGlobals();
  });

  it("loads a project and submits a Wiki question with cited sources", async () => {
    const fetchMock = vi.fn((path: string, init?: RequestInit) => {
      if (path === "/api/v1/wiki/projects") return Promise.resolve(payload([{ id: "project-1", name: "Manual" }]));
      if (path === "/api/v1/wiki/projects/project-1" && (!init || !init.method)) return Promise.resolve(payload({ id: "project-1", name: "Manual", description: "Docs" }));
      if (path.startsWith("/api/v1/wiki/projects/project-1/pages?") && (!init || !init.method)) return Promise.resolve(payload({ items: [], total: 0 }));
      if (path === "/api/v1/wiki/projects/project-1/tags") return Promise.resolve(payload([]));
      if (path === "/api/v1/wiki/projects/project-1/sources") return Promise.resolve(payload([]));
      if (path === "/api/v1/wiki/projects/project-1/graph") return Promise.resolve(payload({ nodes: [], edges: [] }));
      if (path === "/api/v1/wiki/projects/project-1/ask" && init?.method === "POST") return Promise.resolve(payload({ answer: "Use the getting started guide.", sources: [{ page_id: "page-1", path: "guide.md", title: "Guide", content: "Start here." }] }));
      return Promise.resolve(payload(null, 404));
    });
    vi.stubGlobal("fetch", fetchMock);
    host = document.createElement("div");
    document.body.appendChild(host);
    root = createRoot(host);
    await act(async () => { root?.render(<WikiManager onError={vi.fn()} />); await Promise.resolve(); await Promise.resolve(); });
    expect(host.textContent).toContain("Wiki 问答");
    const question = host.querySelector<HTMLTextAreaElement>("textarea[aria-label='Wiki 问题']");
    expect(question).not.toBeNull();
    const setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value")?.set;
    setter?.call(question, "如何开始？");
    question?.dispatchEvent(new Event("input", { bubbles: true }));
    await act(async () => { await Promise.resolve(); });
    const form = question?.closest("form");
    expect(form).not.toBeNull();
    await act(async () => { form?.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true })); await Promise.resolve(); await Promise.resolve(); });
    expect(fetchMock).toHaveBeenCalledWith("/api/v1/wiki/projects/project-1/ask", expect.objectContaining({ method: "POST" }));
    expect(host.textContent).toContain("Use the getting started guide.");
    expect(host.textContent).toContain("guide.md");
  });
});
