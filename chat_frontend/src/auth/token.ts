import { jwtDecode } from "jwt-decode";

/**
 * The access token lives **in memory only**.
 *
 * Nothing JavaScript-readable survives a reload: the durable half of the
 * session is a refresh token in an `HttpOnly` cookie the DOM never sees, and
 * `AuthProvider` trades it for a fresh access token on boot. The legacy
 * `localStorage` key — the old storage — is read once, adopted if still
 * valid, and deleted either way, so an already-signed-in browser migrates off
 * the XSS-readable copy on its first visit after this ships.
 */
const LEGACY_TOKEN_KEY = "token";

let accessToken: string | null = null;

export interface TokenPayload {
  sub: string;
  exp: number;
}

function decodeToken(token: string): TokenPayload | null {
  try {
    const payload = jwtDecode<TokenPayload>(token);
    if (
      !payload.sub ||
      !Number.isInteger(Number(payload.sub)) ||
      !Number.isFinite(payload.exp)
    ) {
      return null;
    }
    return payload;
  } catch {
    return null;
  }
}

/** The in-memory token as it stands — valid or not. */
export function getAccessToken(): string | null {
  return accessToken;
}

/** The in-memory token only while it is still usable; expired means cleared. */
export function getValidAccessToken(): string | null {
  if (!accessToken) return null;
  const payload = decodeToken(accessToken);
  if (!payload || payload.exp * 1000 <= Date.now()) {
    accessToken = null;
    return null;
  }
  return accessToken;
}

export function setAccessToken(token: string): void {
  accessToken = token;
}

export function clearAccessToken(): void {
  accessToken = null;
}

/**
 * Adopt the legacy `localStorage` token — if it still qualifies — and remove
 * the stored copy in every case. Moving it out of `localStorage` is the whole
 * point; keeping an expired one around would only preserve the leak.
 */
export function takeLegacyToken(): string | null {
  const stored = localStorage.getItem(LEGACY_TOKEN_KEY);
  localStorage.removeItem(LEGACY_TOKEN_KEY);
  if (!stored) return null;
  const payload = decodeToken(stored);
  if (!payload || payload.exp * 1000 <= Date.now()) return null;
  accessToken = stored;
  return stored;
}

export function getTokenUserId(token: string | null): number | null {
  if (!token) return null;
  const payload = decodeToken(token);
  return payload ? Number(payload.sub) : null;
}

export function getTokenExpiration(token: string): number | null {
  const payload = decodeToken(token);
  return payload ? payload.exp * 1000 : null;
}
