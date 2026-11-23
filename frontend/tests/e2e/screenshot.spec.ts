// Captures the viewer for visual review (docs/screenshots). Runs with the e2e suite.
import path from "node:path";
import { fileURLToPath } from "node:url";

import { expect, test } from "@playwright/test";

const here = path.dirname(fileURLToPath(import.meta.url));

test("viewer highlights the customs value where it is printed", async ({ page }) => {
  test.setTimeout(4 * 60_000);
  const id = Date.now().toString(36);
  await page.goto("/register");
  await page.getByLabel("Full name").fill("Screenshot Analyst");
  await page.getByLabel("Organization name").fill(`Screenshot Org ${id}`);
  await page.getByLabel("Work email").fill(`shot-${id}@example.com`);
  await page.getByLabel("Password").fill(`shot-password-${id}`);
  await page.getByRole("button", { name: "Create organization" }).click();
  await expect(page.getByRole("heading", { name: "Overview" })).toBeVisible();
  await page.goto("/investigations/new");
  await page.getByLabel("Case title").fill("Customs value check");
  await page.getByLabel("Choose documents to upload").setInputFiles(
    path.resolve(here, "../../../sample-data/shipment-case/03_customs_declaration.pdf"));
  await page.getByRole("button", { name: "Create and process 1 document" }).click();
  await expect(page.getByRole("list", { name: "Case documents" }).getByText("Completed")).toHaveCount(1, { timeout: 3 * 60_000 });
  await page.getByRole("link", { name: "Open full view" }).click();
  await page.getByRole("list", { name: "Extracted fields" }).getByRole("button", { name: /Total amount/ }).click();
  const box = page.getByRole("button", { name: "Total amount: USD 68,000.00" });
  await expect(box).toBeVisible();
  await expect(page.getByRole("img", { name: "Page 2" })).toBeVisible();
  await box.scrollIntoViewIfNeeded();
  await page.waitForTimeout(500);
  await page.screenshot({ path: path.resolve(here, "../../../docs/screenshots/viewer-customs-value.png"), fullPage: false });
});

test("finding detail with its evidence and review panel", async ({ page }) => {
  test.setTimeout(4 * 60_000);
  const id = Date.now().toString(36);
  await page.setViewportSize({ width: 1440, height: 1100 });
  await page.goto("/register");
  await page.getByLabel("Full name").fill("Screenshot Analyst");
  await page.getByLabel("Organization name").fill(`Screenshot Findings ${id}`);
  await page.getByLabel("Work email").fill(`shot-f-${id}@example.com`);
  await page.getByLabel("Password").fill(`shot-password-${id}`);
  await page.getByRole("button", { name: "Create organization" }).click();
  await expect(page.getByRole("heading", { name: "Overview" })).toBeVisible();
  await page.goto("/investigations/new");
  await page.getByLabel("Case title").fill("Shipment SHIP-2049 declared values");
  const dir = path.resolve(here, "../../../sample-data/shipment-case");
  await page.getByLabel("Choose documents to upload").setInputFiles([
    "01_purchase_order.pdf", "02_commercial_invoice.pdf", "03_customs_declaration.pdf",
    "04_insurance_certificate.pdf", "05_payment_receipt.pdf", "06_packing_list.pdf", "07_bill_of_lading.pdf",
  ].map((f) => path.join(dir, f)));
  await page.getByRole("button", { name: "Create and process 7 documents" }).click();
  const findings = page.getByRole("list", { name: "Case findings" });
  await expect(findings.getByRole("listitem")).toHaveCount(1, { timeout: 3 * 60_000 });
  await findings.getByRole("link").first().click();
  await expect(page.getByRole("table", { name: "Evidence items" }).locator("tbody tr")).toHaveCount(5);
  await page.waitForTimeout(300);
  await page.screenshot({ path: path.resolve(here, "../../../docs/screenshots/finding-financial-discrepancy.png"), fullPage: true });
});

test("intelligence graph of the shipment case", async ({ page }) => {
  test.setTimeout(5 * 60_000);
  const id = Date.now().toString(36);
  await page.setViewportSize({ width: 1600, height: 1000 });
  await page.goto("/register");
  await page.getByLabel("Full name").fill("Screenshot Analyst");
  await page.getByLabel("Organization name").fill(`Screenshot Graph ${id}`);
  await page.getByLabel("Work email").fill(`shot-g-${id}@example.com`);
  await page.getByLabel("Password").fill(`shot-password-${id}`);
  await page.getByRole("button", { name: "Create organization" }).click();
  await expect(page.getByRole("heading", { name: "Overview" })).toBeVisible();
  await page.goto("/investigations/new");
  await page.getByLabel("Case title").fill("Shipment SHIP-2049 evidence graph");
  const dir = path.resolve(here, "../../../sample-data/shipment-case");
  await page.getByLabel("Choose documents to upload").setInputFiles([
    "01_purchase_order.pdf", "02_commercial_invoice.pdf", "03_customs_declaration.pdf",
    "04_insurance_certificate.pdf", "05_payment_receipt.pdf", "06_packing_list.pdf", "07_bill_of_lading.pdf",
  ].map((f) => path.join(dir, f)));
  await page.getByRole("button", { name: "Create and process 7 documents" }).click();
  await expect(page.getByRole("list", { name: "Case findings" }).getByRole("listitem")).toHaveCount(1, { timeout: 3 * 60_000 });
  await page.getByRole("link", { name: "Open graph" }).click();
  await expect(async () => {
    await page.reload();
    await expect(page.getByText("Neo4j", { exact: true })).toBeVisible({ timeout: 3_000 });
  }).toPass({ timeout: 90_000 });
  await page.getByLabel(/Highlight contradictions/).check();
  await page.getByLabel("Graph canvas").getByText("03_customs_declaration.pdf").click();
  await page.waitForTimeout(800);
  await page.screenshot({ path: path.resolve(here, "../../../docs/screenshots/intelligence-graph.png"), fullPage: false });
});
