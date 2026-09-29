import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { AuthProvider } from "./AuthContext";
import { RequireAuth } from "./RequireAuth";
import { useAuth } from "./useAuth";
import { clearAccessToken, getAccessToken, setAccessToken } from "./token";
import Login from "../pages/Login";

function createToken(expiresInSeconds: number): string {
  const payload = btoa(
    JSON.stringify({ sub: "7", exp: Math.floor(Date.now() / 1000) + expiresInSeconds })
  );
  return `header.${payload}.signature`;
}

function tokenResponse(expiresInSeconds: number): Response {
  return new Response(
    JSON.stringify({ access_token: createToken(expiresInSeconds), token_type: "bearer" }),
    { status: 200, headers: { "Content-Type": "application/json" } }
  );
}

/** Probe so a test can drive `signOut` from inside the provider (gap S7). */
function SignOutProbe() {
  const { signOut } = useAuth();
  return <button onClick={() => signOut()}>Sign out</button>;
}

function renderProtectedRoute() {
  return render(
    <MemoryRouter initialEntries={["/private"]}>
      <AuthProvider>
        <Routes>
          <Route path="/login" element={<Login />} />
          <Route
            path="/private"
            element={
              <RequireAuth>
                <div>
                  Protected page <SignOutProbe />
                </div>
              </RequireAuth>
            }
          />
        </Routes>
      </AuthProvider>
    </MemoryRouter>
  );
}

describe("authentication guards", () => {
  beforeEach(() => {
    localStorage.clear();
    clearAccessToken();
    // The boot refresh always runs without an in-memory token; by default it
    // finds nothing (network failure ⇒ "not signed in"). Tests that model a
    // valid cookie replace this stub.
    vi.stubGlobal(
      "fetch",
      vi.fn().mockRejectedValue(new TypeError("Failed to fetch"))
    );
  });

  afterEach(() => {
    cleanup();
    vi.useRealTimers();
    vi.unstubAllGlobals();
    localStorage.clear();
    clearAccessToken();
  });

  it("redirects an unauthenticated visitor to login", async () => {
    renderProtectedRoute();

    expect(await screen.findByRole("heading", { name: "Login" })).toBeInTheDocument();
  });

  it("allows a visitor with a valid token through", () => {
    setAccessToken(createToken(60));
    renderProtectedRoute();

    expect(screen.getByText(/Protected page/)).toBeInTheDocument();
  });

  it("adopts the legacy stored token once and deletes it (migration for gap S9)", () => {
    localStorage.setItem("token", createToken(60));

    renderProtectedRoute();

    expect(screen.getByText(/Protected page/)).toBeInTheDocument();
    // The XSS-readable copy is gone; only the in-memory session remains.
    expect(localStorage.getItem("token")).toBeNull();
    expect(getAccessToken()).not.toBeNull();
  });

  it("restores the session from the refresh cookie on boot (gap S9)", async () => {
    const fetchMock = vi.fn().mockResolvedValue(tokenResponse(60));
    vi.stubGlobal("fetch", fetchMock);

    renderProtectedRoute();

    expect(await screen.findByText(/Protected page/)).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith(
      "/users/refresh",
      expect.objectContaining({ method: "POST" })
    );
  });

  it("holds the gate closed while the boot refresh is pending — no login flash", async () => {
    let resolveRefresh!: (response: Response) => void;
    const pending = new Promise<Response>((resolve) => {
      resolveRefresh = resolve;
    });
    vi.stubGlobal("fetch", vi.fn().mockReturnValue(pending));

    renderProtectedRoute();

    // Nothing proven yet: no protected content, but *no login page* either.
    expect(screen.queryByRole("heading", { name: "Login" })).not.toBeInTheDocument();
    expect(screen.queryByText(/Protected page/)).not.toBeInTheDocument();

    await act(async () => {
      resolveRefresh(tokenResponse(60));
    });

    expect(await screen.findByText(/Protected page/)).toBeInTheDocument();
  });

  it("stays on the login page when the boot refresh fails silently", async () => {
    renderProtectedRoute();

    expect(await screen.findByRole("heading", { name: "Login" })).toBeInTheDocument();
    // Boot failure is "not signed in", not an expiry — no expired notice.
    expect(
      screen.queryByText("Your session expired. Please sign in again.")
    ).not.toBeInTheDocument();
  });

  it("renews at expiry instead of ending the session, while the cookie lasts", async () => {
    vi.useFakeTimers();
    // The cookie is still good: the renewal answers with a fresh token.
    const fetchMock = vi.fn().mockImplementation(() => Promise.resolve(tokenResponse(60)));
    vi.stubGlobal("fetch", fetchMock);
    setAccessToken(createToken(60));

    renderProtectedRoute();
    expect(screen.getByText(/Protected page/)).toBeInTheDocument();

    await act(async () => {
      vi.advanceTimersByTime(60_000);
    });

    // Still signed in — with a renewed token, not the expired one.
    expect(screen.getByText(/Protected page/)).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Login" })).not.toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith(
      "/users/refresh",
      expect.objectContaining({ method: "POST" })
    );
    expect(getAccessToken()).not.toBeNull();
  });

  it("ends the session when the token expires and the cookie is gone", async () => {
    vi.useFakeTimers();
    setAccessToken(createToken(60));
    renderProtectedRoute();

    expect(screen.getByText(/Protected page/)).toBeInTheDocument();

    await act(async () => {
      vi.advanceTimersByTime(60_000);
    });

    expect(screen.getByRole("heading", { name: "Login" })).toBeInTheDocument();
    expect(
      screen.getByText("Your session expired. Please sign in again.")
    ).toBeInTheDocument();
  });

  it("revokes the refresh token server-side on sign-out (gap S7)", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ detail: "Logged out" }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      })
    );
    vi.stubGlobal("fetch", fetchMock);
    setAccessToken(createToken(60));

    renderProtectedRoute();
    fireEvent.click(screen.getByRole("button", { name: "Sign out" }));

    // Local session gone, and the cookie revoked upstream — a deliberate exit,
    // so no "session expired" notice.
    expect(await screen.findByRole("heading", { name: "Login" })).toBeInTheDocument();
    expect(getAccessToken()).toBeNull();
    expect(
      screen.queryByText("Your session expired. Please sign in again.")
    ).not.toBeInTheDocument();
    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        "/users/logout",
        expect.objectContaining({ method: "POST" })
      )
    );
  });
});
