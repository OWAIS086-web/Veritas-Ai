import dagre from "@dagrejs/dagre";

import type { GraphEdgeOut, GraphNodeOut } from "@/types/api";

export const NODE_WIDTH = 210;
export const NODE_HEIGHT = 56;

/** Node categories shown in the type filter (node kind for documents and findings, entity
 * type for entities). The API accepts the same values in `types`. */
export const CATEGORIES = [
  { value: "document", label: "Documents" },
  { value: "organization", label: "Organizations" },
  { value: "shipment", label: "Shipments" },
  { value: "transaction", label: "Transactions" },
  { value: "address", label: "Addresses" },
  { value: "product", label: "Products" },
  { value: "finding", label: "Findings" },
] as const;

export const EDGE_LABELS: Record<string, string> = {
  ISSUED_BY: "issued by",
  ISSUED_TO: "issued to",
  REFERENCES: "references",
  BELONGS_TO: "belongs to",
  PAID_BY: "paid by",
  SHIPPED_UNDER: "shipped under",
  SUPPORTS: "evidence for",
  CONTRADICTS: "contradicts",
  DERIVED_FROM: "derived from",
  ASSOCIATED_WITH: "associated with",
};

export function categoryOf(node: GraphNodeOut): string {
  return node.kind === "entity" ? node.type : node.kind;
}

export interface Positioned {
  id: string;
  x: number;
  y: number;
}

/** Deterministic left-to-right layout (dagre): the same graph always gets the same positions. */
export function layout(nodes: GraphNodeOut[], edges: GraphEdgeOut[]): Map<string, Positioned> {
  const g = new dagre.graphlib.Graph();
  g.setGraph({ rankdir: "LR", nodesep: 28, ranksep: 120, marginx: 20, marginy: 20 });
  g.setDefaultEdgeLabel(() => ({}));
  for (const n of [...nodes].sort((a, b) => a.id.localeCompare(b.id))) {
    g.setNode(n.id, { width: NODE_WIDTH, height: NODE_HEIGHT });
  }
  for (const e of [...edges].sort((a, b) => a.id.localeCompare(b.id))) {
    if (g.hasNode(e.source) && g.hasNode(e.target)) g.setEdge(e.source, e.target);
  }
  dagre.layout(g);
  const out = new Map<string, Positioned>();
  for (const id of g.nodes()) {
    const p = g.node(id);
    out.set(id, { id, x: p.x - NODE_WIDTH / 2, y: p.y - NODE_HEIGHT / 2 });
  }
  return out;
}

/** The node and everything one edge away from it. */
export function neighbourhood(focus: string, edges: GraphEdgeOut[]): Set<string> {
  const ids = new Set([focus]);
  for (const e of edges) {
    if (e.source === focus) ids.add(e.target);
    if (e.target === focus) ids.add(e.source);
  }
  return ids;
}
