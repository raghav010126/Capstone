"use client"

import { useMemo } from "react"
import { Background, Handle, Position, ReactFlow, type Edge, type Node, type NodeProps } from "@xyflow/react"
import "@xyflow/react/dist/style.css"
import { CheckCircle2, CircleDashed, Hourglass, Loader2, MinusCircle, TriangleAlert, XCircle } from "lucide-react"
import { cn } from "@/lib/utils"
import type { LiveEvent } from "@/hooks/use-case-events"

type StageState = "pending" | "running" | "done" | "degraded" | "error" | "waiting" | "skipped"
type StageData = { label: string; sub: string; state: StageState }

const STAGES = [
  { id: "received", label: "Received", sub: "Case registered" },
  { id: "perceive", label: "Perceive", sub: "OCR · Classify · Extract" },
  { id: "classified", label: "Classified", sub: "Routed by type" },
  { id: "specialists", label: "Specialists", sub: "KYC · Claims · Policy" },
  { id: "fraud_check", label: "Fraud check", sub: "Case-level signals" },
  { id: "decided", label: "Decision", sub: "Rule engine" },
  { id: "human_review", label: "Human review", sub: "If escalated" },
] as const

const STYLE: Record<StageState, string> = {
  pending: "border-border bg-card text-muted-foreground",
  running: "border-info bg-info-soft text-info shadow-[0_0_0_4px_oklch(0.55_0.15_255/0.12)]",
  done: "border-approve/40 bg-approve-soft text-approve",
  degraded: "border-escalate/50 bg-escalate-soft text-escalate",
  error: "border-reject/50 bg-reject-soft text-reject",
  waiting: "border-escalate bg-escalate-soft text-escalate shadow-[0_0_0_4px_oklch(0.62_0.15_70/0.15)]",
  skipped: "border-dashed border-border bg-muted/40 text-muted-foreground/70",
}

function Icon({ state }: { state: StageState }) {
  const c = "size-4"
  if (state === "done") return <CheckCircle2 className={c} />
  if (state === "running") return <Loader2 className={cn(c, "animate-spin")} />
  if (state === "waiting") return <Hourglass className={c} />
  if (state === "error") return <XCircle className={c} />
  if (state === "degraded") return <TriangleAlert className={c} />
  if (state === "skipped") return <MinusCircle className={c} />
  return <CircleDashed className={c} />
}

function StageNode({ data }: NodeProps<Node<StageData>>) {
  return (
    <div
      className={cn("w-[148px] rounded-xl border px-3 py-2.5 transition-all duration-300", STYLE[data.state])}
      role="group"
      aria-label={`${data.label}: ${data.state}`}
    >
      <Handle type="target" position={Position.Left} className="!size-1.5 !border-0 !bg-border" />
      <div className="flex items-center gap-1.5 text-sm font-semibold">
        <Icon state={data.state} />
        {data.label}
      </div>
      <div className="mt-0.5 text-[11px] leading-tight opacity-80">{data.sub}</div>
      <Handle type="source" position={Position.Right} className="!size-1.5 !border-0 !bg-border" />
    </div>
  )
}

const nodeTypes = { stage: StageNode }

export function stageStates(events: LiveEvent[], totalDocs: number, finished: boolean): Record<string, { state: StageState; sub?: string }> {
  const by = (n: string) => events.filter((e) => e.node === n)
  const failed = events.some((e) => e.node === "failed")
  const out: Record<string, { state: StageState; sub?: string }> = {}
  const perDoc = (node: string) => {
    const evs = by(node)
    const n = new Set(evs.map((e) => e.doc_id)).size
    const bad = evs.some((e) => e.status === "degraded")
    return { n, state: (totalDocs > 0 && n >= totalDocs ? (bad ? "degraded" : "done") : n > 0 ? "running" : "pending") as StageState }
  }
  out.received = { state: by("received").length ? "done" : "pending" }
  const p = perDoc("perceive")
  out.perceive = { state: p.state, sub: totalDocs ? `${p.n}/${totalDocs} documents` : undefined }
  out.classified = { state: by("classified").length ? "done" : "pending" }
  const s = perDoc("specialists")
  out.specialists = { state: s.state, sub: totalDocs ? `${s.n}/${totalDocs} documents` : undefined }
  out.fraud_check = { state: by("fraud_check").length ? "done" : "pending" }
  const decided = by("decided")[0]
  out.decided = { state: decided ? "done" : "pending", sub: decided ? decided.status : undefined }
  const hr = by("human_review")
  if (hr.some((e) => e.status === "resolved")) out.human_review = { state: "done", sub: "Resolved by reviewer" }
  else if (hr.some((e) => e.status === "waiting")) out.human_review = { state: "waiting", sub: "Awaiting reviewer" }
  else if (decided && decided.status !== "ESCALATE") out.human_review = { state: "skipped", sub: "Not needed" }
  else out.human_review = { state: "pending" }
  // the first unfinished stage after the last finished one is the one currently running
  if (!finished && !failed && (by("queued").length || events.length)) {
    const order = STAGES.map((st) => st.id)
    const lastDone = Math.max(-1, ...order.map((id, i) => (out[id].state === "done" || out[id].state === "degraded" ? i : -1)))
    for (let i = lastDone + 1; i < order.length; i++) {
      const st = out[order[i]]
      if (st.state === "pending") {
        if (order[i] !== "human_review" || !decided) st.state = "running"
        break
      }
      if (st.state !== "skipped") break
    }
  }
  if (failed) {
    const firstOpen = STAGES.find((st) => !["done", "degraded", "skipped"].includes(out[st.id].state))
    if (firstOpen) out[firstOpen.id] = { state: "error", sub: "Processing failed" }
  }
  return out
}

export function PipelineGraph({ events, totalDocs, finished, className }: { events: LiveEvent[]; totalDocs: number; finished: boolean; className?: string }) {
  const states = useMemo(() => stageStates(events, totalDocs, finished), [events, totalDocs, finished])
  const nodes: Node<StageData>[] = STAGES.map((s, i) => ({
    id: s.id,
    type: "stage",
    position: { x: i * 188, y: 0 },
    data: { label: s.label, sub: states[s.id].sub ?? s.sub, state: states[s.id].state },
    draggable: false,
    selectable: false,
  }))
  const edges: Edge[] = STAGES.slice(1).map((s, i) => ({
    id: `${STAGES[i].id}-${s.id}`,
    source: STAGES[i].id,
    target: s.id,
    animated: states[s.id].state === "running",
    style: { stroke: states[s.id].state === "pending" ? "var(--color-border)" : "var(--color-info)", strokeWidth: 2 },
  }))
  return (
    <div className={cn("h-[110px] w-full overflow-hidden rounded-xl border bg-muted/20", className)} aria-label="Pipeline progress">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        fitView
        fitViewOptions={{ padding: 0.06 }}
        nodesDraggable={false}
        nodesConnectable={false}
        elementsSelectable={false}
        panOnDrag={false}
        zoomOnScroll={false}
        zoomOnPinch={false}
        zoomOnDoubleClick={false}
        preventScrolling={false}
      >
        <Background gap={18} size={1} color="var(--color-border)" />
      </ReactFlow>
    </div>
  )
}
