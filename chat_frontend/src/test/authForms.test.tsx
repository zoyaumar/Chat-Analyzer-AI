/**
 * The auth forms' own behaviour (gap T2, the remainder). The axe audit proves
 * these screens are *accessible*; it cannot prove they submit the right values
 * or say the right thing when the API refuses — so these do.
 *
 * They drive the real `apiClient` against MSW rather than mocking `../api`, so
 * the form-encoded login body and the `ApiError` shape are exercised end to end.
 */
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it } from "vitest";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import { AuthProvider } from "../auth/AuthContext";
import { clearAccessToken } from "../auth/token";
import Login from "../pages/Login";
import Register from "../pages/Register";
import { handlers, resetMswState } from "./handlers";

/** Recorded request bodies, so a test can assert what went over the wire. */
const submitted: { path: string; body: string }[] = [];

/**
 * A token the client can actually decode. `AuthProvider` reads `exp` off every
 * token it is handed, and a token it cannot decode is treated as a session that
 * has already ended — which would bounce the form to the "session expired"
 * notice before the test could submit anything.
 */
function createToken(expiresInSeconds: number): string {
  const payload = btoa(
    JSON.stringify({ sub: "1", exp: Math.floor(Date.now() / 1000) + expiresInSeconds })
  );
  return `header.${payload}.signature`;
}

/**
 * Auth endpoints the forms drive, recorded for inspection. These come after the
 * shared `handlers`, so they win; a test overrides one again with `server.use`.
 */
const authHandlers = [
  http.post("/users/login", async ({ request }) => {
    submitted.push({ path: "/users/login", body: await request.text() });
    return HttpResponse.json({
      access_token: createToken(3600),
      token_type: "bearer",
    });
  }),
  http.post("/users/register", async ({ request }) => {
    submitted.push({ path: "/users/register", body: await request.text() });
    return HttpResponse.json({ id: 7, username: "newuser" });
  }),
];

/**
 * MSW resolves an overlapping pair by taking the **first** match, so every
 * override here has to be listed *before* `handlers` — otherwise the shared
 * fixture answers and `submitted` stays empty.
 */
const server = setupServer(
  // `AuthProvider` always tries the refresh cookie on boot. Answering it 401
  // models "nobody is signed in", which is the state these tests start from;
  // without this the boot would sign the provider *in* behind the form.
  http.post("/users/refresh", () =>
    HttpResponse.json({ detail: "Not authenticated" }, { status: 401 })
  ),
  ...authHandlers,
  ...handlers
);

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterAll(() => server.close());
beforeEach(() => {
  resetMswState();
  submitted.length = 0;
  window.localStorage.clear();
  clearAccessToken();
});
afterEach(() => cleanup());

/** A destination route, so a successful submit's navigation is observable. */
function Destination() {
  return <p>Signed in</p>;
}

function renderLogin() {
  return render(
    <MemoryRouter initialEntries={["/login"]}>
      <AuthProvider>
        <Routes>
          <Route path="/login" element={<Login />} />
          <Route path="/chat" element={<Destination />} />
        </Routes>
      </AuthProvider>
    </MemoryRouter>
  );
}

function renderRegister() {
  return render(
    <MemoryRouter initialEntries={["/register"]}>
      <Routes>
        <Route path="/register" element={<Register />} />
        <Route path="/login" element={<p>Login screen</p>} />
      </Routes>
    </MemoryRouter>
  );
}

/** Type into a form field, the way this suite does it everywhere else. */
function fillCredentials(username: string, password: string) {
  fireEvent.change(screen.getByLabelText("Username"), { target: { value: username } });
  fireEvent.change(screen.getByLabelText("Password"), { target: { value: password } });
}

/**
 * Click a form's submit button.
 *
 * `fireEvent.submit(form)` rather than `fireEvent.click(button)`: React binds
 * the submit handler to the `form`, and going through the submit event exercises
 * that handler directly. Clicking a submit button works only when jsdom's
 * implicit form submission is also wired up, which it is not for every case —
 * and the request then never leaves.
 */
function submit(formName: RegExp | string) {
  const form = screen.getByRole("button", { name: formName }).closest("form");
  if (!form) throw new Error(`no <form> found for the "${String(formName)}" button`);
  fireEvent.submit(form);
}

describe("login form (T2)", () => {
  it("sends the credentials form-encoded, as the endpoint requires", async () => {
    renderLogin();

    fillCredentials("alice", "s3cret-pw");
    submit("Login");

    await waitFor(() => expect(submitted).toHaveLength(1));
    expect(submitted[0].path).toBe("/users/login");
    // `application/x-www-form-urlencoded`, not JSON — a regression here would
    // answer 422 and the user would be told to "provide both fields" for no reason.
    expect(submitted[0].body).toContain("username=alice");
    expect(submitted[0].body).toContain("password=s3cret-pw");
  });

  it("navigates on to the app when the credentials are accepted", async () => {
    renderLogin();

    fillCredentials("alice", "s3cret-pw");
    submit("Login");

    expect(await screen.findByText("Signed in")).toBeInTheDocument();
  });

  it("keeps a wrong password on the form and says so", async () => {
    server.use(
      http.post("/users/login", () =>
        HttpResponse.json({ detail: "Invalid username or password" }, { status: 401 })
      )
    );
    renderLogin();

    fillCredentials("alice", "wrong-password");
    submit("Login");

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Invalid username or password"
    );
    // The typed password stays, so one wrong character is a one-character fix.
    expect(screen.getByLabelText("Password")).toHaveValue("wrong-password");
  });

  it("will not submit an empty form", () => {
    renderLogin();
    expect(screen.getByRole("button", { name: "Login" })).toBeDisabled();
  });
});

describe("register form (T2)", () => {
  it("posts JSON and moves on to the login screen", async () => {
    renderRegister();

    fillCredentials("newuser", "s3cret-pw");
    submit("Register");

    await waitFor(() => expect(submitted).toHaveLength(1));
    expect(JSON.parse(submitted[0].body)).toEqual({
      username: "newuser",
      password: "s3cret-pw",
    });
    expect(await screen.findByText("Login screen")).toBeInTheDocument();
  });

  it("surfaces the server's own reason, so a taken name is legible", async () => {
    server.use(
      http.post("/users/register", () =>
        HttpResponse.json({ detail: "Username already registered" }, { status: 400 })
      )
    );
    renderRegister();

    fillCredentials("alice", "s3cret-pw");
    submit("Register");

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Username already registered"
    );
  });

  it("will not submit an empty form", () => {
    renderRegister();
    expect(screen.getByRole("button", { name: "Register" })).toBeDisabled();
  });
});
