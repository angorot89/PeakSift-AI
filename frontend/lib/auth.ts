import { apiFetch, postJson } from "@/lib/api";

export type User = {
  id: string;
  email: string;
  created_at: string;
};

export type Credentials = { email: string; password: string };

/** Where to send people once they are signed in. */
export const AFTER_AUTH_PATH = "/";

export const getCurrentUser = () => apiFetch<User>("/auth/me");
export const register = (credentials: Credentials) => postJson<User>("/auth/register", credentials);
export const login = (credentials: Credentials) => postJson<User>("/auth/login", credentials);
export const logout = () => postJson<void>("/auth/logout", undefined);
