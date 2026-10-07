"use client"

import { Check, Hourglass, UserCheck, X } from "lucide-react"
import { money, when, type CaseDetail } from "@/lib/api"
import { useAuth } from "@/lib/auth"
import { ConfidenceMeter, DecisionBadge, RiskPill } from "@/components/status"
import { Button } from "@/components/ui/button"
import { useDecideOverride } from "./review-dialogs"

export function DecisionPanel({ detail }: { detail: CaseDetail }) {
  const { user, can } = useAuth()
  const decide = useDecideOverride(detail.id)
  const final = detail.final_decision
  const overridden = final && detail.ai_decision && final !== detail.ai_decision
  const pending = detail.overrides.filter((o) => o.status === "PENDING_APPROVAL")
  const processing = detail.status === "RECEIVED" || detail.status === "PROCESSING"

  return (
    <div className="space-y-4 rounded-xl border bg-card p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="mb-1.5 text-xs font-medium text-muted-foreground">{final ? "Final decision" : "Automated decision"}</div>
          {processing ? <DecisionBadge decision={null} size="lg" /> : <DecisionBadge decision={final ?? detail.ai_decision} size="lg" />}
          {overridden && (
            <div className="mt-1.5 flex items-center gap-1.5 text-xs text-muted-foreground">
              Automated system said <DecisionBadge decision={detail.ai_decision} /> and a reviewer changed it
            </div>
          )}
          {detail.status === "IN_REVIEW" && !pending.length && (
            <div className="mt-1.5 flex items-center gap-1.5 text-xs text-escalate">
              <Hourglass className="size-3.5" /> Waiting for a human reviewer
            </div>
          )}
        </div>
        <div className="space-y-1.5 text-right">
          <div className="text-xs text-muted-foreground">Confidence</div>
          <ConfidenceMeter value={detail.confidence} className="justify-end" />
          <div className="pt-1 text-xs text-muted-foreground">Fraud risk</div>
          <RiskPill score={detail.risk_score} />
        </div>
      </div>

      {detail.error && <p role="alert" className="rounded-lg border border-reject/30 bg-reject-soft p-2.5 text-sm text-reject">{detail.error}</p>}

      {detail.decision && (
        <div>
          <div className="mb-1 text-xs font-medium text-muted-foreground">Justification</div>
          <p className="text-sm leading-relaxed">{detail.decision.justification}</p>
          <p className="mt-1.5 text-[11px] text-muted-foreground">The rule engine makes the decision. This explanation may use a model or a rule-based fallback.</p>
        </div>
      )}

      {pending.map((o) => {
        const mine = o.requested_by === user?.username
        return (
          <div key={o.id} className="rounded-lg border border-escalate/40 bg-escalate-soft p-3">
            <div className="flex items-center gap-2 text-sm font-medium text-escalate">
              <UserCheck className="size-4" /> Four-eyes approval needed · {money(o.amount)}
            </div>
            <p className="mt-1 text-sm">
              {o.requested_by} proposes <b>{o.decision.toLowerCase()}</b> ({o.reason_code.replace(/_/g, " ").toLowerCase()}).{o.note && <span className="text-muted-foreground"> “{o.note}”</span>}
            </p>
            {can("review:approve") && !mine ? (
              <div className="mt-2 flex gap-2">
                <Button size="sm" disabled={decide.isPending} onClick={() => decide.mutate({ id: o.id, action: "approve" })}>
                  <Check /> Approve
                </Button>
                <Button size="sm" variant="outline" disabled={decide.isPending} onClick={() => decide.mutate({ id: o.id, action: "reject" })}>
                  <X /> Reject
                </Button>
              </div>
            ) : (
              <p className="mt-1.5 text-xs text-muted-foreground">{mine ? "You requested this, so a different senior reviewer has to approve it." : "A senior reviewer must approve it."}</p>
            )}
          </div>
        )
      })}

      {detail.overrides.filter((o) => o.status !== "PENDING_APPROVAL").length > 0 && (
        <div>
          <div className="mb-1 text-xs font-medium text-muted-foreground">Reviewer actions</div>
          <ul className="space-y-1 text-sm">
            {detail.overrides
              .filter((o) => o.status !== "PENDING_APPROVAL")
              .map((o) => (
                <li key={o.id} className="flex flex-wrap items-center gap-x-2 text-xs">
                  <DecisionBadge decision={o.decision} />
                  <span>
                    by {o.requested_by}
                    {o.resolved_by && o.resolved_by !== o.requested_by && ` · approved by ${o.resolved_by}`}
                  </span>
                  <span className="text-muted-foreground">
                    {o.reason_code.replace(/_/g, " ").toLowerCase()} · {o.status.toLowerCase()} · {when(o.created_at)}
                  </span>
                </li>
              ))}
          </ul>
        </div>
      )}
    </div>
  )
}
