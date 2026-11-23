// Req: cross-document-intelligence 5.1, task 7; evidence-explorer 2.1-2.3, 2.5 (UI states)
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";

import { me } from "@/test/fixtures";
import { renderAt, signIn } from "@/test/render";
import { server } from "@/test/server";
import type { CaseOut, FindingDetail, FindingSummary } from "@/types/api";

const summary: FindingSummary = {
  id: "f-1", case_id: "c-1", case_title: "Shipment SHIP-2049", type: "financial_discrepancy",
  title: "Declared totals differ by USD 20,000.00", severity: "high", priority: "high",
  anomaly_score: "0.294", evidence_confidence: "1.000", field: "total_amount", currency: "USD",
  difference: "20000.00", status: "new", evidence_status: "supported", evidence_count: 2,
  requires_human_review: true, active: true, detected_by: "financial.total_amount@1.0",
  last_detected_at: "2026-11-23T10:05:00Z", created_at: "2026-11-23T10:05:00Z", updated_at: "2026-11-23T10:05:00Z",
};

const missing: FindingSummary = {
  ...summary, id: "f-2", type: "missing_document", title: "No packing list in the case", severity: "medium",
  priority: "medium", anomaly_score: null, evidence_confidence: null, field: null, currency: null, difference: null,
  evidence_status: "absence", evidence_count: 0, detected_by: "missing.expected_documents@1.0",
};

function detail(base: FindingSummary, overrides: Partial<FindingDetail> = {}): FindingDetail {
  return {
    ...base,
    explanation: "2 documents state a total in USD, and they do not agree.",
    severity_rationale: "The difference is 29.4% of the highest value.",
    limitations: ['Customs declaration (03_customs_declaration.pdf, page 2) states valuation basis "CIF Long Beach".'],
    recommended_action: "Review each cited value on its page.",
    coverage: { skipped: [] },
    ai_output_json: { detector: "rules", model: null },
    evidence: base.evidence_status === "absence" ? [] : [
      { id: "e-1", document_id: "d-2", document_filename: "02_commercial_invoice.pdf", doc_type: "commercial_invoice",
        extracted_field_id: "x-2", field_name: "total_amount", page_number: 1, bbox: [1, 2, 3, 4], location: null,
        value: "USD 48,000.00", normalized_value: { amount: "48000.00", currency: "USD" }, confidence: "1.000",
        role: "conflicting" },
      { id: "e-2", document_id: "d-3", document_filename: "03_customs_declaration.pdf", doc_type: "customs_declaration",
        extracted_field_id: "x-3", field_name: "total_amount", page_number: 2, bbox: [1, 2, 3, 4], location: null,
        value: "USD 68,000.00", normalized_value: { amount: "68000.00", currency: "USD" }, confidence: "1.000",
        role: "conflicting" },
    ],
    decisions: [],
    comments: [],
    ...overrides,
  };
}

test("the Findings Center lists findings with three separate scores and filters by type", async () => {
  const seen: string[] = [];
  server.use(http.get("/api/v1/findings", ({ request }) => {
    const url = new URL(request.url);
    seen.push(url.searchParams.get("type") ?? "");
    const items = url.searchParams.get("type") === "missing_document" ? [missing] : [summary, missing];
    return HttpResponse.json({ items, next_cursor: null });
  }));
  signIn(me);
  renderAt("/findings");
  const link = await screen.findByRole("link", { name: "Declared totals differ by USD 20,000.00" });
  expect(link).toHaveAttribute("href", "/findings/f-1");
  const row = link.closest("tr") as HTMLElement;
  expect(within(row).getByText("0.294")).toBeInTheDocument();
  expect(within(row).getByText("1.000")).toBeInTheDocument();
  expect(within(row).getByText("USD 20,000.00")).toBeInTheDocument();
  // Severity and priority are separate values; both happen to be high here.
  expect(within(row).getAllByText("high")).toHaveLength(2);
  const absentRow = screen.getByRole("link", { name: "No packing list in the case" }).closest("tr") as HTMLElement;
  expect(within(absentRow).getAllByText("not measured")).toHaveLength(2);
  expect(within(absentRow).getByText("absence")).toBeInTheDocument();

  await userEvent.selectOptions(screen.getByLabelText("Type"), "missing_document");
  await waitFor(() => expect(seen).toContain("missing_document"));
  await waitFor(() => expect(screen.queryByText("Declared totals differ by USD 20,000.00")).not.toBeInTheDocument());
});

test("an empty Findings Center explains where findings come from", async () => {
  server.use(http.get("/api/v1/findings", () => HttpResponse.json({ items: [], next_cursor: null })));
  signIn(me);
  const { router } = renderAt("/findings");
  expect(await screen.findByText("No findings yet")).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Open investigations" }));
  expect(router.state.location.pathname).toBe("/investigations");
});

test("the detail page cites each evidence item at its source and records a decision with a note", async () => {
  let patched: unknown = null;
  let current = detail(summary);
  server.use(
    http.get("/api/v1/findings/f-1", () => HttpResponse.json(current)),
    http.patch("/api/v1/findings/f-1/status", async ({ request }) => {
      patched = await request.json();
      current = detail(summary, {
        status: "confirmed_observation",
        decisions: [{ id: "dec-1", actor_user_id: "u-1", actor_email: "ana@example.com", from_status: "new",
                      to_status: "confirmed_observation", note: "Verified on each page.", created_at: "2026-11-23T11:00:00Z" }],
      });
      return HttpResponse.json(current);
    }),
  );
  signIn(me);
  renderAt("/findings/f-1");
  expect(await screen.findByRole("heading", { level: 1, name: "Declared totals differ by USD 20,000.00" })).toBeInTheDocument();
  expect(screen.getByLabelText("Anomaly score: 0.294")).toBeInTheDocument();
  expect(screen.getByLabelText("Evidence confidence: 1.000")).toBeInTheDocument();
  expect(screen.getByText(/valuation basis "CIF Long Beach"/)).toBeInTheDocument();

  const table = screen.getByRole("table", { name: "Evidence items" });
  const open = within(table).getByRole("link", { name: "Open 03_customs_declaration.pdf at page 2" });
  expect(open).toHaveAttribute("href", "/documents/d-3?field=x-3");

  const submit = screen.getByRole("button", { name: "Record decision" });
  await userEvent.selectOptions(screen.getByLabelText("New status"), "confirmed_observation");
  expect(screen.getByText("Note (required)")).toBeInTheDocument();
  expect(submit).toBeDisabled();
  await userEvent.type(screen.getByLabelText("Note (required)"), "Verified on each page.");
  await userEvent.click(submit);
  await waitFor(() => expect(patched).toEqual({ status: "confirmed_observation", note: "Verified on each page." }));
  const history = await screen.findByRole("list", { name: "Decision history" });
  expect(within(history).getByText("New → Confirmed observation")).toBeInTheDocument();
  expect(within(history).getByText("Verified on each page.")).toBeInTheDocument();
});

test("a finding based on an absence can't be confirmed and the page says why", async () => {
  server.use(http.get("/api/v1/findings/f-2", () => HttpResponse.json(detail(missing))));
  signIn(me);
  renderAt("/findings/f-2");
  expect(await screen.findByText("Based on an absence")).toBeInTheDocument();
  await userEvent.selectOptions(screen.getByLabelText("New status"), "confirmed_observation");
  expect(screen.getByRole("note")).toHaveTextContent("can't be confirmed");
  await userEvent.type(screen.getByLabelText("Note (required)"), "x");
  expect(screen.getByRole("button", { name: "Record decision" })).toBeDisabled();
});

test("a read-only analyst sees findings but no review controls", async () => {
  server.use(http.get("/api/v1/findings/f-1", () => HttpResponse.json(detail(summary))));
  signIn({ ...me, role: "read_only_analyst", permissions: ["findings:read", "cases:read", "documents:read"] });
  renderAt("/findings/f-1");
  expect(await screen.findByText("Your role can read findings but not record decisions.")).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Record decision" })).not.toBeInTheDocument();
  expect(screen.queryByLabelText("Comment")).not.toBeInTheDocument();
});

test("the case workspace lists the case findings and queues a comparison", async () => {
  let compared = false;
  const compareCase: CaseOut = {
    id: "c-1", title: "Shipment SHIP-2049", objective: "", investigation_type: "international_shipment",
    priority: "high", status: "open", created_by: "u-1", created_by_email: "ana@example.com",
    created_at: "2026-11-23T10:00:00Z", updated_at: "2026-11-23T10:00:00Z", document_count: 7,
    documents_completed: 7, documents_failed: 0, finding_count: 1, compared_at: "2026-11-23T10:05:00Z",
  };
  server.use(
    http.get("/api/v1/cases/c-1", () => HttpResponse.json(compareCase)),
    http.get("/api/v1/cases/c-1/documents", () => HttpResponse.json([])),
    http.get("/api/v1/cases/c-1/findings", () => HttpResponse.json([summary])),
    http.post("/api/v1/cases/c-1/compare", () => {
      compared = true;
      return HttpResponse.json({ job_id: "j-9" }, { status: 202 });
    }),
    http.get("/api/v1/jobs/j-9/events", () => new HttpResponse("event: end\ndata: {}\n\n", {
      headers: { "Content-Type": "text/event-stream" } })),
  );
  signIn(me);
  renderAt("/investigations/c-1");
  const list = await screen.findByRole("list", { name: "Case findings" });
  expect(within(list).getByRole("link", { name: "Declared totals differ by USD 20,000.00" })).toHaveAttribute("href", "/findings/f-1");
  expect(within(list).getByText("2 evidence")).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Compare documents" }));
  await waitFor(() => expect(compared).toBe(true));
  expect(await screen.findByText("Comparison queued")).toBeInTheDocument();
});
