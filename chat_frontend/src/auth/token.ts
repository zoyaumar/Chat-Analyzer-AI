import { jwtDecode } from "jwt-decode";

const TOKEN_KEY = "token";

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

export function getValidStoredToken(): string | null {
  const token = localStorage.getItem(TOKEN_KEY);
  if (!token) return null;

  const payload = decodeToken(token);
  if (!payload || payload.exp * 1000 <= Date.now()) {
    clearStoredToken();
    return null;
  }
  return token;
}

export function setStoredToken(token: string): void {
  localStorage.setItem(TOKEN_KEY, token);
}

export function clearStoredToken(): void {
  localStorage.removeItem(TOKEN_KEY);
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
