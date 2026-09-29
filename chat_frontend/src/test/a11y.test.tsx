/**
 * The automated accessibility audit that closes the remaining half of gap F12.
 *
 * Every screen here is rendered the way `App` mounts it — real router, real
 * auth context, real `Navbar` — and handed to axe-core, so a new screen cannot
 * ship without an accessible name, a heading and a landmark. `MessageList` and
 * the `Chat` page run their own audit in their own test files, next to the
 * states they already render; this file is the inventory of screens that have
 * nowhere else to be.
 */
import { cleanup, render } from "@testing-library/react";
import type { ReactElement } from "react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it } from "vitest";
import { AuthProvider } from "../auth/AuthContext";
import Analytics from "../pages/Analytics";
import Login from "../pages/Login";
import Register from "../pages/Register";
import { expectNoA11yViolations } from "./a11y";
import { renderWithQueryClient } from "./renderWithQueryClient";

// `globals` is off in the vitest config, so nothing unmounts a render unless
// the file asks for it (see `MessageList.test.tsx` for the same note).
afterEach(() => {
  cleanup();
  window.localStorage.clear();
});

/** Mount `ui` with the same providers `App` gives it, at `path`. */
function renderScreen(ui: ReactElement, path: string) {
  return renderWithQueryClient(
    <MemoryRouter initialEntries={[path]}>
      <AuthProvider>{ui}</AuthProvider>
    </MemoryRouter>
  );
}

describe("accessibility audit (axe)", () => {
  it("the login screen has no axe violations", async () => {
    renderScreen(<Login />, "/login");

    await expectNoA11yViolations(document.body);
  });

  it("the register screen has no axe violations", async () => {
    renderScreen(<Register />, "/register");

    await expectNoA11yViolations(document.body);
  });

  it("the analytics screen has no axe violations", async () => {
    renderScreen(<Analytics />, "/analytics");

    await expectNoA11yViolations(document.body);
  });

  it("has teeth: inaccessible markup is still reported", async () => {
    // An audit that cannot fail is not an audit. An image without `alt` and a
    // button without an accessible name are both WCAG A failures, so this is
    // the proof that a real screen failing one of them would stop the run.
    const { container } = render(
      <div>
        <img src="avatar.png" />
        <button type="button" />
      </div>
    );

    // The audit must *reject*, so capture its report instead of asserting on
    // an outcome that either answer would satisfy.
    const report: string | null = await expectNoA11yViolations(container).then(
      () => null,
      (error: Error) => error.message
    );

    expect(report).not.toBeNull();
    expect(report).toContain("image-alt");
    expect(report).toContain("button-name");
  });
});
