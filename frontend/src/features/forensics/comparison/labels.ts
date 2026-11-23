import type { BadgeTone } from "@/components/ui/primitives";
import type { ComparisonExportKind, ComparisonOut, ComparisonReviewStatus } from "@/types/api";

export const FINDING_TYPE: Record<string, string> = {
  text_changed: "Text changed",
  text_added: "Text added",
  text_removed: "Text removed",
  visual_difference: "Visual difference",
  vlm_observed_difference: "Vision-model observation (pixel-verified)",
  page_added: "Page added",
  page_removed: "Page missing",
};

export const findingTypeLabel = (t: string) => FINDING_TYPE[t] ?? t.replace(/_/g, " ");

export const SOURCE_LABEL: Record<string, string> = {
  ocr: "Text",
  cv: "Pixels",
  vlm: "Vision model",
  page: "Page count",
};

export const COMPARISON_STATUS: Record<ComparisonOut["status"], { label: string; tone: BadgeTone }> = {
  queued: { label: "Queued", tone: "neutral" },
  waiting_for_documents: { label: "Waiting for processing", tone: "evidence" },
  running: { label: "Comparing", tone: "evidence" },
  completed: { label: "Completed", tone: "primary" },
  failed: { label: "Failed", tone: "danger" },
};

export const STAGE_LABEL: Record<string, string> = {
  waiting_for_documents: "Waiting for both documents to finish processing",
  loading_documents: "Loading both documents",
  aligning_pages: "Aligning pages and comparing text and pixels",
  vision_analysis: "Checking regions with the vision model",
  saving_findings: "Saving the differences",
  completed: "Completed",
};

export const VLM_STATUS: Record<ComparisonOut["vlm_status"], string> = {
  used: "Vision model used",
  unavailable: "Vision model unavailable",
  failed: "Vision model failed",
  disabled: "Vision model disabled",
  not_run: "Vision model not run",
};

export const REVIEW: Record<ComparisonReviewStatus, { label: string; tone: BadgeTone }> = {
  unreviewed: { label: "Not reviewed", tone: "neutral" },
  confirmed_difference: { label: "Confirmed difference", tone: "warning" },
  needs_more_evidence: { label: "Needs more evidence", tone: "evidence" },
  dismissed: { label: "Dismissed", tone: "neutral" },
};

export const EXPORTS: { kind: ComparisonExportKind; label: string; hint: string }[] = [
  { kind: "annotated_pdf", label: "Annotated test document (PDF)", hint: "Numbered boxes on a copy of the test document" },
  { kind: "annotated_images", label: "Annotated page images (ZIP)", hint: "PNG pages with the same marks" },
  { kind: "report_pdf", label: "Comparison report (PDF)", hint: "Each difference with crops of both documents" },
  { kind: "findings_json", label: "Findings (JSON)", hint: "Every finding with regions, sources and review status" },
];

export const ACTIVE_STATUSES = new Set(["queued", "waiting_for_documents", "running"]);
export const COMPARABLE_TYPES = new Set(["application/pdf", "image/png", "image/jpeg", "image/tiff"]);
