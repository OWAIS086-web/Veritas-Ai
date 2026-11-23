// Req: document-forensics 3.1, 3.2, 4.1 (UI states, against API-shaped responses)
import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";

import { formatPdfDate } from "@/features/forensics/labels";
import { me } from "@/test/fixtures";
import { renderAt, signIn } from "@/test/render";
import { server } from "@/test/server";
import type { CaseOut, ForensicRunOut, ForensicSummaryOut } from "@/types/api";

const LIMITATION = "A visual or structural inconsistency alone does not establish document alteration or forgery.";

const caseRow: CaseOut = {
  id: "c-1", title: "Forensic fixtures", objective: "", investigation_type: "international_shipment",
  priority: "high", status: "open", created_by: "u-1", created_by_email: "ana@example.com",
  created_at: "2026-11-23T10:00:00Z", updated_at: "2026-11-23T10:00:00Z", document_count: 2,
  documents_completed: 2, documents_failed: 0, finding_count: 0, compared_at: null,
};

const summary: ForensicSummaryOut[] = [
  { document_id: "d-edit", filename: "edited_invoice.png", doc_type: "commercial_invoice", mime_type: "image/png",
    status: "succeeded", analysis_types: ["visual_compression"], anomalies: 2, medium: 1, low: 1,
    types: ["font_inconsistency", "incremental_update"] },
  { document_id: "d-clean", filename: "clean_invoice.png", doc_type: "commercial_invoice", mime_type: "image/png",
    status: null, analysis_types: [], anomalies: 0, medium: 0, low: 0, types: [] },
];

const run: ForensicRunOut = {
  id: "r-1", document_id: "d-edit", pipeline_version: "1", status: "succeeded",
  analysis_types: ["pdf_structure", "stamps_signatures"],
  pdf_metadata: { producer: "VERITAS fixture generator", modDate: "D:20260112093000+00'00'" },
  structure: { pages_analysed: 1, stamps_signatures: { regions: [{ kind: "stamp", page: 1, region: [1, 2, 3, 4] }] } },
  limitations: [LIMITATION],
  started_at: "2026-11-23T10:00:00Z", finished_at: "2026-11-23T10:00:02Z",
  anomalies: [
    { id: "a-1", type: "font_inconsistency", page_number: 1, region: [196, 219, 320, 234], severity: "medium",
      explanation: "The total uses a font that appears nowhere else in the document.",
      metrics: { font: "Courier", field_id: "x-total", font_spans: 1 }, requires_review: true },
    { id: "a-2", type: "incremental_update", page_number: null, region: null, severity: "low",
      explanation: "The file was saved 2 times.", metrics: { saves: 2 }, requires_review: false },
  ],
};

function handlers(documentRun: ForensicRunOut | null = run) {
  return [
    http.get("/api/v1/cases", () => HttpResponse.json({ items: [caseRow], next_cursor: null })),
    http.get("/api/v1/cases/c-1/forensics", () => HttpResponse.json(summary)),
    http.get("/api/v1/documents/d-edit/forensics", () => HttpResponse.json(documentRun)),
    http.get("/api/v1/documents/d-clean/forensics", () => HttpResponse.json(null)),
    http.get("/api/v1/documents/:id/preview", () =>
      HttpResponse.json({ url: "/blob/page.png", mime_type: "image/png", expires_at: "2026-11-23T10:01:00Z" })),
  ];
}

test("PDF dates are shown in a readable form", () => {
  expect(formatPdfDate("D:20260112093000+00'00'")).toBe("2026-01-12 09:30");
  expect(formatPdfDate("D:2026")).toBe("2026-01-01");
  expect(formatPdfDate("yesterday")).toBe("yesterday");
});

test("the lab lists documents by priority and shows anomalies with their limitations", async () => {
  server.use(...handlers());
  signIn({ ...me, permissions: [...me.permissions, "forensics:read"] });
  renderAt("/forensics?case=c-1");

  const table = await screen.findByRole("table", { name: "Documents by forensic review priority" });
  const [, edited, clean] = within(table).getAllByRole("row");
  expect(within(table).getAllByRole("row")).toHaveLength(3);
  expect(within(edited as HTMLElement).getByText("Font inconsistency, Incremental update")).toBeInTheDocument();
  expect(within(clean as HTMLElement).getByText("Not analysed")).toBeInTheDocument();

  const list = await screen.findByRole("list", { name: "Anomalies" });
  expect(within(list).getByText("The total uses a font that appears nowhere else in the document.")).toBeInTheDocument();
  // Severity is labelled, not shown by colour alone.
  expect(within(list).getByText("medium")).toBeInTheDocument();
  expect(within(screen.getByRole("list", { name: "Limitations" })).getByText(LIMITATION)).toBeInTheDocument();
  expect(screen.getByText("2026-01-12 09:30")).toBeInTheDocument();
  expect(screen.getByRole("link", { name: /Document viewer/ })).toHaveAttribute("href", "/documents/d-edit");

  // Selecting an anomaly shows its measurements and links the overlapping extracted field.
  await userEvent.click(within(list).getByRole("button", { name: /Font inconsistency/ }));
  expect(screen.getByText("Courier")).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "field 1" })).toHaveAttribute("href", "/documents/d-edit?field=x-total");
  expect(screen.getByText("Marked for human review.")).toBeInTheDocument();
});

test("a document without a forensic run explains how to get one", async () => {
  server.use(...handlers());
  signIn({ ...me, permissions: [...me.permissions, "forensics:read"] });
  renderAt("/forensics?case=c-1&doc=d-clean");
  expect(await screen.findByText("Not analysed yet")).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Open the document" })).toHaveAttribute("href", "/documents/d-clean");
});

test("a document with no anomalies says so instead of showing an empty list", async () => {
  server.use(...handlers({ ...run, anomalies: [] }));
  signIn({ ...me, permissions: [...me.permissions, "forensics:read"] });
  renderAt("/forensics?case=c-1");
  expect(await screen.findByText("The analyses that ran found no anomaly in this document.")).toBeInTheDocument();
  expect(screen.getByText(LIMITATION)).toBeInTheDocument();
});

test("a failed summary request offers a retry", async () => {
  server.use(
    http.get("/api/v1/cases", () => HttpResponse.json({ items: [caseRow], next_cursor: null })),
    http.get("/api/v1/cases/c-1/forensics", () =>
      HttpResponse.json({ title: "Service unavailable", status: 503, detail: "Try again." }, {
        status: 503, headers: { "Content-Type": "application/problem+json" } })),
  );
  signIn(me);
  renderAt("/forensics");
  expect(await screen.findByRole("button", { name: /retry/i })).toBeInTheDocument();
});
