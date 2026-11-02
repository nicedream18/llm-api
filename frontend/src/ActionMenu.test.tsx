/** @vitest-environment jsdom */
import { act } from "react";
import { createRoot } from "react-dom/client";
import { expect, it, vi } from "vitest";
import { ActionMenu } from "./ActionMenu";

it("renders outside the table scroll container and restores focus on Escape", async () => {
  vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true);
  const host = document.createElement("div"); document.body.append(host); const root = createRoot(host);
  try {
    await act(async () => root.render(<section className="management-page"><div className="table-wrap"><ActionMenu label="更多操作"><button>同步模型</button></ActionMenu></div></section>));
    const trigger = host.querySelector<HTMLButtonElement>(".action-menu-trigger")!;
    await act(async () => trigger.click());
    const panel = host.querySelector<HTMLElement>(".action-menu-popover")!;
    expect(panel.closest(".table-wrap")).toBeNull();
    expect(panel.style.position).toBe("fixed");
    expect(panel.textContent).toContain("同步模型");
    await act(async () => document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape" })));
    expect(host.querySelector(".action-menu-popover")).toBeNull();
    expect(document.activeElement).toBe(trigger);
  } finally { await act(async () => root.unmount()); host.remove(); vi.unstubAllGlobals(); }
});
