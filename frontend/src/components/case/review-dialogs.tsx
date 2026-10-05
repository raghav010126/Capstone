"use client"

import { useState } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Loader2, UsersRound } from "lucide-react"
import { toast } from "sonner"
import { api, ApiError, money, type CaseDetail, type OverrideOut } from "@/lib/api"
import { Button } from "@/components/ui/button"
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Label } from "@/components/ui/label"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Textarea } from "@/components/ui/textarea"

type Reasons = { reason_codes: Record<string, string>; four_eyes_amount: number }
const useReasons = (enabled: boolean) => useQuery({ queryKey: ["reasons"], queryFn: () => api<Reasons>("/review/reason-codes"), staleTime: Infinity, enabled })

const DECISIONS = [
  { value: "APPROVE", label: "Approve" },
  { value: "REJECT", label: "Reject" },
  { value: "ESCALATE", label: "Keep escalated" },
]
const DOC_TYPES = ["CLAIM_FORM", "ID_DOCUMENT", "DISCHARGE_SUMMARY", "PRESCRIPTION", "POLICY_AMENDMENT", "UNKNOWN"].map((v) => ({ value: v, label: v.replace("_", " ").toLowerCase().replace(/^./, (c) => c.toUpperCase()) }))

function useInvalidate(caseId: string) {
  const qc = useQueryClient()
  return () => {
    qc.invalidateQueries({ queryKey: ["case", caseId] })
    qc.invalidateQueries({ queryKey: ["cases"] })
    qc.invalidateQueries({ queryKey: ["review-queue"] })
    qc.invalidateQueries({ queryKey: ["ops-summary"] })
  }
}

function ReasonSelect({ value, onChange, reasons }: { value: string; onChange: (v: string) => void; reasons?: Reasons }) {
  const items = Object.entries(reasons?.reason_codes ?? {}).map(([value, label]) => ({ value, label }))
  return (
    <Select items={items} value={value} onValueChange={(v) => onChange(v as string)}>
      <SelectTrigger className="w-full" aria-label="Reason code">
        <SelectValue placeholder="Choose a reason" />
      </SelectTrigger>
      <SelectContent>
        {items.map((r) => (
          <SelectItem key={r.value} value={r.value}>
            {r.label}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  )
}

export function OverrideDialog({ detail, open, onOpenChange }: { detail: CaseDetail; open: boolean; onOpenChange: (o: boolean) => void }) {
  const reasons = useReasons(open)
  const invalidate = useInvalidate(detail.id)
  const [decision, setDecision] = useState("APPROVE")
  const [reason, setReason] = useState("")
  const [note, setNote] = useState("")
  const fourEyes = detail.total_amount > (reasons.data?.four_eyes_amount ?? 10000)
  const m = useMutation({
    mutationFn: () => api<OverrideOut>(`/cases/${detail.id}/override`, { method: "POST", json: { decision, reason_code: reason, note } }),
    onSuccess: (ov) => {
      toast.success(ov.status === "APPLIED" ? `Decision set to ${ov.decision.toLowerCase()}` : "Override submitted: waiting for a second approver")
      invalidate()
      onOpenChange(false)
      setNote("")
    },
    onError: (e) => toast.error(e instanceof ApiError ? e.message : "Override failed"),
  })
  const needsNote = reason === "OTHER"
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Override decision</DialogTitle>
          <DialogDescription>
            Automated decision: <b>{detail.ai_decision?.toLowerCase()}</b> · claimed amount {money(detail.total_amount)}
          </DialogDescription>
        </DialogHeader>
        {fourEyes && (
          <div className="flex gap-2 rounded-lg border border-escalate/30 bg-escalate-soft p-3 text-xs text-escalate">
            <UsersRound className="mt-0.5 size-4 shrink-0" />
            <span>
              Over {money(reasons.data?.four_eyes_amount ?? 10000)}: your override is only a request. A different senior reviewer must approve it before it takes effect.
            </span>
          </div>
        )}
        <div className="space-y-3">
          <div className="space-y-1.5">
            <Label>New decision</Label>
            <Select items={DECISIONS} value={decision} onValueChange={(v) => setDecision(v as string)}>
              <SelectTrigger className="w-full" aria-label="New decision">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {DECISIONS.map((d) => (
                  <SelectItem key={d.value} value={d.value}>
                    {d.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-1.5">
            <Label>Reason code (required)</Label>
            <ReasonSelect value={reason} onChange={setReason} reasons={reasons.data} />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="note">Note {needsNote ? "(required)" : "(optional)"}</Label>
            <Textarea id="note" value={note} onChange={(e) => setNote(e.target.value)} maxLength={1000} placeholder="What did you verify, and how?" />
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button disabled={!reason || (needsNote && note.trim().length < 10) || m.isPending} onClick={() => m.mutate()}>
            {m.isPending && <Loader2 className="animate-spin" />} {fourEyes ? "Request override" : "Apply override"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

export function ReclassifyDialog({ caseId, docId, current, open, onOpenChange, onStarted }: { caseId: string; docId: string; current: string | null; open: boolean; onOpenChange: (o: boolean) => void; onStarted?: () => void }) {
  const reasons = useReasons(open)
  const invalidate = useInvalidate(caseId)
  const [docType, setDocType] = useState(current ?? "UNKNOWN")
  const [reason, setReason] = useState("CLASSIFICATION_ERROR")
  const m = useMutation({
    mutationFn: () => api(`/cases/${caseId}/documents/${docId}/reclassify`, { method: "POST", json: { doc_type: docType, reason_code: reason, note: "" } }),
    onSuccess: () => {
      toast.success("Re-running the case with the corrected type")
      onStarted?.()
      invalidate()
      onOpenChange(false)
    },
    onError: (e) => toast.error(e instanceof ApiError ? e.message : "Reclassify failed"),
  })
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Reclassify document</DialogTitle>
          <DialogDescription>
            <span className="font-mono">{docId}</span> is currently {current?.replace("_", " ").toLowerCase() ?? "unclassified"}. The whole case is re-run with the type you set.
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-3">
          <div className="space-y-1.5">
            <Label>Correct type</Label>
            <Select items={DOC_TYPES} value={docType} onValueChange={(v) => setDocType(v as string)}>
              <SelectTrigger className="w-full" aria-label="Correct type">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {DOC_TYPES.map((d) => (
                  <SelectItem key={d.value} value={d.value}>
                    {d.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-1.5">
            <Label>Reason code</Label>
            <ReasonSelect value={reason} onChange={setReason} reasons={reasons.data} />
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button disabled={m.isPending} onClick={() => m.mutate()}>
            {m.isPending && <Loader2 className="animate-spin" />} Reclassify & re-run
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

/** Approve / reject a pending four-eyes override (senior reviewers and admins; never your own request). */
export function useDecideOverride(caseId: string) {
  const invalidate = useInvalidate(caseId)
  return useMutation({
    mutationFn: ({ id, action }: { id: number; action: "approve" | "reject" }) =>
      api<OverrideOut>(`/cases/${caseId}/overrides/${id}/${action}`, { method: "POST", json: action === "reject" ? { note: "" } : undefined }),
    onSuccess: (ov) => {
      toast.success(ov.status === "APPLIED" ? "Approved: the decision is final" : "Override rejected")
      invalidate()
    },
    onError: (e) => toast.error(e instanceof ApiError ? e.message : "Action failed"),
  })
}
