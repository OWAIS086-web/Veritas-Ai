import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import { GitCompareArrows, Upload } from "lucide-react";
import { type FormEvent, useMemo, useState } from "react";

import { EmptyState, ErrorState } from "@/components/QueryState";
import { Button } from "@/components/ui/Button";
import { Badge, Card, CardTitle, Mono, Select, Skeleton } from "@/components/ui/primitives";
import { ComparisonView } from "@/features/forensics/comparison/ComparisonView";
import {
  ACTIVE_STATUSES, COMPARABLE_TYPES, COMPARISON_STATUS, VLM_STATUS,
} from "@/features/forensics/comparison/labels";
import type { PaneDoc } from "@/features/forensics/comparison/SyncedViewer";
import { ApiError, api } from "@/services/api";
import { usePermission } from "@/stores/auth";
import { toast } from "@/stores/toast";
import type { DocumentOut } from "@/types/api";

const ACCEPT = ".pdf,.png,.jpg,.jpeg,.tif,.tiff,application/pdf,image/png,image/jpeg,image/tiff";

function VlmStatus() {
  const status = useQuery({ queryKey: ["vlm-status"], queryFn: api.vlmStatus, staleTime: 60_000 });
  if (status.isPending) return <Skeleton className="h-5 w-64" />;
  if (status.isError) return <p className="text-xs text-muted">Vision-model status could not be checked.</p>;
  const s = status.data;
  const ready = s.enabled && s.reachable && s.model_available;
  return (
    <p className="flex flex-wrap items-center gap-2 text-xs" aria-label="Vision model status">
      <Badge tone={ready ? "primary" : "warning"}>{ready ? "Vision model ready" : "Vision model not available"}</Badge>
      {s.model ? <Mono>{s.model}</Mono> : null}
      {s.endpoint_host ? <span className="text-muted">at {s.endpoint_host}</span> : null}
      {!s.enabled ? <span className="text-muted">Disabled by VERITAS_COMPARISON_VLM_ENABLED.</span>
        : s.error ? <span className="text-muted">{s.error} Comparisons still run with text and pixel evidence.</span> : null}
    </p>
  );
}

function NewComparison({ caseId, documents, onCreated }: {
  caseId: string;
  documents: DocumentOut[];
  onCreated: (id: string) => void;
}) {
  const qc = useQueryClient();
  const [mode, setMode] = useState<"upload" | "existing">("upload");
  const [original, setOriginal] = useState<File | null>(null);
  const [test, setTest] = useState<File | null>(null);
  const comparable = documents.filter((d) => COMPARABLE_TYPES.has(d.mime_type));
  const [originalId, setOriginalId] = useState("");
  const [testId, setTestId] = useState("");
  const done = (id: string) => {
    void qc.invalidateQueries({ queryKey: ["comparisons", caseId] });
    void qc.invalidateQueries({ queryKey: ["case-documents", caseId] });
    onCreated(id);
  };
  const fail = (err: unknown) => toast.error("Comparison not started", err instanceof ApiError ? err.detail : undefined);
  const upload = useMutation({
    mutationFn: () => api.uploadComparison(caseId, original as File, test as File),
    onSuccess: (r) => {
      toast.success("Comparison queued", "Both files are processed first; the comparison starts when they are ready.");
      done(r.comparison.id);
    },
    onError: fail,
  });
  const create = useMutation({
    mutationFn: () => api.createComparison(caseId, originalId, testId),
    onSuccess: (r) => { toast.success("Comparison queued"); done(r.id); },
    onError: fail,
  });
  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (mode === "upload" && original && test) upload.mutate();
    if (mode === "existing" && originalId && testId && originalId !== testId) create.mutate();
  };

  return (
    <form onSubmit={submit} className="space-y-3" aria-label="New comparison">
      <div role="radiogroup" aria-label="Source of the documents" className="flex gap-2">
        {(["upload", "existing"] as const).map((m) => (
          <button key={m} type="button" role="radio" aria-checked={mode === m} onClick={() => setMode(m)}
                  className={clsx("rounded-md border px-3 py-1 text-xs focus:outline-none focus:ring-2 focus:ring-evidence",
                                  mode === m ? "border-evidence bg-elevated" : "border-line text-muted")}>
            {m === "upload" ? "Upload two files" : "Use documents of this investigation"}
          </button>
        ))}
      </div>
      {mode === "upload" ? (
        <div className="grid gap-3 md:grid-cols-2">
          {([["Original document", setOriginal, original], ["Test document", setTest, test]] as const).map(
            ([label, set, file]) => (
              <label key={label} className="block text-xs text-muted">
                {label}
                <input type="file" accept={ACCEPT} aria-label={label}
                       onChange={(e) => set(e.target.files?.[0] ?? null)}
                       className="mt-1 block w-full text-sm text-ink file:mr-3 file:rounded-md file:border file:border-line file:bg-elevated file:px-3 file:py-1 file:text-ink" />
                {file ? <span className="mt-1 block">{file.name}</span> : null}
              </label>
            ),
          )}
        </div>
      ) : comparable.length < 2 ? (
        <p className="text-sm text-muted">This investigation needs at least two PDF or image documents to compare.</p>
      ) : (
        <div className="grid gap-3 md:grid-cols-2">
          <Select label="Original document" value={originalId} onChange={(e) => setOriginalId(e.target.value)}>
            <option value="">Choose…</option>
            {comparable.map((d) => <option key={d.id} value={d.id}>{d.original_filename}</option>)}
          </Select>
          <Select label="Test document" value={testId} onChange={(e) => setTestId(e.target.value)}>
            <option value="">Choose…</option>
            {comparable.filter((d) => d.id !== originalId).map((d) => <option key={d.id} value={d.id}>{d.original_filename}</option>)}
          </Select>
        </div>
      )}
      <Button type="submit" icon={mode === "upload" ? <Upload className="h-4 w-4" /> : <GitCompareArrows className="h-4 w-4" />}
              loading={upload.isPending || create.isPending}
              disabled={mode === "upload" ? !(original && test) : !(originalId && testId)}>
        Compare documents
      </Button>
    </form>
  );
}

/** Original-versus-test comparisons of one investigation. */
export function ComparisonLab({ caseId, comparisonId, onSelect }: {
  caseId: string;
  comparisonId: string | null;
  onSelect: (id: string) => void;
}) {
  const canCompare = usePermission("comparisons:run");
  const canUpload = usePermission("documents:upload");
  const canRun = canCompare && canUpload;
  const list = useQuery({
    queryKey: ["comparisons", caseId],
    queryFn: () => api.caseComparisons(caseId),
    refetchInterval: (q) => (q.state.data?.some((c) => ACTIVE_STATUSES.has(c.status)) ? 2000 : false),
  });
  const documents = useQuery({ queryKey: ["case-documents", caseId], queryFn: () => api.caseDocuments(caseId) });
  const docs = useMemo(() => new Map<string, PaneDoc>((documents.data ?? []).map((d) => [
    d.id, { id: d.id, filename: d.original_filename, mimeType: d.mime_type, pageCount: d.page_count ?? null },
  ])), [documents.data]);
  const current = comparisonId ?? list.data?.[0]?.id ?? null;

  return (
    <div className="space-y-4">
      <Card>
        <CardTitle action={<VlmStatus />}>Compare an original with a test document</CardTitle>
        <p className="mb-3 text-xs text-muted">
          Pages are aligned, text and pixels compared, and the strongest regions checked by the vision model.
          A difference shows what changed between the two files; it does not establish that either is forged or authentic.
        </p>
        {canRun ? (
          documents.isError ? <ErrorState error={documents.error} onRetry={() => void documents.refetch()} />
            : <NewComparison caseId={caseId} documents={documents.data ?? []} onCreated={onSelect} />
        ) : <p className="text-sm text-muted">Your role can read comparisons but not start them.</p>}
      </Card>
      {list.isPending ? <Skeleton className="h-40" /> : list.isError ? (
        <Card><ErrorState error={list.error} onRetry={() => void list.refetch()} /></Card>
      ) : list.data.length === 0 ? (
        <Card>
          <EmptyState title="No comparisons yet">
            Upload an original and a test document above, or pick two documents of this investigation.
          </EmptyState>
        </Card>
      ) : (
        <>
          <Card className="overflow-x-auto p-0">
            <table className="w-full text-left text-sm" aria-label="Comparisons">
              <thead className="border-b border-line text-xs uppercase tracking-wider text-muted">
                <tr>
                  <th scope="col" className="px-4 py-2 font-medium">Original vs test</th>
                  <th scope="col" className="px-4 py-2 font-medium">Status</th>
                  <th scope="col" className="px-4 py-2 font-medium">Differences</th>
                  <th scope="col" className="px-4 py-2 font-medium">Vision model</th>
                  <th scope="col" className="px-4 py-2 font-medium">Started</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line">
                {list.data.map((c) => {
                  const st = COMPARISON_STATUS[c.status];
                  return (
                    <tr key={c.id} className={clsx(c.id === current && "bg-elevated")}>
                      <td className="px-4 py-2">
                        <button type="button" onClick={() => onSelect(c.id)} aria-current={c.id === current ? "true" : undefined}
                                className="text-left hover:text-evidence">
                          {c.original_filename} <span className="text-muted">vs</span> {c.test_filename}
                        </button>
                      </td>
                      <td className="px-4 py-2">
                        <Badge tone={st.tone}>{st.label}</Badge>
                        {ACTIVE_STATUSES.has(c.status) ? <span className="ml-2 text-xs tabular text-muted">{c.progress}%</span> : null}
                      </td>
                      <td className="px-4 py-2 tabular">
                        {c.status === "completed" ? `${c.findings_count} (${c.findings_unreviewed} not reviewed)` : "-"}
                      </td>
                      <td className="px-4 py-2 text-xs text-muted">{VLM_STATUS[c.vlm_status]}</td>
                      <td className="px-4 py-2 text-xs text-muted">{new Date(c.created_at).toLocaleString()}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </Card>
          {current ? (documents.isPending ? <Skeleton className="h-[60vh]" />
            : <ComparisonView key={current} comparisonId={current} docs={docs} />) : null}
        </>
      )}
    </div>
  );
}
