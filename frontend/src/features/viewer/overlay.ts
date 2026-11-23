/**
 * Map a stored bounding box onto the rendered page.
 * Boxes are [x0, y0, x1, y1] with a top-left origin, in PDF points (PDF pages) or pixels
 * (image files). `scale` is rendered size / page size in the same unit.
 */
export interface OverlayBox {
  id: string;
  bbox: number[];
  label: string;
  tone: "evidence" | "warning" | "muted";
  active?: boolean;
}

export interface CssRect {
  left: number;
  top: number;
  width: number;
  height: number;
}

const PAD = 2; // px of breathing room so the highlight doesn't clip glyphs

export function toCssRect(bbox: number[], scale: number): CssRect | null {
  if (bbox.length !== 4 || bbox.some((v) => !Number.isFinite(v)) || scale <= 0) return null;
  const [x0, y0, x1, y1] = bbox as [number, number, number, number];
  if (x1 <= x0 || y1 <= y0) return null;
  return {
    left: x0 * scale - PAD,
    top: y0 * scale - PAD,
    width: (x1 - x0) * scale + PAD * 2,
    height: (y1 - y0) * scale + PAD * 2,
  };
}

/** Scale that fits a page of `pageWidth` units into `containerWidth` pixels, times zoom. */
export function fitScale(containerWidth: number, pageWidth: number, zoom: number): number {
  if (pageWidth <= 0 || containerWidth <= 0) return zoom;
  return (containerWidth / pageWidth) * zoom;
}
