import type { LookupRow } from '../api/types'
import { prettyDate } from '../lib/dates'
import { useI18n } from '../i18n'
import { useLabel } from './context'

export function RowDetail({ row }: { row: LookupRow }) {
  const { role, rulesById, onOpenSource, asOf } = useLabel()
  const { t, lang } = useI18n()
  const sup = row.superseded_by ? rulesById.get(row.superseded_by) : null
  const governing = row.superseded_by_citation ?? sup?.citation ?? row.superseded_by
  return (
    <div className="row-detail" onClick={(e) => e.stopPropagation()}>
      <dl>
        <dt>{role === 'owner' ? t.mustDo : t.meansForYou}</dt>
        <dd>
          {row.answer ?? (
            <>
              <span className="muted">{t.noSummary} </span>
              <q className="quote" lang="en">
                {row.quoted_span}
              </q>
            </>
          )}
        </dd>
        <dt>{t.whoDecides}</dt>
        <dd>
          {t.levelLaw[row.level]}
          {row.result === 'superseded' && (
            <>
              {' '}
              {t.stepsAsideHere} {governing && t.governingRule(governing)}
            </>
          )}
          {row.conflict_flag && <> {t.mayDisagree}</>}
        </dd>
        <dt>{t.effective}</dt>
        <dd className="mono">{prettyDate(row.effective_date, lang)}</dd>
        {row.key_value && (
          <>
            <dt>{t.keyValue}</dt>
            <dd lang="en">{row.key_value}</dd>
          </>
        )}
        <dt>{t.why}</dt>
        <dd>
          {row.explanation ? <span lang="en">{row.explanation}</span> : <span className="muted">{t.noExplanation}</span>}
          {row.derived_for_date && <span className="fine"> {t.derivedForDate(prettyDate(asOf, lang))}</span>}
        </dd>
      </dl>
      <button type="button" className="btn btn-ink" onClick={() => onOpenSource(row)}>
        {t.showSource}
      </button>
    </div>
  )
}
