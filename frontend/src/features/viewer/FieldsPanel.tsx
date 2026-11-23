import { clsx } from "clsx";
import { MapPin } from "lucide-react";

import { EmptyState } from "@/components/QueryState";
import { Mono } from "@/components/ui/primitives";
import { fieldLabel, formatNormalized, methodLabel } from "@/features/documents/labels";
import { FieldStatus } from "@/features/documents/StatusBadge";
import type { ExtractionOut, FieldOut } from "@/types/api";

export function FieldsPanel({ extraction, selectedId, onSelect, pageMethods = {} }: {
  extraction: ExtractionOut | null | undefined;
  selectedId: string | null;
  onSelect: (field: FieldOut) => void;
  pageMethods?: Record<number, string>;
}) {
  if (!extraction) {
    return <EmptyState title="No extracted fields yet">Fields appear when the extract stage finishes.</EmptyState>;
  }
  const ordered = [...extraction.fields].sort(
    (a, b) => Number(a.status !== "extracted") - Number(b.status !== "extracted"),
  );
  return (
    <div className="space-y-3">
      <p className="text-[11px] text-muted">
        Extraction method <Mono className="text-ink">{extraction.method}</Mono> ·{" "}
        <Mono className="text-ink">{extraction.model_version}</Mono>
        {extraction.method === "rules" ? " · no model provider configured" : null}
      </p>
      <ul className="space-y-2" aria-label="Extracted fields">
        {ordered.map((f) => {
          const where = f.page_number ? `page ${f.page_number}` : f.location;
          const normalized = formatNormalized(f.normalized_value);
          return (
            <li key={f.id}>
              <button
                type="button"
                onClick={() => onSelect(f)}
                disabled={f.value === null}
                aria-pressed={selectedId === f.id}
                className={clsx(
                  "w-full rounded-lg border p-3 text-left transition-colors",
                  selectedId === f.id ? "border-evidence bg-evidence/10" : "border-line hover:border-evidence/40",
                  f.value === null && "cursor-default opacity-80",
                )}
              >
                <div className="flex items-start justify-between gap-2">
                  <p className="text-xs text-muted">{fieldLabel(f.name)}</p>
                  <FieldStatus status={f.status} reason={f.rejection_reason} />
                </div>
                <p className="mt-1 break-words font-mono text-sm tabular">
                  {f.value ?? <span className="text-muted">null</span>}
                </p>
                {normalized && normalized !== f.value ? (
                  <p className="mt-0.5 text-[11px] text-muted">normalized: <Mono>{normalized}</Mono></p>
                ) : null}
                <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-muted">
                  {where ? <span className="inline-flex items-center gap-1"><MapPin className="h-3 w-3" aria-hidden />{where}</span> : null}
                  <span>{methodLabel(f, pageMethods)}</span>
                  <span>confidence {f.confidence ?? "not measured"}</span>
                </div>
              </button>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
