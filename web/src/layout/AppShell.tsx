import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { AnimatePresence, motion } from 'motion/react'
import { FilePlus2, Shuffle } from 'lucide-react'
import {
  getChanges,
  getLookup,
  getParcels,
  getRules,
  postLookup,
  resolvePoint,
  type Mode,
} from '../api/client'
import { loadSnapshots, loadTimelineDates } from '../api/static'
import { SnapshotIndex } from '../api/snapshots'
import {
  CATEGORIES,
  type Category,
  type LookupResult,
  type LookupRow,
  type Parcel,
  type Role,
  type RuleRecord,
  type SearchHit,
} from '../api/types'
import { ANCHOR_LINE, CATEGORY_SHORT } from '../copy'
import { CityMap, type FlyRequest } from '../map/CityMap'
import { ruleAsRow } from '../api/fallback'
import { RightsLabel } from '../label/RightsLabel'
import { SourceDrawer } from '../source/SourceDrawer'
import { DateSlider } from '../timeline/DateSlider'
import { SearchBox } from '../search/SearchBox'
import { CityChips } from '../search/CityChips'
import { IngestPanel } from '../ingest/IngestPanel'
import { rowDates } from '../lib/rows'
import { navigate, type Route } from '../lib/router'
import { Footer } from './Footer'

interface Props {
  mode: Mode
  defaultAsOf: string
  route: Route
}

export function AppShell({ mode, defaultAsOf, route }: Props) {
  const [parcels, setParcels] = useState<Parcel[]>([])
  const [rulesById, setRulesById] = useState<Map<string, RuleRecord>>(new Map())
  const [snapshots, setSnapshots] = useState<SnapshotIndex | null>(null)
  const [globalTicks, setGlobalTicks] = useState<string[]>([])
  const [dataError, setDataError] = useState<string | null>(null)

  const [preview, setPreview] = useState(defaultAsOf) // slider position (beacons)
  const [asOf, setAsOf] = useState(defaultAsOf) // committed date (lookups)
  const [role, setRole] = useState<Role>('tenant')
  const [category, setCategory] = useState<Category | 'all'>('all')
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [lookup, setLookup] = useState<LookupResult | null>(null)
  const [loading, setLoading] = useState(false)
  const [lookupError, setLookupError] = useState<string | null>(null)
  const [userFacts, setUserFacts] = useState<Record<string, number>>({})
  const [factBusy, setFactBusy] = useState(false)
  const [level, setLevel] = useState<'state' | 'city' | null>(null)
  const [drawerRow, setDrawerRow] = useState<LookupRow | null>(null)
  const [drawerStatus, setDrawerStatus] = useState<string | undefined>(undefined)
  const [ingestOpen, setIngestOpen] = useState(false)
  const [intro, setIntro] = useState(true)
  const [fly, setFly] = useState<FlyRequest | null>(null)
  const [rippleAt, setRippleAt] = useState<{ lng: number; lat: number; key: number } | null>(null)
  const [highlight, setHighlight] = useState<Set<string>>(new Set())
  const [pulseKey, setPulseKey] = useState(0)
  const [toast, setToast] = useState<string | null>(null)
  const [tilesOnline, setTilesOnline] = useState(true)
  const [testBanner, setTestBanner] = useState<string | null>(null)

  // ---- static data ----
  useEffect(() => {
    Promise.all([getParcels(), getRules(), loadSnapshots(), loadTimelineDates()])
      .then(([p, r, s, td]) => {
        setParcels(p)
        setRulesById(r.byId)
        if (s) setSnapshots(new SnapshotIndex(s))
        setGlobalTicks(s?.dates?.length ? s.dates : td)
      })
      .catch((e) => setDataError(e instanceof Error ? e.message : String(e)))
  }, [])

  const byId = useMemo(() => new Map(parcels.map((p) => [p.address_id, p])), [parcels])

  // ---- deep link from the changes page: ?cat=&date=&test= ----
  const handledLink = useRef('')
  useEffect(() => {
    const key = route.params.toString()
    if (!key || key === handledLink.current) return
    handledLink.current = key
    const cat = route.params.get('cat')
    const date = route.params.get('date')
    const test = route.params.get('test')
    if (cat && (CATEGORIES as readonly string[]).includes(cat)) setCategory(cat as Category)
    if (date && /^\d{4}-\d{2}-\d{2}$/.test(date)) {
      setPreview(date)
      setAsOf(date)
    }
    if (test) {
      setIntro(false)
      getChanges().then((c) => {
        const out = c.outputs[test]
        if (!out) return
        setHighlight(new Set([...out.affected_address_ids, ...out.conflict_flag_address_ids]))
        setPulseKey((k) => k + 1)
        setTestBanner(
          `${test}: ${out.affected_address_ids.length} affected, ${out.conflict_flag_address_ids.length} conflict-flagged addresses ringed`,
        )
      })
    }
  }, [route])

  // ---- lookup fetch ----
  const reqSeq = useRef(0)
  const fetchLookup = useCallback(
    async (id: string, date: string, r: Role, facts: Record<string, number>) => {
      const n = ++reqSeq.current
      setLoading(true)
      setLookupError(null)
      try {
        const p = byId.get(id)
        const res =
          Object.keys(facts).length && p
            ? await postLookup({ address_id: id, lat: p.lat ?? 0, lng: p.lng ?? 0, facts, as_of: date, role: r })
            : await getLookup(id, date, r)
        if (n === reqSeq.current) setLookup(res)
      } catch (e) {
        if (n === reqSeq.current) setLookupError(e instanceof Error ? e.message : String(e))
      } finally {
        if (n === reqSeq.current) setLoading(false)
      }
    },
    [byId],
  )

  useEffect(() => {
    if (selectedId) fetchLookup(selectedId, asOf, role, userFacts)
  }, [selectedId, asOf, role, userFacts, fetchLookup, mode])

  // ---- selection ----
  const select = useCallback(
    (id: string) => {
      const p = byId.get(id)
      setIntro(false)
      if (id !== selectedId) {
        setLookup(null)
        setUserFacts({})
        setLevel(null)
        setDrawerRow(null)
      }
      setSelectedId(id)
      if (p?.lat != null && p.lng != null) setFly({ lng: p.lng, lat: p.lat, zoom: 17.5, pitch: 60, key: Date.now() })
    },
    [byId, selectedId],
  )

  const random = useCallback(() => {
    const withCoords = parcels.filter((p) => p.lat != null)
    if (!withCoords.length) return
    select(withCoords[Math.floor(Math.random() * withCoords.length)].address_id)
  }, [parcels, select])

  const onPick = useCallback(
    (h: SearchHit) => {
      if (h.kind === 'zip') {
        if (h.lat != null && h.lng != null) setFly({ lng: h.lng, lat: h.lat, zoom: 15, pitch: 45, key: Date.now() })
        setIntro(false)
        return
      }
      select(h.address_id)
    },
    [select],
  )

  const onZip = useCallback((hits: SearchHit[]) => {
    // A ZIP only moves the camera; it never shows a jurisdiction or rules by itself.
    const pts = hits.filter((h) => h.lat != null && h.lng != null)
    if (!pts.length) return
    const lng = pts.reduce((a, h) => a + h.lng!, 0) / pts.length
    const lat = pts.reduce((a, h) => a + h.lat!, 0) / pts.length
    setFly({ lng, lat, zoom: 14.5, pitch: 40, key: Date.now() })
    setHighlight(new Set(pts.map((h) => h.address_id)))
    setIntro(false)
  }, [])

  const onClickElsewhere = useCallback(
    async (lat: number, lng: number) => {
      setFly({ lng, lat, zoom: 17.5, pitch: 60, key: Date.now() })
      try {
        const r = await resolvePoint(lat, lng)
        if (r.nearest_address_id) return select(r.nearest_address_id)
        setToast(
          mode === 'api'
            ? 'No sample building within 30 m of this point. Pick a lit building to see its rules.'
            : 'No sample building within 30 m. Lookups for other buildings need the API.',
        )
      } catch (e) {
        setToast(e instanceof Error ? e.message : String(e))
      }
    },
    [mode, select],
  )

  useEffect(() => {
    if (!toast) return
    const t = setTimeout(() => setToast(null), 4500)
    return () => clearTimeout(t)
  }, [toast])

  const onSubmitFact = useCallback(
    (fact: string, value: number) => {
      setFactBusy(true)
      setUserFacts((f) => ({ ...f, [fact]: value }))
    },
    [],
  )
  useEffect(() => {
    if (!loading) setFactBusy(false)
  }, [loading])

  const buildingTicks = useMemo(() => rowDates(lookup), [lookup])

  const ingestDone = useCallback(
    ({ jurisdiction }: { jurisdiction: string | null; affected: string[] }) => {
      // Ripple from the new law's jurisdiction; ring the sample buildings inside it.
      const inside = parcels.filter(
        (p) => p.lat != null && p.lng != null && !!jurisdiction && (p.city === jurisdiction || p.state === jurisdiction),
      )
      if (inside.length && jurisdiction) {
        const lng = inside.reduce((a, p) => a + p.lng!, 0) / inside.length
        const lat = inside.reduce((a, p) => a + p.lat!, 0) / inside.length
        setFly({ lng, lat, zoom: jurisdiction.includes(',') ? 11.5 : 6.5, pitch: 30, key: Date.now() })
        setRippleAt({ lng, lat, key: Date.now() })
        setHighlight(new Set(inside.map((p) => p.address_id)))
        setPulseKey((k) => k + 1)
      }
      if (selectedId) fetchLookup(selectedId, asOf, role, userFacts)
    },
    [parcels, selectedId, asOf, role, userFacts, fetchLookup],
  )

  const labelOpen = !!selectedId

  return (
    <div className={`shell${labelOpen ? ' with-label' : ''}`}>
      <div className="map-wrap">
        <CityMap
          parcels={parcels}
          snapshots={snapshots}
          asOf={preview}
          category={category}
          selectedId={selectedId}
          lookup={lookup}
          highlightIds={highlight}
          pulseKey={pulseKey}
          fly={fly}
          rippleAt={rippleAt}
          onSelect={select}
          onClickElsewhere={onClickElsewhere}
          onLevelChip={(l) => setLevel((cur) => (cur === l ? null : l))}
          onStyleStatus={setTilesOnline}
        />
      </div>

      <div className="top-left">
        <SearchBox onPick={onPick} onZip={onZip} />
        <CityChips
          parcels={parcels}
          onCity={(c) => {
            setIntro(false)
            setFly({ lng: c.lng, lat: c.lat, zoom: 12, pitch: 45, key: Date.now() })
          }}
        />
        {!tilesOnline && <p className="chip-dark note">Street tiles unavailable. Showing sample buildings only.</p>}
        {testBanner && (
          <p className="chip-dark note">
            {testBanner}{' '}
            <button
              type="button"
              className="link light"
              onClick={() => {
                setTestBanner(null)
                setHighlight(new Set())
                navigate('/')
              }}
            >
              Clear
            </button>
          </p>
        )}
      </div>

      <div className="top-right">
        <div className="filters" role="group" aria-label="Category filter">
          <button type="button" className={`chip-dark${category === 'all' ? ' on' : ''}`} onClick={() => setCategory('all')}>
            All protections
          </button>
          {CATEGORIES.map((c) => (
            <button key={c} type="button" className={`chip-dark${category === c ? ' on' : ''}`} onClick={() => setCategory(c)}>
              {CATEGORY_SHORT[c]}
            </button>
          ))}
        </div>
        <div className="actions">
          <button
            type="button"
            className="btn-paper"
            onClick={() => {
              setIntro(false)
              setIngestOpen(true)
            }}
          >
            <FilePlus2 size={16} /> Add a new law
          </button>
          <button type="button" className="chip-dark" onClick={() => navigate('/changes')}>
            Change tests
          </button>
        </div>
        <Legend category={category} />
      </div>

      <AnimatePresence>
        {intro && (
          <motion.div className="intro" initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }}>
            <p className="intro-line">{ANCHOR_LINE}</p>
            <SearchBox onPick={onPick} onZip={onZip} variant="paper" autoFocus />
            <div className="intro-actions">
              <button type="button" className="btn btn-ink" onClick={random} disabled={!parcels.length}>
                <Shuffle size={16} /> Random building
              </button>
              <span className="muted small">or click any lit building on the map</span>
            </div>
            {dataError && <p className="fact-error">{dataError}</p>}
            <p className="fine">Not legal advice. Every answer links to the sentence of law it comes from.</p>
          </motion.div>
        )}
      </AnimatePresence>

      <AnimatePresence>
        {labelOpen && (
          <RightsLabel
            key="label"
            lookup={lookup}
            loading={loading}
            error={lookupError}
            role={role}
            onRole={setRole}
            level={level}
            onLevel={setLevel}
            onClose={() => {
              setSelectedId(null)
              setLookup(null)
              setDrawerRow(null)
            }}
            onClearUserFacts={() => setUserFacts({})}
            ctx={{
              asOf: lookup?.as_of || asOf,
              role,
              rulesById,
              onOpenSource: (r) => {
                setDrawerStatus(undefined)
                setDrawerRow(r)
              },
              onSubmitFact: mode === 'api' ? onSubmitFact : null,
              factBusy,
              offlineNote: 'Typing a fact needs the API. The app is running on bundled data.',
            }}
          />
        )}
      </AnimatePresence>

      <div className="bottom">
        <DateSlider
          value={preview}
          defaultAsOf={defaultAsOf}
          globalTicks={globalTicks}
          buildingTicks={buildingTicks}
          onPreview={setPreview}
          onCommit={setAsOf}
        />
      </div>

      <AnimatePresence>
        {drawerRow && (
          <SourceDrawer
            key={drawerRow.team_rule_id}
            row={drawerRow}
            statusText={drawerStatus}
            asOf={lookup?.as_of || asOf}
            onClose={() => setDrawerRow(null)}
          />
        )}
      </AnimatePresence>

      <AnimatePresence>
        {ingestOpen && (
          <IngestPanel
            mode={mode}
            asOf={asOf}
            onClose={() => setIngestOpen(false)}
            onDone={ingestDone}
            onShowRule={(rule) => {
              setDrawerStatus(rule.status === 'in_force' ? 'In force' : undefined)
              setDrawerRow(ruleAsRow(rule))
            }}
          />
        )}
      </AnimatePresence>

      {toast && (
        <div className="toast" role="status">
          {toast}
        </div>
      )}

      <Footer asOf={preview} mode={mode} />
    </div>
  )
}

function Legend({ category }: { category: Category | 'all' }) {
  if (category === 'all')
    return (
      <div className="legend chip-dark">
        <span className="ramp" /> fewer → more categories with a rule that applies
      </div>
    )
  return (
    <div className="legend chip-dark">
      <span className="sw" style={{ background: 'var(--applies)' }} /> Applies
      <span className="sw" style={{ background: 'var(--unknown)' }} /> Unknown
      <span className="sw" style={{ background: 'var(--not-yet)' }} /> Starts later
      <span className="sw" style={{ background: 'var(--pending)' }} /> Proposed
      <span className="sw" style={{ background: 'var(--conflict)' }} /> Conflict
      <span className="sw" style={{ background: 'var(--none)', outline: '1px solid #444' }} /> No rule found
    </div>
  )
}
