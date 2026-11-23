import { useEffect, useState } from "react";

import { streamEvents } from "@/services/sse";

export interface JobEventData {
  seq: number;
  type: string;
  data: Record<string, unknown>;
  job_status: string;
  progress: number;
  created_at: string;
}

/**
 * Follow a processing job's persisted events over SSE (resumes with Last-Event-ID).
 * `onEvent` runs for each event; the hook returns the latest status and progress.
 */
export function useJobStream(jobId: string | null, onEvent?: (e: JobEventData) => void) {
  const [state, setState] = useState<{ status: string | null; progress: number; last: JobEventData | null }>(
    { status: null, progress: 0, last: null },
  );

  useEffect(() => {
    if (!jobId) return undefined;
    const controller = new AbortController();
    setState({ status: "queued", progress: 0, last: null });
    streamEvents(`/jobs/${jobId}/events`, {
      signal: controller.signal,
      onMessage: (msg) => {
        if (msg.event === "end") return;
        const ev = msg.data as JobEventData;
        setState({ status: ev.job_status, progress: ev.progress, last: ev });
        onEvent?.(ev);
      },
    }).catch(() => setState((s) => ({ ...s, status: s.status ?? "unknown" })));
    return () => controller.abort();
    // onEvent is intentionally not a dependency: a new callback must not restart the stream.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [jobId]);

  return state;
}
