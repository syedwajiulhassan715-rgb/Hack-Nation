import { useMemo } from 'react'
import type { Parcel } from '../api/types'
import { cityCenters } from '../map/beacons'
import { cityName } from '../api/fallback'

interface Props {
  parcels: Parcel[]
  onCity: (c: { lng: number; lat: number }) => void
}

/** The cities with sample addresses, derived from the data (parcels.json). */
export function CityChips({ parcels, onCity }: Props) {
  const cities = useMemo(() => {
    const centers = cityCenters(parcels)
    return [...centers.entries()].sort((a, b) => a[0].localeCompare(b[0]))
  }, [parcels])
  return (
    <div className="city-chips">
      {cities.map(([city, c]) => (
        <button key={city} type="button" className="chip-dark" onClick={() => onCity(c)} title={`${city} · ${c.count} sample buildings`}>
          {cityName(city)}
        </button>
      ))}
    </div>
  )
}
