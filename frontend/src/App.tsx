import { createContext, useContext } from 'react'
import { Routes, Route } from 'react-router-dom'
import { useAppState } from './hooks/useAppState'
import { ErrorBoundary } from './components/ErrorBoundary'
import MenuScreen from './screens/MenuScreen'
import TelemetryScreen from './screens/TelemetryScreen'

type AppContextType = ReturnType<typeof useAppState>
const AppContext = createContext<AppContextType | null>(null)

export function useApp(): AppContextType {
  const ctx = useContext(AppContext)
  if (!ctx) throw new Error('useApp must be used inside <App>')
  return ctx
}

export default function App() {
  const appState = useAppState()
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
      </Routes>
    </AppContext.Provider>
  )
}
