import { act, cleanup, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { AuthProvider } from "./AuthContext";
import { RequireAuth } from "./RequireAuth";
import { setStoredToken } from "./token";
import Login from "../pages/Login";

function createToken(expiresInSeconds: number): string {
  const payload = btoa(
    JSON.stringify({ sub: "7", exp: Math.floor(Date.now() / 1000) + expiresInSeconds })
  );
  return `header.${payload}.signature`;
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
                <div>Protected page</div>
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
  });

  afterEach(() => {
    cleanup();
    vi.useRealTimers();
    localStorage.clear();
  });

  it("redirects an unauthenticated visitor to login", () => {
    renderProtectedRoute();

    expect(screen.getByRole("heading", { name: "Login" })).toBeInTheDocument();
  });

  it("allows a visitor with a valid token through", () => {
    setStoredToken(createToken(60));
    renderProtectedRoute();

    expect(screen.getByText("Protected page")).toBeInTheDocument();
  });

  it("ends the session when the token expires", () => {
    vi.useFakeTimers();
    setStoredToken(createToken(60));
    renderProtectedRoute();

    expect(screen.getByText("Protected page")).toBeInTheDocument();

    act(() => {
      vi.advanceTimersByTime(60_000);
    });

    expect(screen.getByRole("heading", { name: "Login" })).toBeInTheDocument();
    expect(
      screen.getByText("Your session expired. Please sign in again.")
    ).toBeInTheDocument();
  });
});
