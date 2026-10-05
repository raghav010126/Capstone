import type { components } from "./api-types"

type S = components["schemas"]
export type CaseSummary = S["CaseSummary"]
export type CaseDetail = S["CaseDetail"]
export type DocumentOut = S["DocumentOut"]
export type ExtractedField = S["ExtractedField"]
export type OverrideOut = S["OverrideOut"]
export type EventOut = S["EventOut"]
export type AuditOut = S["AuditOut"]
export type ChainStatus = S["ChainStatus"]
export type PolicyOut = S["PolicyOut"]
export type UserOut = S["UserOut"]
export type TokenResponse = S["TokenResponse"]
export type CaseCreated = S["CaseCreated"]
export type AgentRunOut = S["AgentRunOut"]
export type FraudResult = S["FraudResult"]

export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8100"
const TOKEN_KEY = "medishield.token"

export const tokenStore = {
  get: () => (typeof window === "undefined" ? null : window.localStorage.getItem(TOKEN_KEY)),
  set: (t: string) => window.localStorage.setItem(TOKEN_KEY, t),
  clear: () => window.localStorage.removeItem(TOKEN_KEY),
}

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message)
  }
}

async function detail(res: Response): Promise<string> {
  try {
    const body = await res.json()
    if (typeof body.detail === "string") return body.detail
    if (Array.isArray(body.detail)) return body.detail.map((d: { msg: string }) => d.msg).join("; ")
  } catch {
    /* not JSON */
  }
  return res.statusText || `HTTP ${res.status}`
}

export async function api<T>(path: string, init: RequestInit & { json?: unknown } = {}): Promise<T> {
  const headers = new Headers(init.headers)
  const token = tokenStore.get()
  if (token) headers.set("Authorization", `Bearer ${token}`)
  let body = init.body
  if (init.json !== undefined) {
    headers.set("Content-Type", "application/json")
    body = JSON.stringify(init.json)
  }
  const res = await fetch(`${API_URL}${path}`, { ...init, headers, body })
  if (res.status === 401 && token && !path.startsWith("/auth/login")) {
    tokenStore.clear()
    // full reload on purpose: drops all cached data of the signed-out user
    // eslint-disable-next-line @next/next/no-location-assign-relative-destination
    if (typeof window !== "undefined") window.location.href = "/login"
  }
  if (!res.ok) throw new ApiError(res.status, await detail(res))
  if (res.status === 204) return undefined as T
  const type = res.headers.get("content-type") ?? ""
  return (type.includes("json") ? res.json() : res.blob()) as Promise<T>
}

export const wsUrl = (path: string) => {
  const u = new URL(API_URL)
  return `${u.protocol === "https:" ? "wss" : "ws"}://${u.host}${path}?token=${encodeURIComponent(tokenStore.get() ?? "")}`
}

/** Download a protected file (PDF report) with the bearer token. */
export async function download(path: string, filename: string) {
  const blob = await api<Blob>(path)
  const url = URL.createObjectURL(blob)
  const a = document.createElement("a")
  a.href = url
  a.download = filename
  a.click()
  URL.revokeObjectURL(url)
}

export const money = (n: number) => n.toLocaleString("en-US", { style: "currency", currency: "USD" })
export const pct = (n: number | null | undefined, d = 0) => (n == null ? "–" : `${(n * 100).toFixed(d)}%`)
export const when = (iso: string) =>
  new Date(iso).toLocaleString("en-US", { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" })

export const ROLE_LABEL: Record<string, string> = {
  submitter: "Submitter",
  reviewer: "Reviewer",
  senior_reviewer: "Senior reviewer",
  auditor: "Auditor",
  admin: "Admin",
}
