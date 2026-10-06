"use client"

import { useEffect, useRef, useState } from "react"
import { useRouter } from "next/navigation"
import { Loader2, LockKeyhole, Stethoscope, UserCheck } from "lucide-react"
import { Brand } from "@/components/brand"
import { useAuth } from "@/lib/auth"
import { api, ApiError, ROLE_LABEL } from "@/lib/api"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"

const DEMO = [
  { user: "submitter", role: "submitter", blurb: "Uploads cases, sees only their own" },
  { user: "reviewer", role: "reviewer", blurb: "Works the queue, overrides up to $10k" },
  { user: "senior", role: "senior_reviewer", blurb: "Approves high-value overrides" },
  { user: "auditor", role: "auditor", blurb: "Read-only: audit log, insights" },
  { user: "admin", role: "admin", blurb: "Policies and everything else" },
]

export default function LoginPage() {
  const { user, login } = useAuth()
  const router = useRouter()
  const [username, setUsername] = useState("")
  const [password, setPassword] = useState("")
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  // Locally the demo accounts have known passwords (<user>-demo) and a click signs in. On the live site they have private
  // passwords, so a click only fills the username.
  const [demoPasswords, setDemoPasswords] = useState(false)
  const [configLoaded, setConfigLoaded] = useState(false)
  const passwordRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    api<{ demo_passwords: boolean }>("/auth/config")
      .then((c) => setDemoPasswords(c.demo_passwords))
      .catch(() => setDemoPasswords(false))
      .finally(() => setConfigLoaded(true))
  }, [])

  useEffect(() => {
    if (user) router.replace("/")
  }, [user, router])

  async function submit(u: string, p: string) {
    setBusy(true)
    setError(null)
    try {
      await login(u, p)
      router.replace("/")
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not reach the server")
      setBusy(false)
    }
  }

  return (
    <div className="grid min-h-screen lg:grid-cols-[1.05fr_1fr]">
      <aside className="relative hidden overflow-hidden bg-sidebar p-12 text-white lg:flex lg:flex-col lg:justify-between">
        <div className="pointer-events-none absolute -right-24 -top-24 size-96 rounded-full bg-sidebar-primary/20 blur-3xl" />
        <div className="pointer-events-none absolute -bottom-32 -left-16 size-96 rounded-full bg-sidebar-primary/10 blur-3xl" />
        <Brand tone="light" sub="Health Insurance · Claims Intake" />
        <div className="relative max-w-md space-y-8">
          <div className="space-y-3">
            <h1 className="text-3xl font-semibold leading-tight tracking-tight">Claims decisions in minutes, not days.</h1>
            <p className="text-white/75">
              Claim forms, IDs, discharge summaries and prescriptions are read, verified against member records and policy, checked for
              fraud and decided, with a human in the loop for anything uncertain.
            </p>
          </div>
          <ul className="space-y-4 text-sm">
            {[
              { icon: Stethoscope, title: "Clinical documents, understood", text: "ICD-10, CPT and NPI codes extracted and grounded on the page." },
              { icon: UserCheck, title: "Role-based access, four-eyes approval", text: "High-value overrides need a second senior reviewer." },
              { icon: LockKeyhole, title: "PHI protected, every action audited", text: "Redacted logs and a tamper-evident audit trail." },
            ].map((f) => (
              <li key={f.title} className="flex gap-3">
                <span className="grid size-9 shrink-0 place-items-center rounded-lg bg-white/10">
                  <f.icon className="size-4.5 text-sidebar-primary" />
                </span>
                <span>
                  <span className="block font-medium">{f.title}</span>
                  <span className="text-white/70">{f.text}</span>
                </span>
              </li>
            ))}
          </ul>
        </div>
        <p className="relative text-xs text-white/50">Synthetic data for demonstration. No real member information is stored.</p>
      </aside>
      <div className="grid place-items-center bg-background p-6">
      <div className="w-full max-w-md space-y-6">
        <div className="lg:hidden">
          <Brand />
        </div>
        <Card className="shadow-sm">
          <CardHeader>
            <CardTitle>Sign in</CardTitle>
            <CardDescription>{demoPasswords ? "Use your account, or pick a demo role below." : "Pick a role to fill in the username, then enter the password you were given."}</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <form
              className="space-y-3"
              onSubmit={(e) => {
                e.preventDefault()
                submit(username, password)
              }}
            >
              <div className="space-y-1.5">
                <Label htmlFor="username">Username</Label>
                <Input id="username" autoComplete="username" value={username} onChange={(e) => setUsername(e.target.value)} required />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="password">Password</Label>
                <Input ref={passwordRef} id="password" type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} required />
              </div>
              {error && (
                <p role="alert" className="text-sm text-reject">
                  {error}
                </p>
              )}
              <Button type="submit" className="w-full" disabled={busy}>
                {busy && <Loader2 className="animate-spin" />} Sign in
              </Button>
            </form>
            <div className="relative">
              <div className="absolute inset-0 flex items-center">
                <span className="w-full border-t" />
              </div>
              <div className="relative flex justify-center text-xs uppercase">
                <span className="bg-card px-2 text-muted-foreground">{demoPasswords ? "Demo accounts" : "Accounts by role"}</span>
              </div>
            </div>
            <div className="grid gap-2">
              {DEMO.map((d) => (
                <button
                  key={d.user}
                  disabled={busy || !configLoaded}
                  type="button"
                  onClick={() => {
                    if (demoPasswords) return submit(d.user, `${d.user}-demo`)
                    setUsername(d.user)
                    setError(null)
                    passwordRef.current?.focus()
                  }}
                  className="flex items-center justify-between rounded-lg border px-3 py-2 text-left text-sm transition-colors hover:bg-muted disabled:opacity-50"
                >
                  <span>
                    <span className="font-medium">{ROLE_LABEL[d.role]}</span>
                    <span className="block text-xs text-muted-foreground">{d.blurb}</span>
                  </span>
                  <span className="font-mono text-xs text-muted-foreground">{d.user}</span>
                </button>
              ))}
            </div>
          </CardContent>
        </Card>
      </div>
      </div>
    </div>
  )
}
