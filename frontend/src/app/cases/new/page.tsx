"use client"

import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import Link from "next/link"
import { useQueryClient } from "@tanstack/react-query"
import { CloudUpload, FileImage, FileText, Loader2, Trash2, ArrowRight } from "lucide-react"
import { toast } from "sonner"
import { api, ApiError, type CaseCreated, type CaseDetail, type UploadGrant, type UploadMode } from "@/lib/api"
import { useCaseEvents } from "@/hooks/use-case-events"
import { AppShell } from "@/components/app-shell"
import { PipelineGraph } from "@/components/pipeline-graph"
import { DecisionBadge, CaseStatusBadge } from "@/components/status"
import { Button, buttonVariants } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { cn } from "@/lib/utils"
import { useQuery } from "@tanstack/react-query"

const MAX_BYTES = 10 * 1024 * 1024
const MAX_FILES = 10
const ACCEPT = /\.(png|jpe?g|pdf|tiff?)$/i

function size(n: number) {
  return n > 1024 * 1024 ? `${(n / 1024 / 1024).toFixed(1)} MB` : `${Math.max(1, Math.round(n / 1024))} KB`
}

export default function NewCasePage() {
  const qc = useQueryClient()
  const input = useRef<HTMLInputElement>(null)
  const [files, setFiles] = useState<File[]>([])
  const [drag, setDrag] = useState(false)
  const [busy, setBusy] = useState(false)
  const [created, setCreated] = useState<CaseCreated | null>(null)
  const [finished, setFinished] = useState(false)
  const [idempotencyKey, setIdempotencyKey] = useState(() => crypto.randomUUID())

  const { events } = useCaseEvents(created?.case_id ?? null, () => {
    setFinished(true)
    qc.invalidateQueries({ queryKey: ["cases"] })
    qc.invalidateQueries({ queryKey: ["case", created?.case_id] })
  })
  const result = useQuery({
    queryKey: ["case", created?.case_id],
    queryFn: () => api<CaseDetail>(`/cases/${created!.case_id}`),
    enabled: !!created && finished,
  })

  const add = useCallback((list: FileList | File[]) => {
    const next: File[] = []
    for (const f of Array.from(list)) {
      if (!ACCEPT.test(f.name)) toast.error(`${f.name}: only PNG, JPEG, PDF or TIFF`)
      else if (f.size > MAX_BYTES) toast.error(`${f.name}: larger than 10 MB`)
      else next.push(f)
    }
    setFiles((prev) => {
      const all = [...prev, ...next]
      if (all.length > MAX_FILES) toast.error(`At most ${MAX_FILES} files per case`)
      return all.slice(0, MAX_FILES)
    })
  }, [])

  const previews = useMemo(() => files.map((f) => (f.type.startsWith("image/") ? URL.createObjectURL(f) : null)), [files])
  useEffect(() => () => previews.forEach((u) => u && URL.revokeObjectURL(u)), [previews])

  async function submit() {
    setBusy(true)
    try {
      const headers = { "Idempotency-Key": idempotencyKey }
      const mode = await api<UploadMode>("/cases/upload-mode")
      let res: CaseCreated
      if (mode.mode === "presigned") {
        // on AWS a request to the API may carry at most 6 MB: the files go straight to S3 with one-time signed forms
        const grant = await api<UploadGrant>("/cases/uploads", { method: "POST", json: { files: files.map((f) => ({ filename: f.name, size: f.size })) } })
        await Promise.all(
          grant.uploads.map(async (t, i) => {
            const fd = new FormData()
            Object.entries(t.fields).forEach(([k, v]) => fd.append(k, v))
            fd.append("file", files[i])
            const r = await fetch(t.url, { method: "POST", body: fd })
            if (!r.ok) throw new ApiError(r.status, `Upload of ${files[i].name} failed`)
          }),
        )
        res = await api<CaseCreated>("/cases/from-uploads", { method: "POST", json: { upload_id: grant.upload_id }, headers })
      } else {
        const fd = new FormData()
        files.forEach((f) => fd.append("files", f))
        res = await api<CaseCreated>("/cases", { method: "POST", body: fd, headers })
      }
      res.warnings.forEach((w) => toast.warning(w))
      setCreated(res)
      setFinished(false)
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "Upload failed")
    } finally {
      setBusy(false)
    }
  }

  function reset() {
    setFiles([])
    setCreated(null)
    setFinished(false)
    setIdempotencyKey(crypto.randomUUID())
  }

  return (
    <AppShell requires="case:create" title="New case" subtitle="Upload the documents for one claim: forms, IDs, discharge summaries, prescriptions, amendments">
      <div className="mx-auto max-w-5xl space-y-6">
        {!created && (
          <Card>
            <CardContent className="space-y-4 pt-6">
              <div
                onDragOver={(e) => {
                  e.preventDefault()
                  setDrag(true)
                }}
                onDragLeave={() => setDrag(false)}
                onDrop={(e) => {
                  e.preventDefault()
                  setDrag(false)
                  add(e.dataTransfer.files)
                }}
                onClick={() => input.current?.click()}
                role="button"
                tabIndex={0}
                onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && input.current?.click()}
                aria-label="Add documents"
                className={cn(
                  "flex cursor-pointer flex-col items-center justify-center gap-2 rounded-xl border-2 border-dashed px-6 py-14 text-center transition-colors",
                  drag ? "border-info bg-info-soft" : "border-border hover:bg-muted/40",
                )}
              >
                <CloudUpload className="size-9 text-muted-foreground" />
                <div className="text-base font-medium">Drag documents here, or click to browse</div>
                <div className="text-sm text-muted-foreground">PNG, JPEG, PDF or TIFF · up to 10 files · 10 MB each · PDFs are split into pages</div>
                <input ref={input} type="file" multiple accept=".png,.jpg,.jpeg,.pdf,.tif,.tiff" className="hidden" onChange={(e) => e.target.files && add(e.target.files)} />
              </div>

              {files.length > 0 && (
                <ul className="grid gap-2 sm:grid-cols-2">
                  {files.map((f, i) => (
                    <li key={`${f.name}-${i}`} className="flex items-center gap-3 rounded-lg border p-2">
                      <div className="grid size-12 shrink-0 place-items-center overflow-hidden rounded bg-muted">
                        {previews[i] ? (
                          // eslint-disable-next-line @next/next/no-img-element
                          <img src={previews[i]!} alt="" className="size-full object-cover" />
                        ) : f.type === "application/pdf" ? (
                          <FileText className="size-5 text-muted-foreground" />
                        ) : (
                          <FileImage className="size-5 text-muted-foreground" />
                        )}
                      </div>
                      <div className="min-w-0 flex-1">
                        <div className="truncate text-sm font-medium">{f.name}</div>
                        <div className="text-xs text-muted-foreground">{size(f.size)}</div>
                      </div>
                      <Button variant="ghost" size="icon" aria-label={`Remove ${f.name}`} onClick={() => setFiles((p) => p.filter((_, j) => j !== i))}>
                        <Trash2 />
                      </Button>
                    </li>
                  ))}
                </ul>
              )}
              <div className="flex items-center justify-between">
                <p className="text-xs text-muted-foreground">Files are checked by content, not name. Identical files are ignored, and retried submissions are safe.</p>
                <Button disabled={!files.length || busy} onClick={submit}>
                  {busy && <Loader2 className="animate-spin" />} Submit {files.length > 0 && `${files.length} document${files.length > 1 ? "s" : ""}`}
                </Button>
              </div>
            </CardContent>
          </Card>
        )}

        {created && (
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-3">
                <span className="font-mono">{created.case_id}</span>
                {result.data ? <CaseStatusBadge display={result.data.display_status} status={result.data.status} /> : <CaseStatusBadge display="Processing" status="PROCESSING" />}
              </CardTitle>
              <CardDescription>{created.documents.length} documents · live pipeline progress</CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <PipelineGraph events={events} totalDocs={created.documents.length} finished={finished} />
              {result.data && (
                <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border bg-muted/30 p-4">
                  <div className="space-y-1">
                    <div className="flex items-center gap-2">
                      <span className="text-sm text-muted-foreground">Automated decision</span>
                      <DecisionBadge decision={result.data.ai_decision} size="lg" />
                    </div>
                    <p className="max-w-2xl text-sm text-muted-foreground">{result.data.decision?.justification}</p>
                  </div>
                  <div className="flex gap-2">
                    <Button variant="outline" onClick={reset}>
                      Submit another
                    </Button>
                    <Link href={`/cases/view?id=${created.case_id}`} className={buttonVariants()}>
                      Open case <ArrowRight />
                    </Link>
                  </div>
                </div>
              )}
            </CardContent>
          </Card>
        )}
      </div>
    </AppShell>
  )
}
