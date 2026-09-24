import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { getMessages, loginUser } from "./api";
import {
  ApiError,
  apiGet,
  apiPost,
  isApiError,
  setUnauthorizedHandler,
} from "./apiClient";

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

/** Resolves with the `ApiError` a failing request throws, so assertions stay readable. */
async function captureError(action: () => Promise<unknown>): Promise<ApiError> {
  try {
    await action();
  } catch (error) {
    if (isApiError(error)) return error;
    throw error;
  }
  throw new Error("Expected the request to reject");
}

function lastRequest(fetchMock: ReturnType<typeof vi.fn>): [string, RequestInit] {
  return fetchMock.mock.calls.at(-1) as [string, RequestInit];
}

describe("apiClient", () => {
  const fetchMock = vi.fn();

  /** Each call must return a fresh `Response`, because a body can only be read once. */
  function respond(status: number, body: unknown): void {
    fetchMock.mockImplementation(() => Promise.resolve(jsonResponse(status, body)));
  }

  beforeEach(() => {
    localStorage.clear();
    fetchMock.mockReset();
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    setUnauthorizedHandler(null);
    vi.unstubAllGlobals();
    localStorage.clear();
  });

  it("attaches the stored bearer token and returns parsed JSON", async () => {
    localStorage.setItem("token", "test-token");
    respond(200, []);

    await expect(getMessages({ limit: 50 })).resolves.toEqual([]);

    const [path, init] = lastRequest(fetchMock);
    expect(path).toBe("/messages/?limit=50");
    expect(init.method).toBe("GET");
    expect(new Headers(init.headers).get("Authorization")).toBe("Bearer test-token");
  });

  it("maps the keyset cursor onto the API's query parameter names", async () => {
    respond(200, []);

    await getMessages({ limit: 100, before: "2026-01-01T10:00:00Z", beforeId: 12 });

    const [path] = lastRequest(fetchMock);
    const query = new URL(path, "http://localhost").searchParams;
    expect(query.get("limit")).toBe("100");
    expect(query.get("before")).toBe("2026-01-01T10:00:00Z");
    expect(query.get("before_id")).toBe("12");
  });

  it("sends JSON bodies and form-encoded logins", async () => {
    respond(200, { access_token: "jwt", token_type: "bearer" });

    await apiPost("/messages/", { text: "Hello" });
    const [, jsonInit] = lastRequest(fetchMock);
    expect(new Headers(jsonInit.headers).get("Content-Type")).toBe("application/json");
    expect(jsonInit.body).toBe(JSON.stringify({ text: "Hello" }));

    await loginUser({ username: "zoya", password: "secret" });
    const [, formInit] = lastRequest(fetchMock);
    expect(new Headers(formInit.headers).get("Content-Type")).toBe(
      "application/x-www-form-urlencoded"
    );
    expect(formInit.body).toBeInstanceOf(URLSearchParams);
    expect(String(formInit.body)).toBe("username=zoya&password=secret");
  });

  it("throws a typed ApiError carrying the server detail", async () => {
    respond(400, { detail: "Username already registered" });

    const error = await captureError(() => apiPost("/users/register", { username: "taken" }));

    expect(error).toBeInstanceOf(ApiError);
    expect(error.status).toBe(400);
    expect(error.detail).toBe("Username already registered");
    expect(error.message).toBe("Username already registered");
  });

  it("reports a network failure as status 0", async () => {
    fetchMock.mockRejectedValue(new TypeError("Failed to fetch"));

    const error = await captureError(() => apiGet("/health"));

    expect(error.status).toBe(0);
    expect(error.detail).toBeUndefined();
  });

  it("notifies the unauthorized handler except for the login request", async () => {
    const handler = vi.fn();
    setUnauthorizedHandler(handler);
    respond(401, { detail: "Not authenticated" });

    await captureError(() => getMessages());
    expect(handler).toHaveBeenCalledTimes(1);

    await captureError(() => loginUser({ username: "zoya", password: "secret" }));
    expect(handler).toHaveBeenCalledTimes(1);
  });
});
