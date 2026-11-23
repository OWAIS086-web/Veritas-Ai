import {
  Bot,
  FileSearch,
  FileText,
  FolderSearch,
  LayoutDashboard,
  Microscope,
  Network,
  ScrollText,
  Settings,
  ShieldAlert,
  Files,
  type LucideIcon,
} from "lucide-react";

export interface NavItem {
  label: string;
  path: string;
  icon: LucideIcon;
  /** When set, the section isn't built yet and renders the PhasePending state. */
  pending?: { phase: number; summary: string };
}

/** The 11 sections, in the exact order defined in .kiro/steering/ui-design.md. */
export const NAV_ITEMS: NavItem[] = [
  { label: "Overview", path: "/", icon: LayoutDashboard },
  { label: "Investigations", path: "/investigations", icon: FolderSearch },
  { label: "Documents", path: "/documents", icon: Files },
  {
    label: "Evidence Explorer", path: "/evidence", icon: FileSearch,
    pending: { phase: 7, summary: "Open source documents at the cited page with highlighted evidence and side-by-side comparison." },
  },
  { label: "Intelligence Graph", path: "/graph", icon: Network },
  { label: "Forensics Lab", path: "/forensics", icon: Microscope },
  { label: "Findings", path: "/findings", icon: ShieldAlert },
  {
    label: "Reports", path: "/reports", icon: FileText,
    pending: { phase: 7, summary: "Generate cited investigation reports in PDF, DOCX, JSON and XLSX." },
  },
  {
    label: "AI Agents", path: "/agents", icon: Bot,
    pending: { phase: 6, summary: "Follow recorded agent workflow events of real investigation runs." },
  },
  { label: "Audit Logs", path: "/audit", icon: ScrollText },
  { label: "Settings", path: "/settings", icon: Settings },
];
