// Req: evidence-explorer 1.2, 1.3, 3.1; reporting 2.1–2.4, 3.1 (end to end, real stack)
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

test("the demo finding opens side by side with labelled highlights, and its report downloads verified", async ({ page }) => {
  test.setTimeout(8 * 60_000);
  const id = Date.now().toString(36);
  await page.setViewportSize({ width: 1600, height: 1000 });
  await page.goto("/register");
  await page.getByLabel("Full name").fill("Explorer Analyst");
  await page.getByLabel("Organization name").fill(`Explorer ${id}`);
  await page.getByLabel("Work email").fill(`explorer-${id}@example.com`);
  await page.getByLabel("Password").fill(`explorer-password-${id}`);
  await page.getByRole("button", { name: "Create organization" }).click();
  await expect(page.getByRole("heading", { name: "Overview" })).toBeVisible();
  await page.goto("/investigations/new");
  await page.getByLabel("Case title").fill("Shipment SHIP-2049 evidence and report");
  await page.getByLabel("Choose documents to upload").setInputFiles(FILES.map((f) => path.join(CASE_DIR, f)));
  await page.getByRole("button", { name: "Create and process 7 documents" }).click();
  const caseFindings = page.getByRole("list", { name: "Case findings" });
  await expect(caseFindings.getByRole("listitem")).toHaveCount(1, { timeout: 5 * 60_000 });

  // Finding → side-by-side comparison, each document at its cited page with labelled boxes.
  await caseFindings.getByRole("link").first().click();
  await page.getByRole("link", { name: "Compare the documents side by side" }).click();
  await expect(page.getByRole("heading", { name: "Evidence Explorer" })).toBeVisible();
  // Each highlight is labelled with its role (not colour alone). For an amount mismatch every
  // cited value conflicts, so both panes show red "Conflicting" boxes, and by default the right
  // pane opens a document whose value differs from the left one.
  const leftPane = page.getByRole("list", { name: "Evidence in the left document" });
  const rightPane = page.getByRole("list", { name: "Evidence in the right document" });
  await expect(page.getByTestId("overlay-box").and(page.locator('[title^="Conflicting:"]'))).toHaveCount(2, { timeout: 30_000 });
  const leftValue = (await leftPane.locator("span.font-mono").first().textContent())?.trim();
  const rightValue = (await rightPane.locator("span.font-mono").first().textContent())?.trim();
  expect(leftValue).toBeTruthy();
  expect(rightValue).not.toBe(leftValue);
  // Neither pane is stuck on a refused link.
  await expect(page.getByText(/Could not display/)).toHaveCount(0);
  // The customs declaration's value is on page 2: open it in the right pane.
  const right = page.getByLabel("Right document", { exact: true });
  const customs = await right.locator("option", { hasText: "03_customs_declaration.pdf" }).getAttribute("value");
  await right.selectOption(customs ?? "");
  await expect(page.getByText("Page 2 of 2")).toBeVisible({ timeout: 30_000 });
  await expect(page.locator('[title*="68,000.00"]').first()).toBeVisible();

  // Report: generated and verified in the worker, then downloaded through a signed link.
  await page.getByRole("link", { name: "Reports" }).click();
  await page.getByLabel("Format").selectOption("pdf");
  await page.getByRole("button", { name: "Generate report" }).click();
  const history = page.getByRole("table", { name: "Report history" });
  await expect(history.getByText("completed")).toBeVisible({ timeout: 2 * 60_000 });
  await expect(page.getByRole("list", { name: "Report discrepancies" }).getByText("Not yet reviewed")).toBeVisible();
  const refs = page.getByRole("table", { name: "Report evidence references" });
  await expect(refs.getByRole("link", { name: "03_customs_declaration.pdf" })).toBeVisible();
  await page.waitForTimeout(300);
  await page.screenshot({ path: path.resolve(here, "../../../docs/screenshots/reports.png") });
  const [download] = await Promise.all([
    page.waitForEvent("download"),
    page.getByRole("button", { name: "Download PDF" }).click(),
  ]);
  expect(download.suggestedFilename()).toMatch(/^veritas-report-.+\.pdf$/);
  const file = await readFile((await download.path()) as string);
  expect(file.subarray(0, 5).toString()).toBe("%PDF-");

  // Back in the explorer: screenshot of the comparison.
  await page.goBack();
  await page.goto(page.url().replace(/\/reports.*/, "/findings"));
  await page.getByRole("link", { name: /Declared totals differ/ }).click();
  await page.getByRole("link", { name: "Compare the documents side by side" }).click();
  await expect(page.locator('[title^="Conflicting:"]').first()).toBeVisible({ timeout: 30_000 });
  await page.waitForTimeout(500);
  await page.screenshot({ path: path.resolve(here, "../../../docs/screenshots/evidence-explorer.png") });
});
