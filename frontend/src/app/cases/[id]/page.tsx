"use client"

import { useState } from "react"
import Link from "next/link"
import { useParams } from "next/navigation"
import { useQuery, useQueryClient } from "@tanstack/react-query"
import { ArrowLeft, Download, FileWarning, Gavel, Shuffle } from "lucide-react"
import { toast } from "sonner"
import { api, ApiError, download, type CaseDetail } from "@/lib/api"
import { useAuth } from "@/lib/auth"
import { useCaseEvents } from "@/hooks/use-case-events"
import { AppShell } from "@/components/app-shell"
import { PipelineGraph } from "@/components/pipeline-graph"
import { CaseStatusBadge, DecisionBadge } from "@/components/status"
import { DocumentViewer } from "@/components/case/document-viewer"
import { FieldTable } from "@/components/case/field-table"
import { AgentPanels, DocDecisionRow, Telemetry } from "@/components/case/agent-panels"
import { DecisionPanel } from "@/components/case/decision-panel"
import { OverrideDialog, ReclassifyDialog } from "@/components/case/review-dialogs"
import { Button, buttonVariants } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { cn } from "@/lib/utils"

export default function CasePage() {
  const { id } = useParams<{ id: string }>()
  const { can } = useAuth()
  const qc = useQueryClient()
  const [docId, setDocId] = useState<string | null>(null)
  const [field, setField] = useState<string | null>(null)
  const [override, setOverride] = useState(false)
  const [reclass, setReclass] = useState(false)
  const [run, setRun] = useState(0)

  const q = useQuery({
    queryKey: ["case", id],
    queryFn: () => api<CaseDetail>(`/cases/${id}`),
    refetchInterval: (query) => (["RECEIVED", "PROCESSING"].includes(query.state.data?.status ?? "") ? 1500 : false),
  })
  const detail = q.data
  const { events, state } = useCaseEvents(id, () => qc.invalidateQueries({ queryKey: ["case", id] }), run)
  const processing = detail?.status === "RECEIVED" || detail?.status === "PROCESSING"

  if (q.isError) {
    const status = q.error instanceof ApiError ? q.error.status : 0
    return (
      <AppShell title="Case">
        <div className="grid place-items-center gap-3 py-24 text-center">
          <FileWarning className="size-10 text-muted-foreground" />
          <p className="text-lg font-medium">{status === 404 ? "Case not found" : "Could not load this case"}</p>
          <Link href="/" className={buttonVariants({ variant: "outline" })}>
            <ArrowLeft /> Back to cases
          </Link>
        </div>
      </AppShell>
    )
  }
  if (!detail) {
    return (
      <AppShell title="Loading case…">
        <Skeleton className="h-28 w-full" />
        <Skeleton className="mt-4 h-[600px] w-full" />
      </AppShell>
    )
  }

  const doc = detail.documents.find((d) => d.doc_id === docId) ?? detail.documents[0]
  const canOverride = can("review:override") && ["IN_REVIEW", "DECIDED", "FINALIZED"].includes(detail.status)
  const hasPending = detail.overrides.some((o) => o.status === "PENDING_APPROVAL")

  return (
    <AppShell
      title={detail.id}
      subtitle={`${detail.n_documents} documents · submitted by ${detail.submitted_by}`}
      actions={
        <>
          <CaseStatusBadge display={detail.display_status} status={detail.status} />
          {can("report:download") && (
            <Button
              variant="outline"
              onClick={() => download(`/cases/${detail.id}/report.pdf`, `${detail.id}-report.pdf`).catch(() => toast.error("Could not download the report"))}
            >
              <Download /> Case report
            </Button>
          )}
          {canOverride && (
            <Button onClick={() => setOverride(true)} disabled={hasPending}>
              <Gavel /> {hasPending ? "Approval pending" : "Override decision"}
            </Button>
          )}
        </>
      }
    >
      <PipelineGraph events={events} totalDocs={detail.n_documents} finished={state === "done" || !processing} className="mb-5" />

      <div className="grid gap-5 xl:grid-cols-[minmax(0,7fr)_minmax(0,5fr)]">
        <section aria-label="Documents" className="space-y-3">
          <div className="flex flex-wrap gap-1.5" role="tablist">
            {detail.documents.map((d) => (
              <button
                key={d.doc_id}
                role="tab"
                aria-selected={d.doc_id === doc.doc_id}
                onClick={() => {
                  setDocId(d.doc_id)
                  setField(null)
                }}
                className={cn(
                  "flex items-center gap-2 rounded-lg border px-2.5 py-1.5 text-left text-xs transition-colors",
                  d.doc_id === doc.doc_id ? "border-primary bg-primary text-primary-foreground" : "bg-card hover:bg-muted",
                )}
              >
                <span className="font-medium">{(d.doc_type ?? "document").replace("_", " ").toLowerCase()}</span>
                {d.decision && <span className={cn("size-2 rounded-full", d.decision.decision === "APPROVE" ? "bg-approve" : d.decision.decision === "REJECT" ? "bg-reject" : "bg-escalate")} title={d.decision.decision} />}
              </button>
            ))}
          </div>
          <DocumentViewer key={doc.doc_id} caseId={detail.id} doc={doc} activeField={field} onSelectField={setField} />
          <div className="flex items-center justify-between">
            <h2 className="text-sm font-semibold">Extracted fields</h2>
            {can("review:reclassify") && (
              <Button variant="ghost" size="sm" onClick={() => setReclass(true)}>
                <Shuffle /> Reclassify
              </Button>
            )}
          </div>
          <FieldTable doc={doc} active={field} onSelect={setField} />
        </section>

        <section aria-label="Decision and agent outputs" className="space-y-4">
          <DecisionPanel detail={detail} />
          <div>
            <h2 className="mb-2 flex items-center gap-2 text-sm font-semibold">
              Per-document decisions
            </h2>
            <DocDecisionRow detail={detail} />
          </div>
          <div>
            <h2 className="mb-2 flex items-center gap-2 text-sm font-semibold">
              Agent outputs · <span className="font-mono text-xs font-normal text-muted-foreground">{doc.doc_id}</span>
              {doc.decision && <DecisionBadge decision={doc.decision.decision} />}
            </h2>
            <div className="space-y-2">
              <AgentPanels key={`${doc.doc_id}-${detail.status}`} doc={doc} detail={detail} />
              <Telemetry detail={detail} />
            </div>
          </div>
        </section>
      </div>

      {can("review:override") && <OverrideDialog detail={detail} open={override} onOpenChange={setOverride} />}
      {can("review:reclassify") && <ReclassifyDialog key={doc.doc_id} caseId={detail.id} docId={doc.doc_id} current={doc.doc_type} open={reclass} onOpenChange={setReclass} onStarted={() => setRun((r) => r + 1)} />}
    </AppShell>
  )
}
