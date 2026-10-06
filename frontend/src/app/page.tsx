"use client"

import { useState } from "react"
import Link from "next/link"
import { useRouter } from "next/navigation"
import { useQuery } from "@tanstack/react-query"
import { Clock, FilePlus2, Gauge, Inbox, PiggyBank, Zap } from "lucide-react"
import { api, money, pct, when, type CaseSummary } from "@/lib/api"
import { useAuth } from "@/lib/auth"
import { AppShell } from "@/components/app-shell"
import { CaseStatusBadge, ConfidenceMeter, DecisionBadge, RiskPill } from "@/components/status"
import { Kpi } from "@/components/kpi"
import { buttonVariants } from "@/components/ui/button"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Skeleton } from "@/components/ui/skeleton"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"

type Summary = {
  cases: number
  decided: number
  stp_rate: number | null
  avg_processing_seconds: number | null
  baseline_days_per_claim: number
  avg_cost_usd_per_case: number
  open_reviews: number
  llm_spend_today_usd: number
  business_impact: { projected_annual_savings_usd: number }
}

const STATUS = [
  { value: "all", label: "All statuses" },
  { value: "PROCESSING", label: "Processing" },
  { value: "DECIDED", label: "Decided" },
  { value: "IN_REVIEW", label: "In review" },
  { value: "FINALIZED", label: "Reviewed" },
  { value: "FAILED", label: "Failed" },
]
const DECISION = [
  { value: "all", label: "Any decision" },
  { value: "APPROVE", label: "Approved" },
  { value: "REJECT", label: "Rejected" },
  { value: "ESCALATE", label: "Escalated" },
]

export default function Dashboard() {
  const { can } = useAuth()
  const router = useRouter()
  const [status, setStatus] = useState("all")
  const [decision, setDecision] = useState("all")

  const cases = useQuery({
    queryKey: ["cases", status, decision],
    queryFn: () => {
      const q = new URLSearchParams({ limit: "100" })
      if (status !== "all") q.set("status", status)
      if (decision !== "all") q.set("decision", decision)
      return api<CaseSummary[]>(`/cases?${q}`)
    },
    refetchInterval: (query) => (query.state.data?.some((c) => c.display_status === "Processing") ? 5000 : 30000),
  })
  const summary = useQuery({
    queryKey: ["ops-summary"],
    queryFn: () => api<Summary>("/ops/summary"),
    enabled: can("ops:read"),
    refetchInterval: 60000,
  })
  const s = summary.data

  return (
    <AppShell
      title="Cases"
      subtitle="Every document submission, its automated decision and where it stands"
      actions={
        can("case:create") && (
          <Link href="/cases/new" className={buttonVariants()}>
            <FilePlus2 /> New case
          </Link>
        )
      }
    >
      {can("ops:read") && (
        <div className="mb-6 grid grid-cols-2 gap-3 lg:grid-cols-5">
          <Kpi label="Straight-through rate" icon={<Zap className="size-4" />} value={summary.isLoading ? "…" : pct(s?.stp_rate)} hint="decided without a human" />
          <Kpi
            label="Time to decision"
            icon={<Clock className="size-4" />}
            value={s?.avg_processing_seconds != null ? `${s.avg_processing_seconds}s` : "–"}
            hint={`vs ${s?.baseline_days_per_claim ?? 4.2} days manually`}
            tone="good"
          />
          <Kpi label="Cost per case" icon={<Gauge className="size-4" />} value={s ? money(s.avg_cost_usd_per_case) : "–"} hint="model spend, measured" />
          <Kpi label="Open reviews" icon={<Inbox className="size-4" />} value={s?.open_reviews ?? "–"} hint={`${s?.cases ?? 0} cases total`} tone={s && s.open_reviews > 0 ? "warn" : undefined} />
          <Kpi label="Projected savings / yr" icon={<PiggyBank className="size-4" />} value={s ? money(s.business_impact.projected_annual_savings_usd).replace(/\.00$/, "") : "–"} hint="vs $18.4M baseline" tone="good" />
        </div>
      )}

      <div className="mb-3 flex flex-wrap items-center gap-2">
        <Select items={STATUS} value={status} onValueChange={(v) => setStatus(v as string)}>
          <SelectTrigger className="w-40" aria-label="Filter by status">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {STATUS.map((o) => (
              <SelectItem key={o.value} value={o.value}>
                {o.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Select items={DECISION} value={decision} onValueChange={(v) => setDecision(v as string)}>
          <SelectTrigger className="w-40" aria-label="Filter by decision">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {DECISION.map((o) => (
              <SelectItem key={o.value} value={o.value}>
                {o.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <span className="ml-auto text-xs text-muted-foreground">{cases.data ? `${cases.data.length} cases` : ""}</span>
      </div>

      <div className="rounded-xl border">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Case</TableHead>
              <TableHead>Status</TableHead>
              <TableHead>Automated decision</TableHead>
              <TableHead>Confidence</TableHead>
              <TableHead className="text-right">Amount</TableHead>
              <TableHead>Fraud risk</TableHead>
              <TableHead className="text-right">Docs</TableHead>
              <TableHead>Received</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {cases.isLoading &&
              Array.from({ length: 5 }).map((_, i) => (
                <TableRow key={i}>
                  <TableCell colSpan={8}>
                    <Skeleton className="h-5 w-full" />
                  </TableCell>
                </TableRow>
              ))}
            {cases.data?.map((c) => (
              <TableRow key={c.id} className="cursor-pointer" onClick={() => router.push(`/cases/view?id=${c.id}`)}>
                <TableCell>
                  <Link href={`/cases/view?id=${c.id}`} className="font-mono text-sm font-medium hover:underline" onClick={(e) => e.stopPropagation()}>
                    {c.id}
                  </Link>
                  {c.pending_override && <span className="ml-2 rounded bg-escalate-soft px-1.5 py-0.5 text-[10px] font-medium text-escalate">approval pending</span>}
                </TableCell>
                <TableCell>
                  <CaseStatusBadge display={c.display_status} status={c.status} />
                </TableCell>
                <TableCell>{c.ai_decision ? <DecisionBadge decision={c.ai_decision} /> : <span className="text-muted-foreground">–</span>}</TableCell>
                <TableCell>{c.confidence != null ? <ConfidenceMeter value={c.confidence} /> : "–"}</TableCell>
                <TableCell className="text-right tabular-nums">{c.total_amount ? money(c.total_amount) : "–"}</TableCell>
                <TableCell>{c.ai_decision ? <RiskPill score={c.risk_score} /> : "–"}</TableCell>
                <TableCell className="text-right tabular-nums">{c.n_documents}</TableCell>
                <TableCell className="whitespace-nowrap text-muted-foreground">{when(c.created_at)}</TableCell>
              </TableRow>
            ))}
            {cases.data?.length === 0 && (
              <TableRow>
                <TableCell colSpan={8} className="py-12 text-center text-muted-foreground">
                  No cases yet. {can("case:create") ? "Create one to see the pipeline run." : ""}
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
      </div>
    </AppShell>
  )
}
