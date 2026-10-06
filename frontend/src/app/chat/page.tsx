"use client"

import { useMutation, useQuery } from "@tanstack/react-query"
import { Eraser, MessageSquarePlus, ShieldCheck } from "lucide-react"
import { toast } from "sonner"
import { api, type ChatScope } from "@/lib/api"
import { AppShell } from "@/components/app-shell"
import { Composer } from "@/components/chat/composer"
import { Suggestions, Thread } from "@/components/chat/thread"
import { useChat } from "@/components/chat/use-chat"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"

export default function ChatPage() {
  const scope = useQuery({ queryKey: ["chat-scope"], queryFn: () => api<ChatScope>("/chat/scope") })
  const chat = useChat()

  const forget = useMutation({
    mutationFn: () => api<{ forgotten: number }>("/chat/memory", { method: "DELETE" }),
    onSuccess: () => {
      chat.reset()
      toast.success("The assistant's memory of your conversations has been deleted")
    },
    onError: () => toast.error("Could not clear the assistant's memory"),
  })

  return (
    <AppShell
      title="Assistant"
      subtitle="Ask about policies, cases and operations. Answers cite their sources; what you can ask depends on your role."
      requires="policy:ask"
      actions={
        <div className="flex gap-2">
          <Button variant="ghost" size="sm" disabled={forget.isPending} onClick={() => forget.mutate()} title="Delete what the assistant remembers about you">
            <Eraser /> Clear my memory
          </Button>
          <Button variant="outline" size="sm" onClick={chat.reset}>
            <MessageSquarePlus /> New conversation
          </Button>
        </div>
      }
    >
      <div className="grid gap-6 lg:grid-cols-[1fr_280px]">
        <div className="flex min-h-[60vh] flex-col gap-4">
          {chat.turns.length === 0 && <Suggestions examples={scope.data?.examples ?? []} onPick={chat.ask} />}
          <Thread turns={chat.turns} endRef={chat.end} />
          <Composer value={chat.text} onChange={chat.setText} onSend={chat.ask} busy={chat.busy} className="sticky bottom-4 mt-auto" />
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
                questions are written to the audit log. The assistant remembers your earlier questions (personal details redacted) until you clear it.
              </p>
            </CardContent>
          </Card>
        </aside>
      </div>
    </AppShell>
  )
}
