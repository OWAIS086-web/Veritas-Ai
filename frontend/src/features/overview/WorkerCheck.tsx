import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Activity, CheckCircle2, CircleDashed, XCircle } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { Button } from "@/components/ui/Button";
import { Card, CardTitle, Mono } from "@/components/ui/primitives";
import { api, ApiError } from "@/services/api";
import { streamEvents } from "@/services/sse";
import { toast } from "@/stores/toast";
import type { Job } from "@/types/api";

interface LiveEvent {
  seq: number;
  type: string;
  job_status: string;
  data: Record<string, unknown>;
  created_at: string;
}

/**
 * Queues a real `system.ping` job and streams its persisted events over SSE. This verifies
 * the API → Redis → Celery worker → database path end to end.
 */
export function WorkerCheck() {
  const qc = useQueryClient();
  const [job, setJob] = useState<Job | null>(null);
  const [events, setEvents] = useState<LiveEvent[]>([]);
  const [streamError, setStreamError] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => () => abortRef.current?.abort(), []);

  const start = useMutation({
    mutationFn: api.startPingJob,
    onSuccess: (created) => {
      setJob(created);
      setEvents([]);
      setStreamError(null);
      abortRef.current?.abort();
      const controller = new AbortController();
      abortRef.current = controller;
      streamEvents(`/jobs/${created.id}/events`, {
        signal: controller.signal,
        onMessage: (msg) => {
          if (msg.event === "end") return;
          const ev = msg.data as LiveEvent;
          setEvents((prev) => (prev.some((p) => p.seq === ev.seq) ? prev : [...prev, ev]));
          if (ev.job_status === "succeeded" || ev.job_status === "failed") {
            void api.job(created.id).then(setJob);
            void qc.invalidateQueries({ queryKey: ["overview"] });
          }
        },
      }).catch((err: unknown) => setStreamError(err instanceof Error ? err.message : "stream failed"));
    },
    onError: (err) =>
      toast.error("Could not queue the worker check", err instanceof ApiError ? err.detail : undefined),
  });

  const status = job?.status;
  const StatusIcon = status === "succeeded" ? CheckCircle2 : status === "failed" ? XCircle : CircleDashed;
  const statusTone = status === "succeeded" ? "text-primary" : status === "failed" ? "text-danger" : "text-evidence";

  return (
    <Card>
      <CardTitle
        action={
          <Button size="sm" variant="secondary" icon={<Activity className="h-3.5 w-3.5" />}
                  loading={start.isPending} onClick={() => start.mutate()}>
            Run worker check
          </Button>
        }
      >
        Processing pipeline
      </CardTitle>
      {job ? (
        <div className="space-y-3">
          <div className="flex items-center gap-2 text-sm" role="status" aria-live="polite"
               aria-label={`Worker check ${status}`}>
            <StatusIcon className={`h-4 w-4 ${statusTone} ${status === "running" || status === "queued" ? "animate-pulse" : ""}`} aria-hidden />
            <span className="capitalize">{status}</span>
            <Mono className="text-muted">job {job.id.slice(0, 8)}</Mono>
          </div>
          <ol className="space-y-1.5" aria-label="Job events">
            {events.map((ev) => (
              <li key={ev.seq} className="flex items-baseline gap-3 text-xs">
                <Mono className="w-6 text-muted">#{ev.seq}</Mono>
                <span className="w-28 text-ink">{ev.type.replace("_", " ")}</span>
                <span className="text-muted">{new Date(ev.created_at).toLocaleTimeString()}</span>
              </li>
            ))}
          </ol>
          {job.result ? (
            <p className="text-xs text-muted">
              Worker <Mono className="text-ink">{String(job.result.worker)}</Mono> reached the database in{" "}
              <Mono className="text-ink">{String(job.result.db_roundtrip_ms)} ms</Mono>.
            </p>
          ) : null}
          {job.error ? <p className="text-xs text-danger">{job.error}</p> : null}
          {streamError ? <p className="text-xs text-warning">Live updates interrupted: {streamError}</p> : null}
        </div>
      ) : (
        <p className="text-sm text-muted">
          Queue a real background job through Redis and a Celery worker, and follow its persisted
          events live. Document processing in phase 2 uses the same job pipeline.
        </p>
      )}
    </Card>
  );
}
