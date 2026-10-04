// Bird's-eye orbit: after the camera lands on a building it circles it slowly (one full turn
// per ORBIT_SECONDS) until the user presses on the map, scrolls, touches or uses the keyboard.
import type { Map as MlMap } from 'maplibre-gl'

export const ORBIT_SECONDS = 48

const STOP_EVENTS = ['mousedown', 'touchstart', 'wheel', 'keydown', 'pointerdown'] as const

/** Start orbiting around the current center. Returns a stop function (idempotent).
 *  `onStop` fires once, whether the user interrupted or stop() was called. */
export function startOrbit(map: MlMap, onStop: () => void): () => void {
  const el = map.getCanvasContainer()
  let raf = 0
  let last = performance.now()
  let stopped = false

  const step = (now: number) => {
    const dt = Math.min(64, now - last) // a hidden tab must not jump on return
    last = now
    map.setBearing((map.getBearing() + (360 * dt) / (ORBIT_SECONDS * 1000)) % 360)
    raf = requestAnimationFrame(step)
  }

  const stop = () => {
    if (stopped) return
    stopped = true
    cancelAnimationFrame(raf)
    for (const ev of STOP_EVENTS) el.removeEventListener(ev, stop, true)
    onStop()
  }

  for (const ev of STOP_EVENTS) el.addEventListener(ev, stop, { capture: true, passive: true })
  raf = requestAnimationFrame(step)
  return stop
}
