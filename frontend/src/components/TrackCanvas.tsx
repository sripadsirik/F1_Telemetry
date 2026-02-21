import { useRef, useEffect, useCallback } from 'react'
import type { StatePayload } from '../types'

interface Props {
  state: StatePayload | null
  compareSource?: 'current' | 'last'
}

// ─── helpers ──────────────────────────────────────────────────────────────────

function getBBox(pts: [number, number][]) {
  let minX = Infinity, maxX = -Infinity, minZ = Infinity, maxZ = -Infinity
  for (const [x, z] of pts) {
    if (x < minX) minX = x
    if (x > maxX) maxX = x
    if (z < minZ) minZ = z
    if (z > maxZ) maxZ = z
  }
  return { minX, maxX, minZ, maxZ }
}

function worldToCanvas(
  x: number, z: number,
  bbox: ReturnType<typeof getBBox>,
  w: number, h: number,
  pad = 24,
): [number, number] {
  const rangeX = bbox.maxX - bbox.minX || 1
  const rangeZ = bbox.maxZ - bbox.minZ || 1
  const scale = Math.min((w - 2 * pad) / rangeX, (h - 2 * pad) / rangeZ)
  const cx = pad + (x - bbox.minX) * scale + ((w - 2 * pad) - rangeX * scale) / 2
  const cy = pad + (z - bbox.minZ) * scale + ((h - 2 * pad) - rangeZ * scale) / 2
  return [cx, cy]
}

function deltaToColor(delta: number): string {
  if (Math.abs(delta) < 0.02) return 'rgba(140,140,160,0.6)'
  if (delta < 0) {
    const t = Math.min(Math.abs(delta) / 0.5, 1)
    return `rgba(${Math.round(30 + 20 * (1 - t))},${Math.round(160 + 90 * t)},70,0.85)`
  }
  const t = Math.min(delta / 0.5, 1)
  return `rgba(${Math.round(210 + 40 * t)},${Math.round(170 - 120 * t)},60,0.85)`
}

// ─── component ────────────────────────────────────────────────────────────────

export default function TrackCanvas({ state, compareSource = 'last' }: Props) {
  const wrapRef = useRef<HTMLDivElement>(null)
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const stateRef = useRef<StatePayload | null>(null)
  const compareRef = useRef(compareSource)
  const carRender = useRef<[number, number]>([0, 0])
  const rafRef = useRef(0)

  // Keep refs in sync
  useEffect(() => { stateRef.current = state }, [state])
  useEffect(() => { compareRef.current = compareSource }, [compareSource])

  // Stable draw loop
  const draw = useCallback(() => {
    const canvas = canvasRef.current
    if (!canvas) { rafRef.current = requestAnimationFrame(draw); return }
    const ctx = canvas.getContext('2d')
    if (!ctx) { rafRef.current = requestAnimationFrame(draw); return }

    const s = stateRef.current
    const { width: w, height: h } = canvas
    ctx.clearRect(0, 0, w, h)

    if (!s) { rafRef.current = requestAnimationFrame(draw); return }

    // Guard all arrays — the state can arrive partially during socket merges
    const trackPts: [number, number][] = Array.isArray(s.track_outline) ? s.track_outline : []
    const heatPts:  [number, number][] = Array.isArray(s.heatmap_points) ? s.heatmap_points : []
    const rawDeltas = compareRef.current === 'current' ? s.segment_deltas : s.last_lap_segment_deltas
    const deltas: number[] = Array.isArray(rawDeltas) ? rawDeltas : []

    // Reference points for bounding box — prefer track outline, fall back to trail
    const refPts = trackPts.length > 2 ? trackPts : heatPts
    if (refPts.length < 2) { rafRef.current = requestAnimationFrame(draw); return }

    const bbox = getBBox(refPts)

    // ── track outline ──────────────────────────────────────────────────────
    if (trackPts.length > 1) {
      ctx.beginPath()
      const [sx, sy] = worldToCanvas(trackPts[0][0], trackPts[0][1], bbox, w, h)
      ctx.moveTo(sx, sy)
      for (let i = 1; i < trackPts.length; i++) {
        const [cx, cy] = worldToCanvas(trackPts[i][0], trackPts[i][1], bbox, w, h)
        ctx.lineTo(cx, cy)
      }
      ctx.closePath()
      ctx.strokeStyle = '#1a3a5c'
      ctx.lineWidth = 7
      ctx.stroke()
    }

    // ── heatmap overlay ────────────────────────────────────────────────────
    const pathPts = trackPts.length > 2 ? trackPts : heatPts
    if (pathPts.length > 1 && deltas.length > 0) {
      const segCount = deltas.length
      const chunkSize = pathPts.length / segCount
      for (let seg = 0; seg < segCount; seg++) {
        const start = Math.floor(seg * chunkSize)
        const end = Math.min(Math.floor((seg + 1) * chunkSize) + 1, pathPts.length)
        if (end <= start + 1) continue
        ctx.beginPath()
        const [sx, sy] = worldToCanvas(pathPts[start][0], pathPts[start][1], bbox, w, h)
        ctx.moveTo(sx, sy)
        for (let i = start + 1; i < end; i++) {
          const [cx, cy] = worldToCanvas(pathPts[i][0], pathPts[i][1], bbox, w, h)
          ctx.lineTo(cx, cy)
        }
        ctx.strokeStyle = deltaToColor(deltas[seg])
        ctx.lineWidth = 3.5
        ctx.stroke()
      }
    } else if (heatPts.length > 1) {
      // Plain trail when no deltas yet
      ctx.beginPath()
      const [sx, sy] = worldToCanvas(heatPts[0][0], heatPts[0][1], bbox, w, h)
      ctx.moveTo(sx, sy)
      for (let i = 1; i < heatPts.length; i++) {
        const [cx, cy] = worldToCanvas(heatPts[i][0], heatPts[i][1], bbox, w, h)
        ctx.lineTo(cx, cy)
      }
      ctx.strokeStyle = 'rgba(79,195,247,0.35)'
      ctx.lineWidth = 2
      ctx.stroke()
    }

    // ── smooth car position ────────────────────────────────────────────────
    const [tx, ty] = worldToCanvas(s.x, s.z, bbox, w, h)
    const [rx, ry] = carRender.current
    carRender.current = [rx + (tx - rx) * 0.18, ry + (ty - ry) * 0.18]
    const [cx, cy] = carRender.current

    ctx.save()
    ctx.shadowColor = '#ff7043'
    ctx.shadowBlur = 10
    ctx.beginPath()
    ctx.arc(cx, cy, 5, 0, Math.PI * 2)
    ctx.fillStyle = '#ff7043'
    ctx.fill()
    ctx.restore()

    rafRef.current = requestAnimationFrame(draw)
  }, [])

  // Start animation loop once
  useEffect(() => {
    rafRef.current = requestAnimationFrame(draw)
    return () => cancelAnimationFrame(rafRef.current)
  }, [draw])

  // Resize canvas to match container
  useEffect(() => {
    const wrap = wrapRef.current
    const canvas = canvasRef.current
    if (!wrap || !canvas) return
    const sync = () => {
      canvas.width = wrap.clientWidth
      canvas.height = wrap.clientHeight
    }
    sync()
    const ro = new ResizeObserver(sync)
    ro.observe(wrap)
    return () => ro.disconnect()
  }, [])

  return (
    <div ref={wrapRef} style={{ width: '100%', height: '100%', position: 'relative' }}>
      <canvas ref={canvasRef} style={{ display: 'block' }} />
    </div>
  )
}
