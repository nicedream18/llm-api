import { afterEach, describe, expect, it, vi } from "vitest";
import { api, downloadFile, upload, uploadRaw } from "./api";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("api client", () => {
  it("returns the data envelope and sends session credentials", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ code: "ok", info: "", data: { id: 1 } }), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);

    await expect(api<{ id: number }>("/api/v1/example")).resolves.toEqual({ id: 1 });
    expect(fetchMock).toHaveBeenCalledWith("/api/v1/example", expect.objectContaining({ credentials: "include" }));
  });

  it("raises the server message for failed responses", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({ code: "error", info: "拒绝访问", data: null }), { status: 403 })));

    await expect(api("/api/v1/secret")).rejects.toThrow("拒绝访问");
  });

  it("uploads a file without overriding the multipart content type", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ code: "ok", info: "", data: { id: "doc-1" } }), { status: 201 }));
    vi.stubGlobal("fetch", fetchMock);
    const file = new File(["hello"], "hello.txt", { type: "text/plain" });

    await expect(upload<{ id: string }>("/api/v1/kb/kb-1/documents/upload", file)).resolves.toEqual({ id: "doc-1" });
    const init = fetchMock.mock.calls[0][1] as RequestInit;
    expect(init.headers).toEqual({ Accept: "application/json" });
    expect(init.body).toBeInstanceOf(FormData);
  });

  it("uploads a raw attachment body with its media type and session credentials", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ code: "ok", info: "", data: { id: "asset-1" } }), { status: 201 }));
    vi.stubGlobal("fetch", fetchMock);
    const file = new File(["image"], "image.png", { type: "image/png" });

    await expect(uploadRaw<{ id: string }>("/api/v1/wiki/projects/p/pages/x/attachments?filename=image.png", file)).resolves.toEqual({ id: "asset-1" });
    expect(fetchMock).toHaveBeenCalledWith(expect.stringContaining("attachments?filename="), expect.objectContaining({
      method: "POST", credentials: "include", body: file,
      headers: { "Content-Type": "image/png", Accept: "application/json" },
    }));
  });

  it("downloads authenticated backups as files", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response("backup", { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    const click = vi.fn();
    const anchor = { href: "", download: "", click };
    vi.stubGlobal("document", { createElement: vi.fn().mockReturnValue(anchor) });
    vi.stubGlobal("window", { setTimeout: (callback: () => void) => callback() });
    vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:backup");
    vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => {});

    await downloadFile("/api/v1/wiki/projects/p/backup", "wiki-backup.json");
    expect(fetchMock).toHaveBeenCalledWith("/api/v1/wiki/projects/p/backup", { credentials: "include" });
    expect(anchor.download).toBe("wiki-backup.json");
    expect(click).toHaveBeenCalledOnce();
  });
});
