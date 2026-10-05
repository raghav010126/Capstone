"use client"

import { useState } from "react"
import Link from "next/link"
import { useQuery, useQueryClient } from "@tanstack/react-query"
import { Link2, Loader2, RefreshCw, ShieldCheck, ShieldX } from "lucide-react"
import { api, type AuditOut, type ChainStatus } from "@/lib/api"
import { useAuth } from "@/lib/auth"
import { AppShell } from "@/components/app-shell"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { cn } from "@/lib/utils"

const ACTIONS = ["all", "login", "login_failed", "case_created", "upload_rejected", "case_decided", "case_failed", "document_viewed", "override_requested", "override_approved", "override_rejected", "override_applied", "document_reclassified", "report_downloaded", "policy_uploaded", "policy_ingested"]
const TONE: Record<string, string> = {
  login_failed: "bg-reject-soft text-reject",
  upload_rejected: "bg-reject-soft text-reject",
  case_failed: "bg-reject-soft text-reject",
  override_requested: "bg-escalate-soft text-escalate",
  override_applied: "bg-approve-soft text-approve",
  override_approved: "bg-approve-soft text-approve",
  case_decided: "bg-info-soft text-info",
}

export default function AuditPage() {
  const qc = useQueryClient()
  const { can } = useAuth()
  const allowed = can("audit:read")
  const [caseId, setCaseId] = useState("")
  const [action, setAction] = useState("all")
  const [limit, setLimit] = useState(60)

  const chain = useQuery({ queryKey: ["audit-verify"], queryFn: () => api<ChainStatus>("/audit/verify"), enabled: allowed })
  const log = useQuery({
    queryKey: ["audit", caseId, action, limit],
    queryFn: () => {
      const q = new URLSearchParams({ limit: String(limit) })
      if (caseId.trim()) q.set("case_id", caseId.trim())
      if (action !== "all") q.set("action", action)
      return api<AuditOut[]>(`/audit?${q}`)
    },
    refetchInterval: 8000,
    enabled: allowed,
  })
  const c = chain.data

  return (
    <AppShell requires="audit:read" title="Audit log" subtitle="Every login, upload, document view, decision and override, chained by hash so any edit or deletion is detectable">
      <div className={cn("mb-5 flex flex-wrap items-center gap-4 rounded-xl border p-4", c ? (c.ok ? "border-approve/30 bg-approve-soft" : "border-reject/40 bg-reject-soft") : "bg-muted/40")}>
        {chain.isFetching && !c ? <Loader2 className="size-7 animate-spin text-muted-foreground" /> : c?.ok ? <ShieldCheck className="size-8 text-approve" /> : <ShieldX className="size-8 text-reject" />}
        <div className="min-w-0 flex-1">
          <div className={cn("text-base font-semibold", c?.ok ? "text-approve" : "text-reject")}>
            {!c ? "Verifying chain…" : c.ok ? "Chain verified" : `Chain broken at event #${c.broken_at}`}
          </div>
          <div className="text-sm text-muted-foreground">
            {c?.ok ? (
              <>
                {c.length.toLocaleString()} events, each hash linked to the one before. Head <span className="font-mono">{c.head?.slice(0, 16)}…</span>
              </>
            ) : (
              c?.reason
            )}
          </div>
        </div>
        <Button variant="outline" size="sm" onClick={() => qc.invalidateQueries({ queryKey: ["audit-verify"] })} disabled={chain.isFetching}>
          <RefreshCw className={chain.isFetching ? "animate-spin" : ""} /> Re-verify
        </Button>
      </div>

      <div className="mb-3 flex flex-wrap gap-2">
        <Input className="w-56" placeholder="Filter by case id (CASE-…)" value={caseId} onChange={(e) => setCaseId(e.target.value)} aria-label="Filter by case id" />
        <Select items={ACTIONS.map((a) => ({ value: a, label: a === "all" ? "All actions" : a.replace(/_/g, " ") }))} value={action} onValueChange={(v) => setAction(v as string)}>
          <SelectTrigger className="w-52" aria-label="Filter by action">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {ACTIONS.map((a) => (
              <SelectItem key={a} value={a}>
                {a === "all" ? "All actions" : a.replace(/_/g, " ")}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      <ol className="relative space-y-1 border-l pl-5">
        {log.data?.map((e) => (
          <li key={e.seq} className="relative rounded-lg px-3 py-2 hover:bg-muted/50">
            <span className="absolute top-3.5 -left-[26px] size-2.5 rounded-full border-2 border-background bg-border" />
            <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
              <span className="font-mono text-xs text-muted-foreground tabular-nums">#{e.seq}</span>
              <span className={cn("rounded-md px-2 py-0.5 text-xs font-medium", TONE[e.action] ?? "bg-muted text-foreground")}>{e.action.replace(/_/g, " ")}</span>
              <span className="text-sm">{e.actor}</span>
              {e.case_id && (
                <Link href={`/cases/${e.case_id}`} className="font-mono text-xs text-info hover:underline">
                  {e.case_id}
                </Link>
              )}
              <span className="ml-auto flex items-center gap-1 font-mono text-[11px] text-muted-foreground" title={`hash ${e.hash}\nprev ${e.prev_hash}`}>
                <Link2 className="size-3" /> {e.hash.slice(0, 10)}
              </span>
              <time className="w-40 text-right text-xs text-muted-foreground" dateTime={e.ts}>
                {new Date(e.ts).toLocaleString("en-US", { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit", second: "2-digit" })}
              </time>
            </div>
            {Object.keys(e.detail).length > 0 && <div className="mt-0.5 truncate text-xs text-muted-foreground">{Object.entries(e.detail).map(([k, v]) => `${k}: ${typeof v === "object" ? JSON.stringify(v) : v}`).join(" · ")}</div>}
          </li>
        ))}
        {log.data?.length === 0 && <li className="py-10 text-center text-sm text-muted-foreground">No events match.</li>}
      </ol>
      {log.data && log.data.length >= limit && (
        <div className="mt-4 text-center">
          <Button variant="outline" onClick={() => setLimit((l) => l + 60)}>
            Load older events
          </Button>
        </div>
      )}
    </AppShell>
  )
}
