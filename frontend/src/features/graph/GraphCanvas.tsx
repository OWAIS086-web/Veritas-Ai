import "@xyflow/react/dist/style.css";

import {
  Background, Controls, Handle, Position, ReactFlow, type Edge, type Node, type NodeProps,
} from "@xyflow/react";
import { clsx } from "clsx";
import { Boxes, Building2, FileText, MapPin, Package, Receipt, ShieldAlert } from "lucide-react";
import { useMemo } from "react";

import { categoryOf, EDGE_LABELS, layout, NODE_HEIGHT, NODE_WIDTH } from "@/features/graph/model";
import { colors } from "@/styles/tokens";
import type { GraphEdgeOut, GraphNodeOut } from "@/types/api";

const STYLE: Record<string, { icon: typeof FileText; ring: string }> = {
  document: { icon: FileText, ring: "border-evidence/60" },
  organization: { icon: Building2, ring: "border-primary/60" },
  shipment: { icon: Package, ring: "border-warning/60" },
  transaction: { icon: Receipt, ring: "border-line" },
  address: { icon: MapPin, ring: "border-line" },
  product: { icon: Boxes, ring: "border-warning/40" },
  finding: { icon: ShieldAlert, ring: "border-danger/70" },
};

const FALLBACK = { icon: Receipt, ring: "border-line" };

interface NodeData extends Record<string, unknown> {
  node: GraphNodeOut;
  dimmed: boolean;
  selected: boolean;
}

function GraphNodeView({ data }: NodeProps<Node<NodeData>>) {
  const { node, dimmed, selected } = data;
  const category = categoryOf(node);
  const s = STYLE[category] ?? FALLBACK;
  const Icon = s.icon;
  const duplicate = node.properties?.status === "possible_duplicate";
  return (
    <div
      style={{ width: NODE_WIDTH, height: NODE_HEIGHT }}
      className={clsx(
        "flex items-center gap-2 rounded-lg border bg-surface px-3 text-left shadow-sm transition-opacity",
        s.ring, selected && "ring-2 ring-evidence", dimmed && "opacity-30",
      )}
    >
      <Handle type="target" position={Position.Left} className="!h-1.5 !w-1.5 !border-0 !bg-muted" />
      <Icon className="h-4 w-4 shrink-0 text-muted" aria-hidden />
      <div className="min-w-0">
        <p className="truncate text-xs font-medium text-ink">{node.label}</p>
        <p className="truncate text-[10px] text-muted">
          {category}{duplicate ? " · possible duplicate" : ""}
          {node.kind === "finding" && node.properties?.severity ? ` · ${String(node.properties.severity)}` : ""}
        </p>
      </div>
      <Handle type="source" position={Position.Right} className="!h-1.5 !w-1.5 !border-0 !bg-muted" />
    </div>
  );
}

const nodeTypes = { veritas: GraphNodeView };

export default function GraphCanvas({ nodes, edges, selected, highlightContradictions, onSelectNode, onSelectEdge }: {
  nodes: GraphNodeOut[];
  edges: GraphEdgeOut[];
  selected: string | null;
  highlightContradictions: boolean;
  onSelectNode: (id: string) => void;
  onSelectEdge: (id: string) => void;
}) {
  const positions = useMemo(() => layout(nodes, edges), [nodes, edges]);
  const contradictionEnds = useMemo(() => {
    const ids = new Set<string>();
    for (const e of edges) if (e.type === "CONTRADICTS") { ids.add(e.source); ids.add(e.target); }
    return ids;
  }, [edges]);

  const flowNodes: Node<NodeData>[] = nodes.map((n) => ({
    id: n.id,
    type: "veritas",
    position: positions.get(n.id) ?? { x: 0, y: 0 },
    data: { node: n, selected: n.id === selected, dimmed: highlightContradictions && !contradictionEnds.has(n.id) },
    draggable: false,
  }));
  const flowEdges: Edge[] = edges.map((e) => {
    const contradiction = e.type === "CONTRADICTS";
    const dimmed = highlightContradictions && !contradiction;
    return {
      id: e.id,
      source: e.source,
      target: e.target,
      label: EDGE_LABELS[e.type] ?? e.type,
      animated: contradiction,
      selected: e.id === selected,
      style: {
        stroke: contradiction ? colors.danger : colors.muted,
        strokeWidth: contradiction ? 2 : 1,
        opacity: dimmed ? 0.15 : 1,
      },
      labelStyle: { fill: contradiction ? colors.danger : colors.muted, fontSize: 10 },
      labelBgStyle: { fill: colors.surface },
    };
  });

  return (
    <ReactFlow
      nodes={flowNodes}
      edges={flowEdges}
      nodeTypes={nodeTypes}
      onNodeClick={(_, n) => onSelectNode(n.id)}
      onEdgeClick={(_, e) => onSelectEdge(e.id)}
      fitView
      minZoom={0.2}
      proOptions={{ hideAttribution: true }}
      colorMode="dark"
    >
      <Background gap={24} size={1} />
      <Controls showInteractive={false} />
    </ReactFlow>
  );
}
