// Req: autonomous-investigation 1.1, 1.3, 5.3, 6.2 (end to end, real stack and a real model)
// Needs the stack's worker to reach a model provider (VERITAS_LLM_BASE_URL in .env). Run with
// VERITAS_E2E_LIVE_MODEL=1; otherwise it is skipped with that reason.
import path from "node:path";
import { fileURLToPath } from "node:url";

import { expect, test } from "@playwright/test";

const here = path.dirname(fileURLToPath(import.meta.url));

test("an agent investigation pauses for review, is approved and drafts the report", async ({ page }) => {
  test.skip(!process.env.VERITAS_E2E_LIVE_MODEL, "needs a model provider reachable from the worker");
  test.setTimeout(10 * 60_000);
  const id = Date.now().toString(36);
  await page.setViewportSize({ width: 1600, height: 1000 });
  await page.goto("/register");
  await page.getByLabel("Full name").fill("Agent Reviewer");
  await page.getByLabel("Organization name").fill(`Agents ${id}`);
  await page.getByLabel("Work email").fill(`agents-${id}@example.com`);
  await page.getByLabel("Password").fill(`agents-password-${id}`);
  await page.getByRole("button", { name: "Create organization" }).click();
  await expect(page.getByRole("heading", { name: "Overview" })).toBeVisible();

  await page.goto("/investigations/new");
  await page.getByLabel("Case title").fill("Shipment SHIP-2049 agent investigation");
  const dir = path.resolve(here, "../../../sample-data/shipment-case");
  await page.getByLabel("Choose documents to upload").setInputFiles(
    ["02_commercial_invoice.pdf", "03_customs_declaration.pdf"].map((f) => path.join(dir, f)));
  await page.getByRole("button", { name: "Create and process 2 documents" }).click();
  await expect(page.getByRole("list", { name: "Case findings" }).getByRole("listitem").first())
    .toBeVisible({ timeout: 4 * 60_000 });

  await page.getByRole("link", { name: "AI Agents" }).click();
  await page.getByRole("button", { name: "Start investigation" }).click();
  await expect(page.getByText("Awaiting human review", { exact: true }).first()).toBeVisible({ timeout: 5 * 60_000 });
  const steps = page.getByRole("list", { name: "Agent steps" });
  // Every step before the review gate finished; a model failure is shown, not hidden.
  await expect(steps.getByLabel(/^(Succeeded|Failed)$/)).toHaveCount(7);
  await expect(steps.getByRole("button", { name: /Report Generation/ })).toBeDisabled();
  await expect(page.getByRole("list", { name: "Investigation runs" }).getByText("Awaiting human review")).toBeVisible();
  const log = page.getByRole("list", { name: "Agent events" });
  await expect(log.getByText("Paused for human review")).toBeVisible();
  await steps.getByRole("button", { name: /Risk Assessment/ }).click();
  await expect(page.getByRole("list", { name: "Risk assessments" })).toBeVisible();
  await page.waitForTimeout(500);
  await page.screenshot({ path: path.resolve(here, "../../../docs/screenshots/ai-agents-review.png") });

  await page.getByRole("button", { name: "Approve and write report" }).click();
  await expect(page.getByText("Completed", { exact: true }).first()).toBeVisible({ timeout: 3 * 60_000 });
  await expect(steps.getByLabel(/^(Succeeded|Failed)$/)).toHaveCount(8);
  await steps.getByRole("button", { name: /Report Generation/ }).click();
  await expect(page.getByRole("list", { name: "Recommended review" })).toBeVisible();
});
