"use client"

import type { ReactNode } from "react"
import { ChevronDown, Fingerprint, Gavel, ScanText, Scale, ShieldAlert, Tags, Workflow } from "lucide-react"
import type { AgentRunOut, CaseDetail, DocumentOut } from "@/lib/api"
import { money, pct } from "@/lib/api"
import { cn } from "@/lib/utils"
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible"
import { DecisionBadge } from "@/components/status"

type Run = { models: string[]; retried: boolean; calls: number; input: number; output: number; ms: number; cost: number }

/** Telemetry is recorded per agent for the whole case; combine the rows of each agent. */
export function runsByAgent(runs: AgentRunOut[]): Record<string, Run> {
  const out: Record<string, Run> = {}
  for (const r of runs) {
    const a = (out[r.agent] ??= { models: [], retried: false, calls: 0, input: 0, output: 0, ms: 0, cost: 0 })
    if (r.model && !a.models.includes(r.model)) a.models.push(r.model)
    if (r.retried_with) a.retried = true
    a.calls += r.llm_calls
    a.input += r.input_tokens
    a.output += r.output_tokens
    a.ms += r.latency_ms
    a.cost += r.cold_cost_usd || r.cost_usd
  }
  return out
}

const short = (m: string) => m.replace("claude-", "").replace(/-(\d)-(\d)$/, " $1.$2").replace("sonnet", "Sonnet").replace("opus", "Opus")

function ModelChip({ run }: { run?: Run }) {
  if (!run || !run.models.length) return <span className="rounded bg-muted px-1.5 py-0.5 text-[10px] font-medium text-muted-foreground">rules</span>
  if (run.retried) {
    return (
      <span className="rounded bg-escalate-soft px-1.5 py-0.5 text-[10px] font-medium whitespace-nowrap text-escalate" title="The first model's output failed a validation check, so Opus re-ran the step">
        Sonnet → Opus retry
      </span>
    )
  }
  return (
    <span className="flex items-center gap-1">
      {run.models.map((m) => (
        <span key={m} className={cn("rounded px-1.5 py-0.5 text-[10px] font-medium", m.includes("opus") ? "bg-primary text-primary-foreground" : "bg-info-soft text-info")}>
          {short(m)}
        </span>
      ))}
    </span>
  )
}

function Panel({ title, icon, run, chip = true, summary, children, defaultOpen = false }: { title: string; icon: ReactNode; run?: Run; chip?: boolean; summary?: ReactNode; children: ReactNode; defaultOpen?: boolean }) {
  return (
    <Collapsible defaultOpen={defaultOpen} className="rounded-xl border bg-card">
      <CollapsibleTrigger className="group flex w-full items-center gap-2.5 px-3.5 py-2.5 text-left">
        <span className="text-muted-foreground">{icon}</span>
        <span className="text-sm font-semibold whitespace-nowrap">{title}</span>
        {chip && <ModelChip run={run} />}
        <span className="ml-auto flex items-center gap-2 text-xs text-muted-foreground">
          {summary}
          <ChevronDown className="size-4 transition-transform group-data-[panel-open]:rotate-180" />
        </span>
      </CollapsibleTrigger>
      <CollapsibleContent>
        <div className="space-y-2 border-t px-3.5 py-3 text-sm">{children}</div>
      </CollapsibleContent>
    </Collapsible>
  )
}

const KV = ({ k, children }: { k: string; children: ReactNode }) => (
  <div className="flex gap-3">
    <div className="w-32 shrink-0 text-xs text-muted-foreground">{k}</div>
    <div className="min-w-0 flex-1">{children}</div>
  </div>
)

const Tag = ({ children, tone }: { children: ReactNode; tone?: "bad" | "warn" | "good" }) => (
  <span className={cn("mr-1 inline-block rounded-md border px-1.5 py-0.5 text-xs", tone === "bad" && "border-reject/30 bg-reject-soft text-reject", tone === "warn" && "border-escalate/30 bg-escalate-soft text-escalate", tone === "good" && "border-approve/30 bg-approve-soft text-approve", !tone && "bg-muted")}>{children}</span>
)

export function AgentPanels({ doc, detail }: { doc: DocumentOut; detail: CaseDetail }) {
  const runs = runsByAgent(detail.agent_runs)
  const anomalies = (detail.fraud?.anomalies ?? []).filter((a) => a.doc_id === doc.doc_id)
  const c = doc.classification
  return (
    <div className="space-y-2">
      {c && (
        <Panel title="Classifier" icon={<Tags className="size-4" />} run={runs.classifier} summary={`${doc.doc_type ?? ""} · ${pct(c.confidence)}`}>
          <KV k="Document type">{doc.doc_type}</KV>
          {c.language && c.language !== "en" && (
            <KV k="Language">
              {({ es: "Spanish", hi: "Hindi" } as Record<string, string>)[c.language] ?? c.language}
              <span className="ml-2 text-xs text-muted-foreground">read in its own script; dates converted from day/month/year; values normalised to English</span>
            </KV>
          )}
          <KV k="Evidence confidence">
            {pct(c.confidence)} <span className="text-xs text-muted-foreground">(vision model {pct(c.llm_self_confidence)} self-reported, not used)</span>
          </KV>
          <KV k="Agreement">
            Vision: <Tag>{c.llm_doc_type}</Tag> Keywords: <Tag>{c.keyword_doc_type ?? "none"}</Tag> margin {c.keyword_margin}
          </KV>
          <KV k="Tags">{c.routing_tags.map((t) => <Tag key={t}>{t}</Tag>)}</KV>
          <KV k="Reason">{c.reason}</KV>
        </Panel>
      )}
      <Panel title="OCR & extraction" icon={<ScanText className="size-4" />} run={runs.extractor} summary={doc.grounding_rate != null ? `${pct(doc.grounding_rate)} on page` : undefined}>
        <KV k="Confidence">{pct(doc.confidence)}</KV>
        {doc.quality && (
          <>
            <KV k="Image quality">
              sharpness {doc.quality.sharpness} · {doc.quality.ocr_lines} text lines · OCR confidence {pct(doc.quality.ocr_mean_score)}
              {doc.quality.blur_suspected && <Tag tone="bad">blur suspected</Tag>}
              {doc.quality.blank && <Tag tone="bad">blank</Tag>}
            </KV>
          </>
        )}
        <KV k="Grounding">Every value is matched back to the OCR text; unmatched values lower confidence and are marked unverified.</KV>
      </Panel>
      {doc.kyc && (
        <Panel title="KYC" icon={<Fingerprint className="size-4" />} run={runs.kyc_visual} summary={doc.kyc.kyc_passed ? "passed" : "failed"} defaultOpen={!doc.kyc.kyc_passed}>
          <KV k="Result">
            <Tag tone={doc.kyc.kyc_passed ? "good" : "bad"}>{doc.kyc.kyc_passed ? "Identity verified" : "Failed"}</Tag>
            {doc.kyc.flags.map((f) => <Tag key={f} tone="bad">{f}</Tag>)}
            {(doc.kyc.warnings ?? []).map((f) => <Tag key={f} tone="warn">{f}</Tag>)}
          </KV>
          {doc.kyc.reference_date && <KV k="Validated on">date of service {doc.kyc.reference_date} (not today)</KV>}
          {Object.keys(doc.kyc.forensics ?? {}).length > 0 && (
            <KV k="Forensics">
              {(() => {
                const f = doc.kyc.forensics as { typography?: { flagged: boolean; detail: string }; ela?: { applicable: boolean; flagged: boolean; detail: string } }
                return (
                  <div className="space-y-0.5 text-xs">
                    <div>
                      <span className={f.typography?.flagged ? "text-escalate" : "text-approve"}>{f.typography?.flagged ? "Typography: inconsistent" : "Typography: consistent"}</span>
                      <span className="ml-2 text-muted-foreground">{f.typography?.detail}</span>
                    </div>
                    <div>
                      <span className={f.ela?.flagged ? "text-escalate" : "text-muted-foreground"}>{f.ela?.applicable ? (f.ela.flagged ? "ELA: uneven" : "ELA: even") : "ELA: n/a (not a JPEG)"}</span>
                      {f.ela?.applicable && <span className="ml-2 text-muted-foreground">advisory · {f.ela.detail}</span>}
                    </div>
                  </div>
                )
              })()}
            </KV>
          )}
          {(doc.kyc.checks ?? []).map((k) => (
            <KV key={k.name} k={k.name.replace(/_/g, " ")}>
              <span className={k.passed === false ? "text-reject" : k.passed ? "text-approve" : "text-muted-foreground"}>{k.passed == null ? "n/a" : k.passed ? "pass" : "fail"}</span>
              <span className="ml-2 text-xs text-muted-foreground">{k.detail}</span>
            </KV>
          ))}
        </Panel>
      )}
      {doc.claims && (
        <Panel title="Claims" icon={<Gavel className="size-4" />} run={runs.claims} summary={doc.claims.schema_valid ? "meets standard" : `${doc.claims.validation_errors.length} issue(s)`} defaultOpen={!doc.claims.schema_valid}>
          <KV k="Submission standard">
            <Tag tone={doc.claims.schema_valid ? "good" : "bad"}>{doc.claims.schema_valid ? "valid" : "invalid"}</Tag>
          </KV>
          {doc.claims.validation_errors.map((e) => (
            <KV key={e} k="Error"><span className="text-reject">{e}</span></KV>
          ))}
          {(doc.claims.warnings ?? []).map((e) => (
            <KV key={e} k="Warning"><span className="text-escalate">{e}</span></KV>
          ))}
        </Panel>
      )}
      {doc.policy && (
        <Panel title="Policy" icon={<Scale className="size-4" />} run={runs.policy} summary={`${doc.policy.coverage_status.replace("_", " ").toLowerCase()}${doc.policy.coverage_percentage != null ? ` · ${doc.policy.coverage_percentage}%` : ""}`} defaultOpen>
          <KV k="Plan">{doc.policy.plan ? `${doc.policy.plan[0].toUpperCase()}${doc.policy.plan.slice(1)} plan` : "not identified"}</KV>
          <div className="overflow-hidden rounded-lg border">
            <table className="w-full text-xs">
              <thead className="bg-muted/60 text-left text-muted-foreground">
                <tr>
                  <th className="px-2 py-1.5">CPT</th>
                  <th className="px-2 py-1.5">Coverage</th>
                  <th className="px-2 py-1.5">Clause (section, page)</th>
                </tr>
              </thead>
              <tbody>
                {doc.policy.per_code.map((p) => (
                  <tr key={p.code} className="border-t align-top">
                    <td className="px-2 py-1.5 font-mono">{p.code}</td>
                    <td className="px-2 py-1.5">
                      <Tag tone={p.status === "COVERED" ? "good" : p.status === "NOT_COVERED" ? "bad" : "warn"}>{p.status.replace("_", " ").toLowerCase()}</Tag>
                      {p.coverage_percentage != null && <span className="tabular-nums">{p.coverage_percentage}%</span>}
                    </td>
                    <td className="px-2 py-1.5 text-muted-foreground">
                      {p.matched_range && <div className="font-medium text-foreground">Table 4.1 · {p.matched_range} · {p.exclusion_basis}</div>}
                      {p.citation}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {doc.policy.rationale && <p className="text-xs text-muted-foreground">{doc.policy.rationale}</p>}
        </Panel>
      )}
      <Panel title="Fraud signals" icon={<ShieldAlert className="size-4" />} run={runs.fraud} summary={anomalies.length ? `${anomalies.length} signal(s)` : "none"} defaultOpen={anomalies.length > 0}>
        {anomalies.length === 0 && <p className="text-muted-foreground">No signals attributed to this document.</p>}
        {anomalies.map((a) => (
          <KV key={a.code} k={a.source === "rule" ? "Rule" : "Model review"}>
            <div>
              <Tag tone={a.weight >= 0.5 ? "bad" : "warn"}>{a.code}</Tag>
              <span className="text-xs text-muted-foreground">weight {a.weight}</span>
            </div>
            <div className="text-xs">{a.detail}</div>
          </KV>
        ))}
        {detail.fraud?.narrative && (
          <details className="text-xs text-muted-foreground">
            <summary className="cursor-pointer">Case-level analyst narrative</summary>
            <p className="mt-1">{detail.fraud.narrative}</p>
          </details>
        )}
      </Panel>
    </div>
  )
}

export function Telemetry({ detail }: { detail: CaseDetail }) {
  const runs = runsByAgent(detail.agent_runs)
  const rows = Object.entries(runs).filter(([, r]) => r.calls > 0)
  return (
    <Panel title="Run telemetry" icon={<Workflow className="size-4" />} chip={false} summary={`${money(detail.cold_cost_usd || detail.cost_usd)} · ${(detail.wall_ms / 1000).toFixed(1)}s`}>
      <table className="w-full text-xs">
        <thead className="text-left text-muted-foreground">
          <tr>
            <th className="py-1">Agent</th>
            <th>Model</th>
            <th className="text-right">Calls</th>
            <th className="text-right">Tokens in/out</th>
            <th className="text-right">Latency</th>
            <th className="text-right">Cost</th>
          </tr>
        </thead>
        <tbody>
          {rows.map(([agent, r]) => (
            <tr key={agent} className="border-t">
              <td className="py-1 font-medium">{agent}</td>
              <td>
                <ModelChip run={r} />
              </td>
              <td className="text-right tabular-nums">{r.calls}</td>
              <td className="text-right tabular-nums">
                {r.input.toLocaleString()} / {r.output.toLocaleString()}
              </td>
              <td className="text-right tabular-nums">{(r.ms / 1000).toFixed(1)}s</td>
              <td className="text-right tabular-nums">{money(r.cost)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="text-xs text-muted-foreground">Cost is what these model calls cost uncached. Repeat runs are served from the response cache and spend nothing.</p>
    </Panel>
  )
}

export function DocDecisionRow({ detail }: { detail: CaseDetail }) {
  return (
    <ul className="divide-y rounded-xl border">
      {detail.decision?.documents.map((d) => (
        <li key={d.doc_id} className="flex flex-wrap items-center gap-x-3 gap-y-1 px-3 py-2 text-sm">
          <DecisionBadge decision={d.decision} />
          <span className="font-mono text-xs">{d.doc_id}</span>
          <span className="text-xs text-muted-foreground">{d.doc_type.replace("_", " ").toLowerCase()} · {d.rule_id}</span>
          <span className="basis-full text-xs text-muted-foreground">{d.justification || d.reasons.join("; ")}</span>
        </li>
      ))}
    </ul>
  )
}
