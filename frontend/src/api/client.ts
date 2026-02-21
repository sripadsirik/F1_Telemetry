import type { StatePayload } from '../types'

export async function fetchState(): Promise<StatePayload> {
  const res = await fetch('/state')
  if (!res.ok) throw new Error(`/state returned ${res.status}`)
  return res.json()
}

export async function startSession(mode: 1 | 2): Promise<{ ok: boolean; error?: string }> {
  const res = await fetch(`/start/${mode}`, { method: 'POST' })
  return res.json()
}

export async function stopSession(): Promise<{ ok: boolean; error?: string }> {
  const res = await fetch('/stop', { method: 'POST' })
  return res.json()
}
