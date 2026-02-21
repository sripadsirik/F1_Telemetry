import { useRef, useEffect, useCallback } from 'react'

export interface HeatmapPoint {
  x: number
  z: number
  speed: number
  throttle: number
  brake: number
}

interface Props {
  trackOutline: [number, number][]
  heatmap: HeatmapPoint[]
  mode: 'speed' | 'inputs'
}

// green (fast) → yellow → red (slow)
function speedColor(n: number): string {
  const hue = Math.round(120 * n)
  return `hsl(${hue}, 100%, 50%)`
}

// throttle = green, brake = red, coast = gray
function inputColor(throttle: number, brake: number): string {
  if (brake > 0.05) {
    const i = Math.min(1, brake * 1.5)
    return `rgba(239, ${Math.round(83 * (1 - i))}, ${Math.round(80 * (1 - i * 0.5))}, 0.9)`
  }
  if (throttle > 0.05) {
    const i = throttle
    return `rgba(${Math.round(20 + 80 * (1 - i))}, ${Math.round(200 * i + 50)}, ${Math.round(80 * (1 - i))}, 0.9)`
  }
  return 'rgba(90, 90, 110, 0.7)'
}

export default function AnalysisCanvas({ trackOutline, heatmap, mode }: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const containerRef = useRef<HTMLDivElement>(null)

  const draw = useCallback(() => {
    const canvas = canvasRef.current
    const container = containerRef.current
    if (!canvas || !container) return

    const W = container.clientWidth
    const H = container.clientHeight
    if (W === 0 || H === 0) return

    canvas.width = W
    canvas.height = H

    const ctx = canvas.getContext('2d')
    if (!ctx) return

    ctx.fillStyle = '#0a0a1a'
    ctx.fillRect(0, 0, W, H)

    // Use track outline for bounds; fall back to heatmap coords
    const base: [number, number][] =
      trackOutline.length > 0
        ? trackOutline
        : heatmap.map(p => [p.x, p.z])

    if (base.length === 0) {
      ctx.fillStyle = '#555'
      ctx.font = '13px sans-serif'
      ctx.textAlign = 'center'
      ctx.fillText('No track data available', W / 2, H / 2)
      return
    }

    // Bounding box
    let minX = Infinity, maxX = -Infinity, minZ = Infinity, maxZ = -Infinity
    for (const [x, z] of base) {
      if (x < minX) minX = x
      if (x > maxX) maxX = x
      if (z < minZ) minZ = z
      if (z > maxZ) maxZ = z
    }

    const pad = 28
    const rangeX = maxX - minX || 1
    const rangeZ = maxZ - minZ || 1
    const scale = Math.min((W - pad * 2) / rangeX, (H - pad * 2) / rangeZ)
    const offX = (W - rangeX * scale) / 2
    const offZ = (H - rangeZ * scale) / 2

    const cx = (x: number) => (x - minX) * scale + offX
    const cy = (z: number) => (z - minZ) * scale + offZ

    // Draw track outline (thin gray ribbon)
    if (trackOutline.length > 1) {
      ctx.beginPath()
      ctx.moveTo(cx(trackOutline[0][0]), cy(trackOutline[0][1]))
      for (let i = 1; i < trackOutline.length; i++) {
        ctx.lineTo(cx(trackOutline[i][0]), cy(trackOutline[i][1]))
      }
      ctx.strokeStyle = 'rgba(255,255,255,0.07)'
      ctx.lineWidth = Math.max(5, scale * 1.2)
      ctx.lineJoin = 'round'
      ctx.stroke()
    }

    // Draw heatmap dots
    if (heatmap.length > 0) {
      let minSpd = Infinity, maxSpd = -Infinity
      if (mode === 'speed') {
        for (const p of heatmap) {
          if (p.speed < minSpd) minSpd = p.speed
          if (p.speed > maxSpd) maxSpd = p.speed
        }
      }

      const r = Math.max(1.5, Math.min(3.5, scale * 0.7))

      for (const pt of heatmap) {
        const px = cx(pt.x)
        const py = cy(pt.z)
        const color =
          mode === 'speed'
            ? speedColor(maxSpd > minSpd ? (pt.speed - minSpd) / (maxSpd - minSpd) : 0.5)
            : inputColor(pt.throttle, pt.brake)

        ctx.beginPath()
        ctx.arc(px, py, r, 0, Math.PI * 2)
        ctx.fillStyle = color
        ctx.fill()
      }
    }
  }, [trackOutline, heatmap, mode])

  useEffect(() => {
    draw()
  }, [draw])

  useEffect(() => {
    const el = containerRef.current
    if (!el) return
    const obs = new ResizeObserver(() => draw())
    obs.observe(el)
    return () => obs.disconnect()
  }, [draw])

  return (
    <div ref={containerRef} style={{ width: '100%', height: '100%' }}>
      <canvas
        ref={canvasRef}
        style={{ display: 'block', width: '100%', height: '100%' }}
      />
    </div>
  )
}
