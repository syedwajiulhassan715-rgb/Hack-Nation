import circle from '@turf/circle'
import type { Feature, FeatureCollection, Point, Polygon } from 'geojson'
import type { Parcel } from '../api/types'

export const BEACON_RADIUS_M = 12
export const BEACON_HEIGHT_M = 6

/** 12 m radius circle polygon per sample address (extruded 6 m on the map). */
export function beaconPolygons(parcels: Parcel[]): FeatureCollection<Polygon> {
  const features: Feature<Polygon>[] = []
  for (const p of parcels) {
    if (p.lat == null || p.lng == null) continue
    const c = circle([p.lng, p.lat], BEACON_RADIUS_M / 1000, { steps: 24, units: 'kilometers' })
    c.properties = { address_id: p.address_id }
    features.push(c)
  }
  return { type: 'FeatureCollection', features }
}

export function beaconPoints(parcels: Parcel[]): FeatureCollection<Point> {
  return {
    type: 'FeatureCollection',
    features: parcels
      .filter((p) => p.lat != null && p.lng != null)
      .map((p) => ({
        type: 'Feature' as const,
        properties: { address_id: p.address_id },
        geometry: { type: 'Point' as const, coordinates: [p.lng!, p.lat!] },
      })),
  }
}

/** Centroid of the sample addresses of each legal city (for city chips and the ingest ripple). */
export function cityCenters(parcels: Parcel[]): Map<string, { lng: number; lat: number; count: number }> {
  const acc = new Map<string, { lng: number; lat: number; count: number }>()
  for (const p of parcels) {
    if (!p.city || p.lat == null || p.lng == null) continue
    const a = acc.get(p.city) ?? { lng: 0, lat: 0, count: 0 }
    a.lng += p.lng
    a.lat += p.lat
    a.count += 1
    acc.set(p.city, a)
  }
  for (const [k, a] of acc) acc.set(k, { lng: a.lng / a.count, lat: a.lat / a.count, count: a.count })
  return acc
}
