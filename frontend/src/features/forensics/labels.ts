export const ANOMALY_LABELS: Record<string, string> = {
  incremental_update: "Incremental update",
  metadata_inconsistency: "Metadata inconsistency",
  font_inconsistency: "Font inconsistency",
  localized_compression_anomaly: "Localized compression anomaly",
  version_difference: "Difference from the previous version",
  stamp_appearance_variation: "Stamp appearance variation",
};

export const ANALYSIS_LABELS: Record<string, string> = {
  pdf_structure: "PDF structure",
  visual_compression: "Compression analysis",
  version_comparison: "Version comparison",
  stamps_signatures: "Stamps and signatures",
};

export const RUN_STATUS: Record<string, { label: string; tone: "primary" | "warning" | "neutral" }> = {
  succeeded: { label: "Analysed", tone: "primary" },
  partial: { label: "Partly analysed", tone: "warning" },
  not_applicable: { label: "Not applicable", tone: "neutral" },
};

export const anomalyLabel = (t: string) => ANOMALY_LABELS[t] ?? t.replace(/_/g, " ");
export const analysisLabel = (t: string) => ANALYSIS_LABELS[t] ?? t.replace(/_/g, " ");

/** Metadata keys worth showing, in display order, with their labels. */
export const METADATA_KEYS: [string, string][] = [
  ["producer", "Producer"],
  ["creator", "Creator"],
  ["creationDate", "Created"],
  ["modDate", "Modified"],
  ["author", "Author"],
  ["title", "Title"],
  ["format", "Format"],
];

/** "D:20260112093000+00'00'" → "2026-01-12 09:30". Other values are returned unchanged. */
export function formatPdfDate(value: string): string {
  const m = /^D:(\d{4})(\d{2})?(\d{2})?(\d{2})?(\d{2})?/.exec(value);
  if (!m) return value;
  const [, y, mo = "01", d = "01", h, mi] = m;
  return h ? `${y}-${mo}-${d} ${h}:${mi ?? "00"}` : `${y}-${mo}-${d}`;
}
