/**
 * Auth client — session check, login, logout against the FastAPI auth
 * endpoints. When the backend has no admin credentials configured it runs
 * in demo mode: /auth/session answers { authenticated: true } and the
 * console is open. zod-parsed at the boundary like the other clients.
 */

import { z } from "zod";

const sessionSchema = z.object({
  authenticated: z.boolean(),
  user: z.string().nullable().optional(),
});

export type Session = z.infer<typeof sessionSchema>;

export class AuthError extends Error {
  constructor(
    message: string,
    readonly kind: "network" | "credentials" | "http",
  ) {
    super(message);
    this.name = "AuthError";
  }
}

async function parseSession(resp: Response): Promise<Session> {
  const json: unknown = await resp.json().catch(() => null);
  const parsed = sessionSchema.safeParse(json);
  if (!parsed.success) throw new AuthError("Unexpected session response.", "http");
  return parsed.data;
}

/** Current session. Network failure answers unauthenticated so the console
    guard fails closed to /login rather than rendering stale data. */
export async function fetchSession(signal?: AbortSignal): Promise<Session> {
  try {
    const resp = await fetch("/auth/session", {
      credentials: "same-origin",
      signal,
      cache: "no-store",
    });
    if (!resp.ok) return { authenticated: false, user: null };
    return await parseSession(resp);
  } catch (err) {
    if (err instanceof DOMException && err.name === "AbortError") throw err;
    if (err instanceof AuthError) throw err;
    return { authenticated: false, user: null };
  }
}

export async function login(username: string, password: string): Promise<Session> {
  let resp: Response;
  try {
    resp = await fetch("/auth/login", {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, password }),
    });
  } catch {
    throw new AuthError("The gate backend is unreachable.", "network");
  }
  if (resp.status === 401) {
    throw new AuthError("Wrong username or password.", "credentials");
  }
  if (!resp.ok) {
    throw new AuthError(`Login failed (HTTP ${resp.status}).`, "http");
  }
  return parseSession(resp);
}

export async function logout(): Promise<void> {
  try {
    await fetch("/auth/logout", { method: "POST", credentials: "same-origin" });
  } catch {
    // Logout is best-effort: the cookie expires server-side regardless.
  }
}
