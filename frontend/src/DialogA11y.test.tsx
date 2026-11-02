/** @vitest-environment jsdom */
import { act } from "react";
import { createRoot } from "react-dom/client";
import { expect, it, vi } from "vitest";
import { DialogA11y } from "./DialogA11y";

it("focuses the form, traps keyboard navigation, closes on Escape and restores the opener", async () => {
  vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true);
  const host = document.createElement("div"); document.body.append(host);
  const root = createRoot(host); const close = vi.fn();
  try {
    await act(async () => root.render(<><button id="opener">编辑</button></>));
    const opener = host.querySelector<HTMLButtonElement>("#opener")!; opener.focus();
    await act(async () => root.render(<><button id="opener">编辑</button><div className="drawer-backdrop"><section role="dialog" aria-label="编辑"><DialogA11y onClose={close} /><input aria-label="名称" /><button id="last">保存</button></section></div></>));
    expect(document.activeElement).toBe(host.querySelector("input"));
    expect(opener.inert).toBe(true);
    expect(document.body.style.overflow).toBe("hidden");
    const last = host.querySelector<HTMLButtonElement>("#last")!;
    await act(async () => host.querySelector("input")!.dispatchEvent(new KeyboardEvent("keydown", { key: "Tab", shiftKey: true, bubbles: true, cancelable: true })));
    expect(document.activeElement).toBe(last);
    await act(async () => last.dispatchEvent(new KeyboardEvent("keydown", { key: "Tab", bubbles: true, cancelable: true })));
    expect(document.activeElement).toBe(host.querySelector("input"));
    await act(async () => last.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true, cancelable: true })));
    expect(close).toHaveBeenCalledOnce();
    await act(async () => root.render(<><button id="opener">编辑</button></>));
    expect(document.activeElement).toBe(opener);
    expect(opener.inert).toBeFalsy();
    expect(document.body.style.overflow).toBe("");
  } finally { await act(async () => root.unmount()); host.remove(); vi.unstubAllGlobals(); }
});
