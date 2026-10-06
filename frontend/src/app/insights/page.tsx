"use client"

import { useState } from "react"
import { useQuery } from "@tanstack/react-query"
import { CircleCheck, CircleDashed, Clock, Coins, PiggyBank, Timer } from "lucide-react"
import { api, money } from "@/lib/api"
import { useAuth } from "@/lib/auth"
import { AppShell } from "@/components/app-shell"
import { ChartCard, ConfusionMatrix, HBarChart, ReliabilityChart, type Bar, type RelBin } from "@/components/charts"
import { Kpi } from "@/components/kpi"
import { ReviewQuality } from "@/components/review-quality"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Skeleton } from "@/components/ui/skeleton"

type EvalResult = {
  split: string
  dataset: string
  timestamp: string
  classification: { accuracy: number; n: number }
  extraction: { rubric_claim_completeness: number; rubric_n: number; all_fields: number; per_type: Record<string, number>; per_field: Record<string, [number, number]>; misses: string[] }
  retrieval: { "recall@3": number; mrr: number; queries: number }
  decision: { accuracy_all: number; n_all: number; accuracy_visible: number; n_visible: number; by_type: Record<string, number>; confusion: Record<string, number>; wrong: string[] }
  cases: { accuracy: number; n: number }
  fraud: { detected: Record<string, string>; false_positive_docs: string[] }
  edge_cases: Record<string, string>
  calibration?: { fitted_on_this_split: boolean; all: CalSummary; visible: CalSummary }
  ops: { cases: number; docs: number; cache_hits: number; case_latency_s: { p50: number; p95: number }; cold_cost_per_case_usd: number; cold_cost_per_doc_usd: number; cold_cost_by_agent: Record<string, number>; llm_calls: number; retries_by_agent: Record<string, number>; mean_grounding_rate: number }
}
type CalBlock = { ece: number; brier: number; bins: RelBin[] }
type CalSummary = { n: number; accuracy: number; raw: CalBlock; calibrated?: CalBlock }
type Summary = { business_impact: { baseline_annual_cost_usd: number; baseline_cost_per_document_usd: number; projected_annual_cost_usd: number; projected_annual_savings_usd: number; assumptions: string }; stp_rate: number | null; decided: number }

const TYPE = (t: string) => t.replace("_", " ").toLowerCase().replace(/^./, (c) => c.toUpperCase())
const pct1 = (v: number) => `${(v * 100).toFixed(1)}%`

function Scorecard({ label, weight, value, shown, target, targetLabel, n }: { label: string; weight: string; value: number; shown: string; target: number; targetLabel: string; n: string }) {
  const met = value >= target
  return (
    <div className="rounded-xl border bg-card p-4">
      <div className="flex items-center justify-between text-xs font-medium text-muted-foreground">
        <span>{label}</span>
        <span className="rounded bg-muted px-1.5 py-0.5">{weight} of grade</span>
      </div>
      <div className="mt-2 text-3xl font-semibold tracking-tight">{shown}</div>
      <div className="mt-3 h-1.5 rounded-full bg-muted" role="meter" aria-valuenow={Math.round(value * 100)} aria-valuemin={0} aria-valuemax={100} aria-label={`${label} against target`}>
        <div className="relative h-full">
          <div className="h-full rounded-full" style={{ width: `${Math.min(100, value * 100)}%`, background: "#2a78d6" }} />
          <div className="absolute -top-1 h-3.5 w-0.5 bg-foreground/70" style={{ left: `${target * 100}%` }} title={`Target ${targetLabel}`} />
        </div>
      </div>
      <div className="mt-2 flex items-center justify-between text-xs text-muted-foreground">
        <span className="flex items-center gap-1">
          {met ? <CircleCheck className="size-3.5 text-approve" /> : <CircleDashed className="size-3.5 text-escalate" />}
          {met ? "Meets" : "Below"} target {targetLabel}
        </span>
        <span>{n}</span>
      </div>
    </div>
  )
}

function ratio(s: string) {
  const [a, b] = s.split("/").map(Number)
  return { v: b ? a / b : 0, a, b }
}
function scenarioBars(map: Record<string, string>): Bar[] {
  return Object.entries(map).map(([k, s]) => {
    const hidden = k.includes("(not visible)")
    const { v, a, b } = ratio(s)
    return {
      label: k.replace(" (not visible)", "").replace(/_/g, " ") + (hidden ? " *" : ""),
      value: v,
      display: `${a}/${b}`,
      note: hidden ? "The dataset's label for this case is never drawn on the page (documented in the dataset findings)" : `${a} of ${b} detected`,
    }
  })
}

export default function InsightsPage() {
  const { can } = useAuth()
  const allowed = can("ops:read")
  const results = useQuery({ queryKey: ["eval"], queryFn: () => api<Record<string, EvalResult>>("/ops/eval"), enabled: allowed })
  const summary = useQuery({ queryKey: ["ops-summary"], queryFn: () => api<Summary>("/ops/summary"), enabled: allowed })
  const [pick, setPick] = useState<string | null>(null)
  const keys = Object.keys(results.data ?? {})
  const key = pick ?? ["official-heldout", "official-dev"].find((k) => keys.includes(k)) ?? keys[0]
  const r = key ? results.data?.[key] : undefined
  const b = summary.data?.business_impact

  return (
    <AppShell
      requires="ops:read"
      title="Insights"
      subtitle="Measured quality of the pipeline against labelled documents, and what it means for operations"
      actions={
        keys.length > 1 && (
          <Select items={keys.map((k) => ({ value: k, label: k }))} value={key} onValueChange={(v) => setPick(v as string)}>
            <SelectTrigger className="w-48" aria-label="Evaluation run">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {keys.map((k) => (
                <SelectItem key={k} value={k}>
                  {k}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        )
      }
    >
      {results.isLoading && <Skeleton className="h-96 w-full" />}
      {!results.isLoading && !r && <p className="py-16 text-center text-muted-foreground">No evaluation results published yet. Run <code className="rounded bg-muted px-1.5 py-0.5">make eval</code>.</p>}
      {r && (
        <div className="space-y-6">
          <p className="text-sm text-muted-foreground">
            <b className="text-foreground">
              {r.dataset} · {r.split} split
            </b>{" "}
            · {r.ops.cases} cases, {r.ops.docs} documents · run {new Date(r.timestamp).toLocaleString("en-US", { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" })}. Prompts are tuned on the dev split only; held-out results are reported separately and never tuned on.
          </p>

          <section aria-label="Scorecard" className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            <Scorecard label="Classification" weight="20%" value={r.classification.accuracy} shown={pct1(r.classification.accuracy)} target={0.97} targetLabel="97%" n={`${r.classification.n} documents`} />
            <Scorecard label="Extraction" weight="20%" value={r.extraction.rubric_claim_completeness} shown={pct1(r.extraction.rubric_claim_completeness)} target={0.95} targetLabel="95%" n={`${r.extraction.rubric_n} claim fields`} />
            <Scorecard label="Policy retrieval (Recall@3)" weight="15%" value={r.retrieval["recall@3"]} shown={pct1(r.retrieval["recall@3"])} target={0.9} targetLabel="90%" n={`MRR ${r.retrieval.mrr}`} />
            <Scorecard label="Decision correctness" weight="25%" value={r.decision.accuracy_visible} shown={pct1(r.decision.accuracy_visible)} target={0.9} targetLabel="90%" n={`${r.decision.n_visible} visible labels`} />
          </section>
          <p className="-mt-3 text-xs text-muted-foreground">
            Decision accuracy on <i>all</i> {r.decision.n_all} labels is {pct1(r.decision.accuracy_all)}; the difference is documents whose label is never drawn on the page in the dataset (tampering, a name mismatch, a hidden structuring signal).
          </p>

          <div className="grid gap-4 lg:grid-cols-2">
            <ChartCard title="Decisions: expected vs made" subtitle="Every document, by the label we expect and the decision the system made">
              <ConfusionMatrix confusion={r.decision.confusion} />
            </ChartCard>
            <ChartCard title="Decision accuracy by document type" subtitle="Share of documents where the decision matched the label">
              <HBarChart
                bars={Object.entries(r.decision.by_type).map(([t, v]) => ({ label: TYPE(t), value: v }))}
                unit="documents"
                tableHead={["Document type", "Accuracy"]}
              />
            </ChartCard>
          </div>

          {r.calibration && (
            <ChartCard
              title="Does the confidence mean what it says?"
              subtitle={`Each point is a group of documents with similar reported confidence: how often those decisions were right. ECE ${r.calibration.all.raw.ece.toFixed(3)} raw${r.calibration.all.calibrated ? ` → ${r.calibration.all.calibrated.ece.toFixed(3)} calibrated` : ""} · Brier ${r.calibration.all.raw.brier.toFixed(3)}${r.calibration.all.calibrated ? ` → ${r.calibration.all.calibrated.brier.toFixed(3)}` : ""}${r.calibration.fitted_on_this_split ? " (calibrator fitted on this split, so the calibrated numbers are in-sample)" : " (calibrator fitted on the dev split only)"}`}
            >
              <div className="mx-auto max-w-xl">
                <ReliabilityChart raw={r.calibration.all.raw.bins} calibrated={r.calibration.all.calibrated?.bins} />
              </div>
            </ChartCard>
          )}

          <div className="grid gap-4 lg:grid-cols-2">
            <ChartCard title="Extraction accuracy by document type" subtitle={`All ${Object.keys(r.extraction.per_field).length} scored fields: ${pct1(r.extraction.all_fields)} correct`}>
              <HBarChart bars={Object.entries(r.extraction.per_type).map(([t, v]) => ({ label: TYPE(t), value: v }))} tableHead={["Document type", "Fields correct"]} />
            </ChartCard>
            <ChartCard title="Fields that are not at 100%" subtitle="Where extraction still misses (a field is only scored when it is actually printed on the page)">
              {Object.entries(r.extraction.per_field).filter(([, [a]]) => a < 1).length === 0 ? (
                <p className="py-8 text-center text-sm text-muted-foreground">Every field is at 100%.</p>
              ) : (
                <HBarChart
                  labelWidth={190}
                  bars={Object.entries(r.extraction.per_field)
                    .filter(([, [a]]) => a < 1)
                    .sort((x, y) => x[1][0] - y[1][0])
                    .map(([f, [a, n]]) => ({ label: f.replace(".", " · ").replace("_", " ").toLowerCase(), value: a, n, note: `${n} fields scored` }))}
                  unit="fields scored"
                  tableHead={["Field", "Accuracy"]}
                />
              )}
            </ChartCard>
          </div>

          <div className="grid gap-4 lg:grid-cols-2">
            <ChartCard title="Fraud scenarios caught" subtitle="Per-document fraud score at or above 0.3 escalates. * label not drawn on the page">
              <HBarChart bars={scenarioBars(r.fraud.detected)} labelWidth={170} unit="" ticks={[0, 0.5, 1]} format={(v) => `${Math.round(v * 100)}%`} tableHead={["Scenario", "Detected"]} />
              <p className="mt-3 text-xs text-muted-foreground">False fraud escalations on clean documents: <b className="text-foreground">{r.fraud.false_positive_docs.length}</b></p>
            </ChartCard>
            <ChartCard title="Edge cases handled as labelled" subtitle="Expired IDs, missing fields, uncovered procedures, unknown documents, tampered IDs">
              <HBarChart bars={scenarioBars(r.edge_cases)} labelWidth={170} ticks={[0, 0.5, 1]} format={(v) => `${Math.round(v * 100)}%`} tableHead={["Edge case", "Handled"]} />
            </ChartCard>
          </div>

          <div>
            <h2 className="mb-3 text-sm font-semibold">Speed and cost</h2>
            <div className="mb-4 grid grid-cols-2 gap-3 lg:grid-cols-4">
              <Kpi label="Time to decision (median)" icon={<Timer className="size-4" />} value={`${r.ops.case_latency_s.p50}s`} hint={`p95 ${r.ops.case_latency_s.p95}s · ${r.ops.cache_hits} of ${r.ops.llm_calls} model calls replayed from cache, so a fully cold case is slower`} tone="good" />
              <Kpi label="Model cost per case" icon={<Coins className="size-4" />} value={money(r.ops.cold_cost_per_case_usd)} hint="uncached, measured" />
              <Kpi label="Model cost per document" icon={<Coins className="size-4" />} value={money(r.ops.cold_cost_per_doc_usd)} hint={`${r.ops.llm_calls} model calls in this run`} />
              <Kpi label="Fields found on the page" icon={<Clock className="size-4" />} value={pct1(r.ops.mean_grounding_rate)} hint="extracted values matched to OCR text" />
            </div>
            <ChartCard title="Where the money goes" subtitle="Model cost by agent, for the whole run (uncached)">
              <HBarChart
                bars={Object.entries(r.ops.cold_cost_by_agent).filter(([, v]) => v > 0).sort((x, y) => y[1] - x[1]).map(([a, v]) => ({ label: a.replace("_", " "), value: v }))}
                max={Math.max(...Object.values(r.ops.cold_cost_by_agent)) * 1.15}
                ticks={[0, 0.25, 0.5, 0.75, 1].map((t) => t * Math.max(...Object.values(r.ops.cold_cost_by_agent)) * 1.15)}
                format={(v) => `$${v.toFixed(2)}`}
                tableHead={["Agent", "Cost"]}
              />
              <p className="mt-2 text-xs text-muted-foreground">
                Retries on the larger model: {Object.keys(r.ops.retries_by_agent).length ? Object.entries(r.ops.retries_by_agent).map(([a, n]) => `${a} ${n}`).join(", ") : "none"}. Sonnet 5.5 runs perception, policy, fraud and summaries; Opus 5.5 only retries failed validations and gives the second opinion on suspected tampering (runs before 6 Oct used Opus for policy and fraud).
              </p>
            </ChartCard>
          </div>

          {b && (
            <section aria-label="Business impact" className="rounded-xl border bg-card p-5">
              <h2 className="flex items-center gap-2 text-sm font-semibold">
                <PiggyBank className="size-4" /> Business impact{summary.data ? `, projected from ${summary.data.decided} decided cases here (${summary.data.stp_rate != null ? Math.round(summary.data.stp_rate * 100) : 0}% straight-through)` : ""}
              </h2>
              <div className="mt-3 grid gap-6 sm:grid-cols-3">
                <div>
                  <div className="text-xs text-muted-foreground">Today (manual review)</div>
                  <div className="text-2xl font-semibold">{money(b.baseline_annual_cost_usd).replace(".00", "")}</div>
                  <div className="text-xs text-muted-foreground">per year · ${b.baseline_cost_per_document_usd} per document</div>
                </div>
                <div>
                  <div className="text-xs text-muted-foreground">With this system</div>
                  <div className="text-2xl font-semibold">{money(b.projected_annual_cost_usd).replace(".00", "")}</div>
                  <div className="text-xs text-muted-foreground">per year · at the current straight-through rate</div>
                </div>
                <div>
                  <div className="text-xs text-muted-foreground">Projected savings</div>
                  <div className="text-2xl font-semibold text-approve">{money(b.projected_annual_savings_usd).replace(".00", "")}</div>
                  <div className="text-xs text-muted-foreground">per year</div>
                </div>
              </div>
              <p className="mt-4 border-t pt-3 text-xs text-muted-foreground">Assumptions: {b.assumptions}</p>
            </section>
          )}

          {r.decision.wrong.length > 0 && (
            <details className="rounded-xl border bg-card p-4 text-sm">
              <summary className="cursor-pointer font-semibold">Decision errors ({r.decision.wrong.length}) and why</summary>
              <ul className="mt-3 list-disc space-y-1.5 pl-5 text-xs text-muted-foreground">
                {r.decision.wrong.map((w) => (
                  <li key={w}>{w}</li>
                ))}
              </ul>
            </details>
          )}
        </div>
      )}
      <ReviewQuality enabled={allowed} className="mt-8 border-t pt-6" />
    </AppShell>
  )
}
