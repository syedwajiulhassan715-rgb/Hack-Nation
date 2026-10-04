// Hidden /states page (FRONTEND_PLAN 6, slice 2): every row state at once, using real rows
// found in the generated data (no fixtures, no invented law).
import { useEffect, useState } from 'react'
import { getLookup, getParcels, getRules, type Mode } from '../api/client'
import type { LookupRow, RuleRecord } from '../api/types'
import { derivedFromYearBuilt, isLowConfidence } from '../lib/rows'
import { Footer } from '../layout/Footer'
import { navigate } from '../lib/router'
import { prettyDate } from '../lib/dates'
import { LabelContext } from './context'
import { LabelRow } from './LabelRow'
import { StatusChip } from './StatusChip'
import { SourceDrawer } from '../source/SourceDrawer'
import { AnimatePresence } from 'motion/react'

type Example = { name: string; row: LookupRow; address: string }

const WANT: Array<[string, (r: LookupRow) => boolean]> = [
  ['Applies', (r) => r.result === 'applies' && !r.conflict_flag && !isLowConfidence(r)],
  ['Unknown (with fact input)', (r) => r.result === 'unknown' && r.missing_facts.some((f) => f === 'year_built' || f === 'units')],
  ['Unknown (fact not in our data)', (r) => r.result === 'unknown' && r.missing_facts.length > 0],
  ['Superseded', (r) => r.result === 'superseded'],
  ['Starts later', (r) => r.result === 'not_yet_effective'],
  ['Proposed', (r) => r.result === 'pending'],
  ['Conflict', (r) => r.conflict_flag],
  ['Low confidence', (r) => isLowConfidence(r) && !r.conflict_flag],
  ['Derived from year built', (r) => derivedFromYearBuilt(r)],
  ['Sources disagree on the date', (r) => !!r.conflict_note],
  ['Plain-language answer', (r) => !!r.answer],
]

export function StatesPage({ mode, defaultAsOf }: { mode: Mode; defaultAsOf: string }) {
  const [examples, setExamples] = useState<Example[]>([])
  const [missing, setMissing] = useState<string[]>([])
  const [rulesById, setRulesById] = useState<Map<string, RuleRecord>>(new Map())
  const [drawer, setDrawer] = useState<LookupRow | null>(null)
  const [status, setStatus] = useState('Scanning the generated lookups…')

  useEffect(() => {
    let live = true
    ;(async () => {
      const [parcels, rules] = await Promise.all([getParcels(), getRules()])
      setRulesById(rules.byId)
      // a few addresses per legal city, plus unresolved ones
      const perCity = new Map<string, string[]>()
      for (const p of parcels) {
        const k = p.city ?? `none-${p.state}`
        const l = perCity.get(k) ?? []
        if (l.length < 4) l.push(p.address_id)
        perCity.set(k, l)
      }
      const ids = [...perCity.values()].flat()
      const found = new Map<string, Example>()
      for (const id of ids) {
        if (!live || found.size === WANT.length) break
        try {
          const lk = await getLookup(id, defaultAsOf, 'tenant')
          for (const b of lk.categories)
            for (const r of b.rows)
              for (const [name, test] of WANT) if (!found.has(name) && test(r)) found.set(name, { name, row: r, address: lk.address })
        } catch {
          /* skip */
        }
      }
      if (!live) return
      setExamples(WANT.map(([n]) => found.get(n)).filter((x): x is Example => !!x))
      setMissing(WANT.map(([n]) => n).filter((n) => !found.has(n)))
      setStatus(`Scanned ${ids.length} addresses.`)
    })()
    return () => {
      live = false
    }
  }, [defaultAsOf])

  return (
    <div className="page paper-page">
      <header className="page-head">
        <button type="button" className="btn" onClick={() => navigate('/')}>
          Back to the map
        </button>
        <h1>Row states</h1>
        <p className="mono">
          As of {prettyDate(defaultAsOf)} · Not legal advice · real rows from the generated lookups · {status}
        </p>
      </header>
      <LabelContext.Provider
        value={{
          asOf: defaultAsOf,
          role: 'tenant',
          rulesById,
          onOpenSource: setDrawer,
          onSubmitFact: null,
          factBusy: false,
          offlineNote: 'Fact input is shown disabled on this page.',
        }}
      >
        <div className="states-grid">
          {examples.map((e) => (
            <div key={e.name} className="label states-card">
              <h2 className="section-title">{e.name}</h2>
              <p className="fine">{e.address}</p>
              <LabelRow row={e.row} question={e.row.title} />
            </div>
          ))}
          <div className="label states-card">
            <h2 className="section-title">No rule found</h2>
            <div className="lrow lrow-none">
              <p className="lrow-answer muted">No rule found in our sources for this level</p>
              <StatusChip status="none" />
            </div>
          </div>
        </div>
      </LabelContext.Provider>
      {missing.length > 0 && <p className="muted">Not present in the scanned real data: {missing.join(', ')}.</p>}
      <AnimatePresence>{drawer && <SourceDrawer row={drawer} asOf={defaultAsOf} onClose={() => setDrawer(null)} />}</AnimatePresence>
      <Footer asOf={defaultAsOf} mode={mode} />
    </div>
  )
}
