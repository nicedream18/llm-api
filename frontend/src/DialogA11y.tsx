import { useLayoutEffect, useRef } from "react";

/** Keeps keyboard focus inside a mounted drawer and restores its opener. */
export function DialogA11y({ onClose }: { onClose: () => void }) {
  const marker = useRef<HTMLSpanElement>(null);
  const close = useRef(onClose);
  close.current = onClose;
  useLayoutEffect(() => {
    const dialog = marker.current?.closest<HTMLElement>('[role="dialog"]');
    if (!dialog) return;
    const opener = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const overflow = document.body.style.overflow;
    const inertNodes: Array<[HTMLElement, boolean]> = [];
    let branch: HTMLElement = dialog;
    while (branch.parentElement && branch.parentElement !== document.body) {
      for (const sibling of Array.from(branch.parentElement.children)) {
        if (sibling !== branch && sibling instanceof HTMLElement) {
          inertNodes.push([sibling, sibling.inert]); sibling.inert = true;
        }
      }
      branch = branch.parentElement;
    }
    document.body.style.overflow = "hidden";
    const focusable = () => Array.from(dialog.querySelectorAll<HTMLElement>('button, a[href], input, select, textarea, summary, [tabindex="0"]')).filter(element => {
      const details = element.closest("details:not([open])");
      return !element.matches(':disabled, [type="hidden"]') && (!details || element === details.querySelector("summary")) && getComputedStyle(element).display !== "none";
    });
    const firstInput = dialog.querySelector<HTMLElement>('input:not([type="hidden"]), select, textarea');
    (firstInput || focusable()[0] || dialog).focus();
    const keydown = (event: KeyboardEvent) => {
      if (event.key === "Escape") { event.preventDefault(); event.stopPropagation(); close.current(); return; }
      if (event.key !== "Tab") return;
      const items = focusable(); const first = items[0]; const last = items[items.length - 1];
      if (!first) { event.preventDefault(); return; }
      if (event.shiftKey && (document.activeElement === first || !dialog.contains(document.activeElement))) { event.preventDefault(); last.focus(); }
      else if (!event.shiftKey && (document.activeElement === last || !dialog.contains(document.activeElement))) { event.preventDefault(); first.focus(); }
    };
    dialog.addEventListener("keydown", keydown);
    return () => {
      dialog.removeEventListener("keydown", keydown);
      document.body.style.overflow = overflow;
      inertNodes.forEach(([element, wasInert]) => { element.inert = wasInert; });
      if (opener?.isConnected) opener.focus();
    };
  }, []);
  return <span ref={marker} hidden aria-hidden="true" />;
}
