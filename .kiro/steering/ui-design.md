---
inclusion: fileMatch
fileMatchPattern: ["frontend/src/**"]
---

# UI design system

VERITAS should look like a professional forensic intelligence workspace, not a generic admin template. The screens are dense with information but not cluttered, and use restrained glow effects.

## Tokens (defined once in `tailwind.config.ts` and `src/index.css`)
| Token | Hex | Use |
|---|---|---|
| `bg` | #090D16 | App background (dark graphite) |
| `surface` | #111827 | Cards and panels (deep navy) |
| `elevated` | #172033 | Popovers, active rows |
| `primary` | #10B981 | Primary actions, success (emerald) |
| `evidence` | #38BDF8 | Evidence highlights, links (cyan) |
| `warning` | #F59E0B | Warnings, medium severity |
| `danger` | #EF4444 | High or critical severity, destructive actions |
| `ink` | #F8FAFC | Primary text |
| `muted` | #94A3B8 | Secondary text |
| `line` | rgba(148,163,184,0.14) | Soft borders |

Typography: Inter for UI text, JetBrains Mono for ids, hashes and amounts. Use tabular numbers for figures.

## Navigation (exact order)
Overview, Investigations, Documents, Evidence Explorer, Intelligence Graph, Forensics Lab, Findings, Reports, AI Agents, Audit Logs, Settings.

Sections whose backend isn't built yet render `<PhasePending phase="N" />`, an explicit "Available in a later phase" state. Never render fake data.

## UX states
- Every query view handles loading (skeleton), empty (guidance plus a real action), error (problem detail plus a retry) and success.
- Mutations show toasts. Destructive actions use a confirmation dialog.
- Keyboard: every control is reachable with Tab. Dialogs trap focus. Focus rings are visible (`ring-evidence`).
- Contrast meets WCAG AA. Severity is never shown by color alone; always add a label or icon.
- Layouts work from 1280px wide down to tablet widths.
