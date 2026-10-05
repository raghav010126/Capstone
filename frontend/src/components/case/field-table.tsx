"use client"

import { CheckCircle2, CircleHelp, Link2 } from "lucide-react"
import type { DocumentOut } from "@/lib/api"
import { cn } from "@/lib/utils"

const fmt = (v: unknown) => (v == null ? "–" : typeof v === "object" ? JSON.stringify(v) : String(v))

export function FieldTable({ doc, active, onSelect }: { doc: DocumentOut; active: string | null; onSelect: (name: string | null) => void }) {
  if (!doc.fields.length) return <p className="py-6 text-center text-sm text-muted-foreground">No fields were extracted from this document.</p>
  return (
    <div className="max-h-[420px] overflow-auto rounded-xl border">
      <table className="w-full text-sm">
        <thead className="sticky top-0 bg-muted/80 text-left text-xs text-muted-foreground backdrop-blur">
          <tr>
            <th className="px-3 py-2 font-medium">Field</th>
            <th className="px-3 py-2 font-medium">Value</th>
            <th className="px-3 py-2 font-medium">Evidence</th>
          </tr>
        </thead>
        <tbody>
          {doc.fields.map((f) => (
            <tr
              key={f.name}
              onClick={() => onSelect(active === f.name ? null : f.name)}
              className={cn("cursor-pointer border-t transition-colors hover:bg-muted/50", active === f.name && "bg-escalate-soft")}
            >
              <td className="px-3 py-1.5 font-mono text-xs text-muted-foreground">{f.name}</td>
              <td className="px-3 py-1.5 font-medium">{fmt(f.value)}</td>
              <td className="px-3 py-1.5">
                {f.grounded ? (
                  <span className="inline-flex items-center gap-1 text-xs text-approve">
                    <CheckCircle2 className="size-3.5" /> on page
                  </span>
                ) : f.corroborated ? (
                  <span className="inline-flex items-center gap-1 text-xs text-info" title="Not readable by OCR, but matches the member database">
                    <Link2 className="size-3.5" /> member record
                  </span>
                ) : (
                  <span className="inline-flex items-center gap-1 text-xs text-escalate" title="The value was not found in the OCR text; treat with caution">
                    <CircleHelp className="size-3.5" /> unverified
                  </span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
