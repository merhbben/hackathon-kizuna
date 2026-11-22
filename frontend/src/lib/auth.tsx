import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import { api, getToken, setToken } from "./api";
import i18n from "../i18n";

export type User = { id: number; email: string; full_name: string; role: "ministry" | "farmer"; governorate_code: string | null; language: "fr" | "ar" };

type Ctx = {
  user: User | null; loading: boolean;
  login: (email: string, password: string) => Promise<void>;
  register: (data: { email: string; full_name: string; password: string; governorate_code?: string }) => Promise<void>;
  logout: () => void;
};
const AuthCtx = createContext<Ctx>(null as any);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const onLogout = () => setUser(null);
    window.addEventListener("agrosphere:logout", onLogout);
    if (getToken()) api<User>("/api/auth/me").then(setUser).catch(() => setToken(null)).finally(() => setLoading(false));
    else setLoading(false);
    return () => window.removeEventListener("agrosphere:logout", onLogout);
  }, []);

  const login = useCallback(async (email: string, password: string) => {
    const form = new URLSearchParams({ username: email, password });
    const r = await api<{ access_token: string; user: User }>("/api/auth/token", { method: "POST", form });
    setToken(r.access_token); setUser(r.user);
  }, []);
  const register = useCallback(async (data: any) => {
    const r = await api<{ access_token: string; user: User }>("/api/auth/register", { method: "POST", json: { ...data, language: i18n.language } });
    setToken(r.access_token); setUser(r.user);
  }, []);
  const logout = useCallback(() => { setToken(null); setUser(null); }, []);
  return <AuthCtx.Provider value={{ user, loading, login, register, logout }}>{children}</AuthCtx.Provider>;
}

export const useAuth = () => useContext(AuthCtx);
