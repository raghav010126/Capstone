"use client"

import { useRef, useState } from "react"
import { MessageSquarePlus, MessagesSquare } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet"
import { Composer } from "@/components/chat/composer"
import { Suggestions, Thread } from "@/components/chat/thread"
import { useChat } from "@/components/chat/use-chat"

const CASE_QUESTIONS = ["Why was this case decided this way?", "What would change the decision?", "Which policy clause applies?"]

/** "Ask about this case": the assistant in a side panel, every question scoped to this case. Mount with key={caseId}. */
export function CaseChat({ caseId }: { caseId: string }) {
  const [open, setOpen] = useState(false)
  const chat = useChat({ caseId, warm: open })      // warm this conversation's session when the panel opens
  const input = useRef<HTMLTextAreaElement>(null)

  return (
    <>
      <Button variant="outline" aria-expanded={open} onClick={() => setOpen((o) => !o)}>
        <MessagesSquare /> Ask about this case
      </Button>
      {/* not modal: the case stays readable and scrollable next to the panel */}
      <Sheet open={open} onOpenChange={setOpen} modal={false} disablePointerDismissal>
        <SheetContent overlay={false} initialFocus={input} data-testid="case-chat">
          <SheetHeader>
            <SheetTitle>Ask about {caseId}</SheetTitle>
            <SheetDescription>Answers cite this case and the policy. What you can see depends on your role.</SheetDescription>
          </SheetHeader>
          <div className="flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto p-4">
            {chat.turns.length === 0 ? (
              <Suggestions examples={CASE_QUESTIONS} onPick={chat.ask} />
            ) : (
              <Button variant="ghost" size="sm" className="self-end" onClick={chat.reset}>
                <MessageSquarePlus /> New conversation
              </Button>
            )}
            <Thread turns={chat.turns} endRef={chat.end} scope="case-" />
          </div>
          <Composer
            value={chat.text}
            onChange={chat.setText}
            onSend={chat.ask}
            busy={chat.busy}
            inputRef={input}
            placeholder="Ask about this case… (Shift+Enter for a new line)"
            className="m-4 mt-0"
          />
        </SheetContent>
      </Sheet>
    </>
  )
}
