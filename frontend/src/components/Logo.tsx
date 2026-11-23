export function Logo({ compact = false }: { compact?: boolean }) {
  return (
    <div className="flex items-center gap-2.5">
      <svg viewBox="0 0 32 32" className="h-8 w-8" aria-hidden>
        <rect width="32" height="32" rx="8" className="fill-elevated" />
        <path d="M7 9l9 15 9-15" fill="none" strokeWidth="3" strokeLinecap="round"
              strokeLinejoin="round" className="stroke-primary" />
        <circle cx="16" cy="12" r="2.5" className="fill-evidence" />
      </svg>
      {compact ? null : (
        <div className="leading-tight">
          <p className="text-sm font-semibold tracking-[0.2em]">VERITAS</p>
          <p className="text-[10px] uppercase tracking-[0.18em] text-muted">Truth Intelligence</p>
        </div>
      )}
    </div>
  );
}
