import type { MeResponse, OverviewStats } from "@/types/api";

export const me: MeResponse = {
  user: { id: "u-1", email: "ana@example.com", full_name: "Ana Investigator", created_at: "2026-11-20T10:00:00Z" },
  organization: { id: "o-1", name: "Harbor Compliance", slug: "harbor-compliance-abc123", retention_days: null, created_at: "2026-11-20T10:00:00Z" },
  role: "org_admin",
  permissions: ["audit:read", "cases:delete", "cases:read", "cases:write", "documents:process", "documents:read", "documents:upload", "findings:comment", "findings:read", "findings:review", "findings:run", "jobs:read", "members:manage", "members:read", "org:read", "org:update", "stats:read", "system:ping"],
};

export function overview(overrides: Partial<OverviewStats> = {}): OverviewStats {
  return {
    members: { value: 3, available: true, note: null },
    jobs_total: { value: 7, available: true, note: null },
    jobs_running: { value: 1, available: true, note: null },
    jobs_failed: { value: 1, available: true, note: null },
    job_success_rate: { value: 0.8333, available: true, note: null },
    audit_events_7d: { value: 42, available: true, note: null },
    activity_14d: Array.from({ length: 14 }, (_, i) => ({
      day: `2026-11-${String(10 + i).padStart(2, "0")}`, count: i % 3,
    })),
    documents_processed: { value: 7, available: true, note: null },
    active_investigations: { value: 1, available: true, note: null },
    findings_requiring_review: { value: 1, available: true, note: null },
    high_priority_findings: { value: 1, available: true, note: null },
    ...overrides,
  };
}
