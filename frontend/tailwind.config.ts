import type { Config } from "tailwindcss";

import { colors } from "./src/styles/tokens";

export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        bg: colors.bg,
        surface: colors.surface,
        elevated: colors.elevated,
        primary: colors.primary,
        evidence: colors.evidence,
        warning: colors.warning,
        danger: colors.danger,
        ink: colors.ink,
        muted: colors.muted,
        line: colors.line,
      },
      fontFamily: {
        sans: ["'Inter Variable'", "Inter", "system-ui", "sans-serif"],
        mono: ["'JetBrains Mono'", "ui-monospace", "monospace"],
      },
      boxShadow: {
        glow: "0 0 0 1px rgba(16,185,129,0.25), 0 8px 30px -12px rgba(16,185,129,0.35)",
        evidence: "0 0 0 1px rgba(56,189,248,0.3), 0 8px 30px -12px rgba(56,189,248,0.35)",
      },
    },
  },
  plugins: [],
} satisfies Config;
