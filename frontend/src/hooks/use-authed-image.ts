"use client"

import { useEffect, useState } from "react"
import { api } from "@/lib/api"

type Loaded = { path: string; url: string | null; error: boolean }

/** <img> cannot send the bearer token, so protected images are fetched as blobs. */
export function useAuthedImage(path: string | null) {
  const [loaded, setLoaded] = useState<Loaded | null>(null)
  useEffect(() => {
    if (!path) return
    let cancelled = false
    let objectUrl: string | null = null
    api<Blob>(path)
      .then((blob) => {
        if (cancelled) return
        objectUrl = URL.createObjectURL(blob)
        setLoaded({ path, url: objectUrl, error: false })
      })
      .catch(() => !cancelled && setLoaded({ path, url: null, error: true }))
    return () => {
      cancelled = true
      if (objectUrl) URL.revokeObjectURL(objectUrl)
    }
  }, [path])
  const current = loaded?.path === path ? loaded : null     // a different path means the new image is still loading
  return { url: current?.url ?? null, error: current?.error ?? false }
}
