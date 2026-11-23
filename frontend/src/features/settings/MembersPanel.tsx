import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { UserMinus, UserPlus } from "lucide-react";
import { type FormEvent, useState } from "react";

import { EmptyState, ErrorState } from "@/components/QueryState";
import { Button } from "@/components/ui/Button";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { Card, CardTitle, Field, Select, Skeleton } from "@/components/ui/primitives";
import { api, ApiError } from "@/services/api";
import { usePermission } from "@/stores/auth";
import { toast } from "@/stores/toast";
import { ROLE_LABELS, type Member, type Role } from "@/types/api";

const ROLES = Object.keys(ROLE_LABELS) as Role[];

export function MembersPanel({ organizationId, currentUserId }: {
  organizationId: string; currentUserId: string;
}) {
  const canManage = usePermission("members:manage");
  const qc = useQueryClient();
  const key = ["members", organizationId];
  const members = useQuery({ queryKey: key, queryFn: () => api.members(organizationId) });
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<Role>("investigator");
  const [removing, setRemoving] = useState<Member | null>(null);

  const refresh = async () => {
    await qc.invalidateQueries({ queryKey: key });
    await qc.invalidateQueries({ queryKey: ["audit-logs"] });
    await qc.invalidateQueries({ queryKey: ["overview"] });
  };
  const fail = (title: string) => (err: unknown) =>
    toast.error(title, err instanceof ApiError ? err.detail : undefined);

  const add = useMutation({
    mutationFn: () => api.addMember(organizationId, { email, role }),
    onSuccess: async (m) => {
      setEmail("");
      await refresh();
      toast.success("Member added", `${m.email} joined as ${ROLE_LABELS[m.role]}.`);
    },
    onError: fail("Could not add member"),
  });
  const change = useMutation({
    mutationFn: (v: { userId: string; role: Role }) => api.changeRole(organizationId, v.userId, v.role),
    onSuccess: async (m) => {
      await refresh();
      toast.success("Role updated", `${m.email} is now ${ROLE_LABELS[m.role]}.`);
    },
    onError: async (err) => {
      await qc.invalidateQueries({ queryKey: key });
      fail("Could not change role")(err);
    },
  });
  const remove = useMutation({
    mutationFn: (m: Member) => api.removeMember(organizationId, m.user_id),
    onSuccess: async () => {
      setRemoving(null);
      await refresh();
      toast.success("Member removed", "Their sessions in this organization were revoked.");
    },
    onError: fail("Could not remove member"),
  });

  const onAdd = (e: FormEvent) => {
    e.preventDefault();
    add.mutate();
  };

  return (
    <Card>
      <CardTitle>Team members</CardTitle>
      {canManage ? (
        <form onSubmit={onAdd} className="mb-5 grid gap-3 sm:grid-cols-[1fr_200px_auto] sm:items-end">
          <Field label="Email of a registered user" type="email" value={email}
                 onChange={(e) => setEmail(e.target.value)} required />
          <Select label="Role" value={role} onChange={(e) => setRole(e.target.value as Role)}>
            {ROLES.map((r) => <option key={r} value={r}>{ROLE_LABELS[r]}</option>)}
          </Select>
          <Button type="submit" icon={<UserPlus className="h-4 w-4" />} loading={add.isPending} disabled={!email}>
            Add
          </Button>
        </form>
      ) : null}

      {members.isPending ? (
        <div className="space-y-2">{Array.from({ length: 3 }, (_, i) => <Skeleton key={i} className="h-12" />)}</div>
      ) : members.isError ? (
        <ErrorState error={members.error} onRetry={() => void members.refetch()} />
      ) : members.data.length === 0 ? (
        <EmptyState title="No members" />
      ) : (
        <ul className="divide-y divide-line" aria-label="Members">
          {members.data.map((m) => (
            <li key={m.user_id} className="flex flex-wrap items-center gap-3 py-3">
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-medium">
                  {m.full_name}
                  {m.user_id === currentUserId ? <span className="ml-2 text-xs text-muted">(you)</span> : null}
                </p>
                <p className="truncate text-xs text-muted">{m.email}</p>
              </div>
              {canManage ? (
                <>
                  <Select label={`Role for ${m.email}`} hideLabel value={m.role} className="w-52"
                          disabled={change.isPending}
                          onChange={(e) => change.mutate({ userId: m.user_id, role: e.target.value as Role })}>
                    {ROLES.map((r) => <option key={r} value={r}>{ROLE_LABELS[r]}</option>)}
                  </Select>
                  <Button variant="ghost" size="sm" aria-label={`Remove ${m.email}`}
                          icon={<UserMinus className="h-4 w-4" />} onClick={() => setRemoving(m)} />
                </>
              ) : (
                <span className="text-xs text-muted">{ROLE_LABELS[m.role]}</span>
              )}
            </li>
          ))}
        </ul>
      )}

      <ConfirmDialog
        open={removing !== null}
        onOpenChange={(open) => !open && setRemoving(null)}
        title="Remove member?"
        description={<>
          <strong className="text-ink">{removing?.email}</strong> will lose access to this organization
          immediately, and their active sessions here will be revoked.
        </>}
        confirmLabel="Remove member"
        loading={remove.isPending}
        onConfirm={() => removing && remove.mutate(removing)}
      />
    </Card>
  );
}
