import { apiFetch, postJson } from "@/lib/api";

export type User = {
  id: string;
  email: string;
  created_at: string;
};

export type Credentials = { email: string; password: string };

/** Where to send people once they are signed in. */
export const AFTER_AUTH_PATH = "/home";

/** Who is signed in, if anyone (200 either way, so a signed-out visit logs no failed request). */
export const getSession = () => apiFetch<{ user: User | null }>("/auth/session").then((session) => session.user);
export const register = (credentials: Credentials) => postJson<User>("/auth/register", credentials);
export const login = (credentials: Credentials) => postJson<User>("/auth/login", credentials);
export const logout = () => postJson<void>("/auth/logout", undefined);
