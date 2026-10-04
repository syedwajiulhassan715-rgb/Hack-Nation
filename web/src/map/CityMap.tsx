import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import Map, { Marker, type MapRef, type MapLayerMouseEvent } from 'react-map-gl/maplibre'
import type { StyleSpecification, GeoJSONSource } from 'maplibre-gl'
import centroid from '@turf/centroid'
import circle from '@turf/circle'
import type { Feature, MultiPolygon, Polygon } from 'geojson'
import 'maplibre-gl/dist/maplibre-gl.css'
import type { Category, LookupResult, Parcel } from '../api/types'
import { CATEGORIES } from '../api/types'
import type { SnapshotIndex } from '../api/snapshots'
import { snapshotDateFor } from '../api/snapshots'
import { beaconColor, token } from '../lib/colors'
import { levelCounts } from '../lib/rows'
import { beaconPoints, beaconPolygons, BEACON_HEIGHT_M, BEACON_RADIUS_M } from './beacons'
import { vectorSourceId } from './nightStyle'
import { loadEarthStyle } from './earthStyle'
import { startOrbit } from './orbit'
import { animateSlabs } from './slabs'
import { ripple } from './ripple'
import { mapLib } from './maplib'
import { useI18n } from '../i18n'
import { Rotate3d } from 'lucide-react'

export interface FlyRequest {
  lng: number
  lat: number
  zoom: number
  pitch?: number
  /** land in a bird's-eye view and orbit 360 degrees (a building was chosen) */
  orbit?: boolean
  key: number
}

interface Props {
  parcels: Parcel[]
  snapshots: SnapshotIndex | null
  asOf: string
  category: Category | 'all'
  selectedId: string | null
  lookup: LookupResult | null
  highlightIds: Set<string>
  pulseKey: number
  fly: FlyRequest | null
  rippleAt: { lng: number; lat: number; key: number } | null
  onSelect: (addressId: string) => void
  onClickElsewhere: (lat: number, lng: number) => void
  onLevelChip: (level: 'state' | 'city') => void
  onStyleStatus: (online: boolean) => void
}

// Rooftop palette for the 3D city (terracotta, cream, stone, slate, sage, sand): a stable
// pseudo-random pick per building from its id and height, so neighbours differ but a building
// keeps its color between frames.
const ROOFS = ['#c8643c', '#e9dfc9', '#cfc5b3', '#8e9aa8', '#a9c4b0', '#d8b48a', '#b5523b', '#f2ede2']
const BUILDING_COLOR = [
  'match',
  ['%', ['+', ['to-number', ['id'], 0], ['round', ['*', ['coalesce', ['get', 'render_height'], 8], 7]]], ROOFS.length],
  ...ROOFS.slice(0, -1).flatMap((c, i) => [i, c]),
  ROOFS[ROOFS.length - 1],
] as unknown as string

const reduced = () => typeof window !== 'undefined' && !!window.matchMedia?.('(prefers-reduced-motion: reduce)').matches

export function CityMap(props: Props) {
  const { parcels, snapshots, asOf, category, selectedId, lookup, highlightIds, pulseKey, fly, rippleAt } = props
  const { t } = useI18n()
  const [hover, setHover] = useState(false)
  const mapRef = useRef<MapRef | null>(null)
  const [style, setStyle] = useState<StyleSpecification | null>(null)
  const [loaded, setLoaded] = useState(false)
  const [buildingTop, setBuildingTop] = useState(12)
  const onStyleStatus = props.onStyleStatus

  useEffect(() => {
    loadEarthStyle().then(({ style, online }) => {
      setStyle(style)
      onStyleStatus(online)
    })
  }, [onStyleStatus])

  const polygons = useMemo(() => beaconPolygons(parcels), [parcels])
  const points = useMemo(() => beaconPoints(parcels), [parcels])
  const byId = useMemo(() => new globalThis.Map(parcels.map((p) => [p.address_id, p])), [parcels])

  // ---- add sources and layers once the style is loaded ----
  const onLoad = useCallback(() => {
    const map = mapRef.current?.getMap()
    if (!map || !style) return
    const vec = vectorSourceId(style)
    if (vec && !map.getLayer('buildings-3d')) {
      map.addLayer({
        id: 'buildings-3d',
        type: 'fill-extrusion',
        source: vec,
        'source-layer': 'building',
        minzoom: 14,
        paint: {
          'fill-extrusion-color': BUILDING_COLOR,
          'fill-extrusion-height': ['interpolate', ['linear'], ['zoom'], 14, 0, 14.6, ['coalesce', ['get', 'render_height'], 8]],
          'fill-extrusion-base': ['coalesce', ['get', 'render_min_height'], 0],
          'fill-extrusion-opacity': 0.92,
          'fill-extrusion-vertical-gradient': true,
        },
      })
    }
    map.addSource('beacon-pts', { type: 'geojson', data: points, promoteId: 'address_id' })
    map.addSource('beacons', { type: 'geojson', data: polygons, promoteId: 'address_id' })
    map.addSource('selected-building', { type: 'geojson', data: { type: 'FeatureCollection', features: [] } })
    map.addSource('slabs', { type: 'geojson', data: { type: 'FeatureCollection', features: [] } })
    map.addSource('ripple', { type: 'geojson', data: { type: 'FeatureCollection', features: [] } })
    const color = ['to-color', ['coalesce', ['feature-state', 'color'], token('--none')]] as unknown as string
    map.addLayer({
      id: 'beacon-glow',
      type: 'circle',
      source: 'beacon-pts',
      paint: {
        'circle-color': color,
        'circle-radius': ['interpolate', ['linear'], ['zoom'], 3, 4, 8, 4.5, 10, 5, 15, 9],
        'circle-opacity': 0.85,
        'circle-blur': 0.2,
        'circle-stroke-color': token('--paper', '#F6F2E9'),
        'circle-stroke-width': ['case', ['boolean', ['feature-state', 'hl'], false], 2, 0],
        'circle-stroke-opacity': 0.9,
      },
    })
    map.addLayer({
      id: 'beacons-3d',
      type: 'fill-extrusion',
      source: 'beacons',
      minzoom: 13,
      paint: {
        'fill-extrusion-color': color,
        'fill-extrusion-height': BEACON_HEIGHT_M,
        'fill-extrusion-base': 0,
        'fill-extrusion-opacity': 0.95,
      },
    })
    map.addLayer({
      id: 'selected-building',
      type: 'fill-extrusion',
      source: 'selected-building',
      paint: {
        'fill-extrusion-color': token('--applies'),
        'fill-extrusion-height': ['get', 'height'],
        'fill-extrusion-base': ['get', 'base'],
        'fill-extrusion-opacity': 0.85,
      },
    })
    map.addLayer({
      id: 'slabs',
      type: 'fill-extrusion',
      source: 'slabs',
      paint: {
        'fill-extrusion-color': ['match', ['get', 'level'], 'city', '#2DD4BF', '#4F7CFF'],
        'fill-extrusion-opacity': 0.45,
        'fill-extrusion-base': ['get', 'base'],
        'fill-extrusion-height': ['get', 'top'],
      },
    })
    map.addLayer({
      id: 'ripple',
      type: 'circle',
      source: 'ripple',
      paint: {
        'circle-radius': 0,
        'circle-color': 'rgba(0,0,0,0)',
        'circle-stroke-color': token('--applies'),
        'circle-stroke-width': 3,
        'circle-stroke-opacity': 0,
      },
    })
    setLoaded(true)
  }, [style, points, polygons])

  // ---- recolor beacons when the snapshot date or category changes (no API calls) ----
  const lastKey = useRef('')
  useEffect(() => {
    const map = mapRef.current?.getMap()
    if (!map || !loaded) return
    const snapDate = snapshots ? snapshotDateFor(snapshots.dates, asOf) : null
    const key = `${snapDate}|${category}|${snapshots ? 1 : 0}`
    if (key === lastKey.current) return
    lastKey.current = key
    const catIndex = category === 'all' ? 'all' : CATEGORIES.indexOf(category)
    for (const p of parcels) {
      const cells = snapshots ? snapshots.row(asOf, p.address_id) : null
      const c = beaconColor(cells, catIndex)
      map.setFeatureState({ source: 'beacon-pts', id: p.address_id }, { color: c })
      map.setFeatureState({ source: 'beacons', id: p.address_id }, { color: c })
    }
  }, [asOf, category, snapshots, parcels, loaded])

  // ---- highlight (changes page "Show on map", ingest) ----
  const prevHl = useRef<Set<string>>(new Set())
  useEffect(() => {
    const map = mapRef.current?.getMap()
    if (!map || !loaded) return
    for (const id of prevHl.current) map.setFeatureState({ source: 'beacon-pts', id }, { hl: false })
    for (const id of highlightIds) map.setFeatureState({ source: 'beacon-pts', id }, { hl: true })
    prevHl.current = new Set(highlightIds)
  }, [highlightIds, loaded])

  useEffect(() => {
    const map = mapRef.current?.getMap()
    if (!map || !loaded || !pulseKey || reduced()) return
    const t0 = performance.now()
    let raf = 0
    const step = (now: number) => {
      const t = (now - t0) / 1000
      map.setPaintProperty('beacon-glow', 'circle-stroke-opacity', 0.5 + 0.5 * Math.cos(t * Math.PI * 2))
      if (t < 3) raf = requestAnimationFrame(step)
      else map.setPaintProperty('beacon-glow', 'circle-stroke-opacity', 0.9)
    }
    raf = requestAnimationFrame(step)
    return () => cancelAnimationFrame(raf)
  }, [pulseKey, loaded])

  // ---- camera ----
  // A fly to a chosen building lands in a bird's-eye view and then orbits it 360 degrees until the
  // user presses on the map (orbit.ts). Other flies (city, ZIP, a map click) just fly.
  const [orbiting, setOrbiting] = useState(false)
  const stopOrbit = useRef<() => void>(() => {})
  const orbit = useCallback(() => {
    const map = mapRef.current?.getMap()
    if (!map || reduced()) return
    stopOrbit.current()
    setOrbiting(true)
    stopOrbit.current = startOrbit(map, () => setOrbiting(false))
  }, [])
  useEffect(() => () => stopOrbit.current(), [])

  useEffect(() => {
    const map = mapRef.current?.getMap()
    if (!map || !fly) return
    stopOrbit.current()
    const close = !!fly.orbit
    map.flyTo({
      center: [fly.lng, fly.lat],
      zoom: fly.zoom,
      pitch: close ? Math.max(fly.pitch ?? 0, 62) : (fly.pitch ?? map.getPitch()),
      bearing: close ? map.getBearing() - 35 : map.getBearing(),
      duration: reduced() ? 0 : close ? 2600 : 1600,
      curve: 1.6,
      essential: true,
    })
    if (!close) return
    const land = () => orbit()
    map.once('moveend', land)
    return () => {
      map.off('moveend', land)
    }
  }, [fly, orbit])

  useEffect(() => {
    const map = mapRef.current?.getMap()
    if (!map || !loaded || !rippleAt) return
    ripple(map, rippleAt.lng, rippleAt.lat, reduced())
  }, [rippleAt, loaded])

  // ---- selected building: footprint + slabs ----
  const levels = useMemo<Array<'state' | 'city'>>(() => {
    if (!lookup) return []
    return lookup.jurisdiction_stack.map((j) => j.level)
  }, [lookup])

  useEffect(() => {
    const map = mapRef.current?.getMap()
    if (!map || !loaded) return
    const sel = map.getSource('selected-building') as GeoJSONSource
    const slabs = map.getSource('slabs') as GeoJSONSource
    const p = selectedId ? byId.get(selectedId) : null
    if (!p || p.lat == null || p.lng == null) {
      sel.setData({ type: 'FeatureCollection', features: [] })
      slabs.setData({ type: 'FeatureCollection', features: [] })
      return
    }
    let cancel = () => {}
    const place = () => {
      const pt = map.project([p.lng!, p.lat!])
      const hits = map.getLayer('buildings-3d') ? map.queryRenderedFeatures(pt, { layers: ['buildings-3d'] }) : []
      let footprint: Feature<Polygon | MultiPolygon>
      let height = 12
      let base = 0
      if (hits.length && (hits[0].geometry.type === 'Polygon' || hits[0].geometry.type === 'MultiPolygon')) {
        footprint = { type: 'Feature', properties: {}, geometry: hits[0].geometry as Polygon | MultiPolygon }
        height = Number(hits[0].properties?.render_height ?? 12) || 12
        base = Number(hits[0].properties?.render_min_height ?? 0) || 0
        sel.setData({ type: 'FeatureCollection', features: [{ ...footprint, properties: { height: height + 0.5, base } }] })
      } else {
        footprint = circle([p.lng!, p.lat!], BEACON_RADIUS_M / 1000, { steps: 24, units: 'kilometers' })
        height = BEACON_HEIGHT_M
        sel.setData({ type: 'FeatureCollection', features: [] })
      }
      setBuildingTop(height)
      cancel = animateSlabs(map, 'slabs', footprint, height, levels.length ? levels : ['state'], reduced())
    }
    if (map.isMoving()) map.once('moveend', place)
    else place()
    return () => {
      map.off('moveend', place)
      cancel()
    }
  }, [selectedId, loaded, byId, levels])

  // ---- clicks ----
  const onClick = useCallback(
    (e: MapLayerMouseEvent) => {
      const map = mapRef.current?.getMap()
      if (!map) return
      const box: [[number, number], [number, number]] = [
        [e.point.x - 6, e.point.y - 6],
        [e.point.x + 6, e.point.y + 6],
      ]
      const beacon = map.queryRenderedFeatures(box, { layers: ['beacons-3d', 'beacon-glow'].filter((l) => map.getLayer(l)) })
      const id = beacon[0]?.properties?.address_id as string | undefined
      if (id) return props.onSelect(id)
      const bld = map.getLayer('buildings-3d') ? map.queryRenderedFeatures(e.point, { layers: ['buildings-3d'] }) : []
      if (bld.length) {
        const c = centroid(bld[0] as Feature<Polygon>)
        const [lng, lat] = c.geometry.coordinates
        props.onClickElsewhere(lat, lng)
      }
    },
    [props],
  )

  const sel = selectedId ? byId.get(selectedId) : null
  const counts = lookup ? levelCounts(lookup) : null
  const cityLevel = lookup?.jurisdiction_stack.find((j) => j.level === 'city')
  const stateLevel = lookup?.jurisdiction_stack.find((j) => j.level === 'state')

  if (!style) return <div className="map-loading" role="status">{t.loadingMap}</div>
  return (
    <>
    <Map
      ref={mapRef}
      mapLib={mapLib}
      initialViewState={{ longitude: -96, latitude: 38.5, zoom: 3.4, pitch: 0 }}
      mapStyle={style}
      onLoad={onLoad}
      onClick={onClick}
      interactiveLayerIds={loaded ? ['beacon-glow', 'beacons-3d'] : []}
      cursor={hover ? 'pointer' : 'grab'}
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
      attributionControl={{ compact: true }}
      maxPitch={70}
      style={{ position: 'absolute', inset: 0 }}
    >
      {sel && lookup && sel.lat != null && sel.lng != null && counts && (
        <Marker longitude={sel.lng} latitude={sel.lat} anchor="bottom" offset={[0, -40 - buildingTop]}>
          <div className="slab-chips">
            {cityLevel ? (
              <button type="button" className="slab-chip city" onClick={() => props.onLevelChip('city')}>
                {cityLevel.name} · {t.rules(counts.city)}
              </button>
            ) : (
              <span className="slab-chip warn">{t.cityNotConfirmed}</span>
            )}
            {stateLevel && (
              <button type="button" className="slab-chip state" onClick={() => props.onLevelChip('state')}>
                {stateLevel.name} · {t.rules(counts.state)}
              </button>
            )}
          </div>
        </Marker>
      )}
    </Map>
    {sel && (
      <div className="orbit-hud">
        {orbiting ? (
          <span className="orbit-pill" role="status">
            <span className="orbit-dot" aria-hidden="true" />
            {t.orbiting}
          </span>
        ) : (
          !reduced() && (
            <button type="button" className="orbit-btn" onClick={orbit} title={t.orbitStart}>
              <Rotate3d size={16} aria-hidden="true" />
              {t.orbitStart}
            </button>
          )
        )}
      </div>
    )}
    </>
  )
}
