import type { FindingStatus } from "@/types/api";

export const FINDING_TYPES: Record<string, string> = {
  financial_discrepancy: "Financial discrepancy",
  quantity_mismatch: "Quantity mismatch",
  conflicting_reference: "Conflicting reference",
  identity_mismatch: "Party name mismatch",
  duplicate_document: "Duplicate document",
  date_inconsistency: "Date inconsistency",
  missing_document: "Missing document",
  currency_mismatch: "Currency mismatch",
};

export const STATUS_LABELS: Record<FindingStatus, string> = {
  new: "New",
  under_review: "Under review",
  confirmed_observation: "Confirmed observation",
  needs_more_evidence: "Needs more evidence",
  dismissed: "Dismissed",
  resolved: "Resolved",
};

export const STATUSES = Object.keys(STATUS_LABELS) as FindingStatus[];
/** Statuses that need a written reason (evidence-explorer requirement 2.2). */
export const NOTE_REQUIRED: FindingStatus[] = ["dismissed", "confirmed_observation"];

export function findingTypeLabel(type: string): string {
  return FINDING_TYPES[type] ?? type.replace(/_/g, " ");
}

export function formatMoney(value: string | null | undefined, currency?: string | null): string {
  if (value == null) return "—";
  const [whole = "0", frac = "00"] = value.split(".");
  const grouped = whole.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  return `${currency ? `${currency} ` : ""}${grouped}.${frac.padEnd(2, "0").slice(0, 2)}`;
}

/** A 0..1 score as text; null stays explicit instead of becoming 0. */
export function formatScore(value: string | null | undefined): string {
  return value == null ? "not measured" : Number(value).toFixed(3);
}
