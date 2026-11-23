import { clsx } from "clsx";

import { Mono } from "@/components/ui/primitives";
import type { PageOut } from "@/types/api";

interface LineJson {
  text: string;
  location: string | null;
  tokens: { s: number; e: number; loc: string | null }[];
}

/** Parsed view for DOCX, XLSX, CSV and EML: lines with their locations (no page geometry). */
export function ParsedView({ page, activeLocation, query }: {
  page: PageOut;
  activeLocation: string | null;
  query: string;
}) {
  const q = query.trim().toLowerCase();
  const lines = page.lines as unknown as LineJson[];
  return (
    <ol className="space-y-0.5 rounded-xl border border-line bg-bg/60 p-3 font-mono text-xs" aria-label="Parsed content">
      {lines.map((line, i) => {
        const locations = new Set([line.location, ...line.tokens.map((t) => t.loc)]);
        const active = activeLocation !== null && locations.has(activeLocation);
        const hit = q !== "" && line.text.toLowerCase().includes(q);
        return (
          <li
            key={i}
            data-active={active || undefined}
            className={clsx(
              "flex gap-3 rounded px-2 py-1",
              active && "bg-evidence/15 ring-1 ring-evidence",
              hit && !active && "bg-warning/10",
            )}
          >
            <Mono className="w-40 shrink-0 truncate text-muted">{line.location ?? `line ${i + 1}`}</Mono>
            <span className="whitespace-pre-wrap break-words text-ink">{line.text}</span>
          </li>
        );
      })}
    </ol>
  );
}
