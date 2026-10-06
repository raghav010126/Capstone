"use client"

import { useEffect, useRef, useState } from "react"
import { Flame, Maximize2, Minus, Plus, ScanSearch } from "lucide-react"
import { useAuthedImage } from "@/hooks/use-authed-image"
import type { DocumentOut } from "@/lib/api"
import { cn } from "@/lib/utils"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"

/**
 * Page image with zoom and evidence boxes. Boxes come from OCR grounding (pixel coordinates of the stored
 * image), drawn as percentages so they stay aligned at any zoom level. Selecting a field in the table
 * highlights its box here and scrolls it into view, and clicking a box selects the field.
 */
export function DocumentViewer({ caseId, doc, activeField, onSelectField }: { caseId: string; doc: DocumentOut; activeField: string | null; onSelectField: (name: string | null) => void }) {
  const [ela, setEla] = useState(false)
  const isJpeg = doc.media_type === "image/jpeg"
  const { url: pageUrl, error: pageError } = useAuthedImage(`/cases/${caseId}/documents/${doc.doc_id}/image`)
  const { url: elaUrl } = useAuthedImage(ela && isJpeg ? `/cases/${caseId}/documents/${doc.doc_id}/ela` : null)
  const url = ela && elaUrl ? elaUrl : pageUrl
  const error = pageError
  const [zoom, setZoom] = useState(1)
  const [boxes, setBoxes] = useState(true)
  const activeRef = useRef<HTMLButtonElement | null>(null)
  const W = doc.quality?.width ?? 0
  const H = doc.quality?.height ?? 0

  useEffect(() => {
    activeRef.current?.scrollIntoView({ block: "center", inline: "center", behavior: "smooth" })
  }, [activeField, zoom])

  const located = doc.fields.filter((f) => f.box && W && H)
  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <div className="text-xs text-muted-foreground">
          {located.length} of {doc.fields.length} fields located on the page
        </div>
        <div className="flex items-center gap-1">
          <Button variant={boxes ? "secondary" : "ghost"} size="sm" onClick={() => setBoxes((b) => !b)} aria-pressed={boxes}>
            <ScanSearch /> Evidence
          </Button>
          {isJpeg && (
            <Button variant={ela ? "secondary" : "ghost"} size="sm" onClick={() => setEla((v) => !v)} aria-pressed={ela} title="Error Level Analysis heatmap: regions saved with a different JPEG history look different. Advisory only.">
              <Flame /> ELA
            </Button>
          )}
          <Button variant="outline" size="icon-sm" aria-label="Zoom out" onClick={() => setZoom((z) => Math.max(0.5, +(z - 0.25).toFixed(2)))}>
            <Minus />
          </Button>
          <span className="w-12 text-center text-xs tabular-nums text-muted-foreground">{Math.round(zoom * 100)}%</span>
          <Button variant="outline" size="icon-sm" aria-label="Zoom in" onClick={() => setZoom((z) => Math.min(4, +(z + 0.25).toFixed(2)))}>
            <Plus />
          </Button>
          <Button variant="outline" size="icon-sm" aria-label="Fit to width" onClick={() => setZoom(1)}>
            <Maximize2 />
          </Button>
        </div>
      </div>
      <div className="h-[600px] overflow-auto rounded-xl border bg-muted/50" tabIndex={0} aria-label={`Document ${doc.doc_id}`}>
        {!url && !error && <Skeleton className="m-4 h-[560px]" />}
        {error && <div className="grid h-full place-items-center text-sm text-muted-foreground">Could not load the image</div>}
        {url && (
          <div className="relative mx-auto bg-white shadow-sm" style={{ width: `${zoom * 100}%` }}>
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src={url} alt={`Scanned ${doc.doc_type?.toLowerCase().replace("_", " ") ?? "document"}`} className="block w-full select-none" draggable={false} />
            {boxes && !ela &&
              located.map((f) => {
                const [x0, y0, x1, y1] = f.box as number[]
                const active = f.name === activeField
                return (
                  <button
                    key={f.name}
                    ref={active ? activeRef : undefined}
                    onClick={() => onSelectField(active ? null : f.name)}
                    title={`${f.name}: ${typeof f.value === "object" ? JSON.stringify(f.value) : String(f.value)}`}
                    aria-label={`Field ${f.name}`}
                    className={cn(
                      "absolute rounded-[3px] border transition-all",
                      active ? "z-10 border-2 border-escalate bg-escalate/25 shadow-[0_0_0_3px_oklch(0.62_0.15_70/0.25)]" : "border-info/60 bg-info/10 hover:bg-info/25",
                    )}
                    style={{ left: `${(x0 / W) * 100}%`, top: `${(y0 / H) * 100}%`, width: `${((x1 - x0) / W) * 100}%`, height: `${((y1 - y0) / H) * 100}%` }}
                  />
                )
              })}
          </div>
        )}
      </div>
    </div>
  )
}
