import { cn } from "@/lib/utils"
import { CheckCircle2, CircleAlert, Loader2, XCircle, ShieldAlert, Clock } from "lucide-react"

const TONE = {
  APPROVE: "bg-approve-soft text-approve border-approve/25",
  REJECT: "bg-reject-soft text-reject border-reject/25",
  ESCALATE: "bg-escalate-soft text-escalate border-escalate/30",
  PROCESSING: "bg-info-soft text-info border-info/25",
  NEUTRAL: "bg-muted text-muted-foreground border-border",
} as const

export function DecisionBadge({ decision, size = "sm" }: { decision?: string | null; size?: "sm" | "lg" }) {
  const d = (decision ?? "").toUpperCase()
  const tone = d in TONE ? TONE[d as keyof typeof TONE] : TONE.NEUTRAL
  const Icon = d === "APPROVE" ? CheckCircle2 : d === "REJECT" ? XCircle : d === "ESCALATE" ? ShieldAlert : Clock
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full border font-medium",
        size === "lg" ? "px-3.5 py-1.5 text-base" : "px-2.5 py-0.5 text-xs",
        tone,
      )}
    >
      <Icon className={size === "lg" ? "size-5" : "size-3.5"} />
      {d ? d[0] + d.slice(1).toLowerCase() : "Pending"}
    </span>
  )
}

/** Case status as the brief words it: Processing / Approved / Rejected / Escalated (+ Failed). */
export function CaseStatusBadge({ display, status }: { display: string; status: string }) {
  const map: Record<string, string> = {
    Approved: TONE.APPROVE,
    Rejected: TONE.REJECT,
    Escalated: TONE.ESCALATE,
    Processing: TONE.PROCESSING,
    Failed: TONE.REJECT,
  }
  const processing = display === "Processing"
  return (
    <span className={cn("inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-xs font-medium", map[display] ?? TONE.NEUTRAL)}>
      {processing ? <Loader2 className="size-3.5 animate-spin" /> : display === "Failed" ? <CircleAlert className="size-3.5" /> : null}
      {display}
      {status === "FINALIZED" && <span className="text-[10px] opacity-70">· reviewed</span>}
    </span>
  )
}

export function RiskPill({ score }: { score: number }) {
  const level = score >= 0.6 ? "High" : score >= 0.3 ? "Medium" : "Low"
  const tone = score >= 0.6 ? TONE.REJECT : score >= 0.3 ? TONE.ESCALATE : TONE.APPROVE
  return (
    <span className={cn("inline-flex items-center rounded-full border px-2 py-0.5 text-xs font-medium tabular-nums", tone)}>
      {level} · {score.toFixed(2)}
    </span>
  )
}

export function ConfidenceMeter({ value, className }: { value: number | null | undefined; className?: string }) {
  const v = Math.max(0, Math.min(1, value ?? 0))
  const color = v >= 0.8 ? "bg-approve" : v >= 0.6 ? "bg-escalate" : "bg-reject"
  return (
    <div className={cn("flex items-center gap-2", className)}>
      <div className="h-1.5 w-20 overflow-hidden rounded-full bg-muted" role="meter" aria-valuenow={Math.round(v * 100)} aria-valuemin={0} aria-valuemax={100}>
        <div className={cn("h-full rounded-full", color)} style={{ width: `${v * 100}%` }} />
      </div>
      <span className="text-xs tabular-nums text-muted-foreground">{Math.round(v * 100)}%</span>
    </div>
  )
}
