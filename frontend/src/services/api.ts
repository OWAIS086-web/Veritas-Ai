/**
 * The only module that talks to the backend. Attaches the bearer token, refreshes it once on
 * 401 (single-flight), and turns RFC 7807 problem+json responses into ApiError.
 */
import { getStoredRefresh, useAuth } from "@/stores/auth";
import type {
  AuditPage,
  CaseCreate,
  CaseOut,
  CasePage,
  CommentOut,
  CompareResponse,
  DocumentOut,
  DocumentPage,
  EdgeEvidenceOut,
  EntityOut,
  EvidenceOut,
  GraphOut,
  RebuildOut,
  RelationshipOut,
  ExtractionOut,
  FindingDetail,
  FindingPage,
  FindingSummary,
  Job,
  StatusChange,
  PageOut,
  PreviewOut,
  ProcessResponse,
  UploadResponse,
  LoginBody,
  MeResponse,
  Member,
  MemberAdd,
  MyOrganization,
  OrganizationOut,
  OrganizationUpdate,
  OverviewStats,
  RegisterBody,
  Role,
  TokenPair,
} from "@/types/api";

export const API_BASE = "/api/v1";

export interface FieldError {
  loc: string[];
  msg: string;
}

export class ApiError extends Error {
  readonly status: number;
  readonly title: string;
  readonly detail: string;
  readonly errors: FieldError[];
  readonly requestId?: string;

  constructor(status: number, title: string, detail: string, errors: FieldError[] = [],
              requestId?: string) {
    super(detail || title);
    this.status = status;
    this.title = title;
    this.detail = detail;
    this.errors = errors;
    this.requestId = requestId;
  }
}

interface RequestOptions {
  method?: "GET" | "POST" | "PATCH" | "DELETE";
  body?: unknown;
  form?: FormData;
  auth?: boolean;
  signal?: AbortSignal;
}

/** Query string from defined, non-empty values. */
export function query(params: Record<string, string | number | null | undefined>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null && value !== "") search.set(key, String(value));
  }
  return search.toString();
}

async function toApiError(resp: Response): Promise<ApiError> {
  try {
    const body = (await resp.json()) as Partial<{
      title: string; detail: string; errors: FieldError[]; request_id: string;
    }>;
    return new ApiError(resp.status, body.title ?? resp.statusText, body.detail ?? "",
                        body.errors ?? [], body.request_id);
  } catch {
    return new ApiError(resp.status, resp.statusText || "Request failed",
                        "The server returned an unexpected response.");
  }
}

let refreshing: Promise<boolean> | null = null;

/** Exchange the stored refresh token for a new pair. Concurrent callers share one request. */
export function refreshSession(): Promise<boolean> {
  if (!refreshing) {
    refreshing = (async () => {
      const refresh = getStoredRefresh();
      if (!refresh) return false;
      const resp = await fetch(`${API_BASE}/auth/refresh`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ refresh_token: refresh }),
      });
      if (!resp.ok) {
        useAuth.getState().clear();
        return false;
      }
      useAuth.getState().setTokens((await resp.json()) as TokenPair);
      return true;
    })().finally(() => {
      refreshing = null;
    });
  }
  return refreshing;
}

export function authHeaders(): Record<string, string> {
  const token = useAuth.getState().accessToken;
  return token ? { Authorization: `Bearer ${token}` } : {};
}

export async function request<T>(path: string, opts: RequestOptions = {}): Promise<T> {
  const { method = "GET", body, form, auth = true, signal } = opts;
  const send = () =>
    fetch(`${API_BASE}${path}`, {
      method,
      signal,
      headers: {
        Accept: "application/json",
        // FormData sets its own multipart boundary header.
        ...(body !== undefined ? { "Content-Type": "application/json" } : {}),
        ...(auth ? authHeaders() : {}),
      },
      body: form ?? (body !== undefined ? JSON.stringify(body) : undefined),
    });

  let resp = await send();
  if (resp.status === 401 && auth && (await refreshSession())) {
    resp = await send();
  }
  if (!resp.ok) throw await toApiError(resp);
  if (resp.status === 204) return undefined as T;
  return (await resp.json()) as T;
}

export const api = {
  register: (body: RegisterBody) =>
    request<TokenPair>("/auth/register", { method: "POST", body, auth: false }),
  login: (body: LoginBody) =>
    request<TokenPair>("/auth/login", { method: "POST", body, auth: false }),
  logout: (refreshToken: string) =>
    request<undefined>("/auth/logout", { method: "POST", body: { refresh_token: refreshToken },
                                    auth: false }),
  me: () => request<MeResponse>("/auth/me"),

  myOrganizations: () => request<MyOrganization[]>("/organizations"),
  organization: (id: string) => request<OrganizationOut>(`/organizations/${id}`),
  updateOrganization: (id: string, body: OrganizationUpdate) =>
    request<OrganizationOut>(`/organizations/${id}`, { method: "PATCH", body }),
  members: (orgId: string) => request<Member[]>(`/organizations/${orgId}/members`),
  addMember: (orgId: string, body: MemberAdd) =>
    request<Member>(`/organizations/${orgId}/members`, { method: "POST", body }),
  changeRole: (orgId: string, userId: string, role: Role) =>
    request<Member>(`/organizations/${orgId}/members/${userId}`,
                    { method: "PATCH", body: { role } }),
  removeMember: (orgId: string, userId: string) =>
    request<undefined>(`/organizations/${orgId}/members/${userId}`, { method: "DELETE" }),

  auditLogs: (cursor?: string | null, limit = 25) =>
    request<AuditPage>(`/audit-logs?limit=${limit}${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ""}`),
  overview: () => request<OverviewStats>("/stats/overview"),

  cases: (params: { cursor?: string | null; status?: string; priority?: string; q?: string }) =>
    request<CasePage>(`/cases?${query({ limit: 25, ...params })}`),
  caseById: (id: string) => request<CaseOut>(`/cases/${id}`),
  createCase: (body: CaseCreate) => request<CaseOut>("/cases", { method: "POST", body }),
  updateCase: (id: string, body: Partial<CaseCreate> & { status?: "open" | "closed" }) =>
    request<CaseOut>(`/cases/${id}`, { method: "PATCH", body }),
  deleteCase: (id: string) => request<undefined>(`/cases/${id}`, { method: "DELETE" }),
  caseDocuments: (caseId: string) => request<DocumentOut[]>(`/cases/${caseId}/documents`),
  uploadDocuments: (caseId: string, files: File[]) => {
    const form = new FormData();
    for (const file of files) form.append("files", file, file.name);
    return request<UploadResponse>(`/cases/${caseId}/documents`, { method: "POST", form });
  },
  processCase: (caseId: string) =>
    request<ProcessResponse>(`/cases/${caseId}/process`, { method: "POST" }),
  documents: (params: { cursor?: string | null; status?: string; doc_type?: string; q?: string }) =>
    request<DocumentPage>(`/documents?${query({ limit: 50, ...params })}`),
  document: (id: string) => request<DocumentOut>(`/documents/${id}`),
  documentPages: (id: string) => request<PageOut[]>(`/documents/${id}/pages`),
  documentExtraction: (id: string) => request<ExtractionOut | null>(`/documents/${id}/extractions`),
  documentPreview: (id: string, page?: number) =>
    request<PreviewOut>(`/documents/${id}/preview${page ? `?page=${page}` : ""}`),
  retryDocument: (id: string) => request<Job>(`/documents/${id}/retry`, { method: "POST" }),
  compareCase: (caseId: string) =>
    request<CompareResponse>(`/cases/${caseId}/compare`, { method: "POST" }),
  caseFindings: (caseId: string, includeInactive = false) =>
    request<FindingSummary[]>(`/cases/${caseId}/findings?${query({ include_inactive: includeInactive ? "true" : null })}`),
  findings: (params: { cursor?: string | null; status?: string; severity?: string; priority?: string;
                       type?: string; case_id?: string; include_inactive?: boolean }) =>
    request<FindingPage>(`/findings?${query({
      limit: 50, ...params, include_inactive: params.include_inactive ? "true" : null,
    })}`),
  finding: (id: string) => request<FindingDetail>(`/findings/${id}`),
  findingEvidence: (id: string) => request<EvidenceOut[]>(`/findings/${id}/evidence`),
  setFindingStatus: (id: string, body: StatusChange) =>
    request<FindingDetail>(`/findings/${id}/status`, { method: "PATCH", body }),
  addFindingComment: (id: string, body: string) =>
    request<CommentOut>(`/findings/${id}/comments`, { method: "POST", body: { body } }),
  caseGraph: (caseId: string, params: { types?: string; q?: string } = {}) =>
    request<GraphOut>(`/cases/${caseId}/graph?${query(params)}`),
  rebuildGraph: (caseId: string) =>
    request<RebuildOut>(`/cases/${caseId}/graph/rebuild`, { method: "POST" }),
  entity: (id: string) => request<EntityOut>(`/entities/${id}`),
  entityRelationships: (id: string) => request<RelationshipOut[]>(`/entities/${id}/relationships`),
  relationshipEvidence: (id: string) => request<EdgeEvidenceOut[]>(`/relationships/${id}/evidence`),
  startPingJob: () => request<Job>("/system/ping-job", { method: "POST" }),
  job: (id: string) => request<Job>(`/jobs/${id}`),
};
