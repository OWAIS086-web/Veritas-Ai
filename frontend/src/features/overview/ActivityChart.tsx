import { Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import { colors } from "@/styles/tokens";
import type { OverviewStats } from "@/types/api";

const dayLabel = (iso: string) =>
  new Date(`${iso}T00:00:00Z`).toLocaleDateString(undefined, { month: "short", day: "numeric", timeZone: "UTC" });

export function ActivityChart({ data }: { data: OverviewStats["activity_14d"] }) {
  const total = data.reduce((sum, d) => sum + d.count, 0);
  return (
    <figure aria-label={`Audited activity over the last 14 days: ${total} events`}>
      <div className="h-52">
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: -20 }}>
            <defs>
              <linearGradient id="activityFill" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor={colors.primary} stopOpacity={0.35} />
                <stop offset="100%" stopColor={colors.primary} stopOpacity={0} />
              </linearGradient>
            </defs>
            <CartesianGrid stroke={colors.line} vertical={false} />
            <XAxis dataKey="day" tickFormatter={dayLabel} stroke={colors.muted} fontSize={11}
                   tickLine={false} axisLine={false} interval="preserveStartEnd" />
            <YAxis allowDecimals={false} stroke={colors.muted} fontSize={11} tickLine={false}
                   axisLine={false} />
            <Tooltip
              contentStyle={{ background: colors.elevated, border: `1px solid ${colors.line}`,
                              borderRadius: 8, color: colors.ink, fontSize: 12 }}
              labelFormatter={(v) => dayLabel(String(v))}
              formatter={(v) => [v, "events"]}
            />
            <Area type="monotone" dataKey="count" stroke={colors.primary} strokeWidth={2}
                  fill="url(#activityFill)" />
          </AreaChart>
        </ResponsiveContainer>
      </div>
      <figcaption className="sr-only">
        {data.map((d) => `${d.day}: ${d.count}`).join(", ")}
      </figcaption>
    </figure>
  );
}
