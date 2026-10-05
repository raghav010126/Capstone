import type { ReactNode } from "react"
import { cn } from "@/lib/utils"

export function Kpi({ label, value, hint, tone, icon }: { label: string; value: ReactNode; hint?: ReactNode; tone?: "good" | "warn" | "bad"; icon?: ReactNode }) {
  return (
    <div className="rounded-xl border bg-card p-4">
      <div className="flex items-center justify-between text-xs font-medium text-muted-foreground">
        {label}
        {icon}
      </div>
      <div className={cn("mt-1.5 text-2xl font-semibold tabular-nums tracking-tight", tone === "good" && "text-approve", tone === "warn" && "text-escalate", tone === "bad" && "text-reject")}>{value}</div>
      {hint && <div className="mt-0.5 text-xs text-muted-foreground">{hint}</div>}
    </div>
  )
}
