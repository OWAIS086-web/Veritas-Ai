import { useMutation, useQueryClient } from "@tanstack/react-query";
import { X } from "lucide-react";
import { type FormEvent, useState } from "react";
import { useNavigate } from "react-router-dom";

import { Dropzone } from "@/components/Dropzone";
import { PageHeader } from "@/components/PageHeader";
import { Button } from "@/components/ui/Button";
import { Card, CardTitle, Field, Mono, Select } from "@/components/ui/primitives";
import { formatBytes, INVESTIGATION_TYPES } from "@/features/documents/labels";
import { api, ApiError } from "@/services/api";
import { toast } from "@/stores/toast";
import type { CaseCreate } from "@/types/api";

export function CreateInvestigationPage() {
  const navigate = useNavigate();
  const qc = useQueryClient();
  const [form, setForm] = useState<CaseCreate>({
    title: "", objective: "", investigation_type: "international_shipment", priority: "medium",
  });
  const [files, setFiles] = useState<File[]>([]);

  const create = useMutation({
    mutationFn: async () => {
      const created = await api.createCase(form);
      const upload = files.length ? await api.uploadDocuments(created.id, files) : null;
      return { created, upload };
    },
    onSuccess: async ({ created, upload }) => {
      await qc.invalidateQueries({ queryKey: ["cases"] });
      const rejected = upload?.results.filter((r) => r.status === "rejected").length ?? 0;
      toast.success("Investigation created",
        upload ? `${upload.results.filter((r) => r.status === "accepted").length} document(s) queued for processing` +
                 (rejected ? `, ${rejected} rejected` : "") : undefined);
      navigate(`/investigations/${created.id}`, { state: { jobId: upload?.job_id ?? null } });
    },
    onError: (err) => toast.error("Could not create the investigation", err instanceof ApiError ? err.detail : undefined),
  });

  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    create.mutate();
  };
  const addFiles = (more: File[]) => setFiles((prev) => [...prev, ...more].slice(0, 100));

  return (
    <div>
      <PageHeader title="New investigation" subtitle="Describe the case and attach its documents." />
      <form onSubmit={onSubmit} className="grid gap-6 xl:grid-cols-[1fr_1fr]">
        <Card>
          <CardTitle>Case</CardTitle>
          <div className="space-y-4">
            <Field label="Case title" required minLength={3} value={form.title}
                   onChange={(e) => setForm({ ...form, title: e.target.value })}
                   placeholder="International shipment SHIP-2049" />
            <div className="space-y-1.5">
              <label htmlFor="objective" className="block text-xs font-medium text-muted">Objective</label>
              <textarea id="objective" rows={4} value={form.objective ?? ""}
                        onChange={(e) => setForm({ ...form, objective: e.target.value })}
                        placeholder="Reconcile the declared values across the shipment documents."
                        className="w-full rounded-lg border border-line bg-bg/60 p-3 text-sm" />
            </div>
            <div className="grid gap-4 sm:grid-cols-2">
              <Select label="Investigation type" value={form.investigation_type}
                      onChange={(e) => setForm({ ...form, investigation_type: e.target.value as CaseCreate["investigation_type"] })}>
                {Object.entries(INVESTIGATION_TYPES).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
              </Select>
              <Select label="Priority" value={form.priority}
                      onChange={(e) => setForm({ ...form, priority: e.target.value as CaseCreate["priority"] })}>
                {["low", "medium", "high", "critical"].map((p) => <option key={p} value={p}>{p}</option>)}
              </Select>
            </div>
          </div>
        </Card>
        <Card>
          <CardTitle>Documents</CardTitle>
          <Dropzone onFiles={addFiles} disabled={create.isPending} />
          {files.length ? (
            <ul className="mt-4 divide-y divide-line" aria-label="Files to upload">
              {files.map((f, i) => (
                <li key={`${f.name}-${i}`} className="flex items-center gap-3 py-2 text-sm">
                  <span className="min-w-0 flex-1 truncate">{f.name}</span>
                  <Mono className="text-muted">{formatBytes(f.size)}</Mono>
                  <button type="button" aria-label={`Remove ${f.name}`} className="text-muted hover:text-danger"
                          onClick={() => setFiles(files.filter((_, j) => j !== i))}>
                    <X className="h-4 w-4" aria-hidden />
                  </button>
                </li>
              ))}
            </ul>
          ) : (
            <p className="mt-3 text-xs text-muted">You can also add documents later from the case workspace.</p>
          )}
        </Card>
        <div className="flex justify-end gap-2 xl:col-span-2">
          <Button variant="ghost" onClick={() => navigate("/investigations")}>Cancel</Button>
          <Button type="submit" loading={create.isPending} disabled={form.title.trim().length < 3}>
            {files.length ? `Create and process ${files.length} document${files.length === 1 ? "" : "s"}` : "Create investigation"}
          </Button>
        </div>
      </form>
    </div>
  );
}
