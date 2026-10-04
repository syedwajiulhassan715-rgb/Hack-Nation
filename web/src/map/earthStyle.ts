// "Earth" basemap: aerial imagery on a 3D globe with terrain, sky and the OpenFreeMap labels
// on top. Every source is open and allows browser use:
//   - imagery: USGS The National Map orthoimagery (USDA NAIP), public domain, CORS open,
//     tiles to zoom 16 (MapLibre over-zooms beyond that)
//   - terrain: AWS Terrain Tiles (Mapzen terrarium encoding), open data, CORS open
//   - labels + building footprints: OpenFreeMap (OpenStreetMap, ODbL)
// If the label style is unreachable (offline demo), loadNightStyle's plain fallback is used.
import type { LayerSpecification, StyleSpecification } from 'maplibre-gl'
import { minimalNightStyle, STYLE_URL } from './nightStyle'

const IMAGERY = 'https://basemap.nationalmap.gov/arcgis/rest/services/USGSImageryOnly/MapServer/tile/{z}/{y}/{x}'
const TERRAIN = 'https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png'

export const TERRAIN_EXAGGERATION = 1.15

/** Keep only labels from the vector style, restyled to read on photography (white text,
 *  dark halo), plus faint major roads so streets stay legible where imagery is soft. */
function overlay(layer: LayerSpecification): LayerSpecification | null {
  const l = { ...layer, paint: { ...((layer as { paint?: object }).paint ?? {}) } } as LayerSpecification & {
    paint: Record<string, unknown>
  }
  if (layer.type === 'symbol') {
    l.paint['text-color'] = '#ffffff'
    l.paint['text-halo-color'] = 'rgba(8, 10, 14, 0.85)'
    l.paint['text-halo-width'] = 1.4
    l.paint['text-halo-blur'] = 0.4
    l.paint['icon-opacity'] = 0.8
    return l
  }
  if (layer.type === 'line' && /^highway_(major|motorway)_inner$/.test(layer.id)) {
    l.paint['line-color'] = 'rgba(255, 244, 214, 0.28)'
    return l
  }
  if (layer.type === 'line' && /^boundary_[23]$/.test(layer.id)) {
    l.paint['line-color'] = 'rgba(255, 255, 255, 0.45)'
    return l
  }
  return null
}

export function earthStyle(base: StyleSpecification): StyleSpecification {
  const labels = base.layers.map(overlay).filter((x): x is LayerSpecification => x != null)
  return {
    version: 8,
    glyphs: base.glyphs,
    sprite: base.sprite,
    projection: { type: 'globe' },
    sources: {
      ...Object.fromEntries(Object.entries(base.sources).filter(([, s]) => s.type === 'vector')),
      imagery: {
        type: 'raster',
        tiles: [IMAGERY],
        tileSize: 256,
        maxzoom: 16,
        attribution: 'Imagery: USDA, USGS The National Map',
      },
      terrain: {
        type: 'raster-dem',
        tiles: [TERRAIN],
        tileSize: 256,
        maxzoom: 15,
        encoding: 'terrarium',
        attribution: 'Terrain: AWS Terrain Tiles (Mapzen)',
      },
    },
    terrain: { source: 'terrain', exaggeration: TERRAIN_EXAGGERATION },
    sky: {
      'sky-color': '#7fb3e8',
      'horizon-color': '#dfeaf5',
      'fog-color': '#c9d8e8',
      'sky-horizon-blend': 0.6,
      'horizon-fog-blend': 0.7,
      'fog-ground-blend': 0.85,
      'atmosphere-blend': ['interpolate', ['linear'], ['zoom'], 0, 1, 6, 0.6, 10, 0],
    },
    light: { anchor: 'map', color: '#fff4e0', intensity: 0.4, position: [1.4, 210, 35] },
    layers: [
      { id: 'background', type: 'background', paint: { 'background-color': '#0b0e13' } },
      {
        id: 'imagery',
        type: 'raster',
        source: 'imagery',
        paint: {
          'raster-contrast': 0.12,
          'raster-saturation': 0.18,
          'raster-brightness-min': 0.02,
          'raster-fade-duration': 250,
        },
      },
      ...labels,
    ],
  }
}

export async function loadEarthStyle(timeoutMs = 6000): Promise<{ style: StyleSpecification; online: boolean }> {
  const ctrl = new AbortController()
  const t = setTimeout(() => ctrl.abort(), timeoutMs)
  try {
    const res = await fetch(STYLE_URL, { signal: ctrl.signal })
    if (!res.ok) throw new Error(String(res.status))
    return { style: earthStyle((await res.json()) as StyleSpecification), online: true }
  } catch {
    return { style: minimalNightStyle(), online: false }
  } finally {
    clearTimeout(t)
  }
}
