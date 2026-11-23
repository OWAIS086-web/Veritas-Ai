// Req: document-comparison 1.x-8.x (end to end, real stack: upload, processing, comparison,
// synchronized viewer, review and downloads)
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { expect, type Page, test } from "@playwright/test";

const here = path.dirname(fileURLToPath(import.meta.url));
const DIR = path.resolve(here, "../../../sample-data/comparison");

test.setTimeout(10 * 60_000);

async function registerFresh(page: Page) {
  const id = Date.now().toString(36);
  await page.goto("/register");
  await page.getByLabel("Full name").fill("Comparison Analyst");
  await page.getByLabel("Organization name").fill(`Comparison Lab ${id}`);
  await page.getByLabel("Work email").fill(`e2e-compare-${id}@example.com`);
  await page.getByLabel("Password").fill(`e2e-password-${id}`);
  await page.getByRole("button", { name: "Create organization" }).click();
  await expect(page.getByRole("heading", { name: "Overview" })).toBeVisible();
}

test("compare an original with an altered test document and download the annotated copy", async ({ page }) => {
  await registerFresh(page);
  await page.goto("/investigations/new");
  await page.getByLabel("Case title").fill("Invoice comparison (SYNTHETIC DEMONSTRATION DATA)");
  await page.getByRole("button", { name: "Create investigation" }).click();
  await expect(page.getByRole("heading", { name: /Invoice comparison/ })).toBeVisible();

  await page.getByRole("link", { name: "Forensics Lab" }).click();
  await page.getByRole("tab", { name: "Comparison Lab" }).click();
  await expect(page.getByText("No comparisons yet")).toBeVisible();
  await page.getByLabel("Original document").setInputFiles(path.join(DIR, "original_invoice.pdf"));
  await page.getByLabel("Test document").setInputFiles(path.join(DIR, "test_altered.pdf"));
  await page.getByRole("button", { name: "Compare documents" }).click();

  // Real processing of both files, then the real comparison worker (progress is persisted).
  const table = page.getByRole("table", { name: "Comparisons" });
  await expect(table.getByText("Completed")).toBeVisible({ timeout: 8 * 60_000 });
  const differences = page.getByRole("list", { name: "Differences" });
  await expect(differences.getByRole("button")).toHaveCount(3);

  await differences.getByRole("button", { name: /#2/ }).click();
  const article = page.getByRole("article", { name: "Difference 2" });
  await expect(article).toContainText("68,000.00");
  await expect(article).toContainText("48,000.00");
  // Both panes show the same page with a box on the changed total.
  await expect(page.getByRole("region", { name: "Test document" }).getByTestId("overlay-box")).not.toHaveCount(0);
  await expect(page.getByRole("region", { name: "Original document" }).getByTestId("overlay-box")).not.toHaveCount(0);

  await page.getByLabel("Note (required)").fill("Checked against the purchase order.");
  await page.getByRole("button", { name: "Save review" }).click();
  await expect(page.getByText("Review saved")).toBeVisible();
  await expect(page.getByRole("list", { name: "Review history" })).toContainText("Confirmed difference");

  const exports = page.getByRole("list", { name: "Exports" });
  const pdfButton = exports.getByRole("button", { name: "Download Annotated test document (PDF)" });
  await expect(pdfButton).toBeEnabled({ timeout: 2 * 60_000 });
  const [download] = await Promise.all([page.waitForEvent("download"), pdfButton.click()]);
  expect(download.suggestedFilename()).toMatch(/^veritas-comparison-.+-annotated-pdf\.pdf$/);
  const file = await download.path();
  expect(fs.readFileSync(file).subarray(0, 5).toString()).toBe("%PDF-");

  const [json] = await Promise.all([
    page.waitForEvent("download"),
    exports.getByRole("button", { name: "Download Findings (JSON)" }).click(),
  ]);
  const data = JSON.parse(fs.readFileSync(await json.path(), "utf-8")) as { findings: unknown[]; schema: string };
  expect(data.schema).toBe("veritas.document-comparison.v1");
  expect(data.findings).toHaveLength(3);
});
