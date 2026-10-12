/** Minimal fetch wrapper for the PeakSift API. Cookies are always sent. */

export const API_URL = (process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000").replace(
  /\/$/,
  "",
);

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

type ValidationItem = { msg?: string; loc?: (string | number)[] };

export function messageFrom(data: unknown, status: number): string {
  const detail = (data as { detail?: unknown } | null)?.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    const messages = (detail as ValidationItem[])
      .map((item) => item.msg?.replace(/^Value error, /, ""))
      .filter(Boolean);
    if (messages.length) return messages.join(" ");
  }
  return status >= 500 ? "Something went wrong on the server. Please try again." : "Request failed.";
}

export async function apiFetch<T>(path: string, init: RequestInit = {}): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_URL}${path}`, {
      ...init,
      credentials: "include",
      headers: {
        ...(init.body ? { "Content-Type": "application/json" } : {}),
        ...init.headers,
      },
    });
  } catch {
    throw new ApiError(0, "Could not reach the server. Check your connection and try again.");
  }

  if (response.status === 204) return undefined as T;

  const data: unknown = await response.json().catch(() => null);
  if (!response.ok) throw new ApiError(response.status, messageFrom(data, response.status));
  return data as T;
}

export function postJson<T>(path: string, body: unknown): Promise<T> {
  return apiFetch<T>(path, { method: "POST", body: JSON.stringify(body) });
}

/** A readable message for any thrown value. */
export function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "Something went wrong.";
}
