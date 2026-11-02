import { useCallback, useEffect, useRef, useState } from "react";
import { get } from "./api";

export function useAction(onError: (message: string) => void) {
  const [busy, setBusy] = useState(false);
  const pending = useRef(false);
  const run = async (action: () => Promise<void>) => {
    if (pending.current) return;
    pending.current = true; setBusy(true);
    try { await action(); } catch (error) { onError(error instanceof Error ? error.message : "操作失败"); }
    finally { pending.current = false; setBusy(false); }
  };
  return [busy, run] as const;
}

export function useResource<T>(path: string, onError: (message: string) => void) {
  const [value, setValue] = useState<T | null>(null);
  const [revision, setRevision] = useState(0);
  const [error, setError] = useState("");
  const reload = useCallback(() => setRevision(value => value + 1), []);
  useEffect(() => {
    const controller = new AbortController(); setValue(null); setError("");
    get<T>(path, { signal: controller.signal }).then(result => { if (!controller.signal.aborted) setValue(result); }).catch(error => { if (!controller.signal.aborted) { setError(error.message); onError(error.message); } });
    return () => controller.abort();
  }, [path, revision, onError]);
  return [value, reload, { error, loading: value === null && !error }] as const;
}

export const lines = (value: string) => Array.from(new Set(value.split(/[\n,]/).map(item => item.trim()).filter(Boolean)));
