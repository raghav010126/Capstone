"use client"

import { Fragment, useEffect, useState, type Ref } from "react"
import Link from "next/link"
import { BookOpen, Database, FileSearch, Lock, Sparkles } from "lucide-react"
import type { ChatResponse } from "@/lib/api"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { cn } from "@/lib/utils"

export type Turn = { id: number; question: string; reply?: ChatResponse; error?: string; started: number }

/** Seconds since the question was sent, while the answer is on its way. */
export function Elapsed({ since }: { since: number }) {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 500)
    return () => clearInterval(t)
  }, [])
  return <span className="tabular-nums">{Math.max(0, Math.round((now - since) / 1000))} s</span>
}

const KIND_ICON: Record<string, typeof BookOpen> = { policy: BookOpen, exclusion: FileSearch, data: Database }

/** Anchor id of source n of a turn; ``scope`` keeps two chats on one page apart. */
const sourceId = (scope: string, turn: number, n: number | string) => `src-${scope}${turn}-${n}`

/** One line of an answer: **bold** and [n] citations, the latter linked to the numbered sources below it. */
function Inline({ text, turn, scope }: { text: string; turn: number; scope: string }) {
  return (
    <>
      {text.split(/(\[\d+\]|\*\*[^*]+\*\*)/g).map((p, i) => {
        const cite = p.match(/^\[(\d+)\]$/)
        if (cite)
          return (
            <a key={i} href={`#${sourceId(scope, turn, cite[1])}`} className="mx-0.5 align-super text-[11px] font-semibold text-primary hover:underline">
              [{cite[1]}]
            </a>
          )
        if (p.startsWith("**") && p.endsWith("**")) return <strong key={i} className="font-semibold">{p.slice(2, -2)}</strong>
        return <Fragment key={i}>{p}</Fragment>
      })}
    </>
  )
}

const BULLET = /^\s*(?:[-*•]|\d+[.)])\s+/

/** Answer text: paragraphs and bullet lists (the small markdown subset the assistant is asked to write), with citations. */
export function Cited({ text, turn, scope = "" }: { text: string; turn: number; scope?: string }) {
  const blocks: { list: boolean; lines: string[] }[] = []
  for (const line of text.split("\n")) {
    if (!line.trim()) continue
    const list = BULLET.test(line)
    const last = blocks.at(-1)
    if (last && last.list === list && list) last.lines.push(line.replace(BULLET, ""))
    else blocks.push({ list, lines: [list ? line.replace(BULLET, "") : line] })
  }
  return (
    <div className="space-y-2 leading-relaxed">
      {blocks.map((b, i) =>
        b.list ? (
          <ul key={i} className="list-disc space-y-1 pl-5 marker:text-muted-foreground">
            {b.lines.map((l, j) => (
              <li key={j}>
                <Inline text={l} turn={turn} scope={scope} />
              </li>
            ))}
          </ul>
        ) : (
          <p key={i}>
            <Inline text={b.lines[0]} turn={turn} scope={scope} />
          </p>
        ),
      )}
    </div>
  )
}

/** The numbered sources an answer cited, linked to where they live in the app. */
export function Sources({ sources, turn, scope = "" }: { sources: ChatResponse["sources"]; turn: number; scope?: string }) {
  const cited = sources.filter((s) => s.cited)
  if (cited.length === 0) return null
  return (
    <ol className="space-y-1 border-t pt-2 text-xs">
      {cited.map((s) => {
        const Icon = KIND_ICON[s.kind] ?? FileSearch
        const label = `${s.title}${s.page ? `, p. ${s.page}` : ""}`
        return (
          <li key={s.n} id={sourceId(scope, turn, s.n)} className="flex items-start gap-1.5">
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
  )
}

/** One reply: waiting (with a timer), an error, a blocked refusal, or a cited answer with its sources. */
export function Reply({ turn, scope = "" }: { turn: Turn; scope?: string }) {
  const r = turn.reply
  if (turn.error) return <div className="rounded-lg border border-destructive/40 bg-destructive/5 p-3 text-sm">{turn.error}</div>
  if (!r)
    return (
      <div className="flex items-center gap-2 text-sm text-muted-foreground">
        <span className="size-2 animate-pulse rounded-full bg-primary" /> Checking your sources… <Elapsed since={turn.started} />
      </div>
    )
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
      <Cited text={r.answer} turn={turn.id} scope={scope} />
      {r.sql && (
        <details className="text-xs text-muted-foreground">
          <summary className="cursor-pointer">SQL that answered this (read-only, your data scope only)</summary>
          <pre className="mt-1 overflow-x-auto rounded bg-muted p-2">{r.sql}</pre>
        </details>
      )}
      <Sources sources={r.sources} turn={turn.id} scope={scope} />
      <div className="flex gap-2 text-[11px] text-muted-foreground">
        <span>route: {r.route}</span>
        {r.router === "keyword" && <span>· keyword routing (model unavailable)</span>}
      </div>
    </div>
  )
}

/** The conversation so far: each question with its reply, then the element the newest turn scrolls to. */
export function Thread({ turns, endRef, scope = "" }: { turns: Turn[]; endRef?: Ref<HTMLDivElement>; scope?: string }) {
  return (
    <>
      {turns.map((t) => (
        <div key={t.id} className="space-y-2">
          <div className="ml-auto max-w-[80%] rounded-lg bg-primary px-4 py-2 text-sm text-primary-foreground">{t.question}</div>
          <div className="max-w-[92%]">
            <Reply turn={t} scope={scope} />
          </div>
        </div>
      ))}
      <div ref={endRef} />
    </>
  )
}

/** "Try asking": example questions that are sent when clicked. */
export function Suggestions({ examples, onPick }: { examples: string[]; onPick: (question: string) => void }) {
  return (
    <Card>
      <CardContent className="space-y-3 pt-6">
        <div className="flex items-center gap-2 font-medium">
          <Sparkles className="size-4 text-primary" /> Try asking
        </div>
        <div className="flex flex-wrap gap-2">
          {examples.map((ex) => (
            <Button key={ex} variant="secondary" size="sm" className="h-auto whitespace-normal py-1.5 text-left" onClick={() => onPick(ex)}>
              {ex}
            </Button>
          ))}
        </div>
      </CardContent>
    </Card>
  )
}
