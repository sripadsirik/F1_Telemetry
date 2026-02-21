import { Component, type ReactNode, type ErrorInfo } from 'react'

interface Props { children: ReactNode }
interface State { error: Error | null }

/**
 * Catches any render-time JavaScript error inside the telemetry dashboard
 * and shows a recovery screen instead of a blank page.
 */
export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null }

  static getDerivedStateFromError(error: Error): State {
    return { error }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error('[Marco] Dashboard render error:', error.message)
    console.error(info.componentStack)
  }

  reset = () => this.setState({ error: null })

  render() {
    const { error } = this.state
    if (!error) return this.props.children

    return (
      <div style={{
        height: '100%', display: 'flex', flexDirection: 'column',
        alignItems: 'center', justifyContent: 'center',
        background: '#0a0a1a', color: '#e0e0e0', gap: 14, padding: 24,
      }}>
        <div style={{ fontSize: 40 }}>⚠️</div>
        <div style={{ fontWeight: 700, fontSize: 17 }}>Dashboard error</div>
        <pre style={{
          fontSize: 11, color: '#7080a0', maxWidth: 420,
          whiteSpace: 'pre-wrap', textAlign: 'center',
        }}>
          {error.message}
        </pre>
        <button
          onClick={this.reset}
          style={{
            padding: '9px 24px', background: '#0288d1', color: '#fff',
            border: 'none', borderRadius: 7, cursor: 'pointer',
            fontSize: 13, fontWeight: 600,
          }}
        >
          Retry
        </button>
        <div style={{ fontSize: 11, color: '#506070' }}>
          (open DevTools console for full stack trace)
        </div>
      </div>
    )
  }
}
