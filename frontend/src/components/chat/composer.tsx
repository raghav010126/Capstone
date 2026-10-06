"use client"

import type { Ref } from "react"
import { Send } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Textarea } from "@/components/ui/textarea"
import { cn } from "@/lib/utils"

/** The question box: Enter sends, Shift+Enter adds a line. */
export function Composer({
  value,
  onChange,
  onSend,
  busy,
  className,
  inputRef,
  placeholder = "Ask a question… (Shift+Enter for a new line)",
}: {
  value: string
  onChange: (value: string) => void
  onSend: (question: string) => void
  busy: boolean
  className?: string
  inputRef?: Ref<HTMLTextAreaElement>
  placeholder?: string
}) {
  return (
    <form
      className={cn("flex gap-2 rounded-xl border bg-background p-2 shadow-sm", className)}
      onSubmit={(e) => {
        e.preventDefault()
        onSend(value)
      }}
    >
      <Textarea
        ref={inputRef}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault()
            onSend(value)
          }
        }}
        placeholder={placeholder}
        aria-label="Question"
        maxLength={2000}
        className="min-h-10 resize-none border-0 shadow-none focus-visible:ring-0"
      />
      <Button type="submit" disabled={!value.trim() || busy} aria-label="Send">
        <Send />
      </Button>
    </form>
  )
}
