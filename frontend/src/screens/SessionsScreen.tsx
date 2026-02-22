import { useEffect, useState } from 'react'
import { useNavigate, Link } from 'react-router-dom'
import { useToast } from '../context/ToastContext'
import { useRoutePrefix } from '../hooks/useRoutePrefix'
import styles from '../styles/sessions.module.css'

// ─── types ────────────────────────────────────────────────────────────────────

interface SessionMeta {
  folder: string
  path: string
  num_laps: number
  report_available: boolean
  report_summary: {
    laps_analyzed: number
    best_skill_area: string | null
    generated_at: string | null
  } | null
}

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

function fmtDate(iso: string | null | undefined): string {
  if (!iso) return '--'
  try {
    return new Date(iso).toLocaleString()
  } catch {
    return iso
  }
}

function folderToDate(folder: string): string {
  // session_001_20260219_010925 → "Feb 19 2026, 01:09"
  const m = folder.match(/(\d{4})(\d{2})(\d{2})_(\d{2})(\d{2})/)
  if (!m) return folder
  const [, y, mo, d, h, min] = m
  return `${d}/${mo}/${y}  ${h}:${min}`
}

// ─── report detail view ───────────────────────────────────────────────────────

function ReportDetail({ report, folder }: { report: Report; folder: string }) {
  const { addToast } = useToast()

  const openFolder = async () => {
    try {
      const res = await fetch(`/session/${folder}/open-folder`, { method: 'POST' })
      const data = await res.json()
      if (data.ok) {
        addToast('Opened folder in Explorer', 'success')
      } else {
        addToast(`Could not open folder: ${data.error ?? 'unknown error'}`, 'warning')
      }
    } catch {
      addToast('Open folder failed (phone browser cannot open PC folders)', 'warning')
    }
  }

  const skills = report.skill_scores ?? {}
  const losses = report.biggest_time_loss_corners ?? []
  const focuses = report.practice_focuses ?? []
  const tags = report.driver_profile_tags ?? []
  const cons = report.consistency
  const opt = report.optimal_lap

  return (
    <div className={styles.reportWrap}>
      {/* header row */}
      <div className={styles.reportHeader}>
        <div className={styles.reportMeta}>
          <span>{report.laps_analyzed ?? '--'} laps analysed</span>
          <span>·</span>
          <span>{fmtDate(report.generated_at)}</span>
          {report.final && <span className={styles.finalBadge}>Final</span>}
        </div>
        <button className={styles.openBtn} onClick={openFolder}>
          📂 Open folder
        </button>
      </div>

      {/* path hint */}
      <div className={styles.pathHint}>
        session_data/{folder}/
      </div>

      <div className={styles.reportGrid}>

        {/* skill scores */}
        {Object.keys(skills).length > 0 && (
          <div className={styles.reportCard}>
            <h4>Skill Scores</h4>
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

        {/* time losses */}
        {losses.length > 0 && (
          <div className={styles.reportCard}>
            <h4>Top Time Losses</h4>
            {losses.map((l, i) => (
              <div key={i} className={styles.kvRow}>
                <span>Turn {l.turn}</span>
                <span className={styles.neg}>+{l.avg_delta.toFixed(3)}s</span>
              </div>
            ))}
            {report.most_improved_corner && (
              <div className={styles.kvRow}>
                <span>Most improved</span>
                <span className={styles.pos}>
                  T{report.most_improved_corner.turn}{' '}
                  {report.most_improved_corner.delta_gain > 0
                    ? `−${report.most_improved_corner.delta_gain.toFixed(3)}s`
                    : `${report.most_improved_corner.delta_gain.toFixed(3)}s`}
                </span>
              </div>
            )}
          </div>
        )}

        {/* consistency */}
        {cons && (
          <div className={styles.reportCard}>
            <h4>Consistency</h4>
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
                <span>Worst corner</span>
                <span>T{cons.most_inconsistent_corner.turn} {fmtSigma(cons.most_inconsistent_corner.sigma)}</span>
              </div>
            )}
            {typeof cons.braking_point_sigma === 'number' && (
              <div className={styles.kvRow}>
                <span>Brake point σ</span>
                <span>{fmtSigma(cons.braking_point_sigma)}</span>
              </div>
            )}
          </div>
        )}

        {/* optimal lap */}
        {opt && (opt.sectors_best ?? 0) > 0 && (
          <div className={styles.reportCard}>
            <h4>Optimal Lap</h4>
            {opt.sectors_best != null && (
              <div className={styles.kvRow}>
                <span>Sector-based</span>
                <span className={styles.pb}>{fmt(opt.sectors_best)}</span>
              </div>
            )}
            {opt.bins_best != null && (
              <div className={styles.kvRow}>
                <span>Bin-based</span>
                <span className={styles.pb}>{fmt(opt.bins_best)}</span>
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
          <div className={styles.reportCard}>
            <h4>Driver Profile</h4>
            <div className={styles.tagList}>
              {tags.map((t, i) => <span key={i} className={styles.tag}>{t}</span>)}
            </div>
          </div>
        )}

        {/* practice focuses */}
        {focuses.length > 0 && (
          <div className={styles.reportCard}>
            <h4>Practice Focus</h4>
            {focuses.map((f, i) => (
              <div key={i} className={styles.focusRow}>▸ {f}</div>
            ))}
          </div>
        )}

      </div>
    </div>
  )
}

// ─── main screen ──────────────────────────────────────────────────────────────

export default function SessionsScreen() {
  const navigate = useNavigate()
  const { withPrefix } = useRoutePrefix()
  const { addToast } = useToast()
  const [sessions, setSessions] = useState<SessionMeta[]>([])
  const [loading, setLoading] = useState(true)
  const [expanded, setExpanded] = useState<string | null>(null)
  const [reports, setReports] = useState<Record<string, Report | 'loading' | 'error'>>({})

  useEffect(() => {
    fetch('/sessions')
      .then(r => r.json())
      .then((data: SessionMeta[]) => {
        setSessions([...data].reverse())   // newest first
        setLoading(false)
      })
      .catch(() => {
        addToast('Could not load sessions', 'error')
        setLoading(false)
      })
  }, [addToast])

  const toggle = async (folder: string, hasReport: boolean) => {
    if (expanded === folder) { setExpanded(null); return }
    setExpanded(folder)
    if (!hasReport || reports[folder]) return

    setReports(prev => ({ ...prev, [folder]: 'loading' }))
    try {
      const res = await fetch(`/session/${folder}/report`)
      const data = await res.json()
      if (data.ok && data.report) {
        setReports(prev => ({ ...prev, [folder]: data.report as Report }))
      } else {
        setReports(prev => ({ ...prev, [folder]: 'error' }))
        addToast('Could not load report for this session', 'warning')
      }
    } catch {
      setReports(prev => ({ ...prev, [folder]: 'error' }))
      addToast('Failed to fetch report', 'error')
    }
  }

  const sessionNum = (folder: string) => {
    const m = folder.match(/session_(\d+)/)
    return m ? `#${parseInt(m[1])}` : folder
  }

  return (
    <div className={styles.screen}>
      {/* top bar */}
      <div className={styles.topBar}>
        <button className={styles.backBtn} onClick={() => navigate(withPrefix('/'))}>← Menu</button>
        <span className={styles.topTitle}>Past Sessions</span>
        <span className={styles.count}>{sessions.length} session{sessions.length !== 1 ? 's' : ''}</span>
      </div>

      <div className={styles.list}>
        {loading && (
          <div className={styles.empty}>Loading sessions…</div>
        )}

        {!loading && sessions.length === 0 && (
          <div className={styles.empty}>
            No sessions found.<br />
            Start a "Coaching + Log" session to generate a report.
          </div>
        )}

        {sessions.map(s => {
          const isOpen = expanded === s.folder
          const rep = reports[s.folder]

          return (
            <div key={s.folder} className={`${styles.card} ${isOpen ? styles.cardOpen : ''}`}>
              {/* session header — always visible */}
              <button className={styles.cardHeader} onClick={() => toggle(s.folder, s.report_available)}>
                <div className={styles.cardLeft}>
                  <span className={styles.sessionNum}>{sessionNum(s.folder)}</span>
                  <div className={styles.cardInfo}>
                    <span className={styles.sessionDate}>{folderToDate(s.folder)}</span>
                    <span className={styles.sessionSub}>
                      {s.num_laps} lap{s.num_laps !== 1 ? 's' : ''}
                      {s.report_summary?.best_skill_area
                        ? ` · Best: ${s.report_summary.best_skill_area}`
                        : ''}
                    </span>
                  </div>
                </div>
                <div className={styles.cardRight}>
                  {s.report_available
                    ? <span className={styles.reportBadge}>Report ✓</span>
                    : <span className={styles.noReportBadge}>No report</span>
                  }
                  <Link
                    to={withPrefix(`/sessions/${s.folder}`)}
                    className={styles.analyzeBtn}
                    onClick={e => e.stopPropagation()}
                  >
                    Analyze →
                  </Link>
                  <span className={styles.chevron}>{isOpen ? '▲' : '▼'}</span>
                </div>
              </button>

              {/* expanded content */}
              {isOpen && (
                <div className={styles.cardBody}>
                  {!s.report_available && (
                    <div className={styles.noReport}>
                      <p>No performance report for this session.</p>
                      <p>Use <strong>Coaching + Log</strong> to generate one.</p>
                      <div className={styles.pathHint}>session_data/{s.folder}/</div>
                    </div>
                  )}
                  {s.report_available && rep === 'loading' && (
                    <div className={styles.loading}>Loading report…</div>
                  )}
                  {s.report_available && rep === 'error' && (
                    <div className={styles.noReport}>Failed to load report.</div>
                  )}
                  {s.report_available && rep && rep !== 'loading' && rep !== 'error' && (
                    <ReportDetail report={rep} folder={s.folder} />
                  )}
                </div>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}
