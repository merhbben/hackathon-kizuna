const TOKEN_KEY = "agrosphere.token";

export function getToken(): string | null {
  try { return localStorage.getItem(TOKEN_KEY); } catch { return null; }
}
export function setToken(t: string | null) {
  try { t ? localStorage.setItem(TOKEN_KEY, t) : localStorage.removeItem(TOKEN_KEY); } catch { /* private mode */ }
}

export class ApiError extends Error {
  status: number;
  detail: any;
  constructor(status: number, detail: any) {
    super(typeof detail === "string" ? detail : detail?.code || JSON.stringify(detail));
    this.status = status;
    this.detail = detail;
  }
}

const BASE = (import.meta as any).env?.VITE_API_URL || "";

export async function api<T = any>(path: string, opts: RequestInit & { json?: any; form?: FormData | URLSearchParams } = {}): Promise<T> {
  const headers: Record<string, string> = { ...(opts.headers as any) };
  const token = getToken();
  if (token) headers.Authorization = `Bearer ${token}`;
  let body: BodyInit | undefined = opts.body as any;
  if (opts.json !== undefined) { headers["Content-Type"] = "application/json"; body = JSON.stringify(opts.json); }
  if (opts.form) body = opts.form;
  const res = await fetch(`${BASE}${path}`, { ...opts, headers, body });
  if (res.status === 401 && token) { setToken(null); window.dispatchEvent(new Event("agrosphere:logout")); }
  if (!res.ok) {
    let detail: any = res.statusText;
    try { detail = (await res.json()).detail; } catch { /* not json */ }
    throw new ApiError(res.status, detail);
  }
  if (res.status === 204) return undefined as T;
  const ct = res.headers.get("content-type") || "";
  return (ct.includes("json") ? res.json() : res.blob()) as Promise<T>;
}

export async function download(path: string, filename: string) {
  const blob = await api<Blob>(path);
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url; a.download = filename; a.click();
  URL.revokeObjectURL(url);
}
