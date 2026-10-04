// Law-stack slabs: two extruded plates over the selected building, state below and city above.
import type { Feature, FeatureCollection, Polygon, MultiPolygon } from 'geojson'
import type { Map as MlMap, GeoJSONSource } from 'maplibre-gl'

export const SLAB_THICKNESS = 4
export const SLAB_GAP = { state: 18, city: 36 } as const

type Footprint = Feature<Polygon | MultiPolygon>

export function slabFeatures(footprint: Footprint, buildingHeight: number, levels: Array<'state' | 'city'>, t: number[]) {
  const fc: FeatureCollection = { type: 'FeatureCollection', features: [] }
  levels.forEach((level, i) => {
    const e = easeOut(t[i] ?? 1)
    const base = (buildingHeight + SLAB_GAP[level]) * e
    fc.features.push({
      type: 'Feature',
      geometry: footprint.geometry,
      properties: { level, base, top: base + SLAB_THICKNESS * Math.max(e, 0.05) },
    })
  })
  return fc
}

function easeOut(x: number) {
  return 1 - Math.pow(1 - Math.min(1, Math.max(0, x)), 3)
}

/** Animate slabs rising one after another (120 ms stagger). Returns a cancel function. */
export function animateSlabs(
  map: MlMap,
  sourceId: string,
  footprint: Footprint,
  buildingHeight: number,
  levels: Array<'state' | 'city'>,
  reduced: boolean,
): () => void {
  const src = map.getSource(sourceId) as GeoJSONSource | undefined
  if (!src) return () => {}
  if (reduced) {
    src.setData(slabFeatures(footprint, buildingHeight, levels, levels.map(() => 1)))
    return () => {}
  }
  const dur = 600
  const stagger = 120
  const t0 = performance.now()
  let raf = 0
  const step = (now: number) => {
    const ts = levels.map((_, i) => (now - t0 - i * stagger) / dur)
    src.setData(slabFeatures(footprint, buildingHeight, levels, ts))
    if (ts.some((x) => x < 1)) raf = requestAnimationFrame(step)
  }
  raf = requestAnimationFrame(step)
  return () => cancelAnimationFrame(raf)
}
