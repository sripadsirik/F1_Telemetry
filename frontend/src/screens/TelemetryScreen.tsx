import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useApp } from '../App'
import TrackCanvas from '../components/TrackCanvas'
import type { StatePayload, LapEntry } from '../types'
import styles from '../styles/telemetry.module.css'

// ─── safe formatting ──────────────────────────────────────────────────────────

function fmt(sec: unknown): string {
  const n = typeof sec === 'number' && isFinite(sec) ? sec : 0
  const m = Math.floor(n / 60)
  const s = (n % 60).toFixed(3)
  return `${m}:${s.padStart(6, '0')}`
}

function fmtDelta(d: unknown): string {
  if (typeof d !== 'number' || !isFinite(d)) return '--'
  return `${d < 0 ? '-' : '+'}${Math.abs(d).toFixed(3)}s`
}

function fmtSigma(v: unknown): string {
  return typeof v === 'number' && isFinite(v) ? `±${v.toFixed(3)}s` : '--'
}

function safeNum(v: unknown, fallback = 0): number {
  return typeof v === 'number' && isFinite(v) ? v : fallback
}

// ─── sector color → CSS class ──────────────────────────────────────────────────

function sectorClass(color: string | null | undefined, active: boolean): string {
  const cls = [styles.sectorBox]
  if (active) cls.push(styles.sActive)
  if (color === 'purple') cls.push(styles.sPurple)
  else if (color === 'green') cls.push(styles.sGreen)
  else if (color === 'yellow') cls.push(styles.sYellow)
  return cls.join(' ')
}

// ─── sub-components ────────────────────────────────────────────────────────────

function SectorBars({ state }: { state: StatePayload }) {
  const sc = state.sector_colors ?? {}
  const cur = safeNum(state.sector)
  return (
    <div className={styles.sectorBars}>
      {([1, 2, 3] as const).map(n => (
        <div key={n} className={sectorClass(sc[String(n)], cur === n)}>S{n}</div>
      ))}
    </div>
  )
}

function LapList({ laps, fastest }: { laps: LapEntry[]; fastest: StatePayload['fastest_lap'] }) {
  if (!Array.isArray(laps) || laps.length === 0) return null
  return (
    <div className={styles.lapList}>
      {[...laps].reverse().map(lap => {
        if (!lap || typeof lap !== 'object') return null
        const isPb = Boolean(lap.is_pb)
        const valid = Boolean(lap.valid)
        const cls = isPb ? styles.lapPb : valid ? styles.lapValid : styles.lapInvalid
        const label = isPb ? 'PB' : valid ? 'OK' : 'INV'
        const isFastest = fastest?.lap_num === lap.lap_num
        return (
          <div key={lap.lap_num} className={`${styles.lapRow} ${isFastest ? styles.lapFastest : ''}`}>
            <span className={styles.lapNum}>Lap {lap.lap_num}</span>
            <span className={styles.lapTime}>{fmt(lap.time)}</span>
            <span className={`${styles.lapTag} ${cls}`}>{label}</span>
          </div>
        )
      })}
    </div>
  )
}

function TimeLossCard({ state }: { state: StatePayload }) {
  const items = state.time_loss_summary
  if (!Array.isArray(items) || items.length === 0) return null
  return (
    <div className={styles.card}>
      <h3>Top Time Losses</h3>
      {items.map((item, i) => {
        if (!item || typeof item !== 'object') return null
        const delta = safeNum(item.avg_delta)
        return (
          <div key={item.turn ?? i} className={styles.kvRow}>
            <span>Turn {item.turn}</span>
            <span className={styles.negative}>+{delta.toFixed(3)}s</span>
          </div>
        )
      })}
    </div>
  )
}

function ConsistencyCard({ state }: { state: StatePayload }) {
  const c = state.consistency
  if (!c || typeof c !== 'object') return null
  const ss = c.sector_sigma
  const mic = c.most_inconsistent_corner
  const mcc = c.most_consistent_corner
  return (
    <div className={styles.card}>
      <h3>Consistency</h3>
      <div className={styles.kvRow}><span>Lap σ</span><span>{fmtSigma(c.lap_sigma)}</span></div>
      {ss && typeof ss === 'object' && (
        <>
          <div className={styles.kvRow}><span>S1 σ</span><span>{fmtSigma(ss.s1)}</span></div>
          <div className={styles.kvRow}><span>S2 σ</span><span>{fmtSigma(ss.s2)}</span></div>
          <div className={styles.kvRow}><span>S3 σ</span><span>{fmtSigma(ss.s3)}</span></div>
        </>
      )}
      {mic && typeof mic === 'object' && (
        <div className={styles.kvRow}>
          <span>Most inconsistent</span>
          <span>T{mic.turn} {fmtSigma(mic.sigma)}</span>
        </div>
      )}
      {mcc && typeof mcc === 'object' && (
        <div className={styles.kvRow}>
          <span>Most consistent</span>
          <span>T{mcc.turn}</span>
        </div>
      )}
    </div>
  )
}

function ProfileCard({ state }: { state: StatePayload }) {
  const profile = state.driver_profile
  if (!profile || typeof profile !== 'object') return null
  const tags = Array.isArray(profile.tags) ? profile.tags : []
  const stats = profile.stats && typeof profile.stats === 'object' ? profile.stats : {}
  if (tags.length === 0 && Object.keys(stats).length === 0) return null
  return (
    <div className={styles.card}>
      <h3>Driver Profile</h3>
      {tags.length > 0 && (
        <div className={styles.tagList}>
          {tags.map((t, i) => <span key={i} className={styles.tag}>{String(t)}</span>)}
        </div>
      )}
      {Object.entries(stats).map(([k, v]) => (
        <div key={k} className={styles.kvRow}>
          <span>{k}</span>
          <span>{typeof v === 'number' && isFinite(v) ? v.toFixed(2) : String(v ?? '--')}</span>
        </div>
      ))}
    </div>
  )
}

function SkillCard({ state }: { state: StatePayload }) {
  const scores = state.skill_scores
  if (!scores || typeof scores !== 'object' || Object.keys(scores).length === 0) return null
  return (
    <div className={styles.card}>
      <h3>Skill Scores</h3>
      {Object.entries(scores).map(([name, val]) => {
        const pct = Math.max(0, Math.min(100, safeNum(val)))
        return (
          <div key={name} className={styles.skillRow}>
            <span className={styles.skillLabel}>{name}</span>
            <div className={styles.skillTrack}>
              <div className={styles.skillFill} style={{ width: `${pct}%` }} />
            </div>
            <span className={styles.skillVal}>{Math.round(pct)}</span>
          </div>
        )
      })}
    </div>
  )
}

function MasteryCard({ state }: { state: StatePayload }) {
  const mastery = state.corner_mastery
  if (!Array.isArray(mastery) || mastery.length === 0) return null
  const sym = (t: unknown) => t === 'up' ? '↑' : t === 'down' ? '↓' : '→'
  return (
    <div className={styles.card}>
      <h3>Corner Mastery</h3>
      {mastery.map((m, i) => {
        if (!m || typeof m !== 'object') return null
        const score = safeNum(m.score)
        const trendUp = m.trend === 'up'
        const trendDown = m.trend === 'down'
        return (
          <div key={m.turn ?? i} className={styles.kvRow}>
            <span>Turn {m.turn}</span>
            <span>
              {Math.round(score)}%{' '}
              <span className={trendUp ? styles.positive : trendDown ? styles.negative : ''}>
                {sym(m.trend)}
              </span>
            </span>
          </div>
        )
      })}
    </div>
  )
}

function OptimalCard({ state }: { state: StatePayload }) {
  const opt = state.optimal_lap
  if (!opt || typeof opt !== 'object') return null
  const best = safeNum(opt.sectors_best, -1)
  if (best <= 0) return null
  const gainVsPb = opt.gain_vs_pb_sectors
  return (
    <div className={styles.card}>
      <h3>Optimal Lap</h3>
      <div className={styles.kvRow}>
        <span>Sector-based</span>
        <span className={styles.pb}>{fmt(best)}</span>
      </div>
      {typeof opt.bins_best === 'number' && isFinite(opt.bins_best) && opt.bins_best > 0 && (
        <div className={styles.kvRow}>
          <span>Bin-based</span>
          <span className={styles.pb}>{fmt(opt.bins_best)}</span>
        </div>
      )}
      {typeof gainVsPb === 'number' && isFinite(gainVsPb) && (
        <div className={styles.kvRow}>
          <span>Gain vs PB</span>
          <span className={styles.positive}>{fmtDelta(-gainVsPb)}</span>
        </div>
      )}
    </div>
  )
}

function SpeechLog({ state }: { state: StatePayload }) {
  const log = Array.isArray(state.speech_log) ? state.speech_log.slice(-6).reverse() : []
  if (log.length === 0) return null
  return (
    <div className={styles.card}>
      <h3>Marco says…</h3>
      {log.map((entry, i) => (
        <div key={i} className={`${styles.speechEntry} ${i === 0 ? styles.speechLatest : ''}`}>
          "{String(entry?.text ?? '')}"
        </div>
      ))}
    </div>
  )
}

// ─── main screen ───────────────────────────────────────────────────────────────

export default function TelemetryScreen() {
  const navigate = useNavigate()
  const { state, socketConnected, startSession, stopSession } = useApp()
  const [compareSource, setCompareSource] = useState<'current' | 'last'>('last')
  const [compareEnabled, setCompareEnabled] = useState(true)

  const isActive = state?.active ?? false
  const delta = safeNum(state?.delta)
  const speed = safeNum(state?.speed)
  const gear = state?.gear ?? 'N'
  const lap = state?.lap ?? '--'

  const deltaClass =
    delta === 0 ? styles.deltaNeutral : delta < 0 ? styles.deltaNeg : styles.deltaPos

  return (
    <div className={styles.screen}>
      {/* ── top bar ── */}
      <div className={styles.topBar}>
        <button className={styles.backBtn} onClick={() => navigate('/')}>← Menu</button>
        <span className={styles.topTitle}>Telemetry</span>
        <span className={`${styles.liveIndicator} ${socketConnected ? styles.livePing : ''}`}>
          {socketConnected ? '⬤ Live' : '○ Polling'}
        </span>
      </div>

      <div className={styles.grid}>
        {/* ─── LEFT — track panel ─── */}
        <div className={styles.trackPanel}>
          <div className={styles.canvasWrap}>
            <TrackCanvas state={state} compareSource={compareEnabled ? compareSource : undefined} />
            <div className={`${styles.deltaOverlay} ${deltaClass}`}>
              {delta === 0 ? '--' : fmtDelta(delta)}
            </div>
          </div>

          {state && <SectorBars state={state} />}

          <div className={styles.compareRow}>
            <label className={styles.checkLabel}>
              <input
                type="checkbox"
                checked={compareEnabled}
                onChange={e => setCompareEnabled(e.target.checked)}
              />
              Compare vs PB
            </label>
            <select
              className={styles.compareSelect}
              value={compareSource}
              onChange={e => setCompareSource(e.target.value as 'current' | 'last')}
            >
              <option value="last">Last Lap</option>
              <option value="current">Current Lap</option>
            </select>
          </div>

          <div className={styles.telemetryBar}>
            <div className={styles.telVal}>
              <span className={styles.telLabel}>SPD</span>
              <span className={styles.telNumber}>{Math.round(speed)}</span>
            </div>
            <div className={styles.telVal}>
              <span className={styles.telLabel}>GEAR</span>
              <span className={styles.telNumber}>{gear}</span>
            </div>
            <div className={styles.telVal}>
              <span className={styles.telLabel}>LAP</span>
              <span className={styles.telNumber}>{lap}</span>
            </div>
          </div>
        </div>

        {/* ─── RIGHT — laps / analytics panel ─── */}
        <div className={styles.lapsPanel}>
          {state?.fastest_lap && (
            <div className={styles.fastRow}>
              <span className={styles.fastLabel}>FASTEST</span>
              <span className={styles.fastLap}>Lap {state.fastest_lap.lap_num}</span>
              <span className={styles.fastTime}>{fmt(state.fastest_lap.time)}</span>
            </div>
          )}
          {state?.optimal_lap?.sectors_best != null && safeNum(state.optimal_lap.sectors_best) > 0 && (
            <div className={styles.optRow}>
              <span className={styles.fastLabel}>OPTIMAL</span>
              <span className={styles.fastTime}>{fmt(state.optimal_lap.sectors_best)}</span>
              {state.optimal_lap.gain_vs_pb_sectors != null && (
                <span className={styles.gain}>
                  {fmtDelta(-safeNum(state.optimal_lap.gain_vs_pb_sectors))}
                </span>
              )}
            </div>
          )}

          {state && <LapList laps={state.laps ?? []} fastest={state.fastest_lap} />}
          {state && <SpeechLog state={state} />}
          {state && <TimeLossCard state={state} />}
          {state && <ConsistencyCard state={state} />}
          {state && <SkillCard state={state} />}
          {state && <ProfileCard state={state} />}
          {state && <MasteryCard state={state} />}
          {state && <OptimalCard state={state} />}
        </div>
      </div>

      {/* ── controls ── */}
      <div className={styles.controls}>
        <button className={`${styles.ctrlBtn} ${styles.btnCoach}`} disabled={isActive} onClick={() => startSession(1)}>
          Live Coaching
        </button>
        <button className={`${styles.ctrlBtn} ${styles.btnLog}`} disabled={isActive} onClick={() => startSession(2)}>
          Coaching + Log
        </button>
        <button className={`${styles.ctrlBtn} ${styles.btnStop}`} disabled={!isActive} onClick={stopSession}>
          Stop Session
        </button>
      </div>
    </div>
  )
}
