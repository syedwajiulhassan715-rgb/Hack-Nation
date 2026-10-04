import { useState } from 'react'
import { motion } from 'motion/react'
import { X } from 'lucide-react'
import type { LookupResult, LookupRow, Role } from '../api/types'
import { EDITABLE_FACTS, factLabel } from '../copy'
import { FactInput } from './FactInput'
import { prettyDate } from '../lib/dates'
import { categoryView, pendingRows, type CategoryView } from '../lib/rows'
import { LabelContext, useLabel, type LabelCtx } from './context'
import { LabelRow } from './LabelRow'
import { NotesSection } from './NotesSection'
import { ProposedSection } from './ProposedSection'
import { StatusChip } from './StatusChip'

interface Props {
  lookup: LookupResult | null
  loading: boolean
  error: string | null
  role: Role
  onRole: (r: Role) => void
  level: 'state' | 'city' | null
  onLevel: (l: 'state' | 'city' | null) => void
  onClose: () => void
  onClearUserFacts: () => void
  ctx: LabelCtx
}

function unitsText(f: LookupResult['facts']): { text: string; fromUseCode: boolean } {
  if (f.units != null && f.units_source !== 'use_description') return { text: `${f.units} units`, fromUseCode: false }
  const lo = f.units_min ?? null
  const hi = f.units_max ?? null
  const fromUseCode = f.units_source === 'use_description'
  if (lo != null && hi != null) return { text: lo === hi ? `${lo} units` : `${lo}-${hi} units`, fromUseCode }
  if (lo != null) return { text: `${lo}+ units`, fromUseCode }
  if (hi != null) return { text: `up to ${hi} units`, fromUseCode }
  if (f.units != null) return { text: `${f.units} units`, fromUseCode }
  return { text: 'units unknown', fromUseCode: false }
}

function BuildingLine({ lookup }: { lookup: LookupResult }) {
  const u = unitsText(lookup.facts)
  const yb = lookup.facts.year_built
  const city = lookup.jurisdiction_stack.find((j) => j.level === 'city')
  const postal = lookup._postal_city
  const differs = postal && city && postal.toLowerCase() !== city.name.toLowerCase()
  const user = lookup._user_facts ?? {}
  return (
    <div className="building">
      <p className="building-line">
        <span>
          {u.text}
          {u.fromUseCode && <span className="tag-src">from assessor use code</span>}
        </span>
        <span> · {yb != null ? `built ${yb}` : 'year unknown'}</span>
        <span> · {lookup.address}</span>
      </p>
      {differs && (
        <p className="mailing">
          Mailing city: {postal} · Legal city: {city!.name}
        </p>
      )}
      {!city && <p className="mailing warn">City not confirmed. Only state rules are shown.</p>}
      {city && city.confirmed === false && lookup._jurisdiction_confidence !== 'medium' && (
        <p className="mailing warn">City not confirmed by the address match. Flagged for human review.</p>
      )}
      {Object.keys(user).length > 0 && (
        <p className="user-input">
          <span className="tag-user">Using your input</span>{' '}
          {Object.entries(user)
            .map(([k, v]) => (k === 'year_built' ? `built ${v}` : `${factLabel(k)} ${v}`))
            .join(', ')}
        </p>
      )}
    </div>
  )
}

/** Building-level prompt: facts that some Unknown rows depend on, with inputs for the editable ones. */
function MissingFacts({ lookup }: { lookup: LookupResult }) {
  const ctx = useLabel()
  const counts = new Map<string, number>()
  for (const b of lookup.categories)
    for (const r of b.rows) if (r.result === 'unknown') for (const f of r.missing_facts) counts.set(f, (counts.get(f) ?? 0) + 1)
  if (!counts.size) return null
  const editable = [...counts.keys()].filter((f) => f in EDITABLE_FACTS)
  return (
    <div className="missing">
      <p className="lrow-line">
        <StatusChip status="unknown" small /> Some rules depend on facts we do not have:{' '}
        {[...counts.entries()].map(([f, n]) => `${factLabel(f)} (${n})`).join(', ')}
      </p>
      {editable.map((f) => (
        <FactInput
          key={f}
          fact={f}
          disabled={!ctx.onSubmitFact}
          disabledNote={ctx.offlineNote}
          busy={ctx.factBusy}
          onSubmit={(fact, v) => ctx.onSubmitFact?.(fact, v)}
        />
      ))}
    </div>
  )
}

function CategorySection({ view, index }: { view: CategoryView; index: number }) {
  const [more, setMore] = useState(false)
  const { block, winner, others, superseded } = view
  const hidden = others.length + superseded.length
  return (
    <motion.section
      className="cat"
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: 0.04 * index, duration: 0.25 }}
    >
      {winner ? (
        <LabelRow row={winner} question={block.question} />
      ) : (
        <div className="lrow lrow-none">
          <h3 className="lrow-q">{block.question}</h3>
          <p className="lrow-answer muted">{block.no_rule_note ?? 'No rule found in our sources for this level'}</p>
          <div className="lrow-tags">
            <StatusChip status="none" />
          </div>
        </div>
      )}
      {superseded.length > 0 && winner && winner.result !== 'superseded' && (
        <div className="steps-aside">
          {superseded.slice(0, more ? undefined : 1).map((r) => (
            <SupersededLine key={r.team_rule_id} row={r} />
          ))}
        </div>
      )}
      {hidden > 0 && (
        <button type="button" className="more" onClick={() => setMore((m) => !m)}>
          {more ? 'Hide other rules' : `${hidden} more ${hidden === 1 ? 'rule' : 'rules'} in this category`}
        </button>
      )}
      {more && (
        <div className="others">
          {others.map((r) => (
            <LabelRow key={r.team_rule_id} row={r} sub />
          ))}
          {superseded.map((r) => (
            <LabelRow key={r.team_rule_id} row={r} sub />
          ))}
        </div>
      )}
    </motion.section>
  )
}

function SupersededLine({ row }: { row: LookupRow }) {
  const { rulesById, onOpenSource } = useLabel()
  const sup = row.superseded_by ? rulesById.get(row.superseded_by) : null
  return (
    <p className="superseded-line">
      <StatusChip status="superseded" small />{' '}
      {row.level === 'state' ? 'State rule steps aside' : 'City rule steps aside'}:{' '}
      <button type="button" className="link-mono" onClick={() => onOpenSource(row)}>
        {row.citation}
      </button>{' '}
      yields to <span className="mono">{row.superseded_by_citation ?? sup?.citation ?? row.superseded_by ?? 'another rule'}</span>
    </p>
  )
}

export function RightsLabel({ lookup, loading, error, role, onRole, level, onLevel, onClose, onClearUserFacts, ctx }: Props) {
  const views = lookup ? lookup.categories.map((b) => categoryView(b, level)) : []
  const pending = lookup ? pendingRows(lookup, level) : []
  return (
    <LabelContext.Provider value={ctx}>
      <motion.aside
        className="label"
        initial={{ x: 60, opacity: 0 }}
        animate={{ x: 0, opacity: 1 }}
        exit={{ x: 60, opacity: 0 }}
        transition={{ duration: 0.35 }}
        aria-label="Rights label"
      >
        <header className="label-head">
          <h1 className="label-title">Rights label</h1>
          <div className="role-toggle" role="group" aria-label="View as">
            {(['tenant', 'owner'] as const).map((r) => (
              <button key={r} type="button" className={role === r ? 'on' : ''} onClick={() => onRole(r)}>
                {r === 'tenant' ? 'Tenant' : 'Owner'}
              </button>
            ))}
          </div>
          <button type="button" className="icon-btn" onClick={onClose} aria-label="Close label">
            <X size={20} />
          </button>
        </header>

        {error && (
          <div className="label-error">
            <p>{error}</p>
          </div>
        )}
        {!lookup && loading && <p className="label-loading">Loading this building…</p>}

        {lookup && (
          <>
            <BuildingLine lookup={lookup} />
            <MissingFacts lookup={lookup} />
            <nav className="crumbs" aria-label="Jurisdiction">
              {lookup.jurisdiction_stack.map((j, i) => (
                <span key={j.jurisdiction}>
                  {i > 0 && <span className="sep"> › </span>}
                  <button
                    type="button"
                    className={level === j.level ? 'on' : ''}
                    onClick={() => onLevel(level === j.level ? null : j.level)}
                    title={`Show only ${j.level} rules`}
                  >
                    {j.name}
                  </button>
                </span>
              ))}
              {level && (
                <button type="button" className="clear-level" onClick={() => onLevel(null)}>
                  Show all levels
                </button>
              )}
              {lookup._user_facts && (
                <button type="button" className="clear-level" onClick={onClearUserFacts}>
                  Clear my input
                </button>
              )}
            </nav>
            <div className="rule-heavy" />
            <div className="col-head">
              <span>
                As of <span className="mono">{prettyDate(lookup.as_of)}</span>
                {loading && <span className="muted"> · updating</span>}
              </span>
              <span>Source</span>
            </div>
            <div className="cats">
              {views.map((v, i) => (
                <CategorySection key={`${v.block.category}`} view={v} index={i} />
              ))}
            </div>
            <div className="rule-heavy" />
            <ProposedSection rows={pending} />
            <NotesSection notes={lookup.notes} />
          </>
        )}
        <footer className="label-foot">Not legal advice. Tap a citation to see the exact sentence in the law.</footer>
      </motion.aside>
    </LabelContext.Provider>
  )
}
