import type { LookupRow } from '../api/types'
import { prettyDate } from '../lib/dates'
import { useLabel } from './context'

const LEVEL_WORD = { state: 'State law', city: 'City law' } as const

export function RowDetail({ row }: { row: LookupRow }) {
  const { role, rulesById, onOpenSource, asOf } = useLabel()
  const sup = row.superseded_by ? rulesById.get(row.superseded_by) : null
  return (
    <div className="row-detail" onClick={(e) => e.stopPropagation()}>
      <dl>
        <dt>{role === 'owner' ? 'What you must do' : 'What this means for you'}</dt>
        <dd>
          {row.answer ?? (
            <>
              <span className="muted">No plain-language summary passed our checks. The law says: </span>
              <q className="quote">{row.quoted_span}</q>
            </>
          )}
        </dd>
        <dt>Who decides</dt>
        <dd>
          {LEVEL_WORD[row.level]}
          {row.result === 'superseded' && (
            <>
              {' '}
              steps aside here.{' '}
              {row.superseded_by_citation || sup ? (
                <>The governing rule is {row.superseded_by_citation ?? sup?.citation}.</>
              ) : row.superseded_by ? (
                <>Governing rule: {row.superseded_by}.</>
              ) : null}
            </>
          )}
          {row.conflict_flag && <> Two laws may disagree; this needs human review.</>}
        </dd>
        <dt>Effective</dt>
        <dd className="mono">{prettyDate(row.effective_date)}</dd>
        {row.key_value && (
          <>
            <dt>Key value</dt>
            <dd>{row.key_value}</dd>
          </>
        )}
        <dt>Why</dt>
        <dd>
          {row.explanation || <span className="muted">No explanation recorded.</span>}
          {row.derived_for_date && (
            <span className="fine">
              {' '}
              Status for {prettyDate(asOf)} taken from this building's timeline; the explanation was written for the
              default date.
            </span>
          )}
        </dd>
      </dl>
      <button type="button" className="btn btn-ink" onClick={() => onOpenSource(row)}>
        Show source
      </button>
    </div>
  )
}
