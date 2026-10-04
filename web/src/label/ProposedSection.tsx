import type { Category, LookupRow } from '../api/types'
import { useI18n } from '../i18n'
import { LabelRow } from './LabelRow'

export function ProposedSection({ rows }: { rows: Array<LookupRow & { category: string }> }) {
  const { t } = useI18n()
  return (
    <section className="label-section proposed">
      <h2 className="section-title">{t.proposed}</h2>
      {rows.length === 0 ? (
        <p className="empty">{t.proposedEmpty}</p>
      ) : (
        rows.map((r) => (
          <div key={r.team_rule_id} className="ghost">
            <div className="ghost-cat">{t.categoryShort[r.category as Category] ?? r.category}</div>
            <LabelRow row={r} sub />
          </div>
        ))
      )}
    </section>
  )
}
