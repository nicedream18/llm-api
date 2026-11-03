import { useCallback, useEffect, useRef, useState } from "react";
import { get } from "./api";
import { errorText } from "./securityModel";

export function useSecurityResource<T>(path: string) {
  const [state, setState] = useState<{ path: string; data: T | null; loading: boolean; error: string }>({ path, data: null, loading: true, error: "" });
  const version = useRef(0); const controller = useRef<AbortController | null>(null); const alive = useRef(true);
  const reload = useCallback(async (): Promise<T | null> => {
    controller.current?.abort(); const request = new AbortController(); controller.current = request; const id = ++version.current;
    setState(previous => ({ path, data: previous.path === path ? previous.data : null, loading: true, error: "" }));
    try {
      const data = await get<T>(path, { signal: request.signal });
      if (alive.current && id === version.current && !request.signal.aborted) { setState({ path, data, loading: false, error: "" }); return data; }
    } catch (error) { if (alive.current && id === version.current && !request.signal.aborted) setState(previous => ({ ...previous, path, loading: false, error: errorText(error) })); }
    return null;
  }, [path]);
  useEffect(() => { alive.current = true; void reload(); return () => { alive.current = false; version.current++; controller.current?.abort(); }; }, [reload]);
  const commit = useCallback((update: T | ((previous: T | null) => T)) => {
    version.current++; controller.current?.abort();
    if (alive.current) setState(previous => ({ path, data: typeof update === "function" ? (update as (value: T | null) => T)(previous.data) : update, error: "", loading: false }));
  }, [path]);
  return { data: state.path === path ? state.data : null, error: state.path === path ? state.error : "", loading: state.path !== path || state.loading, reload, commit };
}
