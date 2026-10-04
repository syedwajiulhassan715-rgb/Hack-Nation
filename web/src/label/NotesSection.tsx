import type { LookupNote } from '../api/types'
import { prettyDate } from '../lib/dates'
import { useI18n } from '../i18n'

export function NotesSection({ notes }: { notes: LookupNote[] }) {
  const { t, lang } = useI18n()
  return (
    <section className="label-section notes">
      <h2 className="section-title">{t.notes}</h2>
      {notes.length === 0 ? (
        <p className="empty">{t.notesEmpty}</p>
      ) : (
        <ul>
          {notes.map((n, i) => (
            <li key={`${n.team_rule_id ?? i}`}>
              <s lang="en">{n.text}</s> <span className="muted-strong">{t.didNotBecomeLaw}</span>
              {n.date && <span className="mono"> · {prettyDate(n.date, lang)}</span>}
              <span className="mono"> · {n.jurisdiction}</span>
              {n.source_url && (
                <>
                  {' · '}
                  <a href={n.source_url} target="_blank" rel="noreferrer">
                    {t.source}
                  </a>
                </>
              )}
              {n.retrieved_at && (
                <span className="mono fine">
                  {' '}
                  {t.retrieved} {n.retrieved_at}
                </span>
              )}
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
