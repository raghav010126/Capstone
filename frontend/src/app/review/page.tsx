"use client"

import Link from "next/link"
import { useRouter } from "next/navigation"
import { useQuery } from "@tanstack/react-query"
import { Check, CircleCheckBig, Clock, TriangleAlert, UserCheck, X } from "lucide-react"
import { api, money, when, type CaseSummary, type OverrideOut } from "@/lib/api"
import { useAuth } from "@/lib/auth"
import { AppShell } from "@/components/app-shell"
import { ConfidenceMeter, DecisionBadge, RiskPill } from "@/components/status"
import { useDecideOverride } from "@/components/case/review-dialogs"
import { Button, buttonVariants } from "@/components/ui/button"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { cn } from "@/lib/utils"

function sla(c: CaseSummary) {
  const ms = new Date(c.sla_due).getTime() - Date.now()
  const h = Math.abs(ms) / 3.6e6
  const text = h >= 48 ? `${Math.round(h / 24)}d` : h >= 1 ? `${Math.floor(h)}h ${Math.round((h % 1) * 60)}m` : `${Math.max(1, Math.round(h * 60))}m`
  return { late: ms < 0, text: ms < 0 ? `${text} overdue` : `${text} left` }
}

function Approval({ c }: { c: CaseSummary }) {
  const { user, can } = useAuth()
  const decide = useDecideOverride(c.id)
  const ovs = useQuery({ queryKey: ["overrides", c.id], queryFn: () => api<OverrideOut[]>(`/cases/${c.id}/overrides`), refetchInterval: 30000 })
  const o = ovs.data?.find((x) => x.status === "PENDING_APPROVAL")
  if (!o) return null
  const mine = o.requested_by === user?.username
  return (
    <li className="flex flex-wrap items-center gap-x-4 gap-y-2 rounded-xl border border-escalate/40 bg-escalate-soft p-3">
      <UserCheck className="size-5 text-escalate" />
      <div className="min-w-0 flex-1 text-sm">
        <Link href={`/cases/view?id=${c.id}`} className="font-mono font-medium hover:underline">
          {c.id}
        </Link>{" "}
        · {money(o.amount)}
        <div className="text-xs text-muted-foreground">
          {o.requested_by} proposes <b>{o.decision.toLowerCase()}</b> · {o.reason_code.replace(/_/g, " ").toLowerCase()}
          {o.note && ` · “${o.note}”`}
        </div>
      </div>
      {can("review:approve") && !mine ? (
        <div className="flex gap-2">
          <Button size="sm" disabled={decide.isPending} onClick={() => decide.mutate({ id: o.id, action: "approve" })}>
            <Check /> Approve
          </Button>
          <Button size="sm" variant="outline" disabled={decide.isPending} onClick={() => decide.mutate({ id: o.id, action: "reject" })}>
            <X /> Reject
          </Button>
        </div>
      ) : (
        <span className="text-xs text-muted-foreground">{mine ? "Needs a different senior reviewer" : "Senior reviewer approval"}</span>
      )}
    </li>
  )
}

export default function ReviewPage() {
  const router = useRouter()
  const { can } = useAuth()
  const q = useQuery({ queryKey: ["review-queue"], queryFn: () => api<CaseSummary[]>("/review/queue"), refetchInterval: 15000, enabled: can("review:queue") })
  const rows = q.data ?? []
  const waiting = rows.filter((c) => c.pending_override)

  return (
    <AppShell requires="review:queue" title="Review queue" subtitle="Escalated cases waiting for a human decision, most urgent first (SLA, then fraud risk, then age)">
      {waiting.length > 0 && (
        <section className="mb-6">
          <h2 className="mb-2 text-sm font-semibold">Waiting for a second approver</h2>
          <ul className="space-y-2">
            {waiting.map((c) => (
              <Approval key={c.id} c={c} />
            ))}
          </ul>
        </section>
      )}
      <div className="rounded-xl border">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Case</TableHead>
              <TableHead className="text-right">Amount</TableHead>
              <TableHead>Fraud risk</TableHead>
              <TableHead>Confidence</TableHead>
              <TableHead>SLA</TableHead>
              <TableHead>Received</TableHead>
              <TableHead />
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map((c) => {
              const s = sla(c)
              return (
                <TableRow key={c.id} className="cursor-pointer" onClick={() => router.push(`/cases/view?id=${c.id}`)}>
                  <TableCell>
                    <span className="font-mono text-sm font-medium">{c.id}</span>
                    {c.pending_override && <span className="ml-2 rounded bg-escalate-soft px-1.5 py-0.5 text-[10px] font-medium text-escalate">approval pending</span>}
                  </TableCell>
                  <TableCell className="text-right tabular-nums">{c.total_amount ? money(c.total_amount) : "–"}</TableCell>
                  <TableCell>
                    <RiskPill score={c.risk_score} />
                  </TableCell>
                  <TableCell>
                    <ConfidenceMeter value={c.confidence} />
                  </TableCell>
                  <TableCell>
                    <span className={cn("inline-flex items-center gap-1 text-xs", s.late ? "font-medium text-reject" : "text-muted-foreground")}>
                      {s.late ? <TriangleAlert className="size-3.5" /> : <Clock className="size-3.5" />}
                      {s.text}
                    </span>
                  </TableCell>
                  <TableCell className="whitespace-nowrap text-muted-foreground">{when(c.created_at)}</TableCell>
                  <TableCell className="text-right">
                    <Link href={`/cases/view?id=${c.id}`} onClick={(e) => e.stopPropagation()} className={buttonVariants({ size: "sm", variant: "outline" })}>
                      Review
                    </Link>
                  </TableCell>
                </TableRow>
              )
            })}
            {!q.isLoading && rows.length === 0 && (
              <TableRow>
                <TableCell colSpan={7} className="py-14 text-center">
                  <CircleCheckBig className="mx-auto mb-2 size-8 text-approve" />
                  <div className="font-medium">The queue is clear</div>
                  <div className="text-sm text-muted-foreground">Escalated cases will appear here as they arrive.</div>
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
      </div>
      <p className="mt-3 text-xs text-muted-foreground">
        <DecisionBadge decision="ESCALATE" /> cases need a person because of a fraud signal, low confidence, an unrecognised document or an unconfirmed coverage condition. The reasons are on each case.
      </p>
    </AppShell>
  )
}
