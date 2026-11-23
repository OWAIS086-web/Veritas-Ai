import { useMutation } from "@tanstack/react-query";
import { type FormEvent, useState } from "react";
import { Link, Navigate, useNavigate } from "react-router-dom";

import { Button } from "@/components/ui/Button";
import { Field } from "@/components/ui/primitives";
import { AuthLayout } from "@/features/auth/AuthLayout";
import { startSession } from "@/features/auth/session";
import { api, ApiError } from "@/services/api";
import { useAuth } from "@/stores/auth";

const MIN_PASSWORD = 12;

export function RegisterPage() {
  const navigate = useNavigate();
  const status = useAuth((s) => s.status);
  const [form, setForm] = useState({ full_name: "", email: "", password: "", organization_name: "" });
  const set = (key: keyof typeof form) => (e: { target: { value: string } }) =>
    setForm((f) => ({ ...f, [key]: e.target.value }));

  const register = useMutation({
    mutationFn: async () => startSession(await api.register(form)),
    onSuccess: () => navigate("/", { replace: true }),
  });

  if (status === "authenticated") return <Navigate to="/" replace />;

  const fieldError = (name: string) =>
    register.error instanceof ApiError
      ? register.error.errors.find((e) => e.loc.at(-1) === name)?.msg
      : undefined;
  const shortPassword = form.password.length > 0 && form.password.length < MIN_PASSWORD;

  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    register.mutate();
  };

  return (
    <AuthLayout
      title="Create your organization"
      subtitle="You'll be its Organization Admin and can invite your team."
      footer={<>Already registered? <Link to="/login" className="text-evidence hover:underline">Sign in</Link></>}
    >
      <form onSubmit={onSubmit} className="space-y-4" noValidate>
        <Field label="Full name" autoComplete="name" required value={form.full_name}
               onChange={set("full_name")} error={fieldError("full_name")} />
        <Field label="Organization name" required value={form.organization_name}
               onChange={set("organization_name")} error={fieldError("organization_name")} />
        <Field label="Work email" type="email" autoComplete="email" required value={form.email}
               onChange={set("email")} error={fieldError("email")} />
        <Field label="Password" type="password" autoComplete="new-password" required
               value={form.password} onChange={set("password")}
               error={fieldError("password") ?? (shortPassword ? `Use at least ${MIN_PASSWORD} characters.` : undefined)}
               hint={`At least ${MIN_PASSWORD} characters.`} />
        {register.error instanceof ApiError && register.error.errors.length === 0 ? (
          <p role="alert" className="rounded-lg border border-danger/30 bg-danger/10 px-3 py-2 text-xs text-danger">
            {register.error.detail || register.error.title}
          </p>
        ) : null}
        <Button type="submit" className="w-full" loading={register.isPending}
                disabled={!form.email || !form.full_name || !form.organization_name ||
                          form.password.length < MIN_PASSWORD}>
          Create organization
        </Button>
      </form>
    </AuthLayout>
  );
}
