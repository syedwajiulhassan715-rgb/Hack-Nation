import type { LookupRow } from '../api/types'
import { CATEGORY_SHORT } from '../copy'
import type { Category } from '../api/types'
import { LabelRow } from './LabelRow'

export function ProposedSection({ rows }: { rows: Array<LookupRow & { category: string }> }) {
  return (
    <section className="label-section proposed">
      <h2 className="section-title">Proposed, not law</h2>
      {rows.length === 0 ? (
        <p className="empty">No proposed bills in our sources for this address.</p>
      ) : (
        rows.map((r) => (
          <div key={r.team_rule_id} className="ghost">
            <div className="ghost-cat">{CATEGORY_SHORT[r.category as Category] ?? r.category}</div>
            <LabelRow row={r} sub />
          </div>
        ))
      )}
    </section>
  )
}
