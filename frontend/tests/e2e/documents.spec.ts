// Req: document-ingestion 2.x; document-intelligence 1.x, 3.x, 4.x, 6.1 (end to end, real stack)
import path from "node:path";
import { fileURLToPath } from "node:url";

import { expect, type Page, test } from "@playwright/test";

const here = path.dirname(fileURLToPath(import.meta.url));
const CASE_DIR = path.resolve(here, "../../../sample-data/shipment-case");
const FILES = [
  "01_purchase_order.pdf", "02_commercial_invoice.pdf", "03_customs_declaration.pdf",
  "04_insurance_certificate.pdf", "05_payment_receipt.pdf", "06_packing_list.pdf", "07_bill_of_lading.pdf",
];
const EXPECTED_TOTALS: Record<string, { amount: string; page: number }> = {
  "01_purchase_order.pdf": { amount: "USD 48,000.00", page: 1 },
  "02_commercial_invoice.pdf": { amount: "USD 48,000.00", page: 1 },
  "03_customs_declaration.pdf": { amount: "USD 68,000.00", page: 2 },
  "04_insurance_certificate.pdf": { amount: "USD 68,000.00", page: 1 },
  "05_payment_receipt.pdf": { amount: "USD 48,000.00", page: 1 },
};

test.setTimeout(8 * 60_000);

async function registerFresh(page: Page) {
  const id = Date.now().toString(36);
  await page.goto("/register");
  await page.getByLabel("Full name").fill("E2E Analyst");
  await page.getByLabel("Organization name").fill(`E2E Trade Compliance ${id}`);
  await page.getByLabel("Work email").fill(`e2e-docs-${id}@example.com`);
  await page.getByLabel("Password").fill(`e2e-password-${id}`);
  await page.getByRole("button", { name: "Create organization" }).click();
  await expect(page.getByRole("heading", { name: "Overview" })).toBeVisible();
}

test("upload the shipment case, watch real processing, and see the extracted totals", async ({ page }) => {
  await registerFresh(page);
  await page.getByRole("link", { name: "Investigations" }).click();
  await page.getByRole("button", { name: "Create the first investigation" }).click();
  await page.getByLabel("Case title").fill("International Shipment Financial Discrepancy Investigation");
  await page.getByLabel("Objective").fill("Reconcile the declared values for shipment SHIP-2049.");
  await page.getByLabel("Choose documents to upload").setInputFiles(FILES.map((f) => path.join(CASE_DIR, f)));
  await expect(page.getByRole("list", { name: "Files to upload" }).getByRole("listitem")).toHaveCount(7);
  await page.getByRole("button", { name: "Create and process 7 documents" }).click();

  const docs = page.getByRole("list", { name: "Case documents" });
  await expect(docs.getByRole("listitem").filter({ hasText: ".pdf" })).toHaveCount(7);
  // Real Celery processing; status survives because it is persisted (polling + SSE).
  await expect(docs.getByText("Completed")).toHaveCount(7, { timeout: 6 * 60_000 });
  await expect(docs.getByText("Failed")).toHaveCount(0);

  for (const [file, expected] of Object.entries(EXPECTED_TOTALS)) {
    await docs.getByRole("button", { name: new RegExp(file.replace(".", "\\.")) }).click();
    const fields = page.getByRole("list", { name: "Extracted fields" });
    const total = fields.getByRole("button", { name: /Total amount/ });
    await expect(total).toContainText(expected.amount);
    await expect(total).toContainText(`page ${expected.page}`);
    await expect(total).toContainText("PDF text layer");
  }

  // The customs value opens on page 2 of the rendered PDF with its evidence box.
  await docs.getByRole("button", { name: /03_customs_declaration\.pdf/ }).click();
  await page.getByRole("list", { name: "Extracted fields" }).getByRole("button", { name: /Total amount/ }).click();
  await expect(page.getByText("Page 2 of 2")).toBeVisible();
  await expect(page.getByRole("img", { name: "Page 2" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Total amount: USD 68,000.00" })).toBeVisible();

  // Cross-document comparison ran when processing finished: exactly one finding.
  const caseFindings = page.getByRole("list", { name: "Case findings" });
  await expect(caseFindings.getByRole("listitem")).toHaveCount(1, { timeout: 60_000 });
  await caseFindings.getByRole("link", { name: "Declared totals differ by USD 20,000.00" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Declared totals differ by USD 20,000.00" })).toBeVisible();
  await expect(page.getByLabel("Anomaly score: 0.294")).toBeVisible();
  await expect(page.getByLabel("Evidence confidence: 1.000")).toBeVisible();
  const evidence = page.getByRole("table", { name: "Evidence items" });
  await expect(evidence.locator("tbody tr")).toHaveCount(5);
  // Values are shown as printed (a model may cite "48,000.00" next to the printed "USD").
  await expect(evidence.getByText(/68,000\.00/)).toHaveCount(2);
  await expect(evidence.getByText(/48,000\.00/)).toHaveCount(3);

  // Each evidence item opens its source document at the cited page and field.
  await evidence.getByRole("link", { name: "Open 03_customs_declaration.pdf at page 2" }).click();
  await expect(page.getByText("Page 2 of 2")).toBeVisible();
  await expect(page.getByRole("button", { name: "Total amount: USD 68,000.00" })).toBeVisible();
  await page.goBack();

  // A reviewer decision needs a note and is recorded in the history.
  await page.getByLabel("New status").selectOption("under_review");
  await page.getByRole("button", { name: "Record decision" }).click();
  await expect(page.getByRole("list", { name: "Decision history" })).toContainText("New → Under review");

  await page.getByRole("link", { name: "Findings" }).click();
  await expect(page.getByRole("link", { name: "Declared totals differ by USD 20,000.00" })).toHaveCount(1);

  // The evidence graph: synced to Neo4j by the worker, every relationship backed by evidence.
  await page.getByRole("link", { name: "Intelligence Graph" }).click();
  await expect(page.getByLabel("Graph canvas").getByText("Global Trading Ltd")).toBeVisible({ timeout: 30_000 });
  await expect(async () => {
    await page.reload();
    await expect(page.getByText("Neo4j", { exact: true })).toBeVisible({ timeout: 3_000 });
  }).toPass({ timeout: 90_000 });
  await page.getByRole("button", { name: "list" }).click();
  await page.getByLabel(/Highlight contradictions \(6\)/).check();
  const relationships = page.getByRole("table", { name: "Relationships" });
  await expect(relationships.locator("tbody tr")).toHaveCount(6);
  await relationships.getByRole("button", {
    name: /Show evidence: 02_commercial_invoice\.pdf contradicts 03_customs_declaration\.pdf|Show evidence: 03_customs_declaration\.pdf contradicts 02_commercial_invoice\.pdf/,
  }).click();
  const edgeEvidence = page.getByRole("list", { name: "Relationship evidence" });
  await expect(edgeEvidence.getByText("USD 68,000.00")).toBeVisible();
  await edgeEvidence.getByRole("link", { name: "Open 03_customs_declaration.pdf at page 2" }).click();
  await expect(page.getByText("Page 2 of 2")).toBeVisible();
  await page.getByRole("link", { name: "Documents" }).click();
  await expect(page.getByRole("link", { name: "03_customs_declaration.pdf" })).toBeVisible();
  await page.getByRole("link", { name: "Overview" }).click();
  await expect(page.getByLabel("Documents processed: 7")).toBeVisible();
  await expect(page.getByLabel("Active investigations: 1")).toBeVisible();
  await expect(page.getByLabel("Findings requiring review: 1")).toBeVisible();
  await expect(page.getByLabel("High-priority findings: 1")).toBeVisible();
});

test("a scanned invoice goes through OCR and keeps page coordinates", async ({ page }) => {
  await registerFresh(page);
  await page.goto("/investigations/new");
  await page.getByLabel("Case title").fill("Scanned invoice check");
  await page.getByLabel("Choose documents to upload").setInputFiles(
    path.resolve(here, "../../../sample-data/format-variants/commercial_invoice_scanned.pdf"));
  await page.getByRole("button", { name: "Create and process 1 document" }).click();
  const docs = page.getByRole("list", { name: "Case documents" });
  await expect(docs.getByText("Completed")).toHaveCount(1, { timeout: 4 * 60_000 });
  const total = page.getByRole("list", { name: "Extracted fields" }).getByRole("button", { name: /Total amount/ });
  await expect(total).toContainText("48,000.00");
  await expect(total).toContainText("OCR (PaddleOCR)");
  await expect(total).not.toContainText("confidence not measured");
});
