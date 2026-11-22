import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "./api";

/** Minimal data hook: load, reload, error. */
export function useApi<T = any>(path: string | null, deps: any[] = []) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<any>(null);
  const [loading, setLoading] = useState(!!path);
  const alive = useRef(true);
  const load = useCallback(async () => {
    if (!path) { setLoading(false); return; }
    setLoading(true); setError(null);
    try { const d = await api<T>(path); if (alive.current) setData(d); }
    catch (e) { if (alive.current) setError(e); }
    finally { if (alive.current) setLoading(false); }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [path, ...deps]);
  useEffect(() => { alive.current = true; load(); return () => { alive.current = false; }; }, [load]);
  return { data, setData, error, loading, reload: load };
}

export function useAction<A extends any[], R>(fn: (...a: A) => Promise<R>) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<any>(null);
  const run = useCallback(async (...a: A) => {
    setBusy(true); setError(null);
    try { return await fn(...a); } catch (e) { setError(e); throw e; } finally { setBusy(false); }
  }, [fn]);
  return { run, busy, error, setError };
}
