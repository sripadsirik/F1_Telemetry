import {
  createContext, useContext, useState, useCallback,
  type ReactNode,
} from 'react'

export type ToastType = 'success' | 'info' | 'warning' | 'error'

export interface Toast {
  id: number
  message: string
  type: ToastType
}

interface ToastCtx {
  addToast: (message: string, type?: ToastType) => void
}

const Ctx = createContext<ToastCtx | null>(null)

export function useToast(): ToastCtx {
  const c = useContext(Ctx)
  if (!c) throw new Error('useToast must be inside ToastProvider')
  return c
}

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([])

  const dismiss = useCallback((id: number) => {
    setToasts(prev => prev.filter(t => t.id !== id))
  }, [])

  const addToast = useCallback((message: string, type: ToastType = 'info') => {
    const id = Date.now() + Math.random()
    setToasts(prev => [...prev.slice(-4), { id, message, type }])
    setTimeout(() => dismiss(id), 5000)
  }, [dismiss])

  const icons: Record<ToastType, string> = {
    success: '✓', info: 'ℹ', warning: '⚠', error: '✕',
  }

  const bg: Record<ToastType, string> = {
    success: '#0d2a1a',
    info:    '#0a1a2e',
    warning: '#2a1e00',
    error:   '#2a0a0a',
  }
  const border: Record<ToastType, string> = {
    success: '#2d6a4f', info: '#0288d1', warning: '#f9a825', error: '#ef5350',
  }
  const color: Record<ToastType, string> = {
    success: '#95d5b2', info: '#7ecef4', warning: '#fdd835', error: '#ef9a9a',
  }

  return (
    <Ctx.Provider value={{ addToast }}>
      {children}

      {/* ── toast container ── */}
      <div style={{
        position: 'fixed', bottom: 16, right: 16,
        display: 'flex', flexDirection: 'column-reverse',
        gap: 8, zIndex: 9999, pointerEvents: 'none',
        maxWidth: 360,
      }}>
        {toasts.map(t => (
          <div key={t.id} style={{
            pointerEvents: 'all',
            display: 'flex', alignItems: 'flex-start', gap: 10,
            padding: '10px 14px',
            borderRadius: 9,
            background: bg[t.type],
            border: `1px solid ${border[t.type]}`,
            color: color[t.type],
            fontSize: 13,
            boxShadow: '0 4px 20px rgba(0,0,0,0.5)',
            animation: 'toastIn 0.2s ease',
          }}>
            <span style={{ fontSize: 15, flexShrink: 0, marginTop: 1 }}>{icons[t.type]}</span>
            <span style={{ flex: 1, lineHeight: 1.5 }}>{t.message}</span>
            <button
              onClick={() => dismiss(t.id)}
              style={{
                background: 'none', border: 'none', cursor: 'pointer',
                color: 'inherit', opacity: 0.6, fontSize: 16, padding: 0,
                lineHeight: 1, flexShrink: 0,
              }}
            >×</button>
          </div>
        ))}
      </div>

      <style>{`
        @keyframes toastIn {
          from { opacity: 0; transform: translateX(16px); }
          to   { opacity: 1; transform: translateX(0); }
        }
      `}</style>
    </Ctx.Provider>
  )
}
