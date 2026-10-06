"use client"

import { useEffect, useRef, useState } from "react"
import { useMutation } from "@tanstack/react-query"
import { api, ApiError, type ChatResponse } from "@/lib/api"
import type { Turn } from "@/components/chat/thread"

export function newConversation(prefix = "conv") {
  return `${prefix}-${crypto.randomUUID().replaceAll("-", "")}`
}

/**
 * One assistant conversation: its turns, the question box, sending, warming its runtime session and scrolling to the newest
 * turn. With ``caseId`` every question is asked about that case (the API still checks the user may see it).
 */
export function useChat({ caseId, warm = true }: { caseId?: string; warm?: boolean } = {}) {
  const prefix = caseId ? "case" : "conv"
  const [turns, setTurns] = useState<Turn[]>([])
  const [text, setText] = useState("")
  const [conversation, setConversation] = useState(() => newConversation(prefix))
  const end = useRef<HTMLDivElement>(null)
  const seq = useRef(0)

  const send = useMutation({
    mutationFn: (q: { id: number; question: string }) =>
      api<ChatResponse>("/chat", { method: "POST", json: { question: q.question, conversation_id: conversation, ...(caseId ? { case_id: caseId } : {}) } }),
    onSuccess: (reply, q) => setTurns((t) => t.map((x) => (x.id === q.id ? { ...x, reply } : x))),
    onError: (e, q) =>
      setTurns((t) =>
        t.map((x) =>
          x.id === q.id ? { ...x, error: e instanceof ApiError && e.status === 429 ? "Too many questions in a minute; wait a moment." : String(e.message) } : x,
        ),
      ),
  })

  // start the assistant and load its search models while the user is still typing (no model call, no cost)
  // (AgentCore runs each conversation in its own microVM, so warm the one this conversation will use)
  useEffect(() => {
    if (warm) api(`/chat/warm?conversation_id=${conversation}`, { method: "POST" }).catch(() => undefined)
  }, [conversation, warm])

  useEffect(() => {
    end.current?.scrollIntoView({ behavior: "smooth" })     // block body: newer browsers return a Promise here, React wants nothing
  }, [turns])

  const ask = (question: string) => {
    const q = question.trim()
    if (!q || send.isPending) return
    const id = ++seq.current
    setTurns((t) => [...t, { id, question: q, started: Date.now() }])
    setText("")
    send.mutate({ id, question: q })
  }

  const reset = () => {
    setTurns([])
    setConversation(newConversation(prefix))
  }

  return { turns, text, setText, ask, reset, busy: send.isPending, end }
}
