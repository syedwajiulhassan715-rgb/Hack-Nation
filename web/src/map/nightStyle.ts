// Load a light OpenFreeMap style and recolor its layers to the night palette at load time.
// If the tiles are unreachable (offline demo), fall back to a plain night background so the
// beacons still render.
import type { StyleSpecification, LayerSpecification } from 'maplibre-gl'
import { token } from '../lib/colors'

export const STYLE_URL = 'https://tiles.openfreemap.org/styles/positron'

export function minimalNightStyle(): StyleSpecification {
  return {
    version: 8,
    glyphs: 'https://tiles.openfreemap.org/fonts/{fontstack}/{range}.pbf',
    sources: {},
    layers: [{ id: 'background', type: 'background', paint: { 'background-color': token('--night-0') } }],
  }
}

function recolor(layer: LayerSpecification): LayerSpecification | null {
  const id = layer.id.toLowerCase()
  const n0 = token('--night-0')
  const n1 = token('--night-1')
  const n2 = token('--night-2')
  const n3 = token('--night-3')
  const lbl = token('--night-label')
  const l = { ...layer, paint: { ...((layer as { paint?: object }).paint ?? {}) } } as LayerSpecification & {
    paint: Record<string, unknown>
    layout?: Record<string, unknown>
  }
  switch (layer.type) {
    case 'background':
      l.paint['background-color'] = n0
      break
    case 'fill':
      if (/water|ocean|lake|river/.test(id)) l.paint['fill-color'] = n1
      else if (/building/.test(id)) l.paint['fill-color'] = n3
      else if (/park|wood|grass|landcover|green/.test(id)) l.paint['fill-color'] = '#0e1217'
      else l.paint['fill-color'] = n0
      delete l.paint['fill-outline-color']
      delete l.paint['fill-pattern']
      break
    case 'line':
      if (/water|river|stream|canal/.test(id)) l.paint['line-color'] = n1
      else if (/boundary|admin/.test(id)) l.paint['line-color'] = '#2f3640'
      else l.paint['line-color'] = n2
      break
    case 'symbol':
      l.paint['text-color'] = lbl
      l.paint['text-halo-color'] = n0
      l.paint['text-halo-width'] = 1
      l.paint['icon-opacity'] = 0.35
      break
    case 'fill-extrusion':
      l.paint['fill-extrusion-color'] = n3
      break
    case 'raster':
    case 'hillshade':
      return null
  }
  return l
}

export async function loadNightStyle(timeoutMs = 6000): Promise<{ style: StyleSpecification; online: boolean }> {
  const ctrl = new AbortController()
  const t = setTimeout(() => ctrl.abort(), timeoutMs)
  try {
    const res = await fetch(STYLE_URL, { signal: ctrl.signal })
    if (!res.ok) throw new Error(String(res.status))
    const style = (await res.json()) as StyleSpecification
    style.layers = style.layers.map(recolor).filter((x): x is LayerSpecification => x != null)
    return { style, online: true }
  } catch {
    return { style: minimalNightStyle(), online: false }
  } finally {
    clearTimeout(t)
  }
}

/** Name of the OpenMapTiles vector source in the loaded style (for the 3D building layer). */
export function vectorSourceId(style: StyleSpecification): string | null {
  for (const [k, v] of Object.entries(style.sources ?? {})) if ((v as { type: string }).type === 'vector') return k
  return null
}
