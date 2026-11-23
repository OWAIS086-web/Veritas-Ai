/** Friendly aliases over the types generated from backend/openapi.json (npm run gen:api). */
import type { components } from "./openapi";

type S = components["schemas"];

export type TokenPair = S["TokenPair"];
export type MeResponse = S["MeResponse"];
export type Role = MeResponse["role"];
export type OrganizationOut = S["OrganizationOut"];
export type MyOrganization = S["MyOrganizationOut"];
export type Member = S["MemberOut"];
export type AuditLog = S["AuditLogOut"];
export type AuditPage = S["Page_AuditLogOut_"];
export type OverviewStats = S["OverviewStats"];
export type Metric = S["Metric"];
export type Job = S["JobOut"];
export type Health = S["HealthResponse"];

export type RegisterBody = S["RegisterRequest"];
export type LoginBody = S["LoginRequest"];
export type OrganizationUpdate = S["OrganizationUpdate"];
export type MemberAdd = S["MemberAdd"];

export type CaseOut = S["CaseOut"];
export type CaseCreate = S["CaseCreate"];
export type CasePage = S["Page_CaseOut_"];
export type DocumentOut = S["DocumentOut"];
export type DocumentPage = S["Page_DocumentOut_"];
export type StageOut = S["StageOut"];
export type UploadResponse = S["UploadResponse"];
export type UploadResult = S["UploadResult"];
export type ProcessResponse = S["ProcessResponse"];
export type PageOut = S["PageOut"];
export type ExtractionOut = S["ExtractionOut"];
export type FieldOut = S["FieldOut"];
export type PreviewOut = S["PreviewOut"];

export type FindingSummary = S["FindingSummary"];
export type FindingDetail = S["FindingDetail"];
export type FindingPage = S["Page_FindingSummary_"];
export type FindingStatus = FindingSummary["status"];
export type EvidenceOut = S["EvidenceOut"];
export type StatusChange = S["StatusChange"];
export type CommentOut = S["CommentOut"];
export type CompareResponse = S["CompareResponse"];

export type GraphOut = S["GraphOut"];
export type GraphNodeOut = S["GraphNodeOut"];
export type GraphEdgeOut = S["GraphEdgeOut"];
export type RebuildOut = S["RebuildOut"];
export type ForensicSummaryOut = S["ForensicSummaryOut"];
export type ForensicRunOut = S["ForensicRunOut"];
export type ForensicAnomalyOut = S["ForensicAnomalyOut"];
export type InvestigationOut = S["InvestigationOut"];
export type InvestigationDetail = S["InvestigationDetail"];
export type AgentRunOut = S["AgentRunOut"];
export type EvidenceRequestOut = S["EvidenceRequestOut"];
export type ReportOut = S["ReportOut"];
export type ReportDetail = S["ReportDetail"];
export type DownloadOut = S["DownloadOut"];
export type EntityOut = S["EntityOut"];
export type RelationshipOut = S["RelationshipOut"];
export type EdgeEvidenceOut = S["EdgeEvidenceOut"];
export type ComparisonOut = S["ComparisonOut"];
export type ComparisonDetail = S["ComparisonDetail"];
export type ComparisonFindingOut = S["ComparisonFindingOut"];
export type ComparisonExportOut = S["ComparisonExportOut"];
export type ComparisonUploadOut = S["ComparisonUploadOut"];
export type ComparisonReviewStatus = S["ReviewIn"]["status"];
export type ComparisonExportKind = S["ExportCreate"]["kind"];
export type ReviewEntryOut = S["ReviewEntryOut"];
export type VlmStatusOut = S["VlmStatusOut"];

export const ROLE_LABELS: Record<Role, string> = {
  org_admin: "Organization Admin",
  investigation_manager: "Investigation Manager",
  investigator: "Investigator",
  reviewer: "Reviewer",
  read_only_analyst: "Read-only Analyst",
};
