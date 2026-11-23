import { useQuery } from "@tanstack/react-query";
import {
  AlertTriangle, CheckCircle2, Cog, FileStack, FolderSearch, ListChecks, ScrollText, ShieldAlert, Users,
} from "lucide-react";

import { PageHeader } from "@/components/PageHeader";
import { ErrorState } from "@/components/QueryState";
import { Card, CardTitle, Skeleton } from "@/components/ui/primitives";
import { ActivityChart } from "@/features/overview/ActivityChart";
import { MetricCard } from "@/features/overview/MetricCard";
import { WorkerCheck } from "@/features/overview/WorkerCheck";
import { api } from "@/services/api";
import { usePermission } from "@/stores/auth";

const percent = (v: number) => `${(v * 100).toFixed(1)}%`;

export function OverviewPage() {
  const canPing = usePermission("system:ping");
  const stats = useQuery({ queryKey: ["overview"], queryFn: api.overview });

  return (
    <div>
      <PageHeader
        title="Overview"
        subtitle="Live figures for your organization, computed from its own records."
      />
      {stats.isPending ? (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-5" aria-busy>
          {Array.from({ length: 5 }, (_, i) => <Skeleton key={i} className="h-24" />)}
        </div>
      ) : stats.isError ? (
        <Card><ErrorState error={stats.error} onRetry={() => void stats.refetch()} /></Card>
      ) : (
        <div className="space-y-6">
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-5">
            <MetricCard label="Members" metric={stats.data.members} icon={Users} />
            <MetricCard label="Jobs processed" metric={stats.data.jobs_total} icon={Cog} />
            <MetricCard label="Jobs in progress" metric={stats.data.jobs_running} icon={ListChecks} />
            <MetricCard label="Job success rate" metric={stats.data.job_success_rate}
                        icon={CheckCircle2} format={percent} tone="primary" />
            <MetricCard label="Audited events (7 days)" metric={stats.data.audit_events_7d}
                        icon={ScrollText} />
          </div>

          <div className="grid gap-6 xl:grid-cols-[2fr_1fr]">
            <Card>
              <CardTitle>Investigation activity, 14 days</CardTitle>
              <ActivityChart data={stats.data.activity_14d} />
            </Card>
            {canPing ? <WorkerCheck /> : (
              <Card>
                <CardTitle>Processing pipeline</CardTitle>
                <p className="text-sm text-muted">Your role can view the pipeline status but not run checks.</p>
              </Card>
            )}
          </div>

          <section aria-labelledby="investigation-metrics">
            <h2 id="investigation-metrics" className="mb-3 text-xs font-semibold uppercase tracking-[0.14em] text-muted">
              Investigation metrics
            </h2>
            <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
              <MetricCard label="Documents processed" metric={stats.data.documents_processed} icon={FileStack} />
              <MetricCard label="Active investigations" metric={stats.data.active_investigations} icon={FolderSearch} />
              <MetricCard label="Findings requiring review" metric={stats.data.findings_requiring_review}
                          icon={AlertTriangle} tone="warning" />
              <MetricCard label="High-priority findings" metric={stats.data.high_priority_findings}
                          icon={ShieldAlert} tone="danger" />
            </div>
          </section>
        </div>
      )}
    </div>
  );
}
