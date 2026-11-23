import { Link } from "react-router-dom";

export function NotFoundPage() {
  return (
    <div className="panel flex flex-col items-center gap-3 py-16 text-center">
      <p className="font-mono text-3xl text-muted">404</p>
      <p className="font-medium">This page doesn&apos;t exist.</p>
      <Link to="/" className="text-sm text-evidence hover:underline">Back to Overview</Link>
    </div>
  );
}
