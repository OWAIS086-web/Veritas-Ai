import { createBrowserRouter, type RouteObject } from "react-router-dom";

import { NAV_ITEMS } from "@/app/navigation";
import { PhasePending } from "@/components/PhasePending";
import { AuditLogsPage } from "@/features/audit/AuditLogsPage";
import { LoginPage } from "@/features/auth/LoginPage";
import { RegisterPage } from "@/features/auth/RegisterPage";
import { RequireAuth } from "@/features/auth/RequireAuth";
import { DocumentPage } from "@/features/documents/DocumentPage";
import { DocumentsPage } from "@/features/documents/DocumentsPage";
import { FindingDetailPage } from "@/features/findings/FindingDetailPage";
import { FindingsPage } from "@/features/findings/FindingsPage";
import { ForensicsPage } from "@/features/forensics/ForensicsPage";
import { GraphPage } from "@/features/graph/GraphPage";
import { CaseWorkspacePage } from "@/features/investigations/CaseWorkspacePage";
import { CreateInvestigationPage } from "@/features/investigations/CreateInvestigationPage";
import { InvestigationsPage } from "@/features/investigations/InvestigationsPage";
import { OverviewPage } from "@/features/overview/OverviewPage";
import { SettingsPage } from "@/features/settings/SettingsPage";
import { AppShell } from "@/layouts/AppShell";
import { NotFoundPage } from "@/pages/NotFoundPage";

const pendingRoutes: RouteObject[] = NAV_ITEMS.flatMap((n) =>
  n.pending
    ? [{
        path: n.path.slice(1),
        element: <PhasePending title={n.label} phase={n.pending.phase} summary={n.pending.summary} />,
      }]
    : [],
);

export const routes: RouteObject[] = [
  { path: "/login", element: <LoginPage /> },
  { path: "/register", element: <RegisterPage /> },
  {
    path: "/",
    element: (
      <RequireAuth>
        <AppShell />
      </RequireAuth>
    ),
    children: [
      { index: true, element: <OverviewPage /> },
      { path: "investigations", element: <InvestigationsPage /> },
      { path: "investigations/new", element: <CreateInvestigationPage /> },
      { path: "investigations/:caseId", element: <CaseWorkspacePage /> },
      { path: "documents", element: <DocumentsPage /> },
      { path: "documents/:documentId", element: <DocumentPage /> },
      { path: "graph", element: <GraphPage /> },
      { path: "forensics", element: <ForensicsPage /> },
      { path: "findings", element: <FindingsPage /> },
      { path: "findings/:findingId", element: <FindingDetailPage /> },
      { path: "audit", element: <AuditLogsPage /> },
      { path: "settings", element: <SettingsPage /> },
      ...pendingRoutes,
      { path: "*", element: <NotFoundPage /> },
    ],
  },
];

export const createRouter = () => createBrowserRouter(routes);
