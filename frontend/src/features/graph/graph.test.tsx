// Req: evidence-knowledge-graph 4.1, 4.3 (UI states, against API-shaped responses)
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";

import { layout, neighbourhood } from "@/features/graph/model";
import { me } from "@/test/fixtures";
import { renderAt, signIn } from "@/test/render";
import { server } from "@/test/server";
import type { CaseOut, EdgeEvidenceOut, GraphOut } from "@/types/api";

const caseRow: CaseOut = {
  id: "c-1", title: "Shipment SHIP-2049", objective: "", investigation_type: "international_shipment",
  priority: "high", status: "open", created_by: "u-1", created_by_email: "ana@example.com",
  created_at: "2026-11-23T10:00:00Z", updated_at: "2026-11-23T10:00:00Z", document_count: 2,
  documents_completed: 2, documents_failed: 0, finding_count: 1, compared_at: "2026-11-23T10:05:00Z",
};

const graph: GraphOut = {
  source: "postgres", total_nodes: 4, total_edges: 3,
  nodes: [
    { id: "d-inv", kind: "document", type: "commercial_invoice", label: "02_commercial_invoice.pdf", properties: {} },
    { id: "d-cd", kind: "document", type: "customs_declaration", label: "03_customs_declaration.pdf", properties: {} },
    { id: "e-sup", kind: "entity", type: "organization", label: "Global Trading Ltd",
      properties: { status: "resolved", mention_count: 2, confidence: "1.000" } },
    { id: "f-1", kind: "finding", type: "financial_discrepancy", label: "Declared totals differ by USD 20,000.00",
      properties: { severity: "high" } },
  ],
  edges: [
    { id: "r-issued", type: "ISSUED_BY", source: "d-inv", target: "e-sup", evidence_ids: ["x-sup"], finding_id: null, properties: { role: "supplier" } },
    { id: "r-contra", type: "CONTRADICTS", source: "d-inv", target: "d-cd", evidence_ids: ["ev-1", "ev-2"], finding_id: "f-1", properties: {} },
    { id: "r-sup", type: "SUPPORTS", source: "d-cd", target: "f-1", evidence_ids: ["ev-2"], finding_id: null, properties: {} },
  ],
};

const evidence: EdgeEvidenceOut[] = [
  { id: "ev-1", kind: "evidence_item", document_id: "d-inv", document_filename: "02_commercial_invoice.pdf",
    doc_type: "commercial_invoice", extracted_field_id: "x-1", field_name: "total_amount", value: "USD 48,000.00",
    page_number: 1, bbox: [1, 2, 3, 4], location: null, confidence: "1.000" },
  { id: "ev-2", kind: "evidence_item", document_id: "d-cd", document_filename: "03_customs_declaration.pdf",
    doc_type: "customs_declaration", extracted_field_id: "x-2", field_name: "total_amount", value: "USD 68,000.00",
    page_number: 2, bbox: [1, 2, 3, 4], location: null, confidence: "1.000" },
];

function handlers(seen: string[] = []) {
  return [
    http.get("/api/v1/cases", () => HttpResponse.json({ items: [caseRow], next_cursor: null })),
    http.get("/api/v1/cases/c-1/graph", ({ request }) => {
      seen.push(new URL(request.url).searchParams.get("types") ?? "");
      return HttpResponse.json(graph);
    }),
    http.get("/api/v1/relationships/r-contra/evidence", () => HttpResponse.json(evidence)),
  ];
}

test("layout is deterministic and the neighbourhood is one edge away", () => {
  const a = layout(graph.nodes, graph.edges);
  const b = layout([...graph.nodes].reverse(), [...graph.edges].reverse());
  expect([...a.entries()].sort()).toEqual([...b.entries()].sort());
  expect([...neighbourhood("d-inv", graph.edges)].sort()).toEqual(["d-cd", "d-inv", "e-sup"]);
});

test("the list view shows each relationship and the evidence behind it", async () => {
  server.use(...handlers());
  signIn({ ...me, permissions: [...me.permissions, "graph:read", "graph:rebuild"] });
  renderAt("/graph?case=c-1");
  expect(await screen.findByText("Postgres (graph sync pending or unavailable)")).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "list" }));
  const table = screen.getByRole("table", { name: "Relationships" });
  expect(within(table).getAllByRole("row")).toHaveLength(4);
  await userEvent.click(within(table).getByRole("button", {
    name: "Show evidence: 02_commercial_invoice.pdf contradicts 03_customs_declaration.pdf" }));
  const items = await screen.findByRole("list", { name: "Relationship evidence" });
  expect(within(items).getByText("USD 68,000.00")).toBeInTheDocument();
  expect(within(items).getByRole("link", { name: "Open 03_customs_declaration.pdf at page 2" }))
    .toHaveAttribute("href", "/documents/d-cd?field=x-2");
  expect(screen.getByRole("link", { name: "Open the finding" })).toHaveAttribute("href", "/findings/f-1");

  // Highlighting contradictions narrows the list to them.
  await userEvent.click(screen.getByLabelText(/Highlight contradictions \(1\)/));
  expect(within(table).getAllByRole("row")).toHaveLength(2);
});

test("type filters are sent to the API and a read-only role can't rebuild", async () => {
  const seen: string[] = [];
  server.use(...handlers(seen));
  signIn({ ...me, role: "read_only_analyst", permissions: ["cases:read", "graph:read"] });
  renderAt("/graph?case=c-1");
  await screen.findByText("Postgres (graph sync pending or unavailable)");
  expect(screen.queryByRole("button", { name: "Rebuild" })).not.toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Organizations" }));
  await waitFor(() => expect(seen).toContain("organization"));
});

test("rebuild calls the API and reports the counts", async () => {
  let rebuilt = false;
  server.use(...handlers(), http.post("/api/v1/cases/c-1/graph/rebuild", () => {
    rebuilt = true;
    return HttpResponse.json({ entities: 3, relationships: 31 }, { status: 202 });
  }));
  signIn({ ...me, permissions: [...me.permissions, "graph:read", "graph:rebuild"] });
  renderAt("/graph?case=c-1");
  await userEvent.click(await screen.findByRole("button", { name: "Rebuild" }));
  await waitFor(() => expect(rebuilt).toBe(true));
  expect(await screen.findByText("Graph rebuilt")).toBeInTheDocument();
});

test("a case without a graph explains why and links to the investigation", async () => {
  server.use(
    http.get("/api/v1/cases", () => HttpResponse.json({ items: [caseRow], next_cursor: null })),
    http.get("/api/v1/cases/c-1/graph", () => HttpResponse.json({ ...graph, nodes: [], edges: [], total_nodes: 0, total_edges: 0 })),
  );
  signIn({ ...me, permissions: [...me.permissions, "graph:read"] });
  renderAt("/graph?case=c-1");
  expect(await screen.findByText("This case has no graph yet")).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Open the investigation" })).toHaveAttribute("href", "/investigations/c-1");
});

test("the canvas renders the nodes", async () => {
  server.use(...handlers());
  signIn({ ...me, permissions: [...me.permissions, "graph:read"] });
  renderAt("/graph?case=c-1");
  const canvas = await screen.findByLabelText("Graph canvas");
  expect(await within(canvas).findByText("Global Trading Ltd")).toBeInTheDocument();
  expect(within(canvas).getByText("Declared totals differ by USD 20,000.00")).toBeInTheDocument();
});
