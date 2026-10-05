"use client"

import { useState, type ReactNode } from "react"
import { TriangleAlert } from "lucide-react"
import { cn } from "@/lib/utils"

/* Chart tokens (single-series hue = categorical slot 1 of the reference palette; ink and grid are recessive) */
const BAR = "#2a78d6"
const GRID = "oklch(0.92 0 0)"

type Tip = { x: number; y: number; title: string; value: string; note?: string } | null

function useTip() {
  const [tip, setTip] = useState<Tip>(null)
  const show = (el: HTMLElement, title: string, value: string, note?: string) => {
    const r = el.getBoundingClientRect()
    setTip({ x: r.left + r.width / 2, y: r.top, title, value, note })
  }
  const node = tip && (
    <div role="tooltip" className="pointer-events-none fixed z-50 -translate-x-1/2 -translate-y-[calc(100%+8px)] rounded-lg border bg-popover px-3 py-2 text-xs shadow-md" style={{ left: tip.x, top: tip.y }}>
      <div className="text-base font-semibold leading-tight">{tip.value}</div>
      <div className="mt-0.5 text-muted-foreground">{tip.title}</div>
      {tip.note && <div className="mt-0.5 text-muted-foreground">{tip.note}</div>}
    </div>
  )
  return { show, hide: () => setTip(null), node }
}

/** The table-view twin every chart ships with: the same numbers without needing hover or colour. */
export function TableView({ head, rows }: { head: string[]; rows: (string | number)[][] }) {
  return (
    <details className="mt-3 text-xs">
      <summary className="cursor-pointer text-muted-foreground hover:text-foreground">View as table</summary>
      <table className="mt-2 w-full">
        <thead>
          <tr className="text-left text-muted-foreground">
            {head.map((h, i) => (
              <th key={h} className={cn("py-1 font-medium", i > 0 && "text-right")}>
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i} className="border-t">
              {r.map((c, j) => (
                <td key={j} className={cn("py-1 tabular-nums", j > 0 && "text-right")}>
                  {c}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </details>
  )
}

export type Bar = { label: string; value: number; n?: number; note?: string; display?: string }

/**
 * Horizontal bars, one series. Bars are thin (16px), square at the baseline with a 4px rounded tip, grow from a
 * hairline axis, and carry their value at the tip. `max` is the scale's end (1 for accuracy, otherwise the largest value).
 */
export function HBarChart({ bars, max = 1, format = (v: number) => `${(v * 100).toFixed(1)}%`, ticks = [0, 0.25, 0.5, 0.75, 1], unit = "", labelWidth = 150, tableHead }: { bars: Bar[]; max?: number; format?: (v: number) => string; ticks?: number[]; unit?: string; labelWidth?: number; tableHead?: [string, string] }) {
  const tip = useTip()
  return (
    <div>
      <div className="relative" style={{ paddingLeft: labelWidth }}>
        {/* hairline, solid, recessive grid */}
        <div className="pointer-events-none absolute inset-y-0 right-14" style={{ left: labelWidth }} aria-hidden>
          {ticks.map((t) => (
            <div key={t} className="absolute inset-y-0 w-px" style={{ left: `${(t / max) * 100}%`, background: GRID }} />
          ))}
        </div>
        <ul className="relative space-y-1">
          {bars.map((b) => {
            const w = Math.max(0, Math.min(1, b.value / max)) * 100
            return (
              <li key={b.label} className="group relative flex h-8 items-center">
                <div className="absolute text-right text-xs text-foreground" style={{ left: -labelWidth, width: labelWidth - 12 }}>
                  <span className="line-clamp-2 leading-tight">{b.label}</span>
                </div>
                <div
                  tabIndex={0}
                  role="img"
                  aria-label={`${b.label}: ${b.display ?? format(b.value)}${b.n != null ? `, ${b.n} ${unit}` : ""}`}
                  className="relative mr-14 flex h-full flex-1 items-center rounded outline-none focus-visible:ring-2 focus-visible:ring-ring/50"
                  onPointerEnter={(e) => tip.show(e.currentTarget, b.label, b.display ?? format(b.value), b.note ?? (b.n != null ? `${b.n} ${unit}` : undefined))}
                  onPointerLeave={tip.hide}
                  onFocus={(e) => tip.show(e.currentTarget, b.label, b.display ?? format(b.value), b.note ?? (b.n != null ? `${b.n} ${unit}` : undefined))}
                  onBlur={tip.hide}
                >
                  <div className="h-4 rounded-r-[4px] transition-opacity group-hover:opacity-80" style={{ width: `${w}%`, background: BAR, minWidth: w > 0 ? 3 : 0 }} />
                  <span className="absolute text-xs font-semibold tabular-nums" style={{ left: `calc(${w}% + 8px)` }}>
                    {b.display ?? format(b.value)}
                  </span>
                </div>
              </li>
            )
          })}
        </ul>
        <div className="relative mr-14 mt-1 h-4 text-[10px] text-muted-foreground tabular-nums" style={{ marginLeft: 0 }}>
          {ticks.map((t) => (
            <span key={t} className="absolute -translate-x-1/2" style={{ left: `${(t / max) * 100}%` }}>
              {format(t)}
            </span>
          ))}
        </div>
      </div>
      {tip.node}
      <TableView head={tableHead ?? ["Item", "Value"]} rows={bars.map((b) => [b.label, b.display ?? format(b.value)])} />
    </div>
  )
}

/* ── confusion matrix ─────────────────────────────────────────────────────────────────────────────── */
const CLASSES = ["APPROVE", "REJECT", "ESCALATE"] as const
const NAME: Record<string, string> = { APPROVE: "Approve", REJECT: "Reject", ESCALATE: "Escalate" }

/** One-hue sequential ramp (blue, light -> dark). A square-root scale keeps rare errors visible next to large counts. */
function ramp(count: number, max: number) {
  const t = max ? Math.sqrt(count / max) : 0
  return { bg: `oklch(${0.97 - 0.5 * t} ${0.012 + 0.135 * t} 255)`, dark: t > 0.5 }
}

export function ConfusionMatrix({ confusion }: { confusion: Record<string, number> }) {
  const tip = useTip()
  const get = (e: string, p: string) => confusion[`${e}->${p}`] ?? 0
  const max = Math.max(1, ...CLASSES.flatMap((e) => CLASSES.map((p) => get(e, p))))
  const total = CLASSES.reduce((a, e) => a + CLASSES.reduce((b, p) => b + get(e, p), 0), 0)
  const correct = CLASSES.reduce((a, c) => a + get(c, c), 0)
  return (
    <div>
      <div className="grid gap-[2px]" style={{ gridTemplateColumns: "88px repeat(3, minmax(0, 1fr))" }}>
        <div />
        {CLASSES.map((p) => (
          <div key={p} className="pb-1 text-center text-xs font-medium">
            {NAME[p]}
          </div>
        ))}
        {CLASSES.map((e) => (
          <div key={e} className="contents">
            <div className="flex items-center justify-end pr-2 text-xs font-medium">{NAME[e]}</div>
            {CLASSES.map((p) => {
              const n = get(e, p)
              const wrong = e !== p && n > 0
              const { bg, dark } = ramp(n, max)
              const note = e === p ? "correct" : n ? "wrong" : ""
              return (
                <div
                  key={p}
                  tabIndex={0}
                  role="img"
                  aria-label={`Expected ${NAME[e]}, predicted ${NAME[p]}: ${n} documents${wrong ? " (error)" : ""}`}
                  className="relative grid h-16 place-items-center rounded-[4px] outline-none focus-visible:ring-2 focus-visible:ring-ring/60"
                  style={{ background: n ? bg : "oklch(0.975 0 0)" }}
                  onPointerEnter={(ev) => tip.show(ev.currentTarget, `Expected ${NAME[e]}, predicted ${NAME[p]}`, `${n} documents`, note)}
                  onPointerLeave={tip.hide}
                  onFocus={(ev) => tip.show(ev.currentTarget, `Expected ${NAME[e]}, predicted ${NAME[p]}`, `${n} documents`, note)}
                  onBlur={tip.hide}
                >
                  <span className={cn("text-lg font-semibold tabular-nums", n === 0 ? "text-muted-foreground/60" : dark ? "text-white" : "text-foreground")}>{n}</span>
                  {wrong && <TriangleAlert className={cn("absolute top-1 right-1 size-3.5", dark ? "text-white" : "text-reject")} aria-hidden />}
                </div>
              )
            })}
          </div>
        ))}
      </div>
      <div className="mt-2 flex items-center justify-between text-xs text-muted-foreground">
        <span>
          Rows: label expected · Columns: decision made. <TriangleAlert className="inline size-3 text-reject" /> marks an error.
        </span>
        <span className="font-medium text-foreground tabular-nums">
          {correct}/{total} on the diagonal
        </span>
      </div>
      {tip.node}
      <TableView head={["Expected → predicted", "Documents"]} rows={CLASSES.flatMap((e) => CLASSES.map((p) => [`${NAME[e]} → ${NAME[p]}`, get(e, p)]))} />
    </div>
  )
}

export function ChartCard({ title, subtitle, children, className }: { title: string; subtitle?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <section className={cn("rounded-xl border bg-card p-4", className)}>
      <h3 className="text-sm font-semibold">{title}</h3>
      {subtitle && <p className="mb-3 mt-0.5 text-xs text-muted-foreground">{subtitle}</p>}
      {!subtitle && <div className="mb-3" />}
      {children}
    </section>
  )
}
