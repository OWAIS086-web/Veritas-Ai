import { useMutation } from "@tanstack/react-query";
import { type FormEvent, useState } from "react";
import { Link, Navigate, useLocation, useNavigate } from "react-router-dom";

import { Button } from "@/components/ui/Button";
import { Field } from "@/components/ui/primitives";
import { AuthLayout } from "@/features/auth/AuthLayout";
import { startSession } from "@/features/auth/session";
import { api, ApiError } from "@/services/api";
import { useAuth } from "@/stores/auth";

export function LoginPage() {
  const navigate = useNavigate();
  const location = useLocation();
  const status = useAuth((s) => s.status);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");

  const login = useMutation({
    mutationFn: async () => startSession(await api.login({ email, password })),
    onSuccess: () => {
      const from = (location.state as { from?: string } | null)?.from;
      navigate(from && from !== "/login" ? from : "/", { replace: true });
    },
  });

  if (status === "authenticated") return <Navigate to="/" replace />;

  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    login.mutate();
  };
  const err = login.error;

  return (
    <AuthLayout
      title="Sign in"
      subtitle="Access your organization's investigation workspace."
      footer={<>No account yet? <Link to="/register" className="text-evidence hover:underline">Create an organization</Link></>}
    >
      <form onSubmit={onSubmit} className="space-y-4" noValidate>
        <Field label="Work email" type="email" autoComplete="email" required value={email}
               onChange={(e) => setEmail(e.target.value)} />
        <Field label="Password" type="password" autoComplete="current-password" required
               value={password} onChange={(e) => setPassword(e.target.value)} />
        {err ? (
          <p role="alert" className="rounded-lg border border-danger/30 bg-danger/10 px-3 py-2 text-xs text-danger">
            {err instanceof ApiError ? err.detail || err.title : "Sign-in failed. Try again."}
          </p>
        ) : null}
        <Button type="submit" className="w-full" loading={login.isPending}
                disabled={!email || !password}>
          Sign in
        </Button>
      </form>
    </AuthLayout>
  );
}
