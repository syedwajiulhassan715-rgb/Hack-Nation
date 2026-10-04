import { useEffect, useMemo, useRef, useState } from 'react'
import { Pause, Play, RotateCcw } from 'lucide-react'
import { addDays, dayIndex, prettyDate, snapToTick } from '../lib/dates'

export const SLIDER_MIN = '2024-01-01'
export const SLIDER_MAX = '2028-12-31'

interface Props {
  value: string
  defaultAsOf: string
  globalTicks: string[]
  buildingTicks: string[]
  /** live, while dragging (recolor beacons only) */
  onPreview: (d: string) => void
  /** on release (refetch the selected building) */
  onCommit: (d: string) => void
}

export function DateSlider({ value, defaultAsOf, globalTicks, buildingTicks, onPreview, onCommit }: Props) {
  const total = dayIndex(SLIDER_MIN, SLIDER_MAX)
  const [playing, setPlaying] = useState(false)
  const timer = useRef<number | null>(null)
  const ticks = useMemo(() => {
    const inRange = (d: string) => d >= SLIDER_MIN && d <= SLIDER_MAX
    const all = new Set([...globalTicks.filter(inRange), ...buildingTicks.filter(inRange)])
    return [...all].sort()
  }, [globalTicks, buildingTicks])
  const bset = useMemo(() => new Set(buildingTicks), [buildingTicks])

  const fromIndex = (i: number) => snapToTick(addDays(SLIDER_MIN, i), ticks)
  const pos = Math.min(total, Math.max(0, dayIndex(SLIDER_MIN, value)))

  useEffect(() => {
    if (!playing) return
    const seq = ticks.filter((t) => t > value)
    if (!seq.length) {
      setPlaying(false)
      return
    }
    timer.current = window.setTimeout(() => {
      onPreview(seq[0])
      onCommit(seq[0])
    }, 1200)
    return () => {
      if (timer.current) window.clearTimeout(timer.current)
    }
  }, [playing, value, ticks, onPreview, onCommit])

  return (
    <div className="slider">
      <div className="slider-controls">
        <button
          type="button"
          className="icon-btn dark"
          onClick={() => {
            if (!playing && !ticks.some((t) => t > value)) {
              onPreview(ticks[0] ?? SLIDER_MIN)
              onCommit(ticks[0] ?? SLIDER_MIN)
            }
            setPlaying((p) => !p)
          }}
          aria-label={playing ? 'Pause' : 'Play through key dates'}
          title={playing ? 'Pause' : 'Play through key dates'}
        >
          {playing ? <Pause size={18} /> : <Play size={18} />}
        </button>
        <button
          type="button"
          className="btn-dark"
          onClick={() => {
            setPlaying(false)
            onPreview(defaultAsOf)
            onCommit(defaultAsOf)
          }}
          title="Reset to the default query date"
        >
          <RotateCcw size={14} /> Today
        </button>
      </div>
      <div className="slider-track-wrap">
        <div className="slider-readout" style={{ left: `${(pos / total) * 100}%` }}>
          {prettyDate(value)}
        </div>
        <div className="slider-ticks" aria-hidden>
          {ticks.map((t) => (
            <span
              key={t}
              className={`tick${bset.has(t) ? ' tick-b' : ''}`}
              style={{ left: `${(dayIndex(SLIDER_MIN, t) / total) * 100}%` }}
              title={prettyDate(t)}
            />
          ))}
        </div>
        <input
          type="range"
          className="slider-input"
          min={0}
          max={total}
          step={1}
          value={pos}
          aria-label="As-of date"
          aria-valuetext={prettyDate(value)}
          onChange={(e) => {
            setPlaying(false)
            onPreview(fromIndex(Number(e.target.value)))
          }}
          onPointerUp={() => onCommit(value)}
          onKeyUp={() => onCommit(value)}
          onTouchEnd={() => onCommit(value)}
        />
        <div className="slider-ends mono">
          <span>{SLIDER_MIN.slice(0, 4)}</span>
          <span>{SLIDER_MAX.slice(0, 4)}</span>
        </div>
      </div>
    </div>
  )
}
