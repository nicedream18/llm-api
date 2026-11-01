import { afterEach, describe, expect, it, vi } from "vitest";
import { api } from "./api";

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
});
