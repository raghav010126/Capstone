"use client"

import { useEffect, useState } from "react"
import { useRouter } from "next/navigation"
import { Loader2, ShieldCheck } from "lucide-react"
import { useAuth } from "@/lib/auth"
import { ApiError, ROLE_LABEL } from "@/lib/api"
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
    <div className="grid min-h-screen place-items-center bg-muted/40 p-6">
      <div className="w-full max-w-md space-y-6">
        <div className="flex items-center justify-center gap-3">
          <div className="grid size-11 place-items-center rounded-xl bg-primary text-primary-foreground">
            <ShieldCheck className="size-6" />
          </div>
          <div>
            <div className="text-xl font-semibold tracking-tight">MediShield</div>
            <div className="text-sm text-muted-foreground">Multi-agent document intake</div>
          </div>
        </div>
        <Card>
          <CardHeader>
            <CardTitle>Sign in</CardTitle>
            <CardDescription>Use your account, or pick a demo role below.</CardDescription>
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
                <Input id="password" type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} required />
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
                <span className="bg-card px-2 text-muted-foreground">Demo accounts</span>
              </div>
            </div>
            <div className="grid gap-2">
              {DEMO.map((d) => (
                <button
                  key={d.user}
                  disabled={busy}
                  onClick={() => submit(d.user, `${d.user}-demo`)}
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
  )
}
