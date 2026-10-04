import type { LookupNote } from '../api/types'
import { prettyDate } from '../lib/dates'

export function NotesSection({ notes }: { notes: LookupNote[] }) {
  return (
    <section className="label-section notes">
      <h2 className="section-title">Notes</h2>
      {notes.length === 0 ? (
        <p className="empty">No measures that failed to become law are recorded in our sources for this state or city.</p>
      ) : (
        <ul>
          {notes.map((n, i) => (
            <li key={`${n.team_rule_id ?? i}`}>
              <s>{n.text}</s> <span className="muted">did not become law</span>
              {n.date && <span className="mono"> · {prettyDate(n.date)}</span>}
              <span className="mono"> · {n.jurisdiction}</span>
              {n.source_url && (
                <>
                  {' · '}
                  <a href={n.source_url} target="_blank" rel="noreferrer">
                    Source
                  </a>
                </>
              )}
              {n.retrieved_at && <span className="mono fine"> retrieved {n.retrieved_at}</span>}
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
