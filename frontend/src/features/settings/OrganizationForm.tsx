import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { type FormEvent, useEffect, useState } from "react";

import { ErrorState } from "@/components/QueryState";
import { Button } from "@/components/ui/Button";
import { Card, CardTitle, Field, Mono, Skeleton } from "@/components/ui/primitives";
import { api, ApiError } from "@/services/api";
import { useAuth, usePermission } from "@/stores/auth";
import { toast } from "@/stores/toast";

export function OrganizationForm({ organizationId }: { organizationId: string }) {
  const canEdit = usePermission("org:update");
  const qc = useQueryClient();
  const org = useQuery({ queryKey: ["organization", organizationId], queryFn: () => api.organization(organizationId) });
  const [name, setName] = useState("");
  const [retention, setRetention] = useState("");

  useEffect(() => {
    if (org.data) {
      setName(org.data.name);
      setRetention(org.data.retention_days?.toString() ?? "");
    }
  }, [org.data]);

  const save = useMutation({
    mutationFn: () =>
      api.updateOrganization(organizationId, {
        name,
        retention_days: retention === "" ? null : Number(retention),
      }),
    onSuccess: async (updated) => {
      qc.setQueryData(["organization", organizationId], updated);
      const me = useAuth.getState().me;
      if (me) useAuth.getState().setMe({ ...me, organization: updated });
      await qc.invalidateQueries({ queryKey: ["audit-logs"] });
      toast.success("Organization updated");
    },
    onError: (err) => toast.error("Update failed", err instanceof ApiError ? err.detail : undefined),
  });

  const retentionInvalid = retention !== "" && (!/^\d+$/.test(retention) || Number(retention) < 1 || Number(retention) > 3650);
  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    if (!retentionInvalid) save.mutate();
  };

  return (
    <Card>
      <CardTitle>Organization</CardTitle>
      {org.isPending ? (
        <div className="space-y-3"><Skeleton className="h-10" /><Skeleton className="h-10" /></div>
      ) : org.isError ? (
        <ErrorState error={org.error} onRetry={() => void org.refetch()} />
      ) : (
        <form onSubmit={onSubmit} className="space-y-4">
          <Field label="Organization name" value={name} onChange={(e) => setName(e.target.value)}
                 disabled={!canEdit} required minLength={2} />
          <Field label="Data retention (days)" inputMode="numeric" value={retention}
                 onChange={(e) => setRetention(e.target.value.trim())} disabled={!canEdit}
                 error={retentionInvalid ? "Enter a whole number from 1 to 3650, or leave empty." : undefined}
                 hint="Leave empty to keep data until deleted. Automatic purging arrives with the security phase." />
          <p className="text-xs text-muted">Slug <Mono className="text-ink">{org.data.slug}</Mono></p>
          {canEdit ? (
            <Button type="submit" loading={save.isPending} disabled={name.trim().length < 2 || retentionInvalid}>
              Save changes
            </Button>
          ) : (
            <p className="text-xs text-muted">Only an Organization Admin can change these settings.</p>
          )}
        </form>
      )}
    </Card>
  );
}
