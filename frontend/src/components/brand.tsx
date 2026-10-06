import { cn } from "@/lib/utils"

/** MediShield mark: a shield carrying a medical cross. */
export function BrandMark({ className, cross = "white" }: { className?: string; cross?: string }) {
  return (
    <svg viewBox="0 0 32 32" aria-hidden className={cn("size-8", className)}>
      <path d="M16 2.5 4.5 6.8v8.4c0 7.2 4.9 12.2 11.5 14.3 6.6-2.1 11.5-7.1 11.5-14.3V6.8L16 2.5Z" fill="currentColor" />
      <path d="M13.6 9.5h4.8v4.3h4.3v4.8h-4.3v4.3h-4.8v-4.3H9.3v-4.8h4.3V9.5Z" fill={cross} />
    </svg>
  )
}

export function Brand({ tone = "dark", sub = "Claims Intake" }: { tone?: "dark" | "light"; sub?: string }) {
  return (
    <div className="flex items-center gap-2.5">
      <BrandMark className={tone === "light" ? "text-white" : "text-primary"} cross={tone === "light" ? "var(--sidebar)" : "white"} />
      <div className="leading-tight">
        <div className={cn("text-[15px] font-semibold tracking-tight", tone === "light" && "text-white")}>
          MediShield <span className="font-normal opacity-80">Health</span>
        </div>
        <div className={cn("text-[11px]", tone === "light" ? "text-white/70" : "text-muted-foreground")}>{sub}</div>
      </div>
    </div>
  )
}
