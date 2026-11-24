// Req: observability-testing 4.2 (the full shipment scenario on the real stack, one organization)
// upload → processing → extraction values → comparison → the USD 20,000 discrepancy → evidence
// at the cited pages → graph → investigation events → report with verified citations.
// The investigation step needs the stack's worker to reach a model (VERITAS_LLM_BASE_URL in
// .env). Run with VERITAS_E2E_LIVE_MODEL=1; without it the test is skipped with that reason.
import { readFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { expect, test } from "@playwright/test";

const here = path.dirname(fileURLToPath(import.meta.url));
const CASE_DIR = path.resolve(here, "../../../sample-data/shipment-case");
const FILES = [
  "01_purchase_order.pdf", "02_commercial_invoice.pdf", "03_customs_declaration.pdf",
  "04_insurance_certificate.pdf", "05_payment_receipt.pdf", "06_packing_list.pdf", "07_bill_of_lading.pdf",
];
const TOTALS: Record<string, { amount: string; page: number }> = {
  "02_commercial_invoice.pdf": { amount: "USD 48,000.00", page: 1 },
  "03_customs_declaration.pdf": { amount: "USD 68,000.00", page: 2 },
};

test("the shipment case from upload to a verified, investigation-backed report", async ({ page }) => {
  test.skip(!process.env.VERITAS_E2E_LIVE_MODEL, "needs a model provider reachable from the worker");
  test.setTimeout(15 * 60_000);
  const id = Date.now().toString(36);
  await page.setViewportSize({ width: 1600, height: 1000 });
  await page.goto("/register");
  await page.getByLabel("Full name").fill("Scenario Investigator");
  await page.getByLabel("Organization name").fill(`Scenario ${id}`);
  await page.getByLabel("Work email").fill(`scenario-${id}@example.com`);
  await page.getByLabel("Password").fill(`scenario-password-${id}`);
  await page.getByRole("button", { name: "Create organization" }).click();
  await expect(page.getByRole("heading", { name: "Overview" })).toBeVisible({ timeout: 15_000 });

  // 1. Upload and real processing.
  await page.goto("/investigations/new");
  await page.getByLabel("Case title").fill("Shipment SHIP-2049 scenario (SYNTHETIC DEMONSTRATION DATA)");
  await page.getByLabel("Choose documents to upload").setInputFiles(FILES.map((f) => path.join(CASE_DIR, f)));
  await page.getByRole("button", { name: "Create and process 7 documents" }).click();
  const docs = page.getByRole("list", { name: "Case documents" });
  await expect(docs.getByText("Completed")).toHaveCount(7, { timeout: 8 * 60_000 });
  await expect(docs.getByText("Failed")).toHaveCount(0);
  const caseUrl = page.url();

  // 2. Extraction values with their pages.
  for (const [file, expected] of Object.entries(TOTALS)) {
    await docs.getByRole("button", { name: new RegExp(file.replace(".", "\\.")) }).click();
    const total = page.getByRole("list", { name: "Extracted fields" }).getByRole("button", { name: /Total amount/ });
    await expect(total).toContainText(expected.amount);
    await expect(total).toContainText(`page ${expected.page}`);
  }

  // 3. Comparison: exactly the USD 20,000 discrepancy.
  const findings = page.getByRole("list", { name: "Case findings" });
  await expect(findings.getByRole("listitem")).toHaveCount(1, { timeout: 3 * 60_000 });
  await expect(findings).toContainText("20,000.00");

  // 4. Evidence opened at the cited pages.
  await findings.getByRole("link").first().click();
  await page.getByRole("link", { name: "Compare the documents side by side" }).click();
  await expect(page.getByTestId("overlay-box").and(page.locator('[title^="Conflicting:"]'))).toHaveCount(2, { timeout: 30_000 });
  const right = page.getByLabel("Right document", { exact: true });
  const customs = await right.locator("option", { hasText: "03_customs_declaration.pdf" }).getAttribute("value");
  await right.selectOption(customs ?? "");
  await expect(page.getByText("Page 2 of 2")).toBeVisible({ timeout: 30_000 });
  await expect(page.locator('[title*="68,000.00"]').first()).toBeVisible();

  // 5. Graph, synced to Neo4j.
  await page.goto(caseUrl);
  await page.getByRole("link", { name: "Open graph" }).click();
  await expect(async () => {
    await page.reload();
    await expect(page.getByText("Neo4j", { exact: true })).toBeVisible({ timeout: 3_000 });
  }).toPass({ timeout: 90_000 });
  await expect(page.getByLabel("Graph canvas").getByText("03_customs_declaration.pdf")).toBeVisible();

  // 6. Investigation with a real model: persisted events, human approval.
  await page.getByRole("link", { name: "AI Agents" }).click();
  await page.getByRole("button", { name: "Start investigation" }).click();
  await expect(page.getByText("Awaiting human review", { exact: true }).first()).toBeVisible({ timeout: 6 * 60_000 });
  const log = page.getByRole("list", { name: "Agent events" });
  await expect(log.getByText("Paused for human review")).toBeVisible();
  await expect(log.getByRole("listitem")).not.toHaveCount(0);
  await page.getByRole("button", { name: "Approve and write report" }).click();
  await expect(page.getByText("Completed", { exact: true }).first()).toBeVisible({ timeout: 4 * 60_000 });

  // 7. Report from the approved investigation; it is stored only if every citation resolves.
  await page.getByRole("link", { name: "Reports" }).click();
  await page.getByLabel("Format").selectOption("pdf");
  const include = page.getByLabel("Include an investigation");
  const investigation = await include.locator("option").nth(1).getAttribute("value");
  expect(investigation, "the approved investigation is offered").toBeTruthy();
  await include.selectOption(investigation ?? "");
  await page.getByRole("button", { name: "Generate report" }).click();
  const history = page.getByRole("table", { name: "Report history" });
  await expect(history.getByText("completed")).toBeVisible({ timeout: 3 * 60_000 });
  const refs = page.getByRole("table", { name: "Report evidence references" });
  await expect(refs.getByRole("link", { name: "03_customs_declaration.pdf" })).toBeVisible();
  const [download] = await Promise.all([
    page.waitForEvent("download"),
    page.getByRole("button", { name: "Download PDF" }).click(),
  ]);
  const file = await readFile((await download.path()) as string);
  expect(file.subarray(0, 5).toString()).toBe("%PDF-");
});
