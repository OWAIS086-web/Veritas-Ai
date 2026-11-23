import { useQuery } from "@tanstack/react-query";
import { ChevronLeft, ChevronRight, ZoomIn, ZoomOut } from "lucide-react";
import { lazy, Suspense, useCallback, useMemo, useState } from "react";

import { ErrorState } from "@/components/QueryState";
import { Button } from "@/components/ui/Button";
import { Skeleton } from "@/components/ui/primitives";
import { findingTypeLabel } from "@/features/forensics/comparison/labels";
import { ImageCanvas } from "@/features/viewer/ImageCanvas";
import type { OverlayBox } from "@/features/viewer/overlay";
import { useWidth } from "@/hooks/useWidth";
import { api } from "@/services/api";
import type { ComparisonFindingOut } from "@/types/api";

const PdfCanvas = lazy(() => import("@/features/viewer/PdfCanvas"));
const ZOOMS = [0.5, 0.75, 1, 1.25, 1.5, 2];
const TONE: Record<string, OverlayBox["tone"]> = { medium: "warning", low: "evidence", info: "muted" };

export interface PaneDoc {
  id: string;
  filename: string;
  mimeType: string;
  pageCount: number | null;
}

function boxesFor(findings: ComparisonFindingOut[], side: "original" | "test", page: number,
                  selected: string | null): OverlayBox[] {
  const out: OverlayBox[] = [];
  for (const f of findings) {
    const onPage = side === "test" ? f.test_page : f.original_page;
    const region = side === "test" ? f.region : f.original_region;
    if (onPage !== page || !region || f.type.startsWith("page_")) continue;
    const text = side === "test" ? f.test_text : f.original_text;
    out.push({
      id: f.id,
      bbox: region,
      label: `#${f.number} ${findingTypeLabel(f.type)} (${f.severity})${text ? `: ${text}` : ""}`,
      tone: f.review_status === "dismissed" ? "muted" : (TONE[f.severity] ?? "muted"),
      active: selected === f.id,
    });
  }
  return out;
}

function Pane({ doc, role, page, zoom, boxes, onSelect, onPageCount }: {
  doc: PaneDoc;
  role: "Original" | "Test";
  page: number;
  zoom: number;
  boxes: OverlayBox[];
  onSelect: (id: string) => void;
  onPageCount: (n: number) => void;
}) {
  const { ref, width } = useWidth<HTMLDivElement>();
  const isPdf = doc.mimeType === "application/pdf";
  const isTiff = doc.mimeType === "image/tiff";
  const beyond = doc.pageCount !== null && page > doc.pageCount;
  const preview = useQuery({
    queryKey: ["preview", doc.id, isTiff ? page : 0],
    queryFn: () => api.documentPreview(doc.id, isTiff ? page : undefined),
    enabled: !beyond,
    staleTime: 45_000,
  });

  return (
    <section aria-label={`${role} document`} className="min-w-0 rounded-md border border-line">
      <header className="flex items-center justify-between gap-2 border-b border-line px-3 py-1.5">
        <span className="text-xs font-semibold uppercase tracking-wider text-muted">{role}</span>
        <span className="truncate text-xs" title={doc.filename}>{doc.filename}</span>
      </header>
      <div ref={ref} className="max-h-[72vh] overflow-auto bg-bg/40 p-3">
        {beyond ? (
          <p className="p-6 text-sm text-muted">This document has no page {page}.</p>
        ) : preview.isError ? (
          <ErrorState error={preview.error} onRetry={() => void preview.refetch()} />
        ) : !preview.data ? (
          <Skeleton className="h-[60vh]" />
        ) : isPdf ? (
          <Suspense fallback={<Skeleton className="h-[60vh]" />}>
            <PdfCanvas url={preview.data.url} page={page} zoom={zoom} width={width - 24} boxes={boxes}
                       onPageCount={onPageCount} onSelect={onSelect} onExpired={() => void preview.refetch()} />
          </Suspense>
        ) : (
          <ImageCanvas url={preview.data.url} alt={`${role}: ${doc.filename}, page ${page}`} zoom={zoom}
                       width={width - 24} boxes={boxes} onSelect={onSelect} onExpired={() => void preview.refetch()} />
        )}
      </div>
    </section>
  );
}

/**
 * The original and the test document side by side, on the same page number and zoom. Each
 * difference is boxed on the test page and, where it maps there, on the original page too.
 */
export function SyncedViewer({ original, test, findings, page, onPage, selected, onSelect }: {
  original: PaneDoc;
  test: PaneDoc;
  findings: ComparisonFindingOut[];
  page: number;
  onPage: (page: number) => void;
  selected: string | null;
  onSelect: (id: string) => void;
}) {
  const [zoomIndex, setZoomIndex] = useState(1);
  const [counts, setCounts] = useState<{ original: number | null; test: number | null }>({
    original: original.pageCount, test: test.pageCount,
  });
  const setOriginalCount = useCallback((n: number) => setCounts((c) => ({ ...c, original: n })), []);
  const setTestCount = useCallback((n: number) => setCounts((c) => ({ ...c, test: n })), []);
  const total = Math.max(counts.original ?? 1, counts.test ?? 1);
  const zoom = ZOOMS[zoomIndex] ?? 1;
  const testBoxes = useMemo(() => boxesFor(findings, "test", page, selected), [findings, page, selected]);
  const originalBoxes = useMemo(() => boxesFor(findings, "original", page, selected), [findings, page, selected]);

  return (
    <div>
      <div className="mb-2 flex flex-wrap items-center gap-1" role="toolbar" aria-label="Both documents">
        <Button variant="ghost" size="sm" aria-label="Previous page of both documents" disabled={page <= 1}
                icon={<ChevronLeft className="h-4 w-4" />} onClick={() => onPage(page - 1)} />
        <span className="text-xs tabular" aria-live="polite">Page {page} of {total}</span>
        <Button variant="ghost" size="sm" aria-label="Next page of both documents" disabled={page >= total}
                icon={<ChevronRight className="h-4 w-4" />} onClick={() => onPage(page + 1)} />
        <span className="mx-1 h-5 w-px bg-line" aria-hidden />
        <Button variant="ghost" size="sm" aria-label="Zoom out both documents" disabled={zoomIndex === 0}
                icon={<ZoomOut className="h-4 w-4" />} onClick={() => setZoomIndex((z) => z - 1)} />
        <span className="w-10 text-center text-xs tabular">{Math.round(zoom * 100)}%</span>
        <Button variant="ghost" size="sm" aria-label="Zoom in both documents" disabled={zoomIndex === ZOOMS.length - 1}
                icon={<ZoomIn className="h-4 w-4" />} onClick={() => setZoomIndex((z) => z + 1)} />
        <span className="ml-auto text-[11px] text-muted">
          Boxes: amber medium, cyan low, grey info or dismissed. Hover a box for its label.
        </span>
      </div>
      <div className="grid gap-3 lg:grid-cols-2">
        <Pane doc={{ ...original, pageCount: counts.original }} role="Original" page={page} zoom={zoom}
              boxes={originalBoxes} onSelect={onSelect} onPageCount={setOriginalCount} />
        <Pane doc={{ ...test, pageCount: counts.test }} role="Test" page={page} zoom={zoom}
              boxes={testBoxes} onSelect={onSelect} onPageCount={setTestCount} />
      </div>
    </div>
  );
}
