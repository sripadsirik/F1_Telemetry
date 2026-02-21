export interface LapEntry {
  lap_num: number
  time: number
  valid: boolean
  is_pb: boolean
}

export interface SpeechEntry {
  text: string
  ts: number
}

export interface FastestLap {
  lap_num: number
  time: number
}

export interface BinMeta {
  count: number
  track_length: number
}

export interface CornerMetric {
  turn: number
  avg_entry_speed?: number
  avg_apex_speed?: number
  avg_exit_speed?: number
  entry_score?: number
  apex_score?: number
  exit_score?: number
}

export interface CornerMastery {
  turn: number
  score: number
  trend: string
}

export interface Consistency {
  lap_sigma: number | null
  sector_sigma: { s1: number | null; s2: number | null; s3: number | null }
  most_inconsistent_corner: { turn: number; sigma: number } | null
  most_consistent_corner: { turn: number; sigma: number } | null
  braking_point_sigma: number | null
}

export interface DriverProfile {
  tags: string[]
  stats: Record<string, number>
}

export interface SkillScores {
  [key: string]: number
}

export interface OptimalLap {
  sectors_best: number | null
  bins_best: number | null
  gain_vs_pb_sectors: number | null
  gain_vs_pb_bins: number | null
}

export interface TimeLossSummary {
  turn: number
  avg_delta: number
}

// sector_colors keys come back as strings ("1","2","3") in JSON
export type SectorColors = Record<string, string | null>

export interface StatePayload {
  active: boolean
  track_outline: [number, number][]
  laps: LapEntry[]
  x: number
  z: number
  speed: number
  gear: number
  lap: number
  delta: number
  sector: number
  sector_colors: SectorColors
  fastest_lap: FastestLap | null
  speech_log: SpeechEntry[]
  bin_meta: BinMeta
  reference_bins: number[]
  current_lap_bins: number[]
  segment_deltas: number[]
  last_lap_segment_deltas: number[]
  heatmap_points: [number, number][]
  corner_metrics: CornerMetric[]
  time_loss_summary: TimeLossSummary[]
  corner_mastery: CornerMastery[]
  consistency: Consistency
  driver_profile: DriverProfile
  skill_scores: SkillScores
  optimal_lap: OptimalLap
  session_report_summary: unknown
}

// Partial update pushed by "telemetry" socket event
export type TelemetryUpdate = Pick<
  StatePayload,
  'x' | 'z' | 'speed' | 'gear' | 'lap' | 'delta' | 'sector' | 'sector_colors' | 'fastest_lap'
>
