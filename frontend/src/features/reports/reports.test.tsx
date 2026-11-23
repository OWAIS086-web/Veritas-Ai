// Req: reporting 2.1, 2.4, 3.1, 3.2 (against API-shaped responses)
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { vi } from "vitest";

import * as download from "@/features/reports/download";
import { me } from "@/test/fixtures";
import { renderAt, signIn } from "@/test/render";
import { server } from "@/test/server";
import type { CaseOut, InvestigationOut, ReportDetail, ReportOut } from "@/types/api";

const caseRow: CaseOut = {
  id: "c-1", title: "Shipment SHIP-2049", objective: "", investigation_type: "international_shipment",
  priority: "high", status: "open", created_by: "u-1", created_by_email: "ana@example.com",
  created_at: "2026-11-23T10:00:00Z", updated_at: "2026-11-23T10:00:00Z", document_count: 7,
  documents_completed: 7, documents_failed: 0, finding_count: 1, compared_at: "2026-11-23T10:05:00Z",
};

const done: ReportOut = {
  id: "r-1", case_id: "c-1", investigation_id: null, format: "pdf", status: "completed", sha256: "ab".repeat(32),
  size_bytes: 20480, error: null, created_by: "u-1", created_by_email: "ana@example.com",
  created_at: "2026-11-23T10:10:00Z", finished_at: "2026-11-23T10:10:03Z", findings_total: 1, findings_not_reviewed: 1,
};
const failed: ReportOut = {
  ...done, id: "r-2", format: "docx", status: "failed", sha256: null, size_bytes: null,
  error: "document_not_in_case: {\"document_id\":\"x\"}; summary_value_not_in_content: 999999",
  created_at: "2026-11-23T10:00:00Z",
};

const detail: ReportDetail = {
  ...done,
  model: {
    title: "Investigation report: Shipment SHIP-2049",
    label: "SYNTHETIC DEMONSTRATION DATA",
    executive_summary: "The case contains 7 document(s).",
    scope: { documents: 7, findings: 1 },
    identified_discrepancies: [{
      finding_id: "f-1", title: "Declared totals differ by USD 20,000.00", severity: "high", priority: "high",
      review_label: "Not yet reviewed", evidence: [{}],
    }],
    evidence_references: [{
      finding_id: "f-1", document_id: "d-cd", filename: "03_customs_declaration.pdf", page: 2, field_id: "x-1",
      field_name: "total_amount", value: "USD 68,000.00", role: "conflicting",
    }],
    forensic_observations: [],
    missing_supporting_documents: [],
    alternative_explanations: [],
    limitations: ["This report states observations from the documents provided."],
    audit: { generated_by: "ana@example.com", generated_at: "2026-11-23T10:10:00Z", summary_method: "template", summary_note: null },
  },
};

const approvedInv = { id: "i-1", status: "completed", approved_at: "2026-11-23T10:08:00Z" } as InvestigationOut;

function handlers(reports: ReportOut[], created: unknown[] = []) {
  return [
    http.get("/api/v1/cases", () => HttpResponse.json({ items: [caseRow], next_cursor: null })),
    http.get("/api/v1/cases/c-1/reports", () => HttpResponse.json(reports)),
    http.get("/api/v1/cases/c-1/investigations", () =>
      HttpResponse.json([approvedInv, { ...approvedInv, id: "i-2", status: "awaiting_review", approved_at: null }])),
    http.get("/api/v1/reports/r-1", () => HttpResponse.json(detail)),
    http.get("/api/v1/reports/r-1/download", () =>
      HttpResponse.json({ url: "/api/v1/report-files/signed-token", expires_at: "2026-11-23T10:11:00Z" })),
    http.post("/api/v1/cases/c-1/reports", async ({ request }) => {
      created.push(await request.json());
      return HttpResponse.json({ ...done, id: "r-3", status: "queued", sha256: null }, { status: 202 });
    }),
  ];
}

test("the history shows each report's review status; the preview cites documents and pages", async () => {
  const spy = vi.spyOn(download, "startDownload").mockImplementation(() => undefined);
  server.use(...handlers([done, failed]));
  signIn({ ...me, permissions: [...me.permissions, "reports:read", "reports:create"] });
  renderAt("/reports?case=c-1");
  const history = await screen.findByRole("table", { name: "Report history" });
  expect(within(history).getAllByRole("row")).toHaveLength(3);
  expect(within(history).getByText("1 of 1")).toBeInTheDocument();
  expect(await screen.findByText("SYNTHETIC DEMONSTRATION DATA")).toBeInTheDocument();
  const discrepancies = screen.getByRole("list", { name: "Report discrepancies" });
  expect(within(discrepancies).getByText("Not yet reviewed")).toBeInTheDocument();
  const refs = screen.getByRole("table", { name: "Report evidence references" });
  expect(within(refs).getByRole("link", { name: "03_customs_declaration.pdf" })).toHaveAttribute("href", "/documents/d-cd?field=x-1");
  expect(within(refs).getByText("2")).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Download PDF" }));
  await waitFor(() => expect(spy).toHaveBeenCalledWith("/api/v1/report-files/signed-token"));
  spy.mockRestore();
});

test("a failed report lists the references that didn't resolve and offers no download", async () => {
  server.use(...handlers([failed]));
  signIn({ ...me, permissions: [...me.permissions, "reports:read", "reports:create"] });
  renderAt("/reports?case=c-1&report=r-2");
  const problems = await screen.findByRole("alert");
  expect(problems).toHaveTextContent("document_not_in_case");
  expect(problems).toHaveTextContent("summary_value_not_in_content: 999999");
  expect(screen.queryByRole("button", { name: /Download/ })).not.toBeInTheDocument();
});

test("only approved investigations can be included, and the request sends the format", async () => {
  const created: unknown[] = [];
  server.use(...handlers([], created));
  signIn({ ...me, permissions: [...me.permissions, "reports:read", "reports:create"] });
  renderAt("/reports?case=c-1");
  expect(await screen.findByText("No report has been generated for this case yet.")).toBeInTheDocument();
  const include = screen.getByLabelText("Include an investigation");
  expect(within(include).getAllByRole("option")).toHaveLength(2); // none + the one approved run
  await userEvent.selectOptions(screen.getByLabelText("Format"), "xlsx");
  await userEvent.selectOptions(include, "i-1");
  await userEvent.click(screen.getByRole("button", { name: "Generate report" }));
  await waitFor(() => expect(created).toEqual([{ format: "xlsx", investigation_id: "i-1" }]));
});

test("a read-only role sees reports but can't generate them", async () => {
  server.use(...handlers([done]));
  signIn({ ...me, role: "read_only_analyst", permissions: ["cases:read", "reports:read"] });
  renderAt("/reports?case=c-1");
  expect(await screen.findByText("Your role can read reports but not generate them.")).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Generate report" })).not.toBeInTheDocument();
});
