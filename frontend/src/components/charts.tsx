"use client"

import { useState, type ReactNode } from "react"
import { TriangleAlert } from "lucide-react"
import { cn } from "@/lib/utils"

/* Chart tokens (single-series hue = categorical slot 1 of the reference palette; ink and grid are recessive) */
const BAR = "#2a78d6"
const GRID = "oklch(0.92 0 0)"

/* Decision tones: the theme's semantic tokens (approve green, reject red, escalate amber). They fail colour-blind
   separation on their own, so a toned mark always carries its decision as text or an icon too. */
export type Tone = "approve" | "reject" | "escalate"
export const TONE_BG: Record<Tone, string> = { approve: "bg-approve", reject: "bg-reject", escalate: "bg-escalate" }

type Tip = { x: number; y: number; title: string; value: string; note?: string } | null

export function useTip() {
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

export type Bar = { label: string; value: number; n?: number; note?: string; display?: string; tone?: Tone }

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
                  <div className={cn("h-4 rounded-r-[4px] transition-opacity group-hover:opacity-80", b.tone && TONE_BG[b.tone])} style={{ width: `${w}%`, background: b.tone ? undefined : BAR, minWidth: w > 0 ? 3 : 0 }} />
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

/* ── reliability diagram ──────────────────────────────────────────────────────────────────────────── */
export type RelBin = { lo: number; hi: number; n: number; mean_conf: number; accuracy: number }
const SERIES2 = "#eb6834"

/**
 * Confidence vs observed accuracy. The dashed-free diagonal is perfect calibration; points above it are under-confident,
 * below it over-confident. Marker size grows with the number of documents in the bin, so a lonely bin does not look as
 * trustworthy as a full one. Series are told apart by shape as well as colour (circle = raw, diamond = calibrated).
 */
export function ReliabilityChart({ raw, calibrated }: { raw: RelBin[]; calibrated?: RelBin[] }) {
  const tip = useTip()
  const W = 420
  const H = 300
  const m = { l: 44, r: 14, t: 12, b: 40 }
  const x = (v: number) => m.l + v * (W - m.l - m.r)
  const y = (v: number) => H - m.b - v * (H - m.t - m.b)
  const ticks = [0, 0.25, 0.5, 0.75, 1]
  const nMax = Math.max(1, ...raw.map((b) => b.n), ...(calibrated ?? []).map((b) => b.n))
  const r = (n: number) => 4 + 4 * Math.sqrt(n / nMax)
  const path = (bins: RelBin[]) => bins.map((b, i) => `${i ? "L" : "M"}${x(b.mean_conf)},${y(b.accuracy)}`).join(" ")

  const series = (bins: RelBin[], color: string, shape: "circle" | "diamond", label: string) => (
    <g key={label}>
      {bins.length > 1 && <path d={path(bins)} fill="none" stroke={color} strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" />}
      {bins.map((b) => {
        const cx = x(b.mean_conf)
        const cy = y(b.accuracy)
        const rr = r(b.n)
        const show = (el: SVGElement) => tip.show(el as unknown as HTMLElement, `${label}: confidence ${b.lo.toFixed(1)}–${b.hi.toFixed(1)}`, `${(b.accuracy * 100).toFixed(0)}% correct`, `${b.n} documents · mean confidence ${(b.mean_conf * 100).toFixed(0)}%`)
        return (
          <g key={`${label}-${b.lo}`} tabIndex={0} role="img" aria-label={`${label}, confidence ${b.lo}–${b.hi}: ${(b.accuracy * 100).toFixed(0)}% correct, ${b.n} documents`}
            onPointerEnter={(e) => show(e.currentTarget)} onPointerLeave={tip.hide} onFocus={(e) => show(e.currentTarget)} onBlur={tip.hide} className="outline-none">
            <circle cx={cx} cy={cy} r={Math.max(rr + 8, 14)} fill="transparent" />
            {shape === "circle" ? (
              <circle cx={cx} cy={cy} r={rr} fill={color} stroke="white" strokeWidth={2} />
            ) : (
              <rect x={cx - rr} y={cy - rr} width={rr * 2} height={rr * 2} transform={`rotate(45 ${cx} ${cy})`} fill={color} stroke="white" strokeWidth={2} rx={1.5} />
            )}
          </g>
        )
      })}
    </g>
  )

  return (
    <div>
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full" role="group" aria-label="Reliability diagram: confidence against observed accuracy">
        {ticks.map((t) => (
          <g key={t}>
            <line x1={x(0)} x2={x(1)} y1={y(t)} y2={y(t)} stroke={GRID} />
            <line x1={x(t)} x2={x(t)} y1={y(0)} y2={y(1)} stroke={GRID} />
            <text x={m.l - 8} y={y(t) + 3} textAnchor="end" fontSize="10" className="fill-muted-foreground tabular-nums">{Math.round(t * 100)}%</text>
            <text x={x(t)} y={H - m.b + 14} textAnchor="middle" fontSize="10" className="fill-muted-foreground tabular-nums">{Math.round(t * 100)}%</text>
          </g>
        ))}
        <line x1={x(0)} y1={y(0)} x2={x(1)} y2={y(1)} stroke="oklch(0.65 0 0)" strokeWidth={1.5} />
        <text x={x(0.98)} y={y(0.9)} textAnchor="end" fontSize="10" className="fill-muted-foreground">perfect calibration</text>
        {series(raw, "#2a78d6", "circle", "Raw")}
        {calibrated && series(calibrated, SERIES2, "diamond", "Calibrated")}
        <text x={(x(0) + x(1)) / 2} y={H - 6} textAnchor="middle" fontSize="11" className="fill-muted-foreground">confidence reported by the system</text>
        <text transform={`translate(11 ${(y(0) + y(1)) / 2}) rotate(-90)`} textAnchor="middle" fontSize="11" className="fill-muted-foreground">decisions that were correct</text>
      </svg>
      <ul className="mt-1 flex flex-wrap gap-x-5 gap-y-1 text-xs">
        <li className="flex items-center gap-1.5"><span className="inline-block size-2.5 rounded-full" style={{ background: "#2a78d6" }} /> Raw confidence</li>
        {calibrated && <li className="flex items-center gap-1.5"><span className="inline-block size-2.5 rotate-45 rounded-[2px]" style={{ background: SERIES2 }} /> After isotonic calibration</li>}
        <li className="flex items-center gap-1.5 text-muted-foreground"><span className="inline-block h-0.5 w-4" style={{ background: "oklch(0.65 0 0)" }} /> Perfect calibration</li>
      </ul>
      {tip.node}
      <TableView head={["Confidence bin", "Documents", "Raw accuracy", ...(calibrated ? ["Calibrated accuracy"] : [])]}
        rows={raw.map((b, i) => [`${b.lo.toFixed(1)}–${b.hi.toFixed(1)}`, b.n, `${(b.accuracy * 100).toFixed(0)}%`, ...(calibrated?.[i] ? [`${(calibrated[i].accuracy * 100).toFixed(0)}%`] : [])])} />
    </div>
  )
}
