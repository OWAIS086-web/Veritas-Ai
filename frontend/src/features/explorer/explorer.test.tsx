// Req: evidence-explorer 1.2, 1.3, 2.4 (against API-shaped responses)
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";

import { me } from "@/test/fixtures";
import { renderAt, signIn } from "@/test/render";
import { server } from "@/test/server";
import type { DocumentOut, EvidenceOut, FindingDetail } from "@/types/api";

const ev = (id: string, doc: string, name: string, page: number, value: string, role: "supporting" | "conflicting"): EvidenceOut => ({
  id, document_id: doc, document_filename: name, doc_type: "commercial_invoice", extracted_field_id: `x-${id}`,
  field_name: "total_amount", page_number: page, bbox: [100, 200, 220, 214], location: null, value,
  normalized_value: null, confidence: "1.000", role,
});

const finding: FindingDetail = {
  id: "f-1", case_id: "c-1", case_title: "Shipment SHIP-2049", type: "financial_discrepancy",
  title: "Declared totals differ by USD 20,000.00", severity: "high", priority: "high", anomaly_score: "0.294",
  evidence_confidence: "1.000", field: "total_amount", currency: "USD", difference: "20000.00", status: "new",
  evidence_status: "supported", evidence_count: 2, assignee_user_id: null, requires_human_review: true, active: true,
  detected_by: "amount_mismatch@1", last_detected_at: "2026-11-23T10:00:00Z", created_at: "2026-11-23T10:00:00Z",
  updated_at: "2026-11-23T10:00:00Z", explanation: "The totals differ.", severity_rationale: "", limitations: [],
  recommended_action: "", coverage: {}, ai_output_json: {}, decisions: [], comments: [], assignee_email: null,
  evidence_requests: [],
  evidence: [
    ev("e-inv", "d-inv", "02_commercial_invoice.png", 1, "USD 48,000.00", "supporting"),
    ev("e-cd", "d-cd", "03_customs_declaration.png", 2, "USD 68,000.00", "conflicting"),
  ],
};

const doc = (id: string, name: string): DocumentOut => ({
  id, case_id: "c-1", original_filename: name, sha256: "ab", mime_type: "image/png", size_bytes: 10, page_count: 2,
  doc_type: "commercial_invoice", classification_confidence: null, language: "en", status: "completed",
  current_stage: null, error: null, pipeline_version: "2", uploaded_at: "2026-11-23T10:00:00Z",
  processed_at: "2026-11-23T10:00:00Z", supersedes_id: null, stages: [], detection_reason: "magic bytes",
  source_archive: null,
});

function handlers() {
  return [
    http.get("/api/v1/findings", () => HttpResponse.json({ items: [finding], next_cursor: null })),
    http.get("/api/v1/findings/f-1", () => HttpResponse.json(finding)),
    http.get("/api/v1/documents/d-inv", () => HttpResponse.json(doc("d-inv", "02_commercial_invoice.png"))),
    http.get("/api/v1/documents/d-cd", () => HttpResponse.json(doc("d-cd", "03_customs_declaration.png"))),
    http.get("/api/v1/documents/:id/preview", () =>
      HttpResponse.json({ url: "/blob/page.png", mime_type: "image/png", expires_at: "2026-11-23T10:01:00Z" })),
  ];
}

test("the explorer opens supporting and conflicting documents side by side at the cited pages", async () => {
  server.use(...handlers());
  signIn(me);
  renderAt("/evidence?finding=f-1");
  expect(await screen.findByText("Declared totals differ by USD 20,000.00")).toBeInTheDocument();
  expect(screen.getByLabelText("Highlight legend")).toHaveTextContent("Supporting value");
  expect(screen.getByLabelText("Highlight legend")).toHaveTextContent("Conflicting value");
  // The left pane opens the supporting document at page 1, the right the conflicting one at page 2.
  expect(screen.getByLabelText("Left document")).toHaveValue("d-inv");
  expect(screen.getByLabelText("Right document")).toHaveValue("d-cd");
  expect(await screen.findByText("Page 1 of 2")).toBeInTheDocument();
  expect(screen.getByText("Page 2 of 2")).toBeInTheDocument();
  const right = screen.getByRole("list", { name: "Evidence in the right document" });
  expect(within(right).getByText("Conflicting")).toBeInTheDocument();
  expect(within(right).getByText("USD 68,000.00")).toBeInTheDocument();

  // Choosing another document in a pane opens it at its evidence page.
  await userEvent.selectOptions(screen.getByLabelText("Right document"), "d-inv");
  await waitFor(() => expect(screen.getAllByText("Page 1 of 2")).toHaveLength(2));
});

test("without a finding the explorer asks for one", async () => {
  server.use(...handlers());
  signIn(me);
  renderAt("/evidence");
  // The empty-state title (a paragraph), not the picker option with the same words.
  expect(await screen.findByText("Choose a finding", { selector: "p" })).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Open the Findings Center" })).toHaveAttribute("href", "/findings");
});

test("a finding based on an absence explains that there is nothing to highlight", async () => {
  server.use(...handlers(), http.get("/api/v1/findings/f-2", () => HttpResponse.json({ ...finding, id: "f-2", evidence: [] })));
  signIn(me);
  renderAt("/evidence?finding=f-2");
  expect(await screen.findByText("This finding has no evidence documents")).toBeInTheDocument();
});

test("a finding can be assigned to a member and documents requested for it", async () => {
  const assigned: unknown[] = [];
  const requested: unknown[] = [];
  let current = finding;
  server.use(
    http.get("/api/v1/findings/f-1", () => HttpResponse.json(current)),
    http.get("/api/v1/organizations/o-1/members", () => HttpResponse.json([
      { user_id: "u-1", email: "ana@example.com", full_name: "Ana", role: "org_admin", created_at: "2026-11-20T10:00:00Z" },
      { user_id: "u-2", email: "ben@example.com", full_name: "Ben", role: "investigator", created_at: "2026-11-20T10:00:00Z" },
    ])),
    http.patch("/api/v1/findings/f-1/assignee", async ({ request }) => {
      assigned.push(await request.json());
      current = { ...current, assignee_user_id: "u-2", assignee_email: "ben@example.com" };
      return HttpResponse.json(current);
    }),
    http.post("/api/v1/findings/f-1/evidence-requests", async ({ request }) => {
      requested.push(await request.json());
      return HttpResponse.json({ id: "r-1", case_id: "c-1", investigation_id: null, finding_id: "f-1",
        document_types: ["freight_invoice"], note: "Explain the gap.", status: "open", created_by: "u-1",
        created_at: "2026-11-23T10:00:00Z" }, { status: 201 });
    }),
  );
  signIn({ ...me, permissions: [...me.permissions, "findings:assign"] });
  renderAt("/findings/f-1");
  expect(await screen.findByText("nobody")).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Compare the documents side by side" })).toHaveAttribute("href", "/evidence?finding=f-1");
  await userEvent.selectOptions(await screen.findByLabelText("Assign to"), "u-2");
  await waitFor(() => expect(assigned).toEqual([{ user_id: "u-2" }]));
  expect(await screen.findByText("ben@example.com", { selector: "span" })).toBeInTheDocument();

  await userEvent.type(screen.getByLabelText(/Request documents/), "freight_invoice");
  await userEvent.type(screen.getByLabelText("Why they are needed"), "Explain the gap.");
  await userEvent.click(screen.getByRole("button", { name: "Request documents" }));
  await waitFor(() => expect(requested).toEqual([{ document_types: ["freight_invoice"], note: "Explain the gap." }]));
});

test("a role without the assign permission sees the assignee but no control", async () => {
  server.use(http.get("/api/v1/findings/f-1", () => HttpResponse.json(finding)));
  signIn({ ...me, role: "reviewer", permissions: ["findings:read", "findings:review", "findings:comment"] });
  renderAt("/findings/f-1");
  expect(await screen.findByText("nobody")).toBeInTheDocument();
  expect(screen.queryByLabelText("Assign to")).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Request documents" })).toBeInTheDocument();
});
