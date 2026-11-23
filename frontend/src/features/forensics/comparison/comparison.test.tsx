// Req: document-comparison 6.x, 7.x, 8.x (Comparison Lab UI states, against API-shaped responses)
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";

import { vi } from "vitest";

import * as download from "@/features/reports/download";
import { api } from "@/services/api";
import { me } from "@/test/fixtures";
import { renderAt, signIn } from "@/test/render";
import { server } from "@/test/server";
import type {
  CaseOut, ComparisonDetail, ComparisonFindingOut, ComparisonOut, DocumentOut, VlmStatusOut,
} from "@/types/api";

const LIMITATION = "A difference between two files shows what changed, not who changed it or why; on its own it does not establish that either document is forged or authentic.";
const PERMS = [...me.permissions, "forensics:read", "comparisons:read", "comparisons:run"];

const caseRow: CaseOut = {
  id: "c-1", title: "Invoice comparison", objective: "", investigation_type: "international_shipment",
  priority: "high", status: "open", created_by: "u-1", created_by_email: "ana@example.com",
  created_at: "2026-11-23T10:00:00Z", updated_at: "2026-11-23T10:00:00Z", document_count: 2,
  documents_completed: 2, documents_failed: 0, finding_count: 0, compared_at: null,
};

function doc(id: string, name: string): DocumentOut {
  return {
    id, case_id: "c-1", original_filename: name, mime_type: "image/png", page_count: 1, status: "completed",
    sha256: "a".repeat(64), size_bytes: 1000, detection_reason: "magic_bytes", doc_type: "commercial_invoice",
    classification_confidence: null, current_stage: null, error: null, language: "en", pipeline_version: "1",
    processed_at: "2026-11-23T10:00:00Z", source_archive: null, uploaded_at: "2026-11-23T10:00:00Z",
    supersedes_id: null, stages: [],
  } as DocumentOut;
}

const base: ComparisonOut = {
  id: "cmp-1", case_id: "c-1", original_document_id: "d-o", test_document_id: "d-t",
  original_filename: "original_invoice.png", test_filename: "test_altered.png", status: "completed",
  stage: "completed", progress: 100, vlm_status: "used", vlm_model: "qwen2.5vl:7b", error: null,
  created_by: "u-1", created_at: "2026-11-23T10:00:00Z", started_at: "2026-11-23T10:00:01Z",
  finished_at: "2026-11-23T10:00:30Z", findings_count: 2, findings_unreviewed: 2,
};

const total: ComparisonFindingOut = {
  id: "f-1", number: 1, type: "text_changed", sources: ["ocr", "cv", "vlm"], test_page: 1, original_page: 1,
  region: [223, 239, 268, 253], original_region: [223, 239, 268, 253], original_text: "48,000.00",
  test_text: "68,000.00", severity: "medium", evidence_confidence: "0.900",
  explanation: 'On page 1, the test document reads "68,000.00" where the original reads "48,000.00".',
  metrics: { confidence_basis: ["ocr + cv + text_layer evidence: 0.80", "vision model sees the difference: +0.10"],
             extracted_fields: [{ id: "x-1", document: "test", name: "total_amount", value: "USD 68,000.00" }] },
  vlm_assessment: { status: "assessed", visible_difference: true, description: "The number changed." },
  review_status: "unreviewed", reviewed_by: null, reviewed_at: null,
};
const removed: ComparisonFindingOut = {
  ...total, id: "f-2", number: 2, type: "page_removed", sources: ["page"], test_page: null, original_page: 2,
  region: null, original_region: [0, 0, 595, 842], original_text: null, test_text: null,
  explanation: "The original's page 2 has no counterpart in the test document.", metrics: {}, vlm_assessment: null,
};

const detail: ComparisonDetail = {
  ...base, settings: {}, limitation: LIMITATION,
  summary: {
    original: { sha256: "1".repeat(64) }, test: { sha256: "2".repeat(64) },
    pages: [{ test_page: 1, original_page: 1, alignment: "ecc", page_ssim: 0.983, text_compared: true, test_text_method: "ocr" }],
    vlm: { calls: 3, seconds: 15.5, boxes_rejected: 2, proposals_rejected: [{}, {}] },
  },
  findings: [total, removed],
  exports: [
    { id: "e-1", kind: "annotated_pdf", status: "completed", sha256: "f".repeat(64), size_bytes: 10, error: null,
      created_at: "2026-11-23T10:00:31Z", finished_at: "2026-11-23T10:00:33Z" },
    { id: "e-2", kind: "report_pdf", status: "queued", sha256: null, size_bytes: null, error: null,
      created_at: "2026-11-23T10:00:31Z", finished_at: null },
  ],
};

const vlm: VlmStatusOut = {
  enabled: true, configured: true, model: "qwen2.5vl:7b", endpoint_host: "host.docker.internal",
  reachable: true, model_available: true, error: null,
};

function handlers(d: ComparisonDetail = detail, list: ComparisonOut[] = [base]) {
  return [
    http.get("/api/v1/cases", () => HttpResponse.json({ items: [caseRow], next_cursor: null })),
    http.get("/api/v1/cases/c-1/comparisons", () => HttpResponse.json(list)),
    http.get("/api/v1/cases/c-1/documents", () =>
      HttpResponse.json([doc("d-o", "original_invoice.png"), doc("d-t", "test_altered.png")])),
    http.get("/api/v1/comparisons/cmp-1", () => HttpResponse.json(d)),
    http.get("/api/v1/comparisons/cmp-1/findings/:fid/reviews", () => HttpResponse.json([])),
    http.get("/api/v1/system/vlm-status", () => HttpResponse.json(vlm)),
    http.get("/api/v1/documents/:id/preview", () =>
      HttpResponse.json({ url: "/blob/page.png", mime_type: "image/png", expires_at: "2026-11-23T10:01:00Z" })),
  ];
}

test("the lab is a tab of the Forensics Lab and shows both documents with the differences", async () => {
  server.use(...handlers());
  signIn({ ...me, permissions: PERMS });
  renderAt("/forensics?case=c-1&tab=compare");

  expect(await screen.findByRole("tab", { name: "Comparison Lab", selected: true })).toBeInTheDocument();
  expect(await screen.findByText("Vision model ready")).toBeInTheDocument();
  const table = await screen.findByRole("table", { name: "Comparisons" });
  expect(within(table).getByText("2 (2 not reviewed)")).toBeInTheDocument();

  expect(await screen.findByRole("region", { name: "Original document" })).toBeInTheDocument();
  const testPane = screen.getByRole("region", { name: "Test document" });
  expect(within(testPane).getByText("test_altered.png")).toBeInTheDocument();
  expect(screen.getByText("Page 1 of 1")).toBeInTheDocument();

  const list = screen.getByRole("list", { name: "Differences" });
  expect(within(list).getAllByRole("button")).toHaveLength(2);
  expect(within(list).getByText("Page missing")).toBeInTheDocument();
  expect(within(list).getAllByText("medium")).toHaveLength(2); // severity is labelled, not colour-only
  expect(screen.getByText(LIMITATION)).toBeInTheDocument();
  expect(screen.getByText(/3 calls, 15.5 s, 2 model boxes rejected, 2 proposals without pixel evidence/)).toBeInTheDocument();

  await userEvent.click(within(list).getByRole("button", { name: /Text changed/ }));
  const article = screen.getByRole("article", { name: "Difference 1" });
  expect(within(article).getByText("68,000.00")).toBeInTheDocument();
  expect(within(article).getByText("48,000.00")).toBeInTheDocument();
  expect(within(article).getByText("Vision model")).toBeInTheDocument();
  expect(within(article).getByText(/test total amount = USD 68,000.00/)).toBeInTheDocument();
  expect(await within(article).findByText("No review decisions yet.")).toBeInTheDocument();
});

test("confirming a difference needs a note and records the review", async () => {
  let sent: unknown = null;
  server.use(
    ...handlers(),
    http.patch("/api/v1/comparisons/cmp-1/findings/f-1/review", async ({ request }) => {
      sent = await request.json();
      return HttpResponse.json({ ...total, review_status: "confirmed_difference" });
    }),
  );
  signIn({ ...me, permissions: PERMS });
  renderAt("/forensics?case=c-1&tab=compare&cmp=cmp-1");
  const list = await screen.findByRole("list", { name: "Differences" });
  await userEvent.click(within(list).getByRole("button", { name: /Text changed/ }));

  const save = screen.getByRole("button", { name: "Save review" });
  expect(save).toBeDisabled();
  await userEvent.type(screen.getByLabelText("Note (required)"), "Matches the purchase order.");
  expect(save).toBeEnabled();
  await userEvent.click(save);
  await waitFor(() => expect(sent).toEqual({ status: "confirmed_difference", note: "Matches the purchase order." }));
  expect(await screen.findByText("Review saved")).toBeInTheDocument();
});

test("exports download through a signed link and a queued export can't be downloaded yet", async () => {
  const spy = vi.spyOn(download, "startDownload").mockImplementation(() => undefined);
  server.use(
    ...handlers(),
    http.get("/api/v1/comparison-exports/e-1/download", () =>
      HttpResponse.json({ url: "/api/v1/comparison-files/tok", expires_at: "2026-11-23T10:01:00Z" })),
  );
  signIn({ ...me, permissions: PERMS });
  renderAt("/forensics?case=c-1&tab=compare");
  const exports = await screen.findByRole("list", { name: "Exports" });
  expect(within(exports).getByRole("button", { name: "Download Comparison report (PDF)" })).toBeDisabled();
  expect(within(exports).getAllByText("Not generated")).toHaveLength(2);
  await userEvent.click(within(exports).getByRole("button", { name: "Download Annotated test document (PDF)" }));
  await waitFor(() => expect(spy).toHaveBeenCalledWith("/api/v1/comparison-files/tok"));
  spy.mockRestore();
});

test("uploading an original and a test file starts a comparison", async () => {
  // jsdom's FormData can't be serialized by Node's fetch, so the hand-off to the API client is
  // checked here; the real multipart request runs in the backend and Playwright suites.
  const uploadSpy = vi.spyOn(api, "uploadComparison").mockResolvedValue({
    comparison: { ...base, status: "queued", progress: 0 },
    original: { filename: "a.pdf", status: "accepted", document_id: "d-o", reason: null, detected_type: "application/pdf" },
    test: { filename: "b.pdf", status: "accepted", document_id: "d-t", reason: null, detected_type: "application/pdf" },
    job_id: "j-1",
  });
  server.use(...handlers(detail, []));
  signIn({ ...me, permissions: PERMS });
  renderAt("/forensics?case=c-1&tab=compare");
  expect(await screen.findByText("No comparisons yet")).toBeInTheDocument();
  const submit = screen.getByRole("button", { name: "Compare documents" });
  expect(submit).toBeDisabled();
  const original = new File(["%PDF"], "a.pdf", { type: "application/pdf" });
  const testFile = new File(["%PDF"], "b.pdf", { type: "application/pdf" });
  await userEvent.upload(screen.getByLabelText("Original document"), original);
  await userEvent.upload(screen.getByLabelText("Test document"), testFile);
  await userEvent.click(submit);
  await waitFor(() => expect(uploadSpy).toHaveBeenCalledWith("c-1", original, testFile));
  expect(await screen.findByText("Comparison queued")).toBeInTheDocument();
  uploadSpy.mockRestore();
});

test("a running comparison shows its persisted stage and a failed one offers a retry", async () => {
  let retried = false;
  const running = { ...detail, status: "running" as const, stage: "vision_analysis", progress: 60, findings: [], exports: [] };
  server.use(...handlers(running, [{ ...base, status: "running", progress: 60 }]));
  signIn({ ...me, permissions: PERMS });
  const { unmount } = renderAt("/forensics?case=c-1&tab=compare");
  expect(await screen.findByText("Checking regions with the vision model")).toBeInTheDocument();
  expect(screen.getByRole("progressbar", { name: "Comparison progress" })).toHaveAttribute("aria-valuenow", "60");
  unmount();

  const failed = { ...running, status: "failed" as const, error: "Document processing failed for broken.pdf." };
  server.use(
    ...handlers(failed, [{ ...base, status: "failed" }]),
    http.post("/api/v1/comparisons/cmp-1/retry", () => { retried = true; return HttpResponse.json({ ...base, status: "queued" }, { status: 202 }); }),
  );
  renderAt("/forensics?case=c-1&tab=compare");
  expect(await screen.findByText(/Document processing failed for broken.pdf/)).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Retry comparison" }));
  await waitFor(() => expect(retried).toBe(true));
});

test("a read-only analyst can read comparisons but not start or review them", async () => {
  server.use(...handlers());
  signIn({ ...me, permissions: ["cases:read", "documents:read", "forensics:read", "comparisons:read"] });
  renderAt("/forensics?case=c-1&tab=compare");
  expect(await screen.findByText("Your role can read comparisons but not start them.")).toBeInTheDocument();
  const list = await screen.findByRole("list", { name: "Differences" });
  await userEvent.click(within(list).getByRole("button", { name: /Text changed/ }));
  expect(screen.getByText("Your role can read but not review differences.")).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Save review" })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /Regenerate/ })).not.toBeInTheDocument();
});

test("without the comparison permission the Forensics Lab shows no comparison tab", async () => {
  server.use(
    http.get("/api/v1/cases", () => HttpResponse.json({ items: [caseRow], next_cursor: null })),
    http.get("/api/v1/cases/c-1/forensics", () => HttpResponse.json([])),
  );
  signIn({ ...me, permissions: [...me.permissions, "forensics:read"] });
  renderAt("/forensics?case=c-1&tab=compare");
  expect(await screen.findByText("No documents in this investigation")).toBeInTheDocument();
  expect(screen.queryByRole("tab")).not.toBeInTheDocument();
});
