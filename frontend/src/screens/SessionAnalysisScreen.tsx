import { useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { useToast } from '../context/ToastContext'
import AnalysisCanvas, { type HeatmapPoint } from '../components/AnalysisCanvas'
import styles from '../styles/analysis.module.css'

// ─── types ────────────────────────────────────────────────────────────────────

interface LapEntry { lap_num: number; time: number; valid: boolean }

interface Report {
  generated_at?: string
  final?: boolean
  laps_analyzed?: number
  biggest_time_loss_corners?: Array<{ turn: number; avg_delta: number }>
  most_improved_corner?: { turn: number; delta_gain: number } | null
  best_skill_area?: string | null
  practice_focuses?: string[]
  driver_profile_tags?: string[]
  skill_scores?: Record<string, number>
  consistency?: {
    lap_sigma: number | null
    sector_sigma?: { s1: number | null; s2: number | null; s3: number | null }
    most_inconsistent_corner?: { turn: number; sigma: number } | null
    most_consistent_corner?: { turn: number; sigma: number } | null
    braking_point_sigma?: number | null
  }
  optimal_lap?: {
    sectors_best: number | null
    bins_best: number | null
    gain_vs_pb_sectors: number | null
    gain_vs_pb_bins: number | null
  }
}

interface AnalysisData {
  folder: string
  track_outline: [number, number][]
  heatmap: HeatmapPoint[]
  laps: LapEntry[]
  pb_time: number | null
  report: Report | null
}

// ─── helpers ──────────────────────────────────────────────────────────────────

function fmt(sec: unknown): string {
  const n = typeof sec === 'number' && isFinite(sec) ? sec : 0
  const m = Math.floor(n / 60)
  const s = (n % 60).toFixed(3)
  return `${m}:${s.padStart(6, '0')}`
}

function fmtSigma(v: unknown): string {
  return typeof v === 'number' && isFinite(v) ? `±${v.toFixed(3)}s` : '--'
}

function folderToDate(folder: string): string {
  const m = folder.match(/(\d{4})(\d{2})(\d{2})_(\d{2})(\d{2})/)
  if (!m) return folder
  const [, y, mo, d, h, min] = m
  return `${d}/${mo}/${y}  ${h}:${min}`
}

function sessionNum(folder: string): string {
  const m = folder.match(/session_(\d+)/)
  return m ? `#${parseInt(m[1])}` : folder
}

// ─── main screen ──────────────────────────────────────────────────────────────

export default function SessionAnalysisScreen() {
  const { sessionId } = useParams<{ sessionId: string }>()
  const navigate = useNavigate()
  const { addToast } = useToast()

  const [data, setData] = useState<AnalysisData | null>(null)
  const [loading, setLoading] = useState(true)
  const [mapMode, setMapMode] = useState<'speed' | 'inputs'>('speed')

  useEffect(() => {
    if (!sessionId) return
    fetch(`/session/${sessionId}/track-data`)
      .then(r => r.json())
      .then(d => {
        if (d.ok) setData(d)
        else addToast(`Load failed: ${d.error ?? 'unknown error'}`, 'error')
        setLoading(false)
      })
      .catch(() => {
        addToast('Could not load session analysis', 'error')
        setLoading(false)
      })
  }, [sessionId, addToast])

  // ── loading / error states ────────────────────────────────────────────────

  if (loading || !data) {
    return (
      <div className={styles.screen}>
        <div className={styles.topBar}>
          <button className={styles.backBtn} onClick={() => navigate('/sessions')}>← Sessions</button>
          <div className={styles.topCenter}>
            <span className={styles.sessionDate}>{loading ? 'Loading…' : 'Failed to load'}</span>
          </div>
        </div>
        <div className={styles.loadingMsg}>{loading ? 'Loading session analysis…' : 'Could not load session data.'}</div>
      </div>
    )
  }

  const report = data.report
  const skills  = report?.skill_scores ?? {}
  const losses  = report?.biggest_time_loss_corners ?? []
  const focuses = report?.practice_focuses ?? []
  const tags    = report?.driver_profile_tags ?? []
  const cons    = report?.consistency
  const opt     = report?.optimal_lap

  // ── render ────────────────────────────────────────────────────────────────

  return (
    <div className={styles.screen}>
      {/* ── top bar ── */}
      <div className={styles.topBar}>
        <button className={styles.backBtn} onClick={() => navigate('/sessions')}>← Sessions</button>
        <div className={styles.topCenter}>
          <span className={styles.sessionNum}>{sessionNum(data.folder)}</span>
          <span className={styles.sessionDate}>{folderToDate(data.folder)}</span>
        </div>
        {data.pb_time != null && (
          <span className={styles.pbChip}>Best {fmt(data.pb_time)}</span>
        )}
      </div>

      <div className={styles.content}>

        {/* ── track map + lap list ── */}
        <div className={styles.mapSection}>

          {/* map */}
          <div className={styles.mapWrap}>
            <div className={styles.mapToggle}>
              <button
                className={`${styles.toggleBtn} ${mapMode === 'speed' ? styles.toggleActive : ''}`}
                onClick={() => setMapMode('speed')}
              >Speed</button>
              <button
                className={`${styles.toggleBtn} ${mapMode === 'inputs' ? styles.toggleActive : ''}`}
                onClick={() => setMapMode('inputs')}
              >Inputs</button>
            </div>

            <div className={styles.mapCanvas}>
              <AnalysisCanvas
                trackOutline={data.track_outline}
                heatmap={data.heatmap}
                mode={mapMode}
              />
            </div>

            <div className={styles.mapLegend}>
              {mapMode === 'speed' ? (
                <>
                  <span style={{ color: '#ef5350' }}>● Slow</span>
                  <span style={{ color: '#ffeb3b' }}>● Mid</span>
                  <span style={{ color: '#69f0ae' }}>● Fast</span>
                </>
              ) : (
                <>
                  <span style={{ color: '#69f0ae' }}>● Throttle</span>
                  <span style={{ color: '#8090a0' }}>● Coast</span>
                  <span style={{ color: '#ef5350' }}>● Braking</span>
                </>
              )}
            </div>
          </div>

          {/* lap list */}
          <div className={styles.lapSection}>
            <div className={styles.cardTitle}>Lap Times</div>
            {data.laps.length === 0 ? (
              <p className={styles.muted}>No lap data</p>
            ) : (
              <div className={styles.lapList}>
                {data.laps.map(lap => {
                  const isPb = data.pb_time != null && Math.abs(lap.time - data.pb_time) < 0.001
                  const rowCls = `${styles.lapRow} ${isPb ? styles.lapPb : lap.valid ? styles.lapValid : styles.lapInvalid}`
                  return (
                    <div key={lap.lap_num} className={rowCls}>
                      <span className={styles.lapNum}>Lap {lap.lap_num}</span>
                      <span className={styles.lapTime}>{fmt(lap.time)}</span>
                      <span className={styles.lapTag}>
                        {isPb ? 'PB' : lap.valid ? 'OK' : 'INV'}
                      </span>
                    </div>
                  )
                })}
              </div>
            )}
          </div>
        </div>

        {/* ── key stats row ── */}
        <div className={styles.statsRow}>
          <div className={styles.statChip}>
            <span className={styles.statLabel}>Laps</span>
            <span className={styles.statVal}>{report?.laps_analyzed ?? data.laps.length}</span>
          </div>
          {data.pb_time != null && (
            <div className={styles.statChip}>
              <span className={styles.statLabel}>Best Lap</span>
              <span className={`${styles.statVal} ${styles.purple}`}>{fmt(data.pb_time)}</span>
            </div>
          )}
          {opt?.sectors_best != null && opt.sectors_best > 0 && (
            <div className={styles.statChip}>
              <span className={styles.statLabel}>Optimal Lap</span>
              <span className={`${styles.statVal} ${styles.purple}`}>{fmt(opt.sectors_best)}</span>
            </div>
          )}
          {report?.best_skill_area && (
            <div className={styles.statChip}>
              <span className={styles.statLabel}>Best Skill</span>
              <span className={styles.statVal}>{report.best_skill_area}</span>
            </div>
          )}
          {cons?.lap_sigma != null && (
            <div className={styles.statChip}>
              <span className={styles.statLabel}>Lap σ</span>
              <span className={styles.statVal}>{fmtSigma(cons.lap_sigma)}</span>
            </div>
          )}
        </div>

        {/* ── report cards ── */}
        {report ? (
          <div className={styles.reportGrid}>

            {/* skill scores */}
            {Object.keys(skills).length > 0 && (
              <div className={styles.card}>
                <div className={styles.cardTitle}>Skill Scores</div>
                {Object.entries(skills).map(([name, val]) => {
                  const pct = Math.max(0, Math.min(100, typeof val === 'number' ? val : 0))
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
                {report.best_skill_area && (
                  <div className={styles.bestSkill}>⭐ Best: {report.best_skill_area}</div>
                )}
              </div>
            )}

            {/* top time losses */}
            {losses.length > 0 && (
              <div className={styles.card}>
                <div className={styles.cardTitle}>Top Time Losses</div>
                {losses.map((l, i) => (
                  <div key={i} className={styles.kvRow}>
                    <span>Turn {l.turn}</span>
                    <span className={styles.neg}>+{l.avg_delta.toFixed(3)}s</span>
                  </div>
                ))}
                {report.most_improved_corner && (
                  <div className={styles.kvRow}>
                    <span>Most Improved</span>
                    <span className={styles.pos}>
                      T{report.most_improved_corner.turn}{' '}
                      −{Math.abs(report.most_improved_corner.delta_gain).toFixed(3)}s
                    </span>
                  </div>
                )}
              </div>
            )}

            {/* consistency */}
            {cons && (
              <div className={styles.card}>
                <div className={styles.cardTitle}>Consistency</div>
                <div className={styles.kvRow}><span>Lap σ</span><span>{fmtSigma(cons.lap_sigma)}</span></div>
                {cons.sector_sigma && (
                  <>
                    <div className={styles.kvRow}><span>S1 σ</span><span>{fmtSigma(cons.sector_sigma.s1)}</span></div>
                    <div className={styles.kvRow}><span>S2 σ</span><span>{fmtSigma(cons.sector_sigma.s2)}</span></div>
                    <div className={styles.kvRow}><span>S3 σ</span><span>{fmtSigma(cons.sector_sigma.s3)}</span></div>
                  </>
                )}
                {cons.most_inconsistent_corner && (
                  <div className={styles.kvRow}>
                    <span>Worst Corner</span>
                    <span>T{cons.most_inconsistent_corner.turn} {fmtSigma(cons.most_inconsistent_corner.sigma)}</span>
                  </div>
                )}
                {cons.most_consistent_corner && (
                  <div className={styles.kvRow}>
                    <span>Best Corner</span>
                    <span>T{cons.most_consistent_corner.turn}</span>
                  </div>
                )}
                {typeof cons.braking_point_sigma === 'number' && (
                  <div className={styles.kvRow}>
                    <span>Brake Point σ</span>
                    <span>{fmtSigma(cons.braking_point_sigma)}</span>
                  </div>
                )}
              </div>
            )}

            {/* optimal lap */}
            {opt && opt.sectors_best != null && opt.sectors_best > 0 && (
              <div className={styles.card}>
                <div className={styles.cardTitle}>Optimal Lap</div>
                <div className={styles.kvRow}>
                  <span>Sector-based</span>
                  <span className={styles.purple}>{fmt(opt.sectors_best)}</span>
                </div>
                {opt.bins_best != null && opt.bins_best > 0 && (
                  <div className={styles.kvRow}>
                    <span>Bin-based</span>
                    <span className={styles.purple}>{fmt(opt.bins_best)}</span>
                  </div>
                )}
                {opt.gain_vs_pb_sectors != null && (
                  <div className={styles.kvRow}>
                    <span>Gain vs PB</span>
                    <span className={styles.pos}>−{Math.abs(opt.gain_vs_pb_sectors).toFixed(3)}s</span>
                  </div>
                )}
              </div>
            )}

            {/* driver profile */}
            {tags.length > 0 && (
              <div className={styles.card}>
                <div className={styles.cardTitle}>Driver Profile</div>
                <div className={styles.tagList}>
                  {tags.map((t, i) => <span key={i} className={styles.tag}>{t}</span>)}
                </div>
              </div>
            )}

            {/* practice focuses */}
            {focuses.length > 0 && (
              <div className={styles.card}>
                <div className={styles.cardTitle}>Practice Focus</div>
                {focuses.map((f, i) => (
                  <div key={i} className={styles.focusRow}>▸ {f}</div>
                ))}
              </div>
            )}

          </div>
        ) : (
          <div className={styles.noReport}>
            No performance report for this session.<br />
            Use <strong>Coaching + Logging</strong> mode to generate one next time.
          </div>
        )}

      </div>
    </div>
  )
}
