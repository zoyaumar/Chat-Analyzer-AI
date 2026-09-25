/**
 * The SPA's CSP baseline (gap S11): the meta tag is what a host without its
 * own headers inherits, so it must exist and must lock scripts to the origin.
 */
import { describe, expect, it } from "vitest";
import indexHtml from "../../index.html?raw";

function cspContent(): string {
  const match = indexHtml.match(
    /http-equiv="Content-Security-Policy"[\s\S]*?content="([^"]+)"/
  );
  expect(match, "index.html must declare a CSP meta tag").toBeTruthy();
  return match![1];
}

describe("index.html security baseline (gap S11)", () => {
  it("declares a Content-Security-Policy meta tag", () => {
    expect(cspContent()).toContain("default-src 'self'");
  });

  it("locks scripts to the origin and forbids object embedding", () => {
    const content = cspContent();
    expect(content).toContain("script-src 'self'");
    expect(content).toContain("object-src 'none'");
    expect(content).toContain("base-uri 'self'");
  });

  it("keeps API calls same-origin but allows the dev HMR socket", () => {
    const content = cspContent();
    expect(content).toContain("connect-src 'self'");
    expect(content).toContain("ws://localhost:5173");
  });
});
