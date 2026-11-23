import { PageHeader } from "@/components/PageHeader";
import { MembersPanel } from "@/features/settings/MembersPanel";
import { OrganizationForm } from "@/features/settings/OrganizationForm";
import { useAuth } from "@/stores/auth";

export function SettingsPage() {
  const me = useAuth((s) => s.me);
  if (!me) return null;
  return (
    <div>
      <PageHeader title="Settings" subtitle="Organization profile, data retention and team access." />
      <div className="grid gap-6 xl:grid-cols-[1fr_1.4fr]">
        <OrganizationForm organizationId={me.organization.id} />
        <MembersPanel organizationId={me.organization.id} currentUserId={me.user.id} />
      </div>
    </div>
  );
}
