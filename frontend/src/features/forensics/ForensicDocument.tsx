import { useQuery } from "@tanstack/react-query";
import { clsx } from "clsx";
import { ChevronLeft, ChevronRight, ExternalLink, Stamp, ZoomIn, ZoomOut } from "lucide-react";
import { lazy, Suspense, useMemo, useState } from "react";
import { Link } from "react-router-dom";

import { EmptyState, ErrorState } from "@/components/QueryState";
import { Button } from "@/components/ui/Button";
import { Badge, Card, CardTitle, Skeleton } from "@/components/ui/primitives";
import { SeverityBadge } from "@/features/findings/badges";
import {
  analysisLabel,
  anomalyLabel,
  formatPdfDate,
  METADATA_KEYS,
  RUN_STATUS,
} from "@/features/forensics/labels";
import { ImageCanvas } from "@/features/viewer/ImageCanvas";
import type { OverlayBox } from "@/features/viewer/overlay";
import { useWidth } from "@/hooks/useWidth";
import { api } from "@/services/api";
import type { ForensicAnomalyOut, ForensicRunOut, ForensicSummaryOut } from "@/types/api";

const PdfCanvas = lazy(() => import("@/features/viewer/PdfCanvas"));

const IMAGE_TYPES = new Set(["image/png", "image/jpeg"]);
const ZOOMS = [0.5, 0.75, 1, 1.25, 1.5, 2];
const TONE: Record<string, OverlayBox["tone"]> = { medium: "warning", low: "evidence", info: "muted" };

interface DetectedRegion {
  kind: string;
  page: number;
  region: number[];
}

function detectedRegions(run: ForensicRunOut): DetectedRegion[] {
  const stamps = run.structure["stamps_signatures"] as { regions?: DetectedRegion[] } | undefined;
  return stamps?.regions ?? [];
}

/** Field ids an anomaly relates to, from its metrics. */
function relatedFields(a: ForensicAnomalyOut): string[] {
  const ids = Array.isArray(a.metrics["fields"]) ? (a.metrics["fields"] as string[]) : [];
  const one = a.metrics["field_id"];
  return typeof one === "string" ? [...ids, one] : ids;
}

function scalarMetrics(a: ForensicAnomalyOut): [string, string][] {
  return Object.entries(a.metrics)
    .filter(([k, v]) => !["fields", "field_id"].includes(k) && v !== null && typeof v !== "object")
    .map(([k, v]) => [k.replace(/_/g, " "), String(v)]);
}

export function ForensicDocument({ summary }: { summary: ForensicSummaryOut }) {
  const id = summary.document_id;
  const run = useQuery({ queryKey: ["document-forensics", id], queryFn: () => api.documentForensics(id) });

  if (run.isPending) return <Skeleton className="h-[60vh]" />;
  if (run.isError) return <Card><ErrorState error={run.error} onRetry={() => void run.refetch()} /></Card>;
  if (!run.data) {
    return (
      <Card>
        <EmptyState title="Not analysed yet"
                    action={<Link to={`/documents/${id}`} className="text-sm text-evidence hover:underline">Open the document</Link>}>
          Forensic analysis runs as the last processing stage. Process the document to analyse it.
        </EmptyState>
      </Card>
    );
  }
  return <RunView summary={summary} run={run.data} />;
}

function RunView({ summary, run }: { summary: ForensicSummaryOut; run: ForensicRunOut }) {
  const id = summary.document_id;
  const mime = summary.mime_type;
  const isPdf = mime === "application/pdf";
  const isTiff = mime === "image/tiff";
  const positioned = isPdf || isTiff || IMAGE_TYPES.has(mime);
  const [page, setPage] = useState(1);
  const [pageCount, setPageCount] = useState(1);
  const [zoomIndex, setZoomIndex] = useState(2);
  const [selected, setSelected] = useState<string | null>(null);
  const [showDetected, setShowDetected] = useState(false);
  const { ref, width } = useWidth<HTMLDivElement>();
  const anomalies = useMemo(() => run.anomalies ?? [], [run.anomalies]);

  const preview = useQuery({
    queryKey: ["preview", id, isTiff ? page : 0],
    queryFn: () => api.documentPreview(id, isTiff ? page : undefined),
    enabled: positioned,
    staleTime: 45_000,
  });

  const boxes = useMemo<OverlayBox[]>(() => {
    const out: OverlayBox[] = [];
    if (showDetected) {
      detectedRegions(run).forEach((r, i) => {
        if (r.page === page) out.push({ id: `d-${i}`, bbox: r.region, label: `Detected ${r.kind}`, tone: "muted" });
      });
    }
    for (const a of anomalies) {
      if (a.region && a.page_number === page) {
        out.push({ id: a.id, bbox: a.region, label: `${anomalyLabel(a.type)} (${a.severity})`,
                   tone: TONE[a.severity] ?? "muted", active: selected === a.id });
      }
    }
    return out;
  }, [anomalies, page, run, selected, showDetected]);

  const select = (a: ForensicAnomalyOut) => {
    setSelected(a.id);
    if (a.page_number) setPage(a.page_number);
  };
  const zoom = ZOOMS[zoomIndex] ?? 1;
  const status = RUN_STATUS[run.status] ?? { label: run.status, tone: "neutral" as const };
  const metadata = METADATA_KEYS.filter(([k]) => typeof run.pdf_metadata[k] === "string" && run.pdf_metadata[k]);
  const errors = (run.structure["errors"] ?? {}) as Record<string, string>;
  const reason = run.structure["reason"];

  return (
    <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_360px]">
      <Card className="min-w-0 p-0">
        <div className="flex flex-wrap items-center gap-2 border-b border-line p-3">
          <Button variant="ghost" size="sm" aria-label="Previous page" disabled={page <= 1}
                  icon={<ChevronLeft className="h-4 w-4" />} onClick={() => setPage((p) => p - 1)} />
          <span className="text-xs tabular" aria-live="polite">Page {page} of {pageCount}</span>
          <Button variant="ghost" size="sm" aria-label="Next page" disabled={page >= pageCount}
                  icon={<ChevronRight className="h-4 w-4" />} onClick={() => setPage((p) => p + 1)} />
          <span className="mx-1 h-5 w-px bg-line" aria-hidden />
          <Button variant="ghost" size="sm" aria-label="Zoom out" disabled={zoomIndex === 0}
                  icon={<ZoomOut className="h-4 w-4" />} onClick={() => setZoomIndex((z) => z - 1)} />
          <span className="w-10 text-center text-xs tabular">{Math.round(zoom * 100)}%</span>
          <Button variant="ghost" size="sm" aria-label="Zoom in" disabled={zoomIndex === ZOOMS.length - 1}
                  icon={<ZoomIn className="h-4 w-4" />} onClick={() => setZoomIndex((z) => z + 1)} />
          {detectedRegions(run).length > 0 ? (
            <Button variant={showDetected ? "secondary" : "ghost"} size="sm" aria-pressed={showDetected}
                    icon={<Stamp className="h-4 w-4" />} onClick={() => setShowDetected((v) => !v)}>
              Detected stamps and signatures
            </Button>
          ) : null}
          <Link to={`/documents/${id}`} className="ml-auto inline-flex items-center gap-1 text-xs text-evidence hover:underline">
            Document viewer <ExternalLink className="h-3 w-3" aria-hidden />
          </Link>
        </div>
        <div ref={ref} className="max-h-[78vh] overflow-auto bg-bg/40 p-4">
          {!positioned ? (
            <p className="p-6 text-sm text-muted">
              {typeof reason === "string" ? `Not analysed: ${reason}.` : "This file type has no page image to inspect."}
            </p>
          ) : preview.isError ? (
            <ErrorState error={preview.error} onRetry={() => void preview.refetch()} />
          ) : !preview.data ? (
            <Skeleton className="h-[70vh]" />
          ) : isPdf ? (
            <Suspense fallback={<Skeleton className="h-[70vh]" />}>
              <PdfCanvas url={preview.data.url} page={page} zoom={zoom} width={width - 32}
                         boxes={boxes} onPageCount={setPageCount} onSelect={setSelected} />
            </Suspense>
          ) : (
            <ImageCanvas url={preview.data.url} alt={`${summary.filename}, page ${page}`}
                         zoom={zoom} width={width - 32} boxes={boxes} onSelect={setSelected} />
          )}
        </div>
      </Card>

      <div className="space-y-4 xl:max-h-[84vh] xl:overflow-auto">
        <Card>
          <CardTitle action={<Badge tone={status.tone}>{status.label}</Badge>}>Anomalies</CardTitle>
          {anomalies.length === 0 ? (
            <p className="text-sm text-muted">
              {run.status === "not_applicable"
                ? "No forensic analysis applies to this file type."
                : "The analyses that ran found no anomaly in this document."}
            </p>
          ) : (
            <ul className="space-y-2" aria-label="Anomalies">
              {anomalies.map((a) => (
                <li key={a.id}>
                  <button type="button" onClick={() => select(a)} aria-pressed={selected === a.id}
                          className={clsx("w-full rounded-lg border p-3 text-left text-sm",
                                          selected === a.id ? "border-evidence/60 bg-elevated" : "border-line hover:bg-elevated/60")}>
                    <span className="flex flex-wrap items-center gap-2">
                      <SeverityBadge severity={a.severity} />
                      <span className="font-medium">{anomalyLabel(a.type)}</span>
                      {a.page_number ? <span className="text-xs text-muted">Page {a.page_number}</span> : null}
                    </span>
                    <span className="mt-1.5 block text-muted">{a.explanation}</span>
                  </button>
                  {selected === a.id ? <AnomalyDetail documentId={id} anomaly={a} /> : null}
                </li>
              ))}
            </ul>
          )}
        </Card>

        <Card>
          <CardTitle>Analyses</CardTitle>
          <ul className="space-y-1 text-sm">
            {run.analysis_types.map((t) => <li key={t}>{analysisLabel(t)}</li>)}
            {Object.entries(errors).map(([t, err]) => (
              <li key={t} className="text-warning">{analysisLabel(t)} could not run ({err})</li>
            ))}
          </ul>
          {typeof run.structure["pages_analysed"] === "number" ? (
            <p className="mt-2 text-xs text-muted">{String(run.structure["pages_analysed"])} page(s) analysed.</p>
          ) : null}
        </Card>

        {metadata.length > 0 ? (
          <Card>
            <CardTitle>PDF metadata</CardTitle>
            <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-sm">
              {metadata.map(([k, label]) => (
                <div key={k} className="contents">
                  <dt className="text-muted">{label}</dt>
                  <dd className="break-all font-mono text-xs">{formatPdfDate(String(run.pdf_metadata[k]))}</dd>
                </div>
              ))}
            </dl>
          </Card>
        ) : null}

        <Card>
          <CardTitle>Limitations</CardTitle>
          <ul className="list-disc space-y-1 pl-4 text-sm text-muted" aria-label="Limitations">
            {run.limitations.map((l) => <li key={l}>{l}</li>)}
          </ul>
        </Card>
      </div>
    </div>
  );
}

function AnomalyDetail({ documentId, anomaly }: { documentId: string; anomaly: ForensicAnomalyOut }) {
  const metrics = scalarMetrics(anomaly);
  const fields = relatedFields(anomaly);
  return (
    <div className="mt-1 rounded-lg border border-line bg-bg/40 p-3 text-xs">
      {metrics.length > 0 ? (
        <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5">
          {metrics.map(([k, v]) => (
            <div key={k} className="contents">
              <dt className="capitalize text-muted">{k}</dt>
              <dd className="tabular font-mono">{v}</dd>
            </div>
          ))}
        </dl>
      ) : null}
      {fields.length > 0 ? (
        <p className="mt-2">
          Overlaps extracted field{fields.length === 1 ? "" : "s"}:{" "}
          {fields.map((f, i) => (
            <span key={f}>
              {i > 0 ? ", " : ""}
              <Link to={`/documents/${documentId}?field=${f}`} className="text-evidence hover:underline">field {i + 1}</Link>
            </span>
          ))}
        </p>
      ) : null}
      <p className="mt-2 text-muted">{anomaly.requires_review ? "Marked for human review." : "Informational; review is optional."}</p>
    </div>
  );
}
