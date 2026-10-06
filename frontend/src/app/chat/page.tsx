"use client"

import { Fragment, useEffect, useRef, useState } from "react"
import Link from "next/link"
import { useMutation, useQuery } from "@tanstack/react-query"
import { BookOpen, Database, FileSearch, Lock, MessageSquarePlus, Send, ShieldCheck, Sparkles } from "lucide-react"
import { api, ApiError, type ChatResponse, type ChatScope } from "@/lib/api"
import { AppShell } from "@/components/app-shell"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { Textarea } from "@/components/ui/textarea"
import { cn } from "@/lib/utils"

type Turn = { id: number; question: string; reply?: ChatResponse; error?: string }

const KIND_ICON: Record<string, typeof BookOpen> = { policy: BookOpen, exclusion: FileSearch, data: Database }

function newConversation() {
  return `conv-${crypto.randomUUID().replaceAll("-", "")}`
}

/** Answer text with [n] citations rendered as links to the numbered sources below it. */
function Cited({ text, turn }: { text: string; turn: number }) {
  const parts = text.split(/(\[\d+\])/g)
  return (
    <p className="whitespace-pre-wrap leading-relaxed">
      {parts.map((p, i) => {
        const m = p.match(/^\[(\d+)\]$/)
        return m ? (
          <a key={i} href={`#src-${turn}-${m[1]}`} className="mx-0.5 align-super text-[11px] font-semibold text-primary hover:underline">
            [{m[1]}]
          </a>
        ) : (
          <Fragment key={i}>{p}</Fragment>
        )
      })}
    </p>
  )
}

function Reply({ turn }: { turn: Turn }) {
  const r = turn.reply
  if (turn.error) return <div className="rounded-lg border border-destructive/40 bg-destructive/5 p-3 text-sm">{turn.error}</div>
  if (!r) return <div className="animate-pulse text-sm text-muted-foreground">Thinking… (the first answer after a pause can take ~20 s while the agent starts)</div>
  const cited = r.sources.filter((s) => s.cited)
  return (
    <div
      className={cn("space-y-3 rounded-lg border p-4 text-sm", r.blocked ? "border-escalate/60 bg-escalate-soft" : "bg-card")}
      data-testid={r.blocked ? "chat-blocked" : "chat-answer"}
    >
      {r.blocked && (
        <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-escalate">
          <Lock className="size-3.5" /> Blocked for your role
        </div>
      )}
      <Cited text={r.answer} turn={turn.id} />
      {r.sql && (
        <details className="text-xs text-muted-foreground">
          <summary className="cursor-pointer">SQL that answered this (read-only, your data scope only)</summary>
          <pre className="mt-1 overflow-x-auto rounded bg-muted p-2">{r.sql}</pre>
        </details>
      )}
      {cited.length > 0 && (
        <ol className="space-y-1 border-t pt-2 text-xs">
          {cited.map((s) => {
            const Icon = KIND_ICON[s.kind] ?? FileSearch
            const label = `${s.title}${s.page ? `, p. ${s.page}` : ""}`
            return (
              <li key={s.n} id={`src-${turn.id}-${s.n}`} className="flex items-start gap-1.5">
                <span className="font-semibold text-primary">[{s.n}]</span>
                <Icon className="mt-0.5 size-3.5 shrink-0 text-muted-foreground" />
                {s.url ? (
                  <Link href={s.url} className="hover:underline">
                    {label}
                  </Link>
                ) : (
                  <span>{label}</span>
                )}
              </li>
            )
          })}
        </ol>
      )}
      <div className="flex gap-2 text-[11px] text-muted-foreground">
        <span>route: {r.route}</span>
        {r.router === "keyword" && <span>· keyword routing (model unavailable)</span>}
      </div>
    </div>
  )
}

export default function ChatPage() {
  const scope = useQuery({ queryKey: ["chat-scope"], queryFn: () => api<ChatScope>("/chat/scope") })
  const [turns, setTurns] = useState<Turn[]>([])
  const [text, setText] = useState("")
  const [conversation, setConversation] = useState(newConversation)
  const end = useRef<HTMLDivElement>(null)
  const seq = useRef(0)

  const send = useMutation({
    mutationFn: (q: { id: number; question: string }) =>
      api<ChatResponse>("/chat", { method: "POST", json: { question: q.question, conversation_id: conversation } }),
    onSuccess: (reply, q) => setTurns((t) => t.map((x) => (x.id === q.id ? { ...x, reply } : x))),
    onError: (e, q) =>
      setTurns((t) =>
        t.map((x) =>
          x.id === q.id ? { ...x, error: e instanceof ApiError && e.status === 429 ? "Too many questions in a minute; wait a moment." : String(e.message) } : x,
        ),
      ),
  })

  useEffect(() => end.current?.scrollIntoView({ behavior: "smooth" }), [turns])

  const ask = (question: string) => {
    const q = question.trim()
    if (!q || send.isPending) return
    const id = ++seq.current
    setTurns((t) => [...t, { id, question: q }])
    setText("")
    send.mutate({ id, question: q })
  }

  return (
    <AppShell
      title="Assistant"
      subtitle="Ask about policies, cases and operations. Answers cite their sources; what you can ask depends on your role."
      requires="policy:ask"
      actions={
        <Button variant="outline" size="sm" onClick={() => (setTurns([]), setConversation(newConversation()))}>
          <MessageSquarePlus /> New conversation
        </Button>
      }
    >
      <div className="grid gap-6 lg:grid-cols-[1fr_280px]">
        <div className="flex min-h-[60vh] flex-col gap-4">
          {turns.length === 0 && (
            <Card>
              <CardContent className="space-y-3 pt-6">
                <div className="flex items-center gap-2 font-medium">
                  <Sparkles className="size-4 text-primary" /> Try asking
                </div>
                <div className="flex flex-wrap gap-2">
                  {(scope.data?.examples ?? []).map((ex) => (
                    <Button key={ex} variant="secondary" size="sm" className="h-auto whitespace-normal py-1.5 text-left" onClick={() => ask(ex)}>
                      {ex}
                    </Button>
                  ))}
                </div>
              </CardContent>
            </Card>
          )}
          {turns.map((t) => (
            <div key={t.id} className="space-y-2">
              <div className="ml-auto max-w-[80%] rounded-lg bg-primary px-4 py-2 text-sm text-primary-foreground">{t.question}</div>
              <div className="max-w-[92%]">
                <Reply turn={t} />
              </div>
            </div>
          ))}
          <div ref={end} />
          <form
            className="sticky bottom-4 mt-auto flex gap-2 rounded-xl border bg-background p-2 shadow-sm"
            onSubmit={(e) => {
              e.preventDefault()
              ask(text)
            }}
          >
            <Textarea
              value={text}
              onChange={(e) => setText(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault()
                  ask(text)
                }
              }}
              placeholder="Ask a question… (Shift+Enter for a new line)"
              aria-label="Question"
              maxLength={2000}
              className="min-h-10 resize-none border-0 shadow-none focus-visible:ring-0"
            />
            <Button type="submit" disabled={!text.trim() || send.isPending} aria-label="Send">
              <Send />
            </Button>
          </form>
        </div>

        <aside className="space-y-4">
          <Card>
            <CardContent className="space-y-3 pt-6 text-sm">
              <div className="flex items-center gap-2 font-medium">
                <ShieldCheck className="size-4 text-primary" /> Your access
                {scope.data && <Badge variant="secondary">{scope.data.role.replace("_", " ")}</Badge>}
              </div>
              <ul className="space-y-1.5" aria-label="Sources you can ask about">
                {scope.data?.accessible.map((s) => (
                  <li key={s.id} className="flex items-center gap-2">
                    <span aria-hidden>✅</span> {s.label}
                  </li>
                ))}
                {scope.data?.restricted.map((s) => (
                  <li key={s.id} className="flex items-center gap-2 text-muted-foreground">
                    <span aria-hidden>🔒</span> {s.label}
                  </li>
                ))}
              </ul>
              <p className="text-xs text-muted-foreground">
                Enforced where the data is read (policy search, case lookups, a read-only per-role analytics database), not just in this page. Blocked
                questions are written to the audit log.
              </p>
            </CardContent>
          </Card>
        </aside>
      </div>
    </AppShell>
  )
}
