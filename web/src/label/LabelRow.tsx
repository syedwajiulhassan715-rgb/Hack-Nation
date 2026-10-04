import { useState } from 'react'
import { motion } from 'motion/react'
import type { LookupRow } from '../api/types'
import { EDITABLE_FACTS, factLabel } from '../copy'
import { countdown } from '../lib/dates'
import { answerText, derivedFromYearBuilt, isLowConfidence } from '../lib/rows'
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
  const [open, setOpen] = useState(false)
  const ans = answerText(row, sub ? 120 : 180)
  const low = isLowConfidence(row)
  const cd = row.result === 'not_yet_effective' ? countdown(ctx.asOf, row.effective_date) : null
  const editable = row.missing_facts.filter((f) => f in EDITABLE_FACTS)

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
      transition={{ duration: 0.3 }}
      onClick={() => setOpen((o) => !o)}
      role="button"
      tabIndex={0}
      aria-expanded={open}
      onKeyDown={(e) => {
        if (e.key === 'Enter' && e.target === e.currentTarget) setOpen((o) => !o)
      }}
    >
      <div className="lrow-main">
        <div className="lrow-text">
          {question && <h3 className="lrow-q">{question}</h3>}
          {sub && <div className="lrow-title">{row.title}</div>}
          <p
            className={`lrow-answer${ans.isQuote ? ' is-quote' : ''}${low ? ' low-conf' : ''}`}
            title={low ? ['Confidence reasons:', ...row.confidence_reasons].join('\n') : undefined}
          >
            {ans.isQuote ? `“${ans.text}”` : ans.text}
          </p>
          {row.result === 'unknown' && row.missing_facts.length > 0 && (
            <p className="lrow-line">Depends on: {row.missing_facts.map(factLabel).join(', ')}</p>
          )}
          {cd && <p className="lrow-line lrow-countdown">{cd}</p>}
          {row.conflict_flag && (
            <p className="lrow-line lrow-conflict-line">
              Two laws disagree. A court would decide.
              {row.conflict_note && <span className="fine"> {row.conflict_note}</span>}
            </p>
          )}
          {row.conflict_note && !row.conflict_flag && (
            <p className="lrow-line fine">Sources disagree on the date: {row.conflict_note}</p>
          )}
          {derivedFromYearBuilt(row) && (
            <p className="fine">Based on year built, not the certificate of occupancy date</p>
          )}
          <div className="lrow-tags">
            <StatusChip status={row.result} small={sub} />
            {row.conflict_flag && <StatusChip status="conflict" small={sub} />}
            {low && <span className="tag-review">Needs human review</span>}
            {row.level && <span className="tag-level">{row.level === 'city' ? 'City' : 'State'}</span>}
          </div>
        </div>
        <button
          type="button"
          className="lrow-cite"
          onClick={(e) => {
            e.stopPropagation()
            ctx.onOpenSource(row)
          }}
          title="Show the exact sentence in the law"
        >
          {row.citation || 'Citation missing'}
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
