import { useState } from 'react'
import { motion } from 'motion/react'
import type { LookupRow } from '../api/types'
import { EDITABLE_FACTS } from '../copy'
import { countdown } from '../lib/dates'
import { answerText, derivedFromYearBuilt, isLowConfidence } from '../lib/rows'
import { useI18n } from '../i18n'
import { useLabel } from './context'
import { FactInput } from './FactInput'
import { RowDetail } from './RowDetail'
import { StatusChip } from './StatusChip'

interface Props {
  row: LookupRow
  question?: string | null
  sub?: boolean
}

export function LabelRow({ row, question, sub = false }: Props) {
  const ctx = useLabel()
  const { t, lang } = useI18n()
  const [open, setOpen] = useState(false)
  const ans = answerText(row, sub ? 120 : 180)
  const low = isLowConfidence(row)
  const cd = row.result === 'not_yet_effective' ? countdown(ctx.asOf, row.effective_date, lang) : null
  const editable = row.missing_facts.filter((f) => f in EDITABLE_FACTS)
  const factName = (f: string) => t.factLabels[f] ?? f.replace(/_/g, ' ')

  const cls = [
    'lrow',
    `lrow-${row.result}`,
    row.conflict_flag ? 'lrow-conflict' : '',
    sub ? 'lrow-sub' : '',
    open ? 'lrow-open' : '',
  ].join(' ')

  return (
    <motion.div
      key={row.result}
      className={cls}
      initial={{ rotateX: 80, opacity: 0.4 }}
      animate={{ rotateX: 0, opacity: 1 }}
      transition={{ type: 'spring', stiffness: 380, damping: 30 }}
      onClick={() => setOpen((o) => !o)}
      role="button"
      tabIndex={0}
      aria-expanded={open}
      onKeyDown={(e) => {
        if ((e.key === 'Enter' || e.key === ' ') && e.target === e.currentTarget) {
          e.preventDefault()
          setOpen((o) => !o)
        }
      }}
    >
      <div className="lrow-main">
        <div className="lrow-text">
          {question && <h3 className="lrow-q">{question}</h3>}
          {sub && (
            <div className="lrow-title" lang="en">
              {row.title}
            </div>
          )}
          <p
            className={`lrow-answer${ans.isQuote ? ' is-quote' : ''}${low ? ' low-conf' : ''}`}
            title={low ? [t.confidenceReasons, ...row.confidence_reasons].join('\n') : undefined}
            lang={ans.isQuote ? 'en' : lang}
          >
            {ans.kind === 'quote' && `“${ans.text}”`}
            {ans.kind === 'answer' && ans.text}
            {ans.kind === 'explanation' && (
              <>
                <strong>{t.whyApplies}</strong> <span lang="en">{ans.text}</span>
              </>
            )}
          </p>
          {ans.kind === 'explanation' && <p className="lrow-line fine">{t.exemptionQuoteNote}</p>}
          {row.result === 'unknown' && row.missing_facts.length > 0 && (
            <p className="lrow-line">
              {t.dependsOn} {row.missing_facts.map(factName).join(', ')}
            </p>
          )}
          {cd && <p className="lrow-line lrow-countdown">{cd}</p>}
          {row.conflict_flag && (
            <p className="lrow-line lrow-conflict-line">
              {t.conflictLine}
              {row.conflict_note && (
                <span className="fine" lang="en">
                  {' '}
                  {row.conflict_note}
                </span>
              )}
            </p>
          )}
          {row.conflict_note && !row.conflict_flag && (
            <p className="lrow-line fine">
              {t.datesDisagree} <span lang="en">{row.conflict_note}</span>
            </p>
          )}
          {derivedFromYearBuilt(row) && <p className="fine">{t.derivedYear}</p>}
          {low && row.confidence_reasons.length > 0 && (
            <p className="fine low-reasons" lang="en">
              {row.confidence_reasons.join(' · ')}
            </p>
          )}
          <div className="lrow-tags">
            <StatusChip status={row.result} small={sub} />
            {row.conflict_flag && <StatusChip status="conflict" small={sub} />}
            {low && <span className="tag-review">{t.needsReview}</span>}
            {row.level && <span className="tag-level">{row.level === 'city' ? t.levelCity : t.levelState}</span>}
          </div>
        </div>
        <button
          type="button"
          className="lrow-cite"
          onClick={(e) => {
            e.stopPropagation()
            ctx.onOpenSource(row)
          }}
          onKeyDown={(e) => e.stopPropagation()}
          title={t.citeTitle}
          lang="en"
        >
          {row.citation || t.citationMissing}
        </button>
      </div>
      {row.result === 'unknown' &&
        editable.map((f) => (
          <FactInput
            key={f}
            fact={f}
            disabled={!ctx.onSubmitFact}
            disabledNote={ctx.offlineNote}
            busy={ctx.factBusy}
            onSubmit={(fact, v) => ctx.onSubmitFact?.(fact, v)}
          />
        ))}
      {open && <RowDetail row={row} />}
    </motion.div>
  )
}
