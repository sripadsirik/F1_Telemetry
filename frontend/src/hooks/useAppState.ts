import { useState, useEffect, useRef, useCallback } from 'react'
import { io } from 'socket.io-client'
import type { Socket } from 'socket.io-client'
import { fetchState, startSession as apiStart, stopSession as apiStop } from '../api/client'
import type { StatePayload, TelemetryUpdate } from '../types'

// Polling intervals ─────────────────────────────────────────────────────────
// When socket is alive we still poll slowly as an analytics safety net
// (the backend already pushes session_state every 1 s via socket, but a
// background HTTP poll means stale data can never silently persist).
const POLL_SOCKET_ALIVE_MS  = 2000   // gentle background sync
const POLL_ACTIVE_MS        = 350    // socket dead, session running
const POLL_IDLE_MS          = 1500   // socket dead, idle

const SOCKET_FALLBACK_DELAY_MS = 4000

export function useAppState() {
  const [state, setState] = useState<StatePayload | null>(null)
  const [socketConnected, setSocketConnected] = useState(false)

  const socketRef    = useRef<Socket | null>(null)
  const pollRef      = useRef<ReturnType<typeof setTimeout> | null>(null)
  const aliveRef     = useRef(false)   // socket currently connected?
  const mountedRef   = useRef(true)
  const stateRef     = useRef<StatePayload | null>(null)

  useEffect(() => { stateRef.current = state }, [state])

  // ── polling ───────────────────────────────────────────────────────────────
  const clearPoll = useCallback(() => {
    if (pollRef.current !== null) { clearTimeout(pollRef.current); pollRef.current = null }
  }, [])

  const schedulePoll = useCallback(() => {
    clearPoll()
    const delay = aliveRef.current
      ? POLL_SOCKET_ALIVE_MS
      : stateRef.current?.active ? POLL_ACTIVE_MS : POLL_IDLE_MS

    pollRef.current = setTimeout(async () => {
      if (!mountedRef.current) return
      try {
        const data = await fetchState()
        if (mountedRef.current) setState(data)
      } catch { /* ignore transient network errors */ }
      if (mountedRef.current) schedulePoll()
    }, delay)
  }, [clearPoll])

  // ── socket + lifecycle ────────────────────────────────────────────────────
  useEffect(() => {
    mountedRef.current = true

    // Immediate first load
    fetchState()
      .then(d => { if (mountedRef.current) setState(d) })
      .catch(() => {})

    const socket = io('/', { transports: ['websocket', 'polling'] })
    socketRef.current = socket

    socket.on('connect', () => {
      if (!mountedRef.current) return
      aliveRef.current = true
      setSocketConnected(true)
      // Keep polling running, but switch to the slower "alive" interval.
      schedulePoll()
    })

    socket.on('disconnect', () => {
      if (!mountedRef.current) return
      aliveRef.current = false
      setSocketConnected(false)
      schedulePoll()   // switch back to fast polling
    })

    socket.on('connect_error', () => {
      if (!mountedRef.current) return
      if (!aliveRef.current) schedulePoll()
    })

    // Full state snapshot (sent on connect + every ~1 s by the server)
    socket.on('session_state', (data: StatePayload) => {
      if (mountedRef.current) setState(data)
    })

    // High-frequency partial update (position, speed, gear, delta, sector)
    socket.on('telemetry', (data: TelemetryUpdate) => {
      if (mountedRef.current) {
        setState(prev => prev ? { ...prev, ...data } : null)
      }
    })

    // Start polling as fallback if socket hasn't connected within timeout
    const fallback = setTimeout(() => {
      if (!aliveRef.current && mountedRef.current) schedulePoll()
    }, SOCKET_FALLBACK_DELAY_MS)

    return () => {
      mountedRef.current = false
      socket.disconnect()
      clearPoll()
      clearTimeout(fallback)
    }
  }, [clearPoll, schedulePoll])

  // ── session control ───────────────────────────────────────────────────────
  const startSession = useCallback(async (mode: 1 | 2) => {
    try { await apiStart(mode) } catch (e) { console.error('startSession:', e) }
  }, [])

  const stopSession = useCallback(async () => {
    try { await apiStop() } catch (e) { console.error('stopSession:', e) }
  }, [])

  return { state, socketConnected, startSession, stopSession }
}
