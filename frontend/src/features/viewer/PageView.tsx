import { useQuery } from "@tanstack/react-query";
import { ChevronLeft, ChevronRight, ZoomIn, ZoomOut } from "lucide-react";
import { lazy, Suspense, useState } from "react";

import { ErrorState } from "@/components/QueryState";
import { Button } from "@/components/ui/Button";
import { Skeleton } from "@/components/ui/primitives";
import { ImageCanvas } from "@/features/viewer/ImageCanvas";
import type { OverlayBox } from "@/features/viewer/overlay";
import { ParsedView } from "@/features/viewer/ParsedView";
import { useWidth } from "@/hooks/useWidth";
import { api } from "@/services/api";

const PdfCanvas = lazy(() => import("@/features/viewer/PdfCanvas"));
const IMAGE_TYPES = new Set(["image/png", "image/jpeg"]);
const ZOOMS = [0.5, 0.75, 1, 1.25, 1.5];

/**
 * One document page with highlight boxes, controlled by the parent (`page`, `onPage`).
 * Formats without page geometry (DOCX, XLSX, CSV, EML) show the parsed view with the
 * evidence location highlighted.
 */
export function PageView({ documentId, mimeType, filename, page, onPage, boxes, activeLocation, knownPages }: {
  documentId: string;
  mimeType: string;
  filename: string;
  page: number;
  onPage: (page: number) => void;
  boxes: OverlayBox[];
  activeLocation?: string | null;
  /** The document's page count, when known (PDFs report their own). */
  knownPages?: number | null;
}) {
  const [pageCount, setPageCount] = useState<number | null>(null);
  const [zoomIndex, setZoomIndex] = useState(1);
  const { ref, width } = useWidth<HTMLDivElement>();
  const isPdf = mimeType === "application/pdf";
  const isTiff = mimeType === "image/tiff";
  const positioned = isPdf || isTiff || IMAGE_TYPES.has(mimeType);
  const preview = useQuery({
    queryKey: ["preview", documentId, isTiff ? page : 0],
    queryFn: () => api.documentPreview(documentId, isTiff ? page : undefined),
    enabled: positioned,
    staleTime: 45_000,
  });
  const pages = useQuery({ queryKey: ["pages", documentId], queryFn: () => api.documentPages(documentId), enabled: !positioned });
  const zoom = ZOOMS[zoomIndex] ?? 1;
  const total = positioned ? (pageCount ?? knownPages ?? null) : pages.data?.length ?? null;
  const parsedPage = pages.data?.find((p) => p.page_number === page) ?? pages.data?.[0];

  return (
    <div className="min-w-0">
      <div className="flex flex-wrap items-center gap-1 border-b border-line px-2 py-1.5">
        <Button variant="ghost" size="sm" aria-label={`Previous page of ${filename}`} disabled={page <= 1}
                icon={<ChevronLeft className="h-4 w-4" />} onClick={() => onPage(page - 1)} />
        <span className="text-xs tabular" aria-live="polite">Page {page}{total ? ` of ${total}` : ""}</span>
        <Button variant="ghost" size="sm" aria-label={`Next page of ${filename}`} disabled={total !== null && page >= total}
                icon={<ChevronRight className="h-4 w-4" />} onClick={() => onPage(page + 1)} />
        {positioned ? (
          <>
            <Button variant="ghost" size="sm" aria-label="Zoom out" disabled={zoomIndex === 0}
                    icon={<ZoomOut className="h-4 w-4" />} onClick={() => setZoomIndex((z) => z - 1)} />
            <Button variant="ghost" size="sm" aria-label="Zoom in" disabled={zoomIndex === ZOOMS.length - 1}
                    icon={<ZoomIn className="h-4 w-4" />} onClick={() => setZoomIndex((z) => z + 1)} />
          </>
        ) : null}
      </div>
      <div ref={ref} className="max-h-[72vh] overflow-auto bg-bg/40 p-3">
        {!positioned ? (
          pages.isError ? <ErrorState error={pages.error} onRetry={() => void pages.refetch()} />
            : parsedPage ? <ParsedView page={parsedPage} activeLocation={activeLocation ?? null} query="" />
            : <Skeleton className="h-96" />
        ) : preview.isError ? (
          <ErrorState error={preview.error} onRetry={() => void preview.refetch()} />
        ) : !preview.data ? (
          <Skeleton className="h-[60vh]" />
        ) : isPdf ? (
          <Suspense fallback={<Skeleton className="h-[60vh]" />}>
            <PdfCanvas onExpired={() => void preview.refetch()} url={preview.data.url} page={page} zoom={zoom} width={width - 24} boxes={boxes} onPageCount={setPageCount} />
          </Suspense>
        ) : (
          <ImageCanvas onExpired={() => void preview.refetch()} url={preview.data.url} alt={`${filename}, page ${page}`} zoom={zoom} width={width - 24} boxes={boxes} />
        )}
      </div>
    </div>
  );
}
