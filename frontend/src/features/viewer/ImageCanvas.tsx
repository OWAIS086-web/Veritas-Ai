import { useState } from "react";

import { fitScale, type OverlayBox } from "@/features/viewer/overlay";
import { Overlays } from "@/features/viewer/Overlays";

/** An image page (PNG/JPG, or a TIFF frame rendered to PNG) with pixel-space boxes. */
export function ImageCanvas({ url, alt, zoom, width, boxes, onSelect }: {
  url: string;
  alt: string;
  zoom: number;
  width: number;
  boxes: OverlayBox[];
  onSelect?: (id: string) => void;
}) {
  const [natural, setNatural] = useState<{ w: number; h: number } | null>(null);
  const scale = natural ? fitScale(width, natural.w, zoom) : 1;
  return (
    <div className="relative mx-auto shadow-2xl"
         style={natural ? { width: natural.w * scale, height: natural.h * scale } : undefined}>
      <img
        src={url}
        alt={alt}
        className="block h-full w-full select-none"
        onLoad={(e) => setNatural({ w: e.currentTarget.naturalWidth, h: e.currentTarget.naturalHeight })}
      />
      {natural ? <Overlays boxes={boxes} scale={scale} onSelect={onSelect} /> : null}
    </div>
  );
}
