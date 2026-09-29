/**
 * The whole HTTP layer: one thin, typed wrapper over native `fetch`
 * (docs/DESIGN_DECISIONS.md Q27, gap F14).
 *
 * Requests are same-origin (Q34), so paths are relative, no base URL is needed,
 * and the refresh cookie rides along with every same-origin request (S9).
 * Non-2xx responses throw an `ApiError` carrying the server's `detail`.
 *
 * Authentication and renewal (gaps S4/F4/F5/S7/S9): the bearer token is read
 * from the in-memory session store, never from storage. A `401` asks the
 * session refresher — registered by `AuthProvider` — for a fresh token once and
 * replays the request; a `401` that survives that (or finds no refresher) ends
 * the session through the registered unauthorized handler.
 */

import { getAccessToken } from "./auth/token";

type UnauthorizedHandler = () => void;

let unauthorizedHandler: UnauthorizedHandler | null = null;

/** Registered by `AuthProvider`; called once per rejected request. */
export function setUnauthorizedHandler(handler: UnauthorizedHandler | null): void {
  unauthorizedHandler = handler;
}

/**
 * Silent renewal: trades the refresh cookie for a new access token.
 * Single-flight and `false`-able — a `401` is retried only when it answers
 * `true`, so a failed refresh ends the session instead of looping (gap S7).
 */
type SessionRefresher = () => Promise<boolean>;

let sessionRefresher: SessionRefresher | null = null;

/** Registered by `AuthProvider` for as long as a session could need renewing. */
export function setSessionRefresher(refresher: SessionRefresher | null): void {
  sessionRefresher = refresher;
}

/** A failed request: a non-2xx response, or status `0` when the network failed. */
export class ApiError extends Error {
  readonly status: number;
  /** FastAPI's `detail` when it is a string (validation errors use an array, so this is unset). */
  readonly detail?: string;

  constructor(status: number, fallback: string, detail?: string) {
    super(detail ?? fallback);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}

export function isApiError(error: unknown): error is ApiError {
  return error instanceof ApiError;
}

/** True when the request failed because the token is missing, invalid or expired. */
export function isUnauthorized(error: unknown): boolean {
  return isApiError(error) && error.status === 401;
}

interface RequestOptions {
  /** Login must not trigger the session-expired redirect on its own 401. */
  skipUnauthorizedHandler?: boolean;
  /** Refresh and logout must not recurse into a refresh of their own (S7). */
  skipRefresh?: boolean;
  /** Internal: the post-refresh replay — one rescue attempt per request. */
  retried?: boolean;
}

async function readBody(response: Response): Promise<unknown> {
  if (response.status === 204) return null;
  const text = await response.text();
  if (!text) return null;
  try {
    return JSON.parse(text) as unknown;
  } catch {
    return text;
  }
}

function readDetail(data: unknown): string | undefined {
  if (data === null || typeof data !== "object" || !("detail" in data)) return undefined;
  const { detail } = data as { detail?: unknown };
  return typeof detail === "string" ? detail : undefined;
}

async function request<T>(
  method: string,
  path: string,
  body?: unknown,
  options: RequestOptions = {}
): Promise<T> {
  const headers = new Headers({ Accept: "application/json" });
  const token = getAccessToken();
  if (token) {
    headers.set("Authorization", `Bearer ${token}`);
  }

  let payload: BodyInit | undefined;
  if (body instanceof URLSearchParams) {
    headers.set("Content-Type", "application/x-www-form-urlencoded");
    payload = body;
  } else if (body !== undefined) {
    headers.set("Content-Type", "application/json");
    payload = JSON.stringify(body);
  }

  let response: Response;
  try {
    response = await fetch(path, { method, headers, body: payload });
  } catch {
    throw new ApiError(0, "Network request failed");
  }

  const data = await readBody(response);

  if (!response.ok) {
    if (response.status === 401 && !options.skipUnauthorizedHandler) {
      // One rescue attempt: renew via the refresh cookie, then replay the
      // request with the new token. A renewal that fails — or a replay that
      // still 401s — ends the session (gaps S7/S9).
      if (sessionRefresher && !options.skipRefresh && !options.retried) {
        const renewed = await sessionRefresher();
        if (renewed) {
          return request<T>(method, path, body, { ...options, retried: true });
        }
      }
      unauthorizedHandler?.();
    }
    throw new ApiError(
      response.status,
      `Request failed with status ${response.status}`,
      readDetail(data)
    );
  }

  return data as T;
}

function buildQuery(params: Record<string, string | number | undefined>): string {
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined) query.set(key, String(value));
  }
  const serialized = query.toString();
  return serialized ? `?${serialized}` : "";
}

export function apiGet<T>(
  path: string,
  params: Record<string, string | number | undefined> = {}
): Promise<T> {
  return request<T>("GET", `${path}${buildQuery(params)}`);
}

export function apiPost<T>(
  path: string,
  body?: unknown,
  options?: RequestOptions
): Promise<T> {
  return request<T>("POST", path, body, options);
}

export function apiDelete<T>(path: string): Promise<T> {
  return request<T>("DELETE", path);
}
