// Req: document-ingestion 1.1-1.2, 2.1; document-intelligence 1.5, 6.1 (UI states)
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";

import { api } from "@/services/api";
import { me } from "@/test/fixtures";
import { renderAt, signIn } from "@/test/render";
import { server } from "@/test/server";
import type { CaseOut, DocumentOut, ExtractionOut } from "@/types/api";

const caseRow: CaseOut = {
  id: "c-1", title: "Shipment SHIP-2049", objective: "Reconcile declared values",
  investigation_type: "international_shipment", priority: "high", status: "open",
  created_by: "u-1", created_by_email: "ana@example.com", created_at: "2026-11-23T10:00:00Z",
  updated_at: "2026-11-23T10:00:00Z", document_count: 2, documents_completed: 1, documents_failed: 1,
  finding_count: null, compared_at: null,
};

function doc(overrides: Partial<DocumentOut>): DocumentOut {
  return {
    id: "d-1", case_id: "c-1", original_filename: "02_commercial_invoice.pdf", sha256: "a".repeat(64),
    mime_type: "text/csv", detection_reason: "delimited text", size_bytes: 1200, page_count: 1,
    doc_type: "commercial_invoice", classification_confidence: "0.900", language: "en",
    status: "completed", current_stage: null, error: null, pipeline_version: "p2.1", source_archive: null,
    uploaded_at: "2026-11-23T10:00:00Z", processed_at: "2026-11-23T10:01:00Z", supersedes_id: null,
    stages: [
      { stage: "parse", status: "succeeded", attempts: 1, started_at: null, finished_at: null, error: null, metrics: {} },
      { stage: "classify", status: "succeeded", attempts: 1, started_at: null, finished_at: null, error: null, metrics: {} },
    ],
    ...overrides,
  };
}

const extraction: ExtractionOut = {
  run_id: "r-1", document_id: "d-1", method: "rules", provider: null, model_version: "rules-extract-1.0",
  prompt_version: null, pipeline_version: "p2.1", notes: {}, finished_at: "2026-11-23T10:01:00Z",
  fields: [
    { id: "f-1", name: "total_amount", value: "USD 48,000.00", normalized_value: { amount: "48000.00", currency: "USD" },
      value_type: "amount", currency: "USD", semantic_role: "invoice_total", confidence: "1.000", document_id: "d-1",
      page_number: null, bbox: null, location: "row 11 col 2", method: "parser", model_version: "rules-extract-1.0",
      status: "extracted", rejection_reason: null },
    { id: "f-2", name: "buyer", value: null, normalized_value: null, value_type: "party", currency: null,
      semantic_role: null, confidence: null, document_id: "d-1", page_number: null, bbox: null, location: null,
      method: "rules", model_version: "rules-extract-1.0", status: "uncertain", rejection_reason: "not_found" },
  ],
};

test("the list shows cases with real counts and links to the workspace", async () => {
  server.use(http.get("/api/v1/cases", () => HttpResponse.json({ items: [caseRow], next_cursor: null })));
  signIn(me);
  renderAt("/investigations");
  const link = await screen.findByRole("link", { name: "Shipment SHIP-2049" });
  expect(link).toHaveAttribute("href", "/investigations/c-1");
  const row = link.closest("tr") as HTMLElement;
  expect(within(row).getByText("1/2")).toBeInTheDocument();
  expect(within(row).getByText("1 failed")).toBeInTheDocument();
  expect(within(row).getByText("Not compared yet")).toBeInTheDocument();
});

test("a compared case shows its finding count linked to the Findings Center", async () => {
  server.use(http.get("/api/v1/cases", () => HttpResponse.json({
    items: [{ ...caseRow, finding_count: 1, compared_at: "2026-11-23T10:05:00Z" }], next_cursor: null,
  })));
  signIn(me);
  renderAt("/investigations");
  const row = (await screen.findByRole("link", { name: "Shipment SHIP-2049" })).closest("tr") as HTMLElement;
  expect(within(row).getByRole("link", { name: "1" })).toHaveAttribute("href", "/findings?case=c-1");
});

test("an empty organization gets guidance and a real create action", async () => {
  server.use(http.get("/api/v1/cases", () => HttpResponse.json({ items: [], next_cursor: null })));
  signIn(me);
  const { router } = renderAt("/investigations");
  await userEvent.click(await screen.findByRole("button", { name: "Create the first investigation" }));
  expect(router.state.location.pathname).toBe("/investigations/new");
});

test("creating an investigation uploads the chosen files as multipart", async () => {
  let createdBody: unknown = null;
  // jsdom's FormData can't be serialized by Node's fetch, so the hand-off to the API client is
  // checked here; the real multipart request runs in the backend and Playwright suites.
  const uploadSpy = vi.spyOn(api, "uploadDocuments").mockResolvedValue({
    results: [{ filename: "invoice.pdf", status: "accepted", document_id: "d-1", reason: null, detected_type: "application/pdf" },
              { filename: "notes.txt", status: "rejected", document_id: null, reason: "unsupported_type", detected_type: null }],
    job_id: "j-1",
  });
  server.use(
    http.post("/api/v1/cases", async ({ request }) => {
      createdBody = await request.json();
      return HttpResponse.json(caseRow, { status: 201 });
    }),
    http.get("/api/v1/cases/c-1", () => HttpResponse.json(caseRow)),
    http.get("/api/v1/cases/c-1/documents", () => HttpResponse.json([])),
    http.get("/api/v1/cases/c-1/findings", () => HttpResponse.json([])),
    http.get("/api/v1/jobs/j-1/events", () => new HttpResponse("event: end\ndata: {}\n\n", {
      headers: { "Content-Type": "text/event-stream" } })),
  );
  signIn(me);
  const { router } = renderAt("/investigations/new");
  // Drag-and-drop bypasses the input's accept filter, so the server must reject bad types.
  const user = userEvent.setup({ applyAccept: false });
  await user.type(screen.getByLabelText("Case title"), "Shipment SHIP-2049");
  await user.upload(screen.getByLabelText("Choose documents to upload"), [
    new File(["%PDF-1.7"], "invoice.pdf", { type: "application/pdf" }),
    new File(["hello"], "notes.txt", { type: "text/plain" }),
  ]);
  expect(screen.getByRole("list", { name: "Files to upload" })).toHaveTextContent("invoice.pdf");
  await user.click(screen.getByRole("button", { name: "Create and process 2 documents" }));
  await waitFor(() => expect(router.state.location.pathname).toBe("/investigations/c-1"));
  expect(createdBody).toMatchObject({ title: "Shipment SHIP-2049", investigation_type: "international_shipment" });
  expect(uploadSpy).toHaveBeenCalledOnce();
  expect(uploadSpy.mock.calls[0]?.[0]).toBe("c-1");
  expect(uploadSpy.mock.calls[0]?.[1].map((f) => f.name)).toEqual(["invoice.pdf", "notes.txt"]);
  uploadSpy.mockRestore();
  expect(await screen.findByText(/1 document\(s\) queued for processing, 1 rejected/)).toBeInTheDocument();
});

test("the workspace lists documents, shows failures with retry and the fields with provenance", async () => {
  let retried = false;
  const failed = doc({ id: "d-2", original_filename: "scan.pdf", status: "failed", doc_type: null,
                       error: "parse: ocr_unavailable", mime_type: "application/pdf" });
  server.use(
    http.get("/api/v1/cases/c-1", () => HttpResponse.json(caseRow)),
    http.get("/api/v1/cases/c-1/documents", () => HttpResponse.json([doc({}), failed])),
    http.get("/api/v1/cases/c-1/findings", () => HttpResponse.json([])),
    http.get("/api/v1/documents/d-1/pages", () => HttpResponse.json([{
      page_number: 1, width: null, height: null, coord_unit: "pt", method: "parser", text: "Invoice Total | USD 48,000.00",
      lines: [{ text: "Invoice Total | USD 48,000.00", location: "row 11", tokens: [{ s: 0, e: 13, loc: "row 11 col 1" }, { s: 16, e: 29, loc: "row 11 col 2" }] }],
      tables: [], ocr_mean_confidence: null }])),
    http.get("/api/v1/documents/d-1/extractions", () => HttpResponse.json(extraction)),
    http.post("/api/v1/documents/d-2/retry", () => {
      retried = true;
      return HttpResponse.json({ id: "j-2", kind: "document.process", status: "queued", progress: 0, attempts: 0,
                                 max_attempts: 2, error: null, result: null, created_at: "", updated_at: "" }, { status: 202 });
    }),
    http.get("/api/v1/jobs/j-2/events", () => new HttpResponse("event: end\ndata: {}\n\n", {
      headers: { "Content-Type": "text/event-stream" } })),
  );
  signIn(me);
  renderAt("/investigations/c-1");
  const list = await screen.findByRole("list", { name: "Case documents" });
  expect(within(list).getByText("parse: ocr_unavailable")).toBeInTheDocument();
  expect(within(list).getAllByText("Failed")[0]).toBeInTheDocument();

  const fields = await screen.findByRole("list", { name: "Extracted fields" });
  expect(within(fields).getByText("USD 48,000.00")).toBeInTheDocument();
  expect(within(fields).getByText("row 11 col 2")).toBeInTheDocument();
  expect(within(fields).getByText("Uncertain: not found")).toBeInTheDocument();
  expect(within(fields).getByText("null")).toBeInTheDocument();

  await userEvent.click(within(fields).getByRole("button", { name: /Total amount/ }));
  const parsed = screen.getByRole("list", { name: "Parsed content" });
  expect(parsed.querySelector("[data-active]")).toHaveTextContent("Invoice Total | USD 48,000.00");

  await userEvent.click(within(list).getByRole("button", { name: "Retry" }));
  await waitFor(() => expect(retried).toBe(true));
  expect(await screen.findByText("Retry queued")).toBeInTheDocument();
});
