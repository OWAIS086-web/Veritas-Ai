export const AGENTS: { key: string; title: string }[] = [
  { key: "planner", title: "Planner" },
  { key: "document", title: "Document Intelligence" },
  { key: "forensics", title: "Forensics" },
  { key: "cross_reference", title: "Cross-Reference" },
  { key: "entity", title: "Entity Resolution" },
  { key: "graph", title: "Evidence Graph" },
  { key: "risk", title: "Risk Assessment" },
  { key: "report", title: "Report Generation" },
];

export const agentTitle = (key: string | null | undefined) =>
  AGENTS.find((a) => a.key === key)?.title ?? key ?? "Workflow";

export const STATUS: Record<string, { label: string; tone: "neutral" | "primary" | "evidence" | "warning" | "danger" }> = {
  queued: { label: "Queued", tone: "neutral" },
  running: { label: "Running", tone: "evidence" },
  awaiting_review: { label: "Awaiting human review", tone: "warning" },
  approved: { label: "Approved, writing report", tone: "evidence" },
  completed: { label: "Completed", tone: "primary" },
  failed: { label: "Failed", tone: "danger" },
  budget_exhausted: { label: "Budget exhausted", tone: "danger" },
};

export const ACTIVE = new Set(["queued", "running", "awaiting_review", "approved"]);

export const EVENT_LABELS: Record<string, string> = {
  queued: "Investigation queued",
  investigation_started: "Workflow started",
  report_started: "Report step started",
  agent_started: "Agent started",
  agent_completed: "Agent finished",
  agent_failed: "Agent failed",
  tool_called: "Tool called",
  tool_failed: "Tool returned nothing",
  tool_rejected: "Tool call refused",
  reference_rejected: "Citation removed",
  output_invalid: "Model output rejected",
  awaiting_review: "Paused for human review",
  approved: "Approved by a reviewer",
  evidence_requested: "Evidence requested",
  investigation_completed: "Investigation completed",
  investigation_failed: "Investigation failed",
  budget_exhausted: "Budget exhausted",
};

export const BUDGET_LABELS: [string, string, string][] = [
  ["iterations", "max_iterations", "Steps"],
  ["tool_calls", "max_tool_calls", "Tool calls"],
  ["tokens", "max_tokens", "Tokens"],
  ["elapsed_seconds", "timeout_seconds", "Seconds"],
];
