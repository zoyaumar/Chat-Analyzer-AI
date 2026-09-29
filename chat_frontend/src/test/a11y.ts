import { run, type Result } from "axe-core";

/**
 * Run axe over `node` and fail with a report a human can act on (gap F12).
 *
 * The suite used to assert accessibility one attribute at a time; this is the
 * automated audit that closes the gap, so a new screen cannot ship without an
 * accessible name, a heading, or a landmark. The rule set is spelled out rather
 * than left at axe's default so the next axe upgrade cannot silently narrow
 * what is being checked: WCAG A/AA (2.0/2.1) plus `best-practice`, which is
 * what catches landmark and heading-order regressions no unit test would.
 *
 * Axe only applies page-level rules (`landmark-one-main`, `region`,
 * `page-has-heading-one`) when the context *is* the page, so screens pass
 * `document.body` and components pass their own container — auditing a screen's
 * wrapper div would skip exactly the rules that matter for it.
 *
 * jsdom cannot paint, so `color-contrast` reports as *incomplete* instead of a
 * violation and never fails a run here — that rule needs a real browser.
 */
export async function expectNoA11yViolations(node: Element): Promise<void> {
  const { violations } = await run(node, {
    resultTypes: ["violations"],
    runOnly: {
      type: "tag",
      values: ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "best-practice"],
    },
  });
  if (violations.length === 0) return;
  throw new Error(
    `axe found ${violations.length} accessibility violation(s):\n\n` +
      violations.map(formatViolation).join("\n\n")
  );
}

function formatViolation(violation: Result): string {
  const nodes = violation.nodes
    .map(
      (node) =>
        `  • ${node.target.join(" ")}\n` +
        indent(node.failureSummary ?? "no failure summary")
    )
    .join("\n");
  return (
    `${violation.id} (${violation.impact}): ${violation.help}\n` +
    `  ${violation.helpUrl}\n${nodes}`
  );
}

function indent(text: string): string {
  return text.replace(/\n/g, "\n    ").replace(/^/, "    ");
}
