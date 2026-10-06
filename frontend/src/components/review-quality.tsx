"use client"

import { useState, type ReactNode } from "react"
import { useQuery } from "@tanstack/react-query"
import { CheckCircle2, Clock, Gauge, ShieldAlert, Undo2, UsersRound, XCircle, type LucideIcon } from "lucide-react"
import { api, pct } from "@/lib/api"
import { cn } from "@/lib/utils"
import { ChartCard, HBarChart, TableView, TONE_BG, useTip, type Tone } from "@/components/charts"
import { Kpi } from "@/components/kpi"
import { Skeleton } from "@/components/ui/skeleton"

/* GET /ops/quality (backend: services/quality.py). Local types: the generated api-types predate this endpoint. */
type Decision = "APPROVE" | "REJECT" | "ESCALATE"
type QualityWindow = {
  since: string | null
  cases_decided: number
  escalation_rate: number | null
  human_reviewed: number
  awaiting_review: number
  human_resolved: number
  overrides_applied: number
  applied_override_rate: number | null
  agreement_rate: number | null
  agreement_rate_approve_reject: number | null
  reason_codes: { reason_code: string; label: string; requested: number; applied: number }[]
  rules: { rule_id: string; decision: string; cases: number; overridden: number; changed: number; change_rate: number | null }[]
  transitions: { ai_decision: string; final_decision: string; cases: number }[]
  confidence: { confirmed: number | null; overridden: number | null; n_confirmed: number; n_overridden: number }
  reclassifications: number
  reclassification_types: { from_type: string; to_type: string; count: number }[]
  four_eyes: { requested: number; approved: number; rejected: number; pending: number }
  median_hours_to_final: number | null
}
type QualityOut = { generated_at: string; window_days: number; all_time: QualityWindow; recent: QualityWindow }

const DECISIONS: Decision[] = ["APPROVE", "REJECT", "ESCALATE"]
const DEC: Record<Decision, { name: string; past: string; tone: Tone; Icon: LucideIcon; ink: string }> = {
  APPROVE: { name: "Approve", past: "approved", tone: "approve", Icon: CheckCircle2, ink: "text-approve" },
  REJECT: { name: "Reject", past: "rejected", tone: "reject", Icon: XCircle, ink: "text-reject" },
  ESCALATE: { name: "Escalate", past: "escalated", tone: "escalate", Icon: ShieldAlert, ink: "text-escalate" },
}
const isDecision = (d: string): d is Decision => d in DEC
const words = (s: string) => s.replace(/_/g, " ").toLowerCase().replace(/^./, (c) => c.toUpperCase())
const ruleName = (id: string) => id.replace(/^(R\d+)_/, "$1 ").replace(/_/g, " ")
const plural = (n: number, one: string, many = `${one}s`) => `${n} ${n === 1 ? one : many}`
const duration = (h: number | null) => (h == null ? "–" : h < 1 ? `${Math.max(1, Math.round(h * 60))} min` : h < 48 ? `${h.toFixed(1)} h` : `${(h / 24).toFixed(1)} days`)

/** Integer ticks for count axes (never fractional "0.5 overrides"). */
function countAxis(values: number[]) {
  const top = Math.max(1, ...values)
  const step = top <= 5 ? 1 : Math.ceil(top / 4)
  const max = Math.ceil(top / step) * step
  return { max, ticks: Array.from({ length: max / step + 1 }, (_, i) => i * step), format: (v: number) => `${Math.round(v)}` }
}

function Legend({ items }: { items: { tone: Tone; label: string; Icon: LucideIcon; ink: string }[] }) {
  return (
    <ul className="mb-3 flex flex-wrap gap-x-4 gap-y-1 text-xs" aria-label="Legend">
      {items.map(({ tone, label, Icon, ink }) => (
        <li key={label} className="flex items-center gap-1.5">
          <span className={cn("inline-block h-2.5 w-3.5 rounded-[2px]", TONE_BG[tone])} aria-hidden />
          <Icon className={cn("size-3.5", ink)} aria-hidden />
          {label}
        </li>
      ))}
    </ul>
  )
}

type Segment = { key: string; tone: Tone; value: number; title: string; note?: string }

/**
 * Stacked horizontal bars: one row per group, segments in a fixed order (colour follows the decision, never the rank),
 * separated by a 2px surface gap, square at the baseline with a 4px rounded tip. Rows share one scale (`max`), so
 * lengths compare across rows; the total sits at the tip and a text breakdown sits under each bar.
 */
function StackedBars({ rows, max, labelWidth = 120, unit = "cases" }: { rows: { label: string; icon?: ReactNode; segments: Segment[]; breakdown: string }[]; max: number; labelWidth?: number; unit?: string }) {
  const tip = useTip()
  return (
    <div>
      <ul className="space-y-2.5">
        {rows.map((r) => {
          const total = r.segments.reduce((a, s) => a + s.value, 0)
          const shown = r.segments.filter((s) => s.value > 0)
          return (
            <li key={r.label} className="flex items-start">
              <div className="flex h-5 shrink-0 items-center justify-end gap-1.5 pr-3 text-right text-xs" style={{ width: labelWidth }}>
                {r.icon}
                <span className="leading-tight">{r.label}</span>
              </div>
              <div className="min-w-0 flex-1">
                <div className="relative mr-14 flex h-5 items-center">
                  <div className="flex h-4 gap-[2px]" style={{ width: `${max ? (total / max) * 100 : 0}%` }}>
                    {shown.map((s, i) => (
                      <div
                        key={s.key}
                        tabIndex={0}
                        role="img"
                        aria-label={`${s.title}: ${plural(s.value, unit.replace(/s$/, ""), unit)}${s.note ? `, ${s.note}` : ""}`}
                        className={cn("h-full min-w-[3px] outline-none transition-opacity hover:opacity-80 focus-visible:ring-2 focus-visible:ring-ring/60", TONE_BG[s.tone], i === shown.length - 1 && "rounded-r-[4px]")}
                        style={{ flexGrow: s.value, flexBasis: 0 }}
                        onPointerEnter={(e) => tip.show(e.currentTarget, s.title, plural(s.value, unit.replace(/s$/, ""), unit), s.note)}
                        onPointerLeave={tip.hide}
                        onFocus={(e) => tip.show(e.currentTarget, s.title, plural(s.value, unit.replace(/s$/, ""), unit), s.note)}
                        onBlur={tip.hide}
                      />
                    ))}
                  </div>
                  <span className="ml-2 text-xs font-semibold tabular-nums">{total}</span>
                </div>
                <div className="mt-0.5 text-[11px] text-muted-foreground">{r.breakdown}</div>
              </div>
            </li>
          )
        })}
      </ul>
      {tip.node}
    </div>
  )
}

function Empty({ children }: { children: ReactNode }) {
  return <p className="py-8 text-center text-sm text-muted-foreground">{children}</p>
}

function Transitions({ w }: { w: QualityWindow }) {
  const get = (a: Decision, f: Decision) => w.transitions.find((t) => t.ai_decision === a && t.final_decision === f)?.cases ?? 0
  const rows = DECISIONS.map((a) => ({ a, total: DECISIONS.reduce((n, f) => n + get(a, f), 0) })).filter((r) => r.total > 0)
  if (!rows.length) return <Empty>No case has a human final decision yet{w.awaiting_review ? ` (${plural(w.awaiting_review, "case")} awaiting review)` : ""}.</Empty>
  const max = Math.max(...rows.map((r) => r.total))
  return (
    <div>
      <Legend items={DECISIONS.map((d) => ({ tone: DEC[d].tone, label: `Final: ${DEC[d].name.toLowerCase()}`, Icon: DEC[d].Icon, ink: DEC[d].ink }))} />
      <StackedBars
        max={max}
        rows={rows.map(({ a, total }) => {
          const { Icon, ink, name } = DEC[a]
          return {
            label: `AI: ${name.toLowerCase()}`,
            icon: <Icon className={cn("size-3.5", ink)} aria-hidden />,
            segments: DECISIONS.map((f) => ({
              key: f,
              tone: DEC[f].tone,
              value: get(a, f),
              title: `AI ${name.toLowerCase()} → final ${DEC[f].name.toLowerCase()}`,
              note: `${Math.round((get(a, f) / total) * 100)}% of these · ${a === f ? "kept by the reviewer" : "changed by the reviewer"}`,
            })),
            breakdown: DECISIONS.filter((f) => get(a, f) > 0)
              .map((f) => `${get(a, f)} ${DEC[f].past}${a === f ? " (kept)" : ""}`)
              .join(" · "),
          }
        })}
      />
      <TableView head={["AI decision → final decision", "Cases"]} rows={w.transitions.map((t) => [`${words(t.ai_decision)} → ${words(t.final_decision)}`, t.cases])} />
    </div>
  )
}

function FourEyes({ w }: { w: QualityWindow }) {
  const f = w.four_eyes
  if (!f.requested) return <Empty>No override above the four-eyes amount yet.</Empty>
  const items = [
    { key: "approved", tone: "approve" as Tone, value: f.approved, label: "Approved", Icon: CheckCircle2, ink: "text-approve" },
    { key: "rejected", tone: "reject" as Tone, value: f.rejected, label: "Rejected", Icon: XCircle, ink: "text-reject" },
    { key: "pending", tone: "escalate" as Tone, value: f.pending, label: "Awaiting a second reviewer", Icon: Clock, ink: "text-escalate" },
  ]
  return (
    <div>
      <Legend items={items} />
      <StackedBars
        max={f.requested}
        unit="requests"
        labelWidth={90}
        rows={[{ label: "Requests", segments: items.map((s) => ({ key: s.key, tone: s.tone, value: s.value, title: s.label })), breakdown: `${f.approved} approved · ${f.rejected} rejected · ${f.pending} pending` }]}
      />
      <TableView head={["Outcome", "Requests"]} rows={items.map((s) => [s.label, s.value])} />
    </div>
  )
}

export function ReviewQuality({ enabled = true, className }: { enabled?: boolean; className?: string }) {
  const q = useQuery({ queryKey: ["ops-quality"], queryFn: () => api<QualityOut>("/ops/quality"), enabled })
  const [win, setWin] = useState<"all_time" | "recent">("all_time")
  const w = q.data?.[win]
  const scope = win === "recent" && q.data ? ` in the last ${q.data.window_days} days` : ""

  return (
    <section aria-labelledby="review-quality" className={cn("space-y-4", className)}>
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 id="review-quality" className="flex items-center gap-2 text-sm font-semibold">
            <UsersRound className="size-4" /> Human review quality
          </h2>
          <p className="mt-0.5 text-xs text-muted-foreground">How reviewers&apos; final decisions compare with the AI&apos;s, from recorded overrides and the audit trail (live data, no model calls).</p>
        </div>
        {q.data && (
          <div role="group" aria-label="Time window" className="inline-flex rounded-lg bg-muted p-[3px] text-xs">
            {(["all_time", "recent"] as const).map((k) => (
              <button
                key={k}
                type="button"
                aria-pressed={win === k}
                onClick={() => setWin(k)}
                className={cn("rounded-md px-2.5 py-1 font-medium text-muted-foreground transition-colors hover:text-foreground", win === k && "bg-card text-foreground shadow-sm")}
              >
                {k === "all_time" ? "All time" : `Last ${q.data.window_days} days`}
              </button>
            ))}
          </div>
        )}
      </div>

      {q.isLoading && <Skeleton className="h-64 w-full" />}
      {q.isError && <p className="py-8 text-center text-sm text-muted-foreground">Review quality could not be loaded.</p>}
      {w && w.human_reviewed === 0 && w.reclassifications === 0 && (
        <div className="rounded-xl border border-dashed bg-card px-6 py-10 text-center">
          <UsersRound className="mx-auto size-6 text-muted-foreground" aria-hidden />
          <p className="mt-2 text-sm font-medium">No human reviews yet{scope}</p>
          <p className="mx-auto mt-1 max-w-md text-xs text-muted-foreground">
            {w.cases_decided ? `${plural(w.cases_decided, "case")} decided by the AI, ${pct(w.escalation_rate)} escalated. ` : ""}
            When a reviewer confirms or overrides a decision, agreement with the AI, override reasons and the rules people disagree with appear here.
          </p>
        </div>
      )}

      {w && (w.human_reviewed > 0 || w.reclassifications > 0) && (
        <>
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            <Kpi
              label="AI–human agreement"
              icon={<Gauge className="size-4" />}
              value={pct(w.agreement_rate)}
              hint={w.human_resolved ? `final decision = AI decision on ${plural(w.human_resolved, "human-decided case")} · ${pct(w.agreement_rate_approve_reject)} where the AI chose approve or reject` : "no human final decision yet"}
            />
            <Kpi label="Applied override rate" icon={<Undo2 className="size-4" />} value={pct(w.applied_override_rate)} hint={`${plural(w.overrides_applied, "override")} applied · ${plural(w.cases_decided, "case")} decided by the AI`} />
            <Kpi label="Escalated to a person" icon={<ShieldAlert className="size-4" />} value={pct(w.escalation_rate)} hint={`${plural(w.human_reviewed, "case")} reviewed by a person · ${w.awaiting_review} awaiting review`} />
            <Kpi label="Time to final decision (median)" icon={<Clock className="size-4" />} value={duration(w.median_hours_to_final)} hint="case received → override applied" />
          </div>

          <div className="grid gap-4 lg:grid-cols-2">
            <ChartCard title="AI decision → final decision" subtitle="Cases a reviewer decided: what the AI said (rows) and what the reviewer decided (segments). An escalation always ends in a human decision.">
              <Transitions w={w} />
            </ChartCard>
            <ChartCard title="Which rules humans disagree with" subtitle="Share of each decision rule's cases whose final human decision differs from the AI's. Escalation rules hand the case to a person, so a change there is expected.">
              {w.rules.length === 0 ? (
                <Empty>No decided cases{scope}.</Empty>
              ) : (
                <HBarChart
                  labelWidth={190}
                  bars={w.rules.map((r) => ({
                    label: `${ruleName(r.rule_id)} · ${isDecision(r.decision) ? DEC[r.decision].name : words(r.decision)}`,
                    value: r.change_rate ?? 0,
                    display: `${r.changed} of ${r.cases}`,
                    note: `${pct(r.change_rate)} changed · ${plural(r.overridden, "case")} with an applied override`,
                    tone: isDecision(r.decision) ? DEC[r.decision].tone : undefined,
                  }))}
                  format={(v) => `${Math.round(v * 100)}%`}
                  tableHead={["Rule · AI decision", "Changed by a human"]}
                />
              )}
            </ChartCard>
          </div>

          <div className="grid gap-4 lg:grid-cols-2">
            <ChartCard title="Why reviewers override" subtitle="Override requests by reason code, whatever their outcome">
              {w.reason_codes.length === 0 ? (
                <Empty>No override requests{scope}.</Empty>
              ) : (
                <HBarChart
                  labelWidth={190}
                  bars={w.reason_codes.map((r) => ({ label: words(r.reason_code), value: r.requested, display: `${r.requested}`, note: `${r.applied} applied · ${r.label}` }))}
                  {...countAxis(w.reason_codes.map((r) => r.requested))}
                  tableHead={["Reason", "Requests"]}
                />
              )}
            </ChartCard>
            <ChartCard title="AI confidence: kept vs changed" subtitle="Mean confidence the AI reported on cases a reviewer later decided. A clear gap means confidence is a useful triage signal.">
              {w.confidence.n_confirmed + w.confidence.n_overridden === 0 ? (
                <Empty>No case has a human final decision yet.</Empty>
              ) : (
                <HBarChart
                  labelWidth={170}
                  unit="cases"
                  bars={[
                    { label: "Kept by the reviewer", value: w.confidence.confirmed ?? 0, n: w.confidence.n_confirmed, display: pct(w.confidence.confirmed) },
                    { label: "Changed by the reviewer", value: w.confidence.overridden ?? 0, n: w.confidence.n_overridden, display: pct(w.confidence.overridden) },
                  ]}
                  format={(v) => `${Math.round(v * 100)}%`}
                  tableHead={["Cases", "Mean AI confidence"]}
                />
              )}
            </ChartCard>
          </div>

          <div className="grid gap-4 lg:grid-cols-2">
            <ChartCard title="Four-eyes approvals" subtitle="Overrides above the four-eyes amount need a second, senior reviewer; nobody approves their own request">
              <FourEyes w={w} />
            </ChartCard>
            <ChartCard title="Documents reclassified by reviewers" subtitle={`From the audit trail: the type the classifier gave → the type a reviewer set (${plural(w.reclassifications, "reclassification")})`}>
              {w.reclassification_types.length === 0 ? (
                <Empty>No documents reclassified{scope}.</Empty>
              ) : (
                <HBarChart
                  labelWidth={220}
                  bars={w.reclassification_types.map((r) => ({ label: `${words(r.from_type)} → ${words(r.to_type)}`, value: r.count, display: `${r.count}` }))}
                  {...countAxis(w.reclassification_types.map((r) => r.count))}
                  tableHead={["From → to", "Documents"]}
                />
              )}
            </ChartCard>
          </div>
        </>
      )}
    </section>
  )
}
