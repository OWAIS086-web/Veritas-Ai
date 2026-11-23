import type { ReactNode } from "react";

import { Logo } from "@/components/Logo";

export function AuthLayout({ title, subtitle, children, footer }: {
  title: string; subtitle: string; children: ReactNode; footer: ReactNode;
}) {
  return (
    <div className="grid min-h-screen lg:grid-cols-[1.1fr_1fr]">
      <section className="grid-lines relative hidden flex-col justify-between overflow-hidden border-r border-line p-12 lg:flex">
        <Logo />
        <div className="max-w-md space-y-5">
          <p className="text-[11px] uppercase tracking-[0.22em] text-evidence">Document investigation platform</p>
          <h1 className="text-4xl font-semibold leading-tight tracking-tight">
            Don&apos;t just read documents.
            <span className="block text-primary">Investigate the truth behind them.</span>
          </h1>
          <ul className="space-y-2 text-sm text-muted">
            <li>Every finding traced to its document, page and region.</li>
            <li>Contradictions found across the whole document set.</li>
            <li>Observations for human review, never automatic verdicts.</li>
          </ul>
        </div>
        <p className="text-xs text-muted">Each organization's data is isolated at the database level.</p>
      </section>
      <section className="flex items-center justify-center p-6">
        <div className="w-full max-w-sm">
          <div className="mb-8 lg:hidden"><Logo /></div>
          <h2 className="text-2xl font-semibold tracking-tight">{title}</h2>
          <p className="mt-1 text-sm text-muted">{subtitle}</p>
          <div className="mt-8">{children}</div>
          <div className="mt-6 text-sm text-muted">{footer}</div>
        </div>
      </section>
    </div>
  );
}
