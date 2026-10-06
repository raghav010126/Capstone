"use client"

import Link from "next/link"
import { usePathname, useRouter } from "next/navigation"
import type { ReactNode } from "react"
import { Activity, ClipboardCheck, FilePlus2, FileText, LayoutDashboard, LogOut, MessagesSquare, ScrollText, ShieldCheck, ShieldOff } from "lucide-react"
import { useRequireAuth } from "@/lib/auth"
import { ROLE_LABEL } from "@/lib/api"
import { cn } from "@/lib/utils"
import { Brand } from "@/components/brand"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"

const NAV = [
  { href: "/", label: "Dashboard", icon: LayoutDashboard, perm: "case:read" },
  { href: "/cases/new", label: "New case", icon: FilePlus2, perm: "case:create" },
  { href: "/review", label: "Review queue", icon: ClipboardCheck, perm: "review:queue" },
  { href: "/audit", label: "Audit log", icon: ScrollText, perm: "audit:read" },
  { href: "/policies", label: "Policies", icon: FileText, perm: "policy:read" },
  { href: "/insights", label: "Insights", icon: Activity, perm: "ops:read" },
  { href: "/chat", label: "Assistant", icon: MessagesSquare, perm: "policy:ask" },
]

export function AppShell({ title, subtitle, actions, requires, children }: { title: string; subtitle?: string; actions?: ReactNode; requires?: string; children: ReactNode }) {
  const { user, loading, logout, can } = useRequireAuth()
  const path = usePathname()
  const router = useRouter()

  if (loading || !user) {
    return (
      <div className="flex min-h-screen">
        <Skeleton className="hidden w-60 md:block" />
        <div className="flex-1 space-y-4 p-8">
          <Skeleton className="h-8 w-64" />
          <Skeleton className="h-64 w-full" />
        </div>
      </div>
    )
  }

  const active = (href: string) => (href === "/" ? path === "/" : path.startsWith(href))
  return (
    <div className="flex min-h-screen md:bg-[linear-gradient(to_right,var(--sidebar)_16rem,transparent_16rem)]">
      <aside className="sticky top-0 hidden h-screen w-64 shrink-0 flex-col bg-sidebar text-sidebar-foreground md:flex">
        <div className="px-5 py-5">
          <Brand tone="light" />
        </div>
        <div className="px-6 pb-2 text-[10px] font-semibold uppercase tracking-[0.12em] text-sidebar-foreground/50">Workspace</div>
        <nav className="flex-1 space-y-0.5 px-3" aria-label="Main">
          {NAV.filter((n) => can(n.perm)).map((n) => (
            <Link
              key={n.href}
              href={n.href}
              aria-current={active(n.href) ? "page" : undefined}
              className={cn(
                "flex items-center gap-2.5 rounded-lg px-3 py-2 text-sm transition-colors",
                active(n.href)
                  ? "bg-sidebar-primary font-medium text-sidebar-primary-foreground shadow-sm"
                  : "text-sidebar-foreground/80 hover:bg-sidebar-accent hover:text-sidebar-foreground",
              )}
            >
              <n.icon className="size-4" />
              {n.label}
            </Link>
          ))}
        </nav>
        <div className="mx-3 mb-3 flex items-start gap-2 rounded-lg bg-sidebar-accent/70 px-3 py-2.5 text-[11px] leading-snug text-sidebar-foreground/80">
          <ShieldCheck className="mt-0.5 size-3.5 shrink-0 text-sidebar-primary" />
          <span>PHI is redacted from logs and traces. Every view and decision is audit-logged.</span>
        </div>
        <div className="border-t border-sidebar-border p-3">
          <div className="mb-2 flex items-center gap-2.5 px-2">
            <div className="grid size-8 shrink-0 place-items-center rounded-full bg-sidebar-primary text-xs font-semibold text-sidebar-primary-foreground">
              {user.display_name
                .split(" ")
                .map((w) => w[0])
                .slice(0, 2)
                .join("")
                .toUpperCase()}
            </div>
            <div className="min-w-0">
              <div className="truncate text-sm font-medium">{user.display_name}</div>
              <div className="text-xs text-sidebar-foreground/60">{ROLE_LABEL[user.role] ?? user.role}</div>
            </div>
          </div>
          <Button
            variant="ghost"
            size="sm"
            className="w-full justify-start text-sidebar-foreground/80 hover:bg-sidebar-accent hover:text-sidebar-foreground"
            onClick={() => {
              logout()
              router.replace("/login")
            }}
          >
            <LogOut /> Sign out
          </Button>
        </div>
      </aside>
      <main className="min-w-0 flex-1">
        <header className="flex flex-wrap items-center justify-between gap-3 border-b bg-card px-6 py-4 md:px-8">
          <div>
            <h1 className="text-xl font-semibold tracking-tight">{title}</h1>
            {subtitle && <p className="text-sm text-muted-foreground">{subtitle}</p>}
          </div>
          <div className="flex items-center gap-2">{actions}</div>
        </header>
        <div className="px-6 py-6 md:px-8">
          {requires && !can(requires) ? (
            <div className="grid place-items-center gap-2 py-24 text-center" role="alert">
              <ShieldOff className="size-9 text-muted-foreground" />
              <p className="text-lg font-medium">Your role cannot open this page</p>
              <p className="max-w-sm text-sm text-muted-foreground">{ROLE_LABEL[user.role] ?? user.role} accounts do not have access to {title.toLowerCase()}. Ask an administrator if you need it.</p>
            </div>
          ) : (
            children
          )}
        </div>
      </main>
    </div>
  )
}
