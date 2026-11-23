import { clsx } from "clsx";

import { type OverlayBox, toCssRect } from "@/features/viewer/overlay";

const toneClass = {
  evidence: "border-evidence bg-evidence/10",
  warning: "border-warning bg-warning/10",
  muted: "border-muted/40 bg-transparent",
} as const;

export function Overlays({ boxes, scale, onSelect }: {
  boxes: OverlayBox[];
  scale: number;
  onSelect?: (id: string) => void;
}) {
  return (
    <div className="pointer-events-none absolute inset-0" aria-hidden={!onSelect}>
      {boxes.map((box) => {
        const rect = toCssRect(box.bbox, scale);
        if (!rect) return null;
        return (
          <button
            key={box.id}
            type="button"
            title={box.label}
            aria-label={box.label}
            data-testid="overlay-box"
            onClick={() => onSelect?.(box.id)}
            tabIndex={onSelect && box.tone !== "muted" ? 0 : -1}
            className={clsx(
              "pointer-events-auto absolute rounded-sm border",
              toneClass[box.tone],
              box.active && "z-10 border-2 shadow-evidence",
            )}
            style={rect}
          />
        );
      })}
    </div>
  );
}
