/** VERITAS design tokens: the single source of color values (see .kiro/steering/ui-design.md). */
export const colors = {
  bg: "#090D16",
  surface: "#111827",
  elevated: "#172033",
  primary: "#10B981",
  evidence: "#38BDF8",
  warning: "#F59E0B",
  danger: "#EF4444",
  ink: "#F8FAFC",
  muted: "#94A3B8",
  line: "rgba(148, 163, 184, 0.14)",
} as const;

export type ColorToken = keyof typeof colors;
