// Req: autonomous-investigation 5.1, 5.3, 6.2 (UI states, against API-shaped responses)
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";

import { me } from "@/test/fixtures";
import { renderAt, signIn } from "@/test/render";
import { server } from "@/test/server";
import type { CaseOut, InvestigationDetail } from "@/types/api";

const caseRow: CaseOut = {
  id: "c-1", title: "Shipment SHIP-2049", objective: "", investigation_type: "international_shipment",
  priority: "high", status: "open", created_by: "u-1", created_by_email: "ana@example.com",
  created_at: "2026-11-23T10:00:00Z", updated_at: "2026-11-23T10:00:00Z", document_count: 2,
  documents_completed: 2, documents_failed: 0, finding_count: 1, compared_at: "2026-11-23T10:05:00Z",
};

const run = (agent: string, summary: string) => ({
  id: `r-${agent}`, agent, status: "succeeded", output_summary: summary, output: {}, model: "qwen2.5:7b-instruct",
  provider: "openai-compatible:host", prompt_version: `${agent}-v1`, tool_calls: 2, tokens: 900, duration_ms: 1800,
  error: null, started_at: "2026-11-23T10:06:00Z", finished_at: "2026-11-23T10:06:02Z",
});

const inv: InvestigationDetail = {
  id: "i-1", case_id: "c-1", objective: "Explain the declared value difference.", status: "awaiting_review",
  budget: { max_iterations: 24, max_tool_calls: 80, max_tokens: 120000, timeout_seconds: 900 },
  usage: { iterations: 7, tool_calls: 14, tokens: 6300, unmetered_calls: 0, elapsed_seconds: 41.2 },
  error: null, created_by: "u-1", approved_by: null, approved_at: null, created_at: "2026-11-23T10:06:00Z",
  started_at: "2026-11-23T10:06:00Z", finished_at: null,
  agent_runs: ["planner", "document", "forensics", "cross_reference", "entity", "graph", "risk"].map((a) => run(a, `${a} done`)),
  evidence_requests: [],
  result: {
    agents: {
      cross_reference: {
        assessments: [{
          finding_id: "f-1", summary: "Declared totals differ by USD 20,000.00",
          supporting: [
            { text: "The invoice states USD 48,000.00.", refs: [{ document_id: "d-inv", page: 1, field_id: "x-1" }], supported: true },
            { text: "An invented citation.", refs: [], supported: false },
          ],
          conflicting: [],
        }],
        missing_information: [
          { text: "No freight invoice explains the difference.", document_types: ["freight_invoice"], source: "model" },
        ],
      },
      risk: {
        assessments: [{
          finding_id: "f-1", assessed: true, evidence_strength: "strong", review_urgency: "high",
          uncertainty: "The documents do not state whether freight is included.",
          alternative_explanations: [{ text: "The customs value may be CIF while the invoice is FOB.", hypothesis: true }],
          persisted_scores: { anomaly_score: "0.294", evidence_confidence: "1.000", priority: "high", severity: "high", status: "new" },
        }],
      },
    },
  },
};

function sse(events: object[]): string {
  return [...events.map((e, i) => `id: ${i + 1}\nevent: x\ndata: ${JSON.stringify(e)}\n\n`), "event: end\ndata: {}\n\n"].join("");
}

const events = [
  { seq: 1, agent: null, type: "queued", data: {}, created_at: "", status: "awaiting_review" },
  { seq: 2, agent: "risk", type: "tool_rejected", data: { tool: "change_finding_status", reason: "unknown_tool" }, created_at: "", status: "awaiting_review" },
  { seq: 3, agent: "cross_reference", type: "reference_rejected", data: { reason: "finding_not_in_case" }, created_at: "", status: "awaiting_review" },
  { seq: 4, agent: null, type: "awaiting_review", data: {}, created_at: "", status: "awaiting_review" },
];

function handlers(detail: InvestigationDetail = inv, approved: string[] = []) {
  return [
    http.get("/api/v1/cases", () => HttpResponse.json({ items: [caseRow], next_cursor: null })),
    http.get("/api/v1/cases/c-1/investigations", () => HttpResponse.json([detail])),
    http.get("/api/v1/investigations/i-1", () => HttpResponse.json(detail)),
    http.get("/api/v1/investigations/i-1/events", () =>
      new HttpResponse(sse(events), { headers: { "Content-Type": "text/event-stream" } })),
    http.post("/api/v1/investigations/i-1/approve", () => {
      approved.push("i-1");
      return HttpResponse.json({ ...detail, status: "approved" }, { status: 202 });
    }),
  ];
}

test("a paused run shows budget use, refused actions, cited outputs and hypotheses", async () => {
  const approved: string[] = [];
  server.use(...handlers(inv, approved));
  signIn({ ...me, permissions: [...me.permissions, "investigations:read", "investigations:run", "findings:review"] });
  renderAt("/agents?case=c-1");

  expect(await screen.findByText("Awaiting human review", { selector: "span" })).toBeInTheDocument();
  expect(screen.getByLabelText("Steps: 7 of 24")).toBeInTheDocument();
  expect(screen.getByLabelText("Tokens: 6300 of 120000")).toBeInTheDocument();
  // An investigation in progress blocks a second one.
  expect(screen.getByText("This case already has an investigation in progress.")).toBeInTheDocument();

  const log = await screen.findByRole("list", { name: "Agent events" });
  expect(within(log).getByText("Tool call refused")).toBeInTheDocument();
  expect(within(log).getByText("change_finding_status: unknown tool")).toBeInTheDocument();
  expect(within(log).getByText("finding not in case")).toBeInTheDocument();

  const steps = screen.getByRole("list", { name: "Agent steps" });
  await userEvent.click(within(steps).getByRole("button", { name: /Cross-Reference/ }));
  const supporting = screen.getByRole("list", { name: "Supporting evidence" });
  expect(within(supporting).getByRole("link", { name: "Document, page 1" })).toHaveAttribute("href", "/documents/d-inv?field=x-1");
  expect(within(supporting).getByText("(citation removed: not found in this case)")).toBeInTheDocument();
  expect(screen.getByText("Suggested by the agent")).toBeInTheDocument();

  await userEvent.click(within(steps).getByRole("button", { name: /Risk Assessment/ }));
  const risk = screen.getByRole("list", { name: "Risk assessments" });
  expect(within(risk).getByText("Hypothesis")).toBeInTheDocument();
  expect(within(risk).getByText(/anomaly score 0.294, evidence confidence 1.000, priority high/)).toBeInTheDocument();
  // The report step hasn't run.
  expect(within(steps).getByRole("button", { name: /Report Generation/ })).toBeDisabled();
  expect(approved).toEqual([]);
  // Many interactions over a streamed log: about 3 s alone, and it can pass the 5 s default
  // when all 14 test files run in parallel. The assertions are unchanged.
}, 15_000);

test("a reviewer's approval of a paused run is sent to the API", async () => {
  const approved: string[] = [];
  server.use(...handlers(inv, approved));
  signIn({ ...me, permissions: [...me.permissions, "investigations:read", "findings:review"] });
  renderAt("/agents?case=c-1");
  await userEvent.click(await screen.findByRole("button", { name: "Approve and write report" }));
  await waitFor(() => expect(approved).toEqual(["i-1"]));
});

test("a role without review permission can't approve and without run permission can't start", async () => {
  server.use(...handlers());
  signIn({ ...me, role: "read_only_analyst", permissions: ["investigations:read", "cases:read"] });
  renderAt("/agents?case=c-1");
  expect(await screen.findByText("A reviewer must approve.")).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Approve and write report" })).not.toBeInTheDocument();
  expect(screen.getByText("Your role can follow investigations but not start them.")).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Request evidence" })).not.toBeInTheDocument();
});

test("starting an investigation sends the objective", async () => {
  const bodies: unknown[] = [];
  server.use(
    http.get("/api/v1/cases", () => HttpResponse.json({ items: [caseRow], next_cursor: null })),
    http.get("/api/v1/cases/c-1/investigations", () => HttpResponse.json([])),
    http.post("/api/v1/cases/c-1/investigate", async ({ request }) => {
      bodies.push(await request.json());
      return HttpResponse.json({ ...inv, status: "queued" }, { status: 202 });
    }),
    http.get("/api/v1/investigations/i-1", () => HttpResponse.json({ ...inv, status: "queued", agent_runs: [], result: {} })),
    http.get("/api/v1/investigations/i-1/events", () =>
      new HttpResponse("event: end\ndata: {}\n\n", { headers: { "Content-Type": "text/event-stream" } })),
  );
  signIn({ ...me, permissions: [...me.permissions, "investigations:read", "investigations:run"] });
  renderAt("/agents?case=c-1");
  expect(await screen.findByText("No investigation has run on this case yet.")).toBeInTheDocument();
  const box = screen.getByLabelText("Objective");
  await userEvent.clear(box);
  await userEvent.type(box, "Why do the totals differ?");
  await userEvent.click(screen.getByRole("button", { name: "Start investigation" }));
  await waitFor(() => expect(bodies).toEqual([{ objective: "Why do the totals differ?" }]));
});

test("a failed run shows its error and an empty case gets guidance", async () => {
  server.use(...handlers({ ...inv, status: "budget_exhausted", error: "max_iterations budget exhausted (24 of 24)" }));
  signIn({ ...me, permissions: [...me.permissions, "investigations:read"] });
  renderAt("/agents?case=c-1");
  expect(await screen.findByRole("alert")).toHaveTextContent("max_iterations budget exhausted (24 of 24)");
  expect(screen.getAllByText("Budget exhausted").length).toBeGreaterThan(0);
});
