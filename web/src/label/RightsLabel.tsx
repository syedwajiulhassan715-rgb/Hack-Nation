import { useEffect, useRef, useState } from 'react'
import { motion } from 'motion/react'
import { X } from 'lucide-react'
import type { LookupResult, LookupRow, Role } from '../api/types'
import { EDITABLE_FACTS } from '../copy'
import { useI18n, type Strings } from '../i18n'
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

function unitsText(f: LookupResult['facts'], t: Strings): { text: string; fromUseCode: boolean } {
  if (f.units != null && f.units_source !== 'use_description') return { text: t.units(f.units), fromUseCode: false }
  const lo = f.units_min ?? null
  const hi = f.units_max ?? null
  const fromUseCode = f.units_source === 'use_description'
  if (lo != null && hi != null) return { text: lo === hi ? t.units(lo) : t.unitsRange(lo, hi), fromUseCode }
  if (lo != null) return { text: t.unitsMin(lo), fromUseCode }
  if (hi != null) return { text: t.unitsMax(hi), fromUseCode }
  if (f.units != null) return { text: t.units(f.units), fromUseCode }
  return { text: t.unitsUnknown, fromUseCode: false }
}

function BuildingLine({ lookup }: { lookup: LookupResult }) {
  const { t } = useI18n()
  const u = unitsText(lookup.facts, t)
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
          {u.fromUseCode && <span className="tag-src">{t.fromUseCode}</span>}
        </span>
        <span> · {yb != null ? t.built(yb) : t.yearUnknown}</span>
        <span> · {lookup.address}</span>
      </p>
      {differs && <p className="mailing">{t.mailing(postal, city!.name)}</p>}
      {!city && <p className="mailing warn">{t.cityNotConfirmedLabel}</p>}
      {city && city.confirmed === false && lookup._jurisdiction_confidence !== 'medium' && (
        <p className="mailing warn">{t.cityNotConfirmedReview}</p>
      )}
      {Object.keys(user).length > 0 && (
        <p className="user-input">
          <span className="tag-user">{t.usingInput}</span>{' '}
          {Object.entries(user)
            .map(([k, v]) => (k === 'year_built' ? t.built(v) : `${t.factLabels[k] ?? k} ${v}`))
            .join(', ')}
        </p>
      )}
    </div>
  )
}

/** Building-level prompt: facts that some Unknown rows depend on, with inputs for the editable ones. */
function MissingFacts({ lookup }: { lookup: LookupResult }) {
  const ctx = useLabel()
  const { t } = useI18n()
  const counts = new Map<string, number>()
  for (const b of lookup.categories)
    for (const r of b.rows) if (r.result === 'unknown') for (const f of r.missing_facts) counts.set(f, (counts.get(f) ?? 0) + 1)
  if (!counts.size) return null
  const editable = [...counts.keys()].filter((f) => f in EDITABLE_FACTS)
  return (
    <div className="missing">
      <p className="lrow-line">
        <StatusChip status="unknown" small /> {t.missingFacts}{' '}
        {[...counts.entries()].map(([f, n]) => `${t.factLabels[f] ?? f.replace(/_/g, ' ')} (${n})`).join(', ')}
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
  const { t, lang } = useI18n()
  const { role } = useLabel()
  const [more, setMore] = useState(false)
  const { block, winner, others, superseded } = view
  const hidden = others.length + superseded.length
  // English: the API's wording; Spanish: fixed UI copy for the same six questions.
  const question = lang === 'es' ? t.questions[block.category][role] : block.question
  return (
    <motion.section
      className="cat"
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: 0.04 * index, duration: 0.25 }}
    >
      {winner ? (
        <LabelRow row={winner} question={question} />
      ) : (
        <div className="lrow lrow-none">
          <h3 className="lrow-q">{question}</h3>
          <p className="lrow-answer">{(lang === 'en' && block.no_rule_note) || t.noRule}</p>
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
        <button type="button" className="more" onClick={() => setMore((m) => !m)} aria-expanded={more}>
          {more ? t.hideOthers : t.moreRules(hidden)}
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
  const { t } = useI18n()
  const sup = row.superseded_by ? rulesById.get(row.superseded_by) : null
  return (
    <p className="superseded-line">
      <StatusChip status="superseded" small /> {row.level === 'state' ? t.stateStepsAside : t.cityStepsAside}:{' '}
      <button type="button" className="link-mono" onClick={() => onOpenSource(row)} lang="en">
        {row.citation}
      </button>{' '}
      {t.yieldsTo}{' '}
      <span className="mono" lang="en">
        {row.superseded_by_citation ?? sup?.citation ?? row.superseded_by ?? t.anotherRule}
      </span>
    </p>
  )
}

export function RightsLabel({ lookup, loading, error, role, onRole, level, onLevel, onClose, onClearUserFacts, ctx }: Props) {
  const { t, lang } = useI18n()
  const views = lookup ? lookup.categories.map((b) => categoryView(b, level)) : []
  const pending = lookup ? pendingRows(lookup, level) : []
  const titleRef = useRef<HTMLHeadingElement | null>(null)
  const addressId = lookup?.address_id ?? null
  // Move focus to the label when a new building opens, so keyboard users land on it.
  useEffect(() => {
    if (addressId) titleRef.current?.focus({ preventScroll: true })
  }, [addressId])

  return (
    <LabelContext.Provider value={ctx}>
      <motion.aside
        className="label"
        initial={{ x: 60, opacity: 0 }}
        animate={{ x: 0, opacity: 1 }}
        exit={{ x: 60, opacity: 0 }}
        transition={{ duration: 0.35 }}
        aria-labelledby="label-title"
        aria-busy={loading}
      >
        <header className="label-head">
          <h1 className="label-title" id="label-title" ref={titleRef} tabIndex={-1}>
            {t.rightsLabel}
          </h1>
          <div className="role-toggle" role="group" aria-label={t.viewAs}>
            {(['tenant', 'owner'] as const).map((r) => (
              <button key={r} type="button" className={role === r ? 'on' : ''} aria-pressed={role === r} onClick={() => onRole(r)}>
                {r === 'tenant' ? t.tenant : t.owner}
              </button>
            ))}
          </div>
          <button type="button" className="icon-btn" onClick={onClose} aria-label={t.closeLabel}>
            <X size={20} aria-hidden />
          </button>
        </header>

        {error && (
          <div className="label-error" role="alert">
            <p>{error}</p>
          </div>
        )}
        {!lookup && loading && (
          <div className="label-skeleton" role="status">
            <p className="label-loading">{t.loadingBuilding}</p>
            {[0, 1, 2, 3, 4, 5].map((i) => (
              <div key={i} className="skel-row" />
            ))}
          </div>
        )}

        {lookup && (
          <>
            <BuildingLine lookup={lookup} />
            <MissingFacts lookup={lookup} />
            <nav className="crumbs" aria-label={t.jurisdiction}>
              {lookup.jurisdiction_stack.map((j, i) => (
                <span key={j.jurisdiction}>
                  {i > 0 && (
                    <span className="sep" aria-hidden>
                      {' '}
                      ›{' '}
                    </span>
                  )}
                  <button
                    type="button"
                    className={level === j.level ? 'on' : ''}
                    aria-pressed={level === j.level}
                    onClick={() => onLevel(level === j.level ? null : j.level)}
                    title={t.showOnly(j.level)}
                  >
                    {j.name}
                  </button>
                </span>
              ))}
              {level && (
                <button type="button" className="clear-level" onClick={() => onLevel(null)}>
                  {t.showAllLevels}
                </button>
              )}
              {lookup._user_facts && (
                <button type="button" className="clear-level" onClick={onClearUserFacts}>
                  {t.clearInput}
                </button>
              )}
            </nav>
            {lang === 'es' && <p className="lang-note">{t.langNote}</p>}
            <div className="rule-heavy" />
            <div className="col-head">
              <span>
                {t.asOf} <span className="mono">{prettyDate(lookup.as_of, lang)}</span>
                {loading && <span className="muted"> · {t.updating}</span>}
              </span>
              <span>{t.source}</span>
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
        <footer className="label-foot">
          {t.disclaimer} <span className="label-foot-sub">{t.labelFoot}</span>
        </footer>
      </motion.aside>
    </LabelContext.Provider>
  )
}
