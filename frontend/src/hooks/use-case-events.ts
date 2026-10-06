"use client"

import { useEffect, useRef, useState } from "react"
import { api, API_URL, wsUrl, type EventOut } from "@/lib/api"

export type LiveEvent = Pick<EventOut, "id" | "node" | "status" | "doc_id"> & { payload?: Record<string, unknown> }
export type StreamState = "live" | "polling" | "done"

const TERMINAL = new Set(["DECIDED", "IN_REVIEW", "FINALIZED", "FAILED"])
type Snapshot = { key: string; events: LiveEvent[]; state: StreamState }

/**
 * Live pipeline events for a case: WebSocket first; if the socket cannot connect or drops before the case
 * finishes, fall back to polling the events endpoint (same data, same order). Change `run` to start over
 * (for example after a reviewer reclassifies a document and the case is re-processed).
 */
export function useCaseEvents(caseId: string | null, onDone?: (status: string) => void, run = 0) {
  const key = `${caseId}:${run}`
  const [snap, setSnap] = useState<Snapshot>({ key: "", events: [], state: "live" })
  const done = useRef(onDone)
  useEffect(() => {
    done.current = onDone
  })

  useEffect(() => {
    if (!caseId) return
    let closed = false
    let finished = false
    let poll: ReturnType<typeof setInterval> | undefined
    const seen = new Set<number>()
    const update = (fn: (s: Snapshot) => Partial<Snapshot>) =>
      setSnap((prev) => {
        const base = prev.key === key ? prev : { key, events: [], state: "live" as StreamState }
        return { ...base, ...fn(base) }
      })

    const push = (e: LiveEvent) => {
      if (seen.has(e.id)) return
      seen.add(e.id)
      update((s) => ({ events: [...s.events, e] }))
    }
    const finish = (status: string) => {
      if (finished) return
      finished = true
      update(() => ({ state: "done" }))
      done.current?.(status)
    }
    const startPolling = () => {
      if (closed || finished || poll) return
      update(() => ({ state: "polling" }))
      const tick = async () => {
        try {
          const evs = await api<EventOut[]>(`/cases/${caseId}/events`)
          evs.forEach(push)
          const c = await api<{ status: string }>(`/cases/${caseId}`)
          if (TERMINAL.has(c.status)) {
            clearInterval(poll)
            finish(c.status)
          }
        } catch {
          /* transient: the next tick retries */
        }
      }
      void tick()
      poll = setInterval(tick, 1500)
    }

    let ws: WebSocket | null = null
    // Start on the next tick so React StrictMode's throw-away first mount never opens a socket.
    const connect = setTimeout(() => {
      if (API_URL.startsWith("/")) return startPolling()          // behind CloudFront/Lambda there are no sockets: poll
      try {
        ws = new WebSocket(wsUrl(`/ws/cases/${caseId}`))
        ws.onmessage = (m) => {
          const msg = JSON.parse(m.data)
          if (msg.type === "event") push(msg)
          else if (msg.type === "done") finish(msg.status)
        }
        ws.onerror = () => startPolling()
        ws.onclose = () => {
          if (!finished && !closed) startPolling()
        }
      } catch {
        startPolling()
      }
    }, 0)
    return () => {
      closed = true
      clearTimeout(connect)
      if (poll) clearInterval(poll)
      ws?.close()
    }
  }, [caseId, key])

  return snap.key === key ? { events: snap.events, state: snap.state } : { events: [] as LiveEvent[], state: "live" as StreamState }
}
