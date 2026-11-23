import { clsx } from "clsx";
import { LogOut } from "lucide-react";
import { NavLink, Outlet, useNavigate } from "react-router-dom";

import { NAV_ITEMS } from "@/app/navigation";
import { Logo } from "@/components/Logo";
import { Badge } from "@/components/ui/primitives";
import { useLogout } from "@/features/auth/session";
import { useAuth } from "@/stores/auth";
import { ROLE_LABELS } from "@/types/api";

export function AppShell() {
  const me = useAuth((s) => s.me);
  const logout = useLogout();
  const navigate = useNavigate();

  return (
    <div className="flex min-h-screen">
      <a href="#main" className="sr-only focus:not-sr-only focus:absolute focus:left-2 focus:top-2 focus:z-50 focus:rounded focus:bg-elevated focus:px-3 focus:py-2">
        Skip to content
      </a>
      <aside className="sticky top-0 flex h-screen w-16 shrink-0 flex-col border-r border-line bg-surface/60 backdrop-blur lg:w-60">
        <div className="flex h-16 items-center px-4">
          <span className="hidden lg:block"><Logo /></span>
          <span className="lg:hidden"><Logo compact /></span>
        </div>
        <nav aria-label="Main" className="flex-1 space-y-0.5 overflow-y-auto px-2 py-2">
          {NAV_ITEMS.map((item) => (
            <NavLink
              key={item.path}
              to={item.path}
              end={item.path === "/"}
              title={item.label}
              className={({ isActive }) =>
                clsx(
                  "group flex items-center gap-3 rounded-lg px-3 py-2 text-sm transition-colors",
                  isActive
                    ? "bg-elevated text-ink shadow-[inset_2px_0_0_0] shadow-primary"
                    : "text-muted hover:bg-elevated/60 hover:text-ink",
                )
              }
            >
              <item.icon className="h-4 w-4 shrink-0" aria-hidden />
              <span className="hidden flex-1 lg:inline">{item.label}</span>
              {item.pending ? (
                <span className="hidden text-[10px] text-warning/80 lg:inline" aria-label={`planned for phase ${item.pending.phase}`}>
                  P{item.pending.phase}
                </span>
              ) : null}
            </NavLink>
          ))}
        </nav>
        <div className="border-t border-line p-3 text-[10px] uppercase tracking-[0.14em] text-muted">
          <span className="hidden lg:inline">Tenant-isolated workspace</span>
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-30 flex h-16 items-center justify-between gap-4 border-b border-line bg-bg/70 px-6 backdrop-blur">
          <div className="min-w-0">
            <p className="text-[10px] uppercase tracking-[0.18em] text-muted">Organization</p>
            <p className="truncate text-sm font-medium">{me?.organization.name}</p>
          </div>
          <div className="flex items-center gap-3">
            {me ? (
              <div className="hidden text-right sm:block">
                <p className="text-sm">{me.user.full_name}</p>
                <Badge tone="evidence">{ROLE_LABELS[me.role]}</Badge>
              </div>
            ) : null}
            <button
              type="button"
              onClick={async () => {
                await logout();
                navigate("/login", { replace: true });
              }}
              className="flex h-9 items-center gap-2 rounded-lg border border-line px-3 text-xs text-muted hover:border-danger/40 hover:text-danger"
            >
              <LogOut className="h-4 w-4" aria-hidden />
              Sign out
            </button>
          </div>
        </header>
        <main id="main" className="mx-auto w-full max-w-[1400px] flex-1 px-6 py-8">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
