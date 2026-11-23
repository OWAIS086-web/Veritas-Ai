import { useQuery } from "@tanstack/react-query";
import { ChevronLeft, ChevronRight, ScanText, Search, ZoomIn, ZoomOut } from "lucide-react";
import { lazy, Suspense, useEffect, useMemo, useState } from "react";

import { ErrorState } from "@/components/QueryState";
import { Button } from "@/components/ui/Button";
import { Card, CardTitle, Skeleton } from "@/components/ui/primitives";
import type { OverlayBox } from "@/features/viewer/overlay";
import { FieldsPanel } from "@/features/viewer/FieldsPanel";
import { ImageCanvas } from "@/features/viewer/ImageCanvas";
import { ParsedView } from "@/features/viewer/ParsedView";
import { fieldLabel } from "@/features/documents/labels";
import { useWidth } from "@/hooks/useWidth";
import { api } from "@/services/api";
import type { DocumentOut, FieldOut } from "@/types/api";

// PDF.js is loaded only when a PDF is opened.
const PdfCanvas = lazy(() => import("@/features/viewer/PdfCanvas"));

const IMAGE_TYPES = new Set(["image/png", "image/jpeg"]);
const ZOOMS = [0.5, 0.75, 1, 1.25, 1.5, 2];

interface LineJson {
  text: string;
  bbox: number[] | null;
}

export function DocumentViewer({ doc, initialFieldId }: { doc: DocumentOut; initialFieldId?: string | null }) {
  const [page, setPage] = useState(1);
  const [pageCount, setPageCount] = useState(doc.page_count ?? 1);
  const [zoomIndex, setZoomIndex] = useState(2);
  const [query, setQuery] = useState("");
  const [showLines, setShowLines] = useState(false);
  const [selected, setSelected] = useState<FieldOut | null>(null);
  const { ref, width } = useWidth<HTMLDivElement>();
  const isPdf = doc.mime_type === "application/pdf";
  const isTiff = doc.mime_type === "image/tiff";
  const positioned = isPdf || isTiff || IMAGE_TYPES.has(doc.mime_type);
  const completed = doc.status === "completed";

  const pages = useQuery({ queryKey: ["pages", doc.id], queryFn: () => api.documentPages(doc.id), enabled: completed });
  const extraction = useQuery({ queryKey: ["extraction", doc.id], queryFn: () => api.documentExtraction(doc.id), enabled: completed });
  // Signed links expire after 60 s; fetch a fresh one per page view.
  const preview = useQuery({
    queryKey: ["preview", doc.id, isTiff ? page : 0],
    queryFn: () => api.documentPreview(doc.id, isTiff ? page : undefined),
    enabled: positioned,
    staleTime: 45_000,
  });

  useEffect(() => {
    const f = extraction.data?.fields.find((x) => x.id === initialFieldId);
    if (f) select(f);
    // only when the requested field changes or fields arrive
  }, [initialFieldId, extraction.data]);

  function select(f: FieldOut) {
    setSelected(f);
    if (f.page_number) setPage(f.page_number);
  }

  const currentPage = pages.data?.find((p) => p.page_number === page) ?? pages.data?.[0];
  const boxes = useMemo<OverlayBox[]>(() => {
    const out: OverlayBox[] = [];
    const q = query.trim().toLowerCase();
    const lines = (currentPage?.lines ?? []) as unknown as LineJson[];
    lines.forEach((ln, i) => {
      if (!ln.bbox) return;
      if (q && ln.text.toLowerCase().includes(q)) {
        out.push({ id: `q-${i}`, bbox: ln.bbox, label: `Match: ${ln.text}`, tone: "warning" });
      } else if (showLines) {
        out.push({ id: `l-${i}`, bbox: ln.bbox, label: ln.text, tone: "muted" });
      }
    });
    for (const f of extraction.data?.fields ?? []) {
      if (f.bbox && f.page_number === page) {
        out.push({ id: f.id, bbox: f.bbox, label: `${fieldLabel(f.name)}: ${f.value ?? ""}`,
                   tone: "evidence", active: selected?.id === f.id });
      }
    }
    return out;
  }, [currentPage, extraction.data, page, query, selected, showLines]);

  const onSelectBox = (id: string) => {
    const f = extraction.data?.fields.find((x) => x.id === id);
    if (f) setSelected(f);
  };
  const zoom = ZOOMS[zoomIndex] ?? 1;
  const matches = boxes.filter((b) => b.tone === "warning").length;

  return (
    <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_320px]">
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
          <span className="mx-1 h-5 w-px bg-line" aria-hidden />
          <label className="relative">
            <span className="sr-only">Search this page</span>
            <Search className="pointer-events-none absolute left-2 top-2 h-4 w-4 text-muted" aria-hidden />
            <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search page text"
                   className="h-8 w-48 rounded-lg border border-line bg-bg/60 pl-8 pr-2 text-xs" />
          </label>
          {query ? <span className="text-xs text-muted">{matches} match{matches === 1 ? "" : "es"}</span> : null}
          {positioned ? (
            <Button variant={showLines ? "secondary" : "ghost"} size="sm" aria-pressed={showLines}
                    icon={<ScanText className="h-4 w-4" />} onClick={() => setShowLines((v) => !v)}>
              {currentPage?.method === "ocr" ? "OCR lines" : "Text lines"}
            </Button>
          ) : null}
        </div>
        <div ref={ref} className="max-h-[78vh] overflow-auto bg-bg/40 p-4">
          {!completed ? (
            <p className="p-6 text-sm text-muted">The document is {doc.status}. Content appears when processing completes.</p>
          ) : preview.isError ? (
            <ErrorState error={preview.error} onRetry={() => void preview.refetch()} />
          ) : !positioned ? (
            pages.data && currentPage ? (
              <ParsedView page={currentPage} activeLocation={selected?.location ?? null} query={query} />
            ) : <Skeleton className="h-96" />
          ) : !preview.data ? (
            <Skeleton className="h-[70vh]" />
          ) : isPdf ? (
            <Suspense fallback={<Skeleton className="h-[70vh]" />}>
              <PdfCanvas url={preview.data.url} page={page} zoom={zoom} width={width - 32}
                         boxes={boxes} onPageCount={setPageCount} onSelect={onSelectBox} />
            </Suspense>
          ) : (
            <ImageCanvas url={preview.data.url} alt={`${doc.original_filename}, page ${page}`}
                         zoom={zoom} width={width - 32} boxes={boxes} onSelect={onSelectBox} />
          )}
        </div>
      </Card>
      <Card className="xl:sticky xl:top-20 xl:max-h-[84vh] xl:overflow-auto">
        <CardTitle>Extracted fields</CardTitle>
        {extraction.isPending && completed ? <Skeleton className="h-64" /> : extraction.isError ? (
          <ErrorState error={extraction.error} onRetry={() => void extraction.refetch()} />
        ) : (
          <FieldsPanel extraction={extraction.data} selectedId={selected?.id ?? null} onSelect={select}
                       pageMethods={Object.fromEntries((pages.data ?? []).map((p) => [p.page_number, p.method]))} />
        )}
      </Card>
    </div>
  );
}
