import { Construction } from "lucide-react";
import { Link } from "react-router-dom";

import { PageHeader } from "@/components/PageHeader";

interface PhasePendingProps {
  title: string;
  phase: number;
  summary: string;
}

/**
 * Explicit "not built yet" state. Shows no sample data, so the UI never implies a
 * capability that the backend doesn't have yet.
 */
export function PhasePending({ title, phase, summary }: PhasePendingProps) {
  return (
    <div>
      <PageHeader title={title} />
      <div className="panel grid-lines flex flex-col items-center gap-4 px-6 py-16 text-center">
        <span className="rounded-full border border-warning/30 bg-warning/10 p-3">
          <Construction className="h-6 w-6 text-warning" aria-hidden />
        </span>
        <div>
          <p className="text-base font-semibold">Available in a later phase</p>
          <p className="mt-1 text-xs uppercase tracking-[0.14em] text-warning">Planned for phase {phase}</p>
        </div>
        <p className="max-w-lg text-sm text-muted">{summary}</p>
        <Link to="/" className="text-sm text-evidence underline-offset-4 hover:underline">
          Back to Overview
        </Link>
      </div>
    </div>
  );
}
