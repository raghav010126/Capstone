"use client"

import { useRef, useState } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { CheckCircle2, CircleAlert, FileText, FileUp, Loader2, Table2 } from "lucide-react"
import { toast } from "sonner"
import { api, ApiError, when, type PolicyOut } from "@/lib/api"
import { useAuth } from "@/lib/auth"
import { AppShell } from "@/components/app-shell"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { cn } from "@/lib/utils"

type Range = { start: string; end: string; category: string; basis: string; kind: string; page: number | null }

const KIND: Record<string, { label: string; cls: string; hint: string }> = {
  exclusion: { label: "Excluded", cls: "bg-reject-soft text-reject", hint: "Claims with codes in this range are denied" },
  prior_auth: { label: "Prior auth", cls: "bg-escalate-soft text-escalate", hint: "Allowed, but needs prior authorisation: routed to a person" },
  copay_rule: { label: "Copay rule", cls: "bg-info-soft text-info", hint: "A cost-sharing note, not an exclusion" },
}

function StatusPill({ p }: { p: PolicyOut }) {
  if (p.status === "READY") return <span className="inline-flex items-center gap-1 text-xs font-medium text-approve"><CheckCircle2 className="size-3.5" /> Ready</span>
  if (p.status === "FAILED") return <span className="inline-flex items-center gap-1 text-xs font-medium text-reject" title={p.error ?? ""}><CircleAlert className="size-3.5" /> Failed</span>
  return <span className="inline-flex items-center gap-1 text-xs font-medium text-info"><Loader2 className="size-3.5 animate-spin" /> Ingesting with Docling…</span>
}

export default function PoliciesPage() {
  const { can } = useAuth()
  const qc = useQueryClient()
  const file = useRef<HTMLInputElement>(null)
  const [plan, setPlan] = useState("")
  const [chosen, setChosen] = useState<File | null>(null)
  const [open, setOpen] = useState<PolicyOut | null>(null)

  const list = useQuery({
    queryKey: ["policies"],
    queryFn: () => api<PolicyOut[]>("/policies"),
    refetchInterval: (q) => (q.state.data?.some((p) => p.status === "INGESTING") ? 1500 : false),
    enabled: can("policy:read"),
  })
  const ranges = useQuery({ queryKey: ["ranges", open?.id], queryFn: () => api<{ plan: string; ranges: Range[] }>(`/policies/${open!.id}/ranges`), enabled: !!open })

  const upload = useMutation({
    mutationFn: () => {
      const fd = new FormData()
      fd.append("plan", plan.trim().toLowerCase())
      fd.append("file", chosen!)
      return api<PolicyOut>("/policies", { method: "POST", body: fd })
    },
    onSuccess: () => {
      toast.success("Policy uploaded: ingestion started")
      setChosen(null)
      setPlan("")
      if (file.current) file.current.value = ""
      qc.invalidateQueries({ queryKey: ["policies"] })
    },
    onError: (e) => toast.error(e instanceof ApiError ? e.message : "Upload failed"),
  })
  const validPlan = /^[a-z][a-z0-9_]{1,23}$/.test(plan.trim().toLowerCase())

  return (
    <AppShell requires="policy:read" title="Policies" subtitle="Coverage rules the policy agent applies. Upload a new PDF and its exclusion table is parsed into rules automatically">
      {can("policy:upload") && (
        <Card className="mb-6">
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base">
              <FileUp className="size-4" /> Upload a policy
            </CardTitle>
            <CardDescription>The PDF is read with Docling, split by section, and its “Excluded CPT Code Ranges” table becomes exact-match rules. It replaces the plan’s current policy for new claims.</CardDescription>
          </CardHeader>
          <CardContent className="flex flex-wrap items-end gap-3">
            <div className="space-y-1.5">
              <Label htmlFor="plan">Plan name</Label>
              <Input id="plan" className="w-40" placeholder="e.g. gold" value={plan} onChange={(e) => setPlan(e.target.value)} />
            </div>
            <div className="space-y-1.5">
              <Label>PDF</Label>
              <div className="flex items-center gap-2">
                <Button variant="outline" onClick={() => file.current?.click()}>
                  <FileText /> {chosen ? chosen.name : "Choose PDF"}
                </Button>
                <input ref={file} type="file" accept="application/pdf,.pdf" className="hidden" onChange={(e) => setChosen(e.target.files?.[0] ?? null)} />
              </div>
            </div>
            <Button disabled={!chosen || !validPlan || upload.isPending} onClick={() => upload.mutate()}>
              {upload.isPending && <Loader2 className="animate-spin" />} Upload & ingest
            </Button>
          </CardContent>
        </Card>
      )}

      <div className="grid gap-3 md:grid-cols-2">
        {list.data?.map((p) => (
          <Card key={p.id}>
            <CardHeader>
              <CardTitle className="flex items-center justify-between text-base">
                <span className="capitalize">{p.plan} plan</span>
                <StatusPill p={p} />
              </CardTitle>
              <CardDescription className="font-mono text-xs">{p.filename}</CardDescription>
            </CardHeader>
            <CardContent className="space-y-3">
              <dl className="grid grid-cols-3 gap-2 text-sm">
                <div>
                  <dt className="text-xs text-muted-foreground">Sections</dt>
                  <dd className="font-semibold tabular-nums">{p.chunk_count || "–"}</dd>
                </div>
                <div>
                  <dt className="text-xs text-muted-foreground">Exclusion rows</dt>
                  <dd className="font-semibold tabular-nums">{p.exclusion_rows || "–"}</dd>
                </div>
                <div>
                  <dt className="text-xs text-muted-foreground">Product</dt>
                  <dd className="truncate font-mono text-xs">{p.product_code ?? "–"}</dd>
                </div>
              </dl>
              {p.error && <p className="text-xs text-reject">{p.error}</p>}
              <div className="flex items-center justify-between text-xs text-muted-foreground">
                <span>{p.uploaded_by === "bundled" ? "Bundled with the dataset" : `Uploaded by ${p.uploaded_by} · ${when(p.created_at)}`}</span>
                <Button size="sm" variant="outline" disabled={p.status !== "READY"} onClick={() => setOpen(p)}>
                  <Table2 /> Exclusion table
                </Button>
              </div>
            </CardContent>
          </Card>
        ))}
      </div>

      <Dialog open={!!open} onOpenChange={(o) => !o && setOpen(null)}>
        <DialogContent className="sm:max-w-3xl">
          <DialogHeader>
            <DialogTitle className="capitalize">{open?.plan} plan · Table 4.1 as parsed rules</DialogTitle>
            <DialogDescription>Neither policy PDF lists individual codes, so coverage is decided by exact range containment. Rows that are not exclusions are classified separately so they cannot deny a covered service.</DialogDescription>
          </DialogHeader>
          <div className="max-h-[60vh] overflow-auto rounded-lg border">
            <table className="w-full text-sm">
              <thead className="sticky top-0 bg-muted text-left text-xs text-muted-foreground">
                <tr>
                  <th className="px-3 py-2">Range</th>
                  <th className="px-3 py-2">Category</th>
                  <th className="px-3 py-2">Basis</th>
                  <th className="px-3 py-2">Treated as</th>
                </tr>
              </thead>
              <tbody>
                {ranges.data?.ranges.map((r) => (
                  <tr key={`${r.start}-${r.end}`} className="border-t">
                    <td className="px-3 py-1.5 font-mono text-xs">{r.start}–{r.end}</td>
                    <td className="px-3 py-1.5">{r.category}</td>
                    <td className="px-3 py-1.5 text-muted-foreground">{r.basis}</td>
                    <td className="px-3 py-1.5">
                      <span className={cn("rounded px-1.5 py-0.5 text-xs font-medium", KIND[r.kind]?.cls)} title={KIND[r.kind]?.hint}>
                        {KIND[r.kind]?.label ?? r.kind}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </DialogContent>
      </Dialog>
    </AppShell>
  )
}
