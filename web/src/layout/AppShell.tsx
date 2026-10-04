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
  type Lang,
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
import { STATE_NAMES } from '../copy'
import { useI18n } from '../i18n'
import { CityMap, type FlyRequest } from '../map/CityMap'
import { ruleAsRow } from '../api/fallback'
import { RightsLabel } from '../label/RightsLabel'
import { SourceDrawer } from '../source/SourceDrawer'
import { DateSlider } from '../timeline/DateSlider'
import { SearchBox } from '../search/SearchBox'
import { CityChips } from '../search/CityChips'
import { IngestPanel } from '../ingest/IngestPanel'
import { rowDates } from '../lib/rows'
import { prettyDate } from '../lib/dates'
import { navigate, type Route } from '../lib/router'
import { Footer } from './Footer'
import { LangSwitch } from './LangSwitch'

interface Props {
  mode: Mode
  defaultAsOf: string
  route: Route
}

export function AppShell({ mode, defaultAsOf, route }: Props) {
  const { t, lang } = useI18n()
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
  const [testBanner, setTestBanner] = useState<{ id: string; affected: number; conflicts: number } | null>(null)

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
        setTestBanner({
          id: test,
          affected: out.affected_address_ids.length,
          conflicts: out.conflict_flag_address_ids.length,
        })
      })
    }
  }, [route])

  // ---- lookup fetch ----
  const reqSeq = useRef(0)
  const fetchLookup = useCallback(
    async (id: string, date: string, r: Role, facts: Record<string, number>, lg: Lang) => {
      const n = ++reqSeq.current
      setLoading(true)
      setLookupError(null)
      try {
        const p = byId.get(id)
        const res =
          Object.keys(facts).length && p
            ? await postLookup({ address_id: id, lat: p.lat ?? 0, lng: p.lng ?? 0, facts, as_of: date, role: r, lang: lg })
            : await getLookup(id, date, r, lg)
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
    if (selectedId) fetchLookup(selectedId, asOf, role, userFacts, lang)
  }, [selectedId, asOf, role, userFacts, fetchLookup, mode, lang])

  // ---- the API went away mid-session: say so once and keep working on bundled data ----
  const prevMode = useRef(mode)
  useEffect(() => {
    if (prevMode.current === 'api' && mode === 'offline') setToast(t.offlineTitle)
    prevMode.current = mode
  }, [mode, t])

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
        setToast(mode === 'api' ? t.noBuildingNear : t.noBuildingNearOffline)
      } catch (e) {
        setToast(e instanceof Error ? e.message : String(e))
      }
    },
    [mode, select, t],
  )

  useEffect(() => {
    if (!toast) return
    const timer = setTimeout(() => setToast(null), 5000)
    return () => clearTimeout(timer)
  }, [toast])

  const onSubmitFact = useCallback((fact: string, value: number) => {
    setFactBusy(true)
    setUserFacts((f) => ({ ...f, [fact]: value }))
  }, [])
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
      if (selectedId) fetchLookup(selectedId, asOf, role, userFacts, lang)
    },
    [parcels, selectedId, asOf, role, userFacts, fetchLookup, lang],
  )

  const labelOpen = !!selectedId
  const closeLabel = useCallback(() => {
    setSelectedId(null)
    setLookup(null)
    setDrawerRow(null)
  }, [])

  // Escape closes the label (the source drawer and the ingest panel handle their own Escape first).
  useEffect(() => {
    if (!labelOpen) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== 'Escape' || drawerRow || ingestOpen) return
      closeLabel()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [labelOpen, drawerRow, ingestOpen, closeLabel])

  // One line under the anchor sentence, counted from the bundled data (geography, not law).
  const coverage = useMemo(() => {
    if (!parcels.length) return null
    const states = [...new Set(parcels.map((p) => p.state))].sort().map((s) => STATE_NAMES[s] ?? s)
    const and = lang === 'es' ? ' y ' : ' and '
    const list =
      states.length > 1 ? `${states.slice(0, -1).join(', ')}${and}${states[states.length - 1]}` : (states[0] ?? '')
    return t.introSub(parcels.length, list)
  }, [parcels, lang, t])

  return (
    <div className={`shell${labelOpen ? ' with-label' : ''}${intro ? ' with-intro' : ''}`}>
      {/* First in the DOM so keyboard users reach the anchor card before the map controls. */}
      <AnimatePresence>
        {intro && (
          <div className="intro-wrap" key="intro">
            <motion.section
              className="intro"
              aria-labelledby="intro-title"
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0 }}
            >
              <div className="intro-top">
                <LangSwitch variant="ink" />
              </div>
              <h1 id="intro-title" className="intro-line">
                {t.anchor}
              </h1>
              {coverage && <p className="intro-sub">{coverage}</p>}
              <SearchBox onPick={onPick} onZip={onZip} variant="paper" placeholder={t.searchPlaceholder} />
              <div className="intro-actions">
                <button type="button" className="btn btn-ink" onClick={random} disabled={!parcels.length}>
                  <Shuffle size={16} aria-hidden /> {t.random}
                </button>
                <span className="intro-or">{t.orClick}</span>
              </div>
              {dataError && (
                <p className="fact-error" role="alert">
                  {t.dataMissing} <span className="mono">{dataError}</span>
                </p>
              )}
              <p className="intro-fine">
                {t.asOf} <span className="mono">{prettyDate(defaultAsOf, lang)}</span> · {t.disclaimer}
              </p>
            </motion.section>
          </div>
        )}
      </AnimatePresence>

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
        {!intro && <SearchBox onPick={onPick} onZip={onZip} placeholder={t.searchPlaceholder} />}
        <CityChips
          parcels={parcels}
          onCity={(c) => {
            setIntro(false)
            setFly({ lng: c.lng, lat: c.lat, zoom: 12, pitch: 45, key: Date.now() })
          }}
        />
        {!tilesOnline && <p className="chip-dark note">{t.tilesDown}</p>}
        {testBanner && (
          <p className="chip-dark note" role="status">
            {t.testBanner(testBanner.id, testBanner.affected, testBanner.conflicts)}{' '}
            <button
              type="button"
              className="link light"
              onClick={() => {
                setTestBanner(null)
                setHighlight(new Set())
                navigate('/')
              }}
            >
              {t.clear}
            </button>
          </p>
        )}
      </div>

      <div className="top-right">
        <div className="filters" role="group" aria-label={t.categoryFilter}>
          <button
            type="button"
            className={`chip-dark${category === 'all' ? ' on' : ''}`}
            aria-pressed={category === 'all'}
            onClick={() => setCategory('all')}
          >
            {t.allProtections}
          </button>
          {CATEGORIES.map((c) => (
            <button
              key={c}
              type="button"
              className={`chip-dark${category === c ? ' on' : ''}`}
              aria-pressed={category === c}
              onClick={() => setCategory(c)}
            >
              {t.categoryShort[c]}
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
            <FilePlus2 size={16} aria-hidden /> {t.addLaw}
          </button>
          <button type="button" className="chip-dark" onClick={() => navigate('/changes')}>
            {t.changeTests}
          </button>
        </div>
        <Legend category={category} />
      </div>


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
            onClose={closeLabel}
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
              offlineNote: t.offlineFact,
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
              setDrawerStatus(rule.status === 'in_force' ? (lang === 'es' ? 'En vigor' : 'In force') : undefined)
              setDrawerRow(ruleAsRow(rule))
            }}
          />
        )}
      </AnimatePresence>

      {toast && (
        <div className="toast" role="status" aria-live="polite">
          {toast}
        </div>
      )}

      <Footer asOf={preview} mode={mode} />
    </div>
  )
}

function Legend({ category }: { category: Category | 'all' }) {
  const { t } = useI18n()
  if (category === 'all')
    return (
      <div className="legend chip-dark">
        <span className="ramp" aria-hidden /> {t.legendAll}
      </div>
    )
  const items: Array<[string, keyof typeof t.status]> = [
    ['var(--applies)', 'applies'],
    ['var(--unknown)', 'unknown'],
    ['var(--not-yet)', 'not_yet_effective'],
    ['var(--pending)', 'pending'],
    ['var(--conflict)', 'conflict'],
    ['var(--none)', 'none'],
  ]
  return (
    <div className="legend chip-dark">
      {items.map(([c, k]) => (
        <span key={k} className="legend-item">
          <span
            className="sw"
            aria-hidden
            style={{ background: c, outline: k === 'none' ? '1px solid #5a616c' : undefined }}
          />
          {t.status[k]}
        </span>
      ))}
    </div>
  )
}
