/** @vitest-environment jsdom */
import { act } from "react";
import { createRoot } from "react-dom/client";
import { expect, it, vi } from "vitest";
import { AdministrationPanel } from "./AdministrationPanel";

it("shows diagnostics and audit, revokes sessions only after confirmation", async () => {
  vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true);
  const fetcher = vi.fn((path: string) => Promise.resolve(new Response(JSON.stringify({ data: path.includes("diagnostics") ? { database: "ok" } : path.includes("audit") ? [{ id: "a", action: "end:POST:/api/v1/channels", username: "admin", success: true, request_id: "r" }] : [{ id: "session1", created_at: 1, expires_at: 2, revoked_at: null }] }))));
  vi.stubGlobal("fetch", fetcher);
  const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
  const host = document.createElement("div"); const root = createRoot(host);
  try {
    await act(async () => root.render(<AdministrationPanel onError={vi.fn()} />));
    expect(host.textContent).toContain('"database": "ok"'); expect(host.textContent).toContain("end:POST");
    const revoke = Array.from(host.querySelectorAll("button")).find(item => item.textContent?.startsWith("撤销会话"))!;
    await act(async () => revoke.click()); expect(fetcher.mock.calls.length).toBe(3);
    confirm.mockReturnValue(true); await act(async () => revoke.click());
    expect(fetcher).toHaveBeenCalledWith("/api/v1/auth/sessions/session1", expect.objectContaining({ method: "DELETE" }));
  } finally { await act(async () => root.unmount()); vi.restoreAllMocks(); vi.unstubAllGlobals(); }
});
