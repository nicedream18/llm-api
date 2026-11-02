import { useEffect, useLayoutEffect, useRef, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";

/** Portals the menu outside the scrolling table, keeping every action visible. */
export function ActionMenu({ label, children }: { label: string; children: ReactNode }) {
  const [open, setOpen] = useState(false);
  const [position, setPosition] = useState({ top: 0, left: 0 });
  const trigger = useRef<HTMLButtonElement>(null);
  const panel = useRef<HTMLDivElement>(null);
  const target = trigger.current?.closest(".management-page, .channel-page") || document.body;
  useLayoutEffect(() => {
    if (!open || !trigger.current || !panel.current) return;
    const anchor = trigger.current.getBoundingClientRect();
    const box = panel.current.getBoundingClientRect();
    setPosition({ top: Math.max(8, Math.min(anchor.bottom + 6, window.innerHeight - box.height - 8)), left: Math.max(8, Math.min(anchor.right - box.width, window.innerWidth - box.width - 8)) });
    panel.current.querySelector<HTMLButtonElement>("button:not(:disabled)")?.focus();
  }, [open]);
  useEffect(() => {
    if (!open) return;
    const outside = (event: PointerEvent) => {
      const node = event.target as Node;
      if (!trigger.current?.contains(node) && !panel.current?.contains(node)) setOpen(false);
    };
    const escape = (event: KeyboardEvent) => {
      if (event.key === "Escape") { setOpen(false); trigger.current?.focus(); }
    };
    document.addEventListener("pointerdown", outside); document.addEventListener("keydown", escape);
    return () => { document.removeEventListener("pointerdown", outside); document.removeEventListener("keydown", escape); };
  }, [open]);
  return <div className="action-menu"><button ref={trigger} type="button" className="action-menu-trigger" aria-label={label} title="更多操作" aria-expanded={open} onClick={() => setOpen(value => !value)}>•••</button>{open && createPortal(<div ref={panel} className="action-menu-popover" role="group" aria-label={label} style={{ position: "fixed", top: position.top, left: position.left, right: "auto", zIndex: 30, maxHeight: "calc(100dvh - 16px)", overflowY: "auto" }} onClickCapture={event => { if ((event.target as Element).closest("button:not(:disabled)")) trigger.current?.focus(); }} onClick={event => { if ((event.target as Element).closest("button:not(:disabled)")) setOpen(false); }}>{children}</div>, target)}</div>;
}
