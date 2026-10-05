"use client"

import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react"
import { useRouter } from "next/navigation"
import { api, ApiError, tokenStore, type UserOut } from "./api"

type AuthState = {
  user: UserOut | null
  loading: boolean
  login: (username: string, password: string) => Promise<void>
  logout: () => void
  can: (permission: string) => boolean
}

const Ctx = createContext<AuthState | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<UserOut | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    const load = tokenStore.get() ? api<UserOut>("/auth/me") : Promise.resolve(null)
    load
      .then((u) => !cancelled && setUser(u))
      .catch((e) => {
        // Only a real 401 means the token is bad. A request aborted by navigation, or an API that is briefly
        // unreachable, must not sign the user out.
        if (e instanceof ApiError && e.status === 401) tokenStore.clear()
      })
      .finally(() => !cancelled && setLoading(false))
    return () => {
      cancelled = true
    }
  }, [])

  const login = useCallback(async (username: string, password: string) => {
    const t = await api<{ access_token: string }>("/auth/login", { method: "POST", json: { username, password } })
    tokenStore.set(t.access_token)
    setUser(await api<UserOut>("/auth/me"))
  }, [])

  const logout = useCallback(() => {
    tokenStore.clear()
    setUser(null)
  }, [])

  const can = useCallback((p: string) => !!user?.permissions?.includes(p), [user])
  return <Ctx.Provider value={{ user, loading, login, logout, can }}>{children}</Ctx.Provider>
}

export function useAuth() {
  const v = useContext(Ctx)
  if (!v) throw new Error("useAuth outside AuthProvider")
  return v
}

/** Redirects to /login when signed out. Returns the user once known. */
export function useRequireAuth() {
  const auth = useAuth()
  const router = useRouter()
  useEffect(() => {
    if (!auth.loading && !auth.user) router.replace("/login")
  }, [auth.loading, auth.user, router])
  return auth
}
