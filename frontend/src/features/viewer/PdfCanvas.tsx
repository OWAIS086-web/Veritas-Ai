import { GlobalWorkerOptions, getDocument, type PDFDocumentProxy } from "pdfjs-dist";
import workerUrl from "pdfjs-dist/build/pdf.worker.min.mjs?url";
import { useEffect, useRef, useState } from "react";

import { Skeleton } from "@/components/ui/primitives";
import { fitScale, type OverlayBox } from "@/features/viewer/overlay";
import { Overlays } from "@/features/viewer/Overlays";

GlobalWorkerOptions.workerSrc = workerUrl;

/** Marks the viewer's own file requests (see `get_file` in backend/app/api/v1/documents.py). */
const VIEWER_HEADER = "X-Veritas-Viewer";

interface PdfCanvasProps {
  url: string;
  page: number;
  zoom: number;
  boxes: OverlayBox[];
  width: number;
  onPageCount: (n: number) => void;
  onSelect?: (id: string) => void;
  /** Called once when the signed link was refused (expired); the parent fetches a new one. */
  onExpired?: () => void;
}

/** Renders one PDF page with PDF.js and draws the evidence boxes over it. */
export default function PdfCanvas({ url, page, zoom, boxes, width, onPageCount, onSelect, onExpired }: PdfCanvasProps) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const [pdf, setPdf] = useState<PDFDocumentProxy | null>(null);
  const [scale, setScale] = useState(1);
  const [size, setSize] = useState<{ w: number; h: number } | null>(null);
  const [error, setError] = useState<string | null>(null);
  // One fresh-link retry per mounted viewer (evidence-explorer design: retry an expired link once).
  const retried = useRef(false);

  useEffect(() => {
    let cancelled = false;
    let task: ReturnType<typeof getDocument> | null = null;
    const controller = new AbortController();
    setError(null);
    // Read the bytes ourselves: the marked request gets an anonymous binary response, which
    // download managers (e.g. IDM) don't capture, unlike a PDF fetched by URL.
    fetch(url, { headers: { [VIEWER_HEADER]: "1" }, signal: controller.signal, cache: "no-store" })
      .then(async (res) => {
        if (res.status === 403 && onExpired && !retried.current) {
          // Signed links last 60 s; a cached one may have expired. Ask for a new one.
          retried.current = true;
          onExpired();
          return;
        }
        if (!res.ok) throw new Error(`The file could not be loaded (HTTP ${res.status}).`);
        const data = new Uint8Array(await res.arrayBuffer());
        if (data.length === 0) {
          throw new Error("The file arrived empty. A download manager or browser extension may have intercepted it.");
        }
        if (cancelled) return;
        task = getDocument({ data, isEvalSupported: false });
        const doc = await task.promise;
        if (cancelled) return;
        setPdf(doc);
        onPageCount(doc.numPages);
      })
      .catch((err: unknown) => {
        if (!cancelled) setError(err instanceof Error ? err.message : "PDF failed to load");
      });
    return () => {
      cancelled = true;
      controller.abort();
      void task?.destroy();
    };
    // onPageCount is a stable setter from the parent
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [url]);

  useEffect(() => {
    if (!pdf || !canvas.current) return undefined;
    let cancelled = false;
    let renderTask: { cancel: () => void; promise: Promise<unknown> } | null = null;
    void pdf.getPage(page).then((p) => {
      if (cancelled || !canvas.current) return;
      const base = p.getViewport({ scale: 1 });
      const s = fitScale(width, base.width, zoom);
      const viewport = p.getViewport({ scale: s * window.devicePixelRatio });
      const el = canvas.current;
      el.width = viewport.width;
      el.height = viewport.height;
      el.style.width = `${base.width * s}px`;
      el.style.height = `${base.height * s}px`;
      setScale(s);
      setSize({ w: base.width * s, h: base.height * s });
      const ctx = el.getContext("2d");
      if (!ctx) return;
      renderTask = p.render({ canvasContext: ctx, viewport });
      renderTask.promise.catch(() => undefined);
    });
    return () => {
      cancelled = true;
      renderTask?.cancel();
    };
  }, [pdf, page, zoom, width]);

  if (error) return <p role="alert" className="p-6 text-sm text-danger">Could not display the PDF: {error}</p>;
  return (
    <div className="relative mx-auto bg-ink shadow-2xl" style={size ? { width: size.w, height: size.h } : undefined}>
      {!size ? <Skeleton className="h-[70vh] w-full" /> : null}
      <canvas ref={canvas} aria-label={`Page ${page}`} role="img" />
      {size ? <Overlays boxes={boxes} scale={scale} onSelect={onSelect} /> : null}
    </div>
  );
}
