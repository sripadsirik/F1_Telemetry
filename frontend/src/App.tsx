import { createContext, useContext, useEffect, useRef } from 'react'
import { Routes, Route } from 'react-router-dom'
import { useAppState } from './hooks/useAppState'
import { ErrorBoundary } from './components/ErrorBoundary'
import { ToastProvider, useToast } from './context/ToastContext'
import MenuScreen from './screens/MenuScreen'
import TelemetryScreen from './screens/TelemetryScreen'
import SessionsScreen from './screens/SessionsScreen'
import SessionAnalysisScreen from './screens/SessionAnalysisScreen'

type AppContextType = ReturnType<typeof useAppState>
const AppContext = createContext<AppContextType | null>(null)

export function useApp(): AppContextType {
  const ctx = useContext(AppContext)
  if (!ctx) throw new Error('useApp must be inside <App>')
  return ctx
}

// Inner component so it can use useToast (which needs ToastProvider above it)
function AppInner() {
  const appState = useAppState()
  const { addToast } = useToast()
  const prevActive = useRef<boolean | null>(null)

  // Watch for session transitions and show save-location toasts
  useEffect(() => {
    const active = appState.state?.active ?? false

    if (prevActive.current === true && active === false) {
      // Session just ended — fetch latest session to show where it was saved
      fetch('/sessions')
        .then(r => r.json())
        .then((sessions: Array<{ folder: string; report_available: boolean }>) => {
          const latest = sessions?.[sessions.length - 1]
          if (latest) {
            addToast(`Session saved → session_data/${latest.folder}`, 'success')
            if (latest.report_available) {
              setTimeout(() => addToast('Performance report generated ✓', 'success'), 400)
            }
          } else {
            addToast('Session ended', 'info')
          }
        })
        .catch(() => addToast('Session ended', 'info'))
    }

    prevActive.current = active
  }, [appState.state?.active, addToast])

  return (
    <AppContext.Provider value={appState}>
      <Routes>
        <Route path="/" element={<MenuScreen />} />
        <Route
          path="/telemetry"
          element={
            <ErrorBoundary>
              <TelemetryScreen />
            </ErrorBoundary>
          }
        />
        <Route
          path="/sessions"
          element={
            <ErrorBoundary>
              <SessionsScreen />
            </ErrorBoundary>
          }
        />
        <Route
          path="/sessions/:sessionId"
          element={
            <ErrorBoundary>
              <SessionAnalysisScreen />
            </ErrorBoundary>
          }
        />
      </Routes>
    </AppContext.Provider>
  )
}

export default function App() {
  return (
    <ToastProvider>
      <AppInner />
    </ToastProvider>
  )
}
