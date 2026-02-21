import { useNavigate } from 'react-router-dom'
import { useApp } from '../App'
import { useToast } from '../context/ToastContext'
import styles from '../styles/menu.module.css'

function fmt(sec: number): string {
  const m = Math.floor(sec / 60)
  const s = (sec % 60).toFixed(3)
  return `${m}:${s.padStart(6, '0')}`
}

export default function MenuScreen() {
  const navigate = useNavigate()
  const { state, socketConnected, startSession, stopSession } = useApp()
  const { addToast } = useToast()

  const isActive = state?.active ?? false
  const lastMsg = state?.speech_log?.slice(-1)[0]?.text ?? null

  const handleStart = async (mode: 1 | 2) => {
    await startSession(mode)
    addToast(mode === 2 ? 'Coaching + Logging started' : 'Coaching started', 'success')
    navigate('/telemetry')
  }

  const handleStop = async () => {
    await stopSession()
    addToast('Session stopped', 'info')
  }

  return (
    <div className={styles.page}>
    <div className={styles.inner}>
      {/* ── hero ── */}
      <div className={styles.hero}>
        <div className={styles.logo}>M</div>
        <h1 className={styles.title}>Marco</h1>
        <p className={styles.sub}>F1 25 Race Engineer</p>
      </div>

      {/* ── status bar ── */}
      <div className={styles.statusBar}>
        <span className={`${styles.dot} ${isActive ? styles.dotOn : styles.dotOff}`} />
        <span className={styles.statusText}>{isActive ? 'Session active' : 'Ready'}</span>
        {socketConnected && <span className={styles.liveBadge}>⬤ Live</span>}
      </div>

      {/* ── last message ── */}
      {lastMsg && (
        <div className={styles.quote}>
          <span className={styles.quoteIcon}>"</span>
          {lastMsg}
          <span className={styles.quoteIcon}>"</span>
        </div>
      )}

      {/* ── action buttons ── */}
      <div className={styles.actions}>
        <button
          className={`${styles.btn} ${styles.btnStart}`}
          disabled={isActive}
          onClick={() => handleStart(1)}
        >
          <span className={styles.btnIcon}>▶</span>
          Start Coaching
        </button>

        <button
          className={`${styles.btn} ${styles.btnLog}`}
          disabled={isActive}
          onClick={() => handleStart(2)}
        >
          <span className={styles.btnIcon}>⬤</span>
          Start Coaching + Logging
        </button>

        <button
          className={`${styles.btn} ${styles.btnDash}`}
          onClick={() => navigate('/telemetry')}
        >
          <span className={styles.btnIcon}>◈</span>
          Telemetry Dashboard
        </button>

        <button
          className={`${styles.btn} ${styles.btnAnalyze}`}
          onClick={() => navigate('/sessions')}
        >
          <span className={styles.btnIcon}>◎</span>
          Analyze Past Sessions
        </button>

        {isActive && (
          <button
            className={`${styles.btn} ${styles.btnStop}`}
            onClick={handleStop}
          >
            <span className={styles.btnIcon}>■</span>
            Stop Session
          </button>
        )}
      </div>

      {/* ── session summary ── */}
      {state && state.laps.length > 0 && (
        <div className={styles.summary}>
          <div className={styles.summaryRow}>
            <span>Laps</span>
            <span>{state.laps.length}</span>
          </div>
          {state.fastest_lap && (
            <div className={styles.summaryRow}>
              <span>Best Lap #{state.fastest_lap.lap_num}</span>
              <span className={styles.pb}>{fmt(state.fastest_lap.time)}</span>
            </div>
          )}
          {state.optimal_lap?.sectors_best != null && (
            <div className={styles.summaryRow}>
              <span>Optimal Lap</span>
              <span>{fmt(state.optimal_lap.sectors_best)}</span>
            </div>
          )}
        </div>
      )}
    </div>
    </div>
  )
}
