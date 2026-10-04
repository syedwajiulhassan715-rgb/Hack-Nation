// Ring ripple from a city outward (new law ingested), 1.6 s.
import type { Map as MlMap, GeoJSONSource } from 'maplibre-gl'

export function ripple(map: MlMap, lng: number, lat: number, reduced: boolean) {
  const src = map.getSource('ripple') as GeoJSONSource | undefined
  if (!src) return
  src.setData({ type: 'FeatureCollection', features: [{ type: 'Feature', properties: {}, geometry: { type: 'Point', coordinates: [lng, lat] } }] })
  if (reduced) {
    map.setPaintProperty('ripple', 'circle-radius', 120)
    map.setPaintProperty('ripple', 'circle-stroke-opacity', 0.8)
    setTimeout(() => map.setPaintProperty('ripple', 'circle-stroke-opacity', 0), 1600)
    return
  }
  const t0 = performance.now()
  const dur = 1600
  const step = (now: number) => {
    const t = Math.min(1, (now - t0) / dur)
    map.setPaintProperty('ripple', 'circle-radius', 10 + 260 * t)
    map.setPaintProperty('ripple', 'circle-stroke-opacity', 0.9 * (1 - t))
    if (t < 1) requestAnimationFrame(step)
  }
  requestAnimationFrame(step)
}
