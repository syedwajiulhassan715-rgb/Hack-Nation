import { useEffect, useState } from 'react'
import { ArrowLeft, MapPin } from 'lucide-react'
import { getChanges, getEvalReport } from '../api/client'
import type { ChangesBundle } from '../api/types'
import { prettyDate } from '../lib/dates'
import { navigate } from '../lib/router'
import { Footer } from '../layout/Footer'
import type { Mode } from '../api/client'
import { changeKind, testCategory, testDate, type ChangeKind } from '../lib/changes'
import { useI18n } from '../i18n'

interface Props {
  mode: Mode
}

export function ChangesPage({ mode }: Props) {
  const { t, lang } = useI18n()
  const [data, setData] = useState<ChangesBundle | null>(null)
  const [report, setReport] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [showReport, setShowReport] = useState(false)

  useEffect(() => {
    getChanges()
      .then(setData)
      .catch((e) => setError(e instanceof Error ? e.message : String(e)))
    getEvalReport().then(setReport)
  }, [mode])

  const asOf = data?.as_of ?? null
  const ids = data ? [...new Set([...data.tests.map((t) => t.test_id), ...Object.keys(data.outputs)])].sort() : []
  const defs = new Map(data?.tests.map((t) => [t.test_id, t]) ?? [])
  const groups: Record<ChangeKind, string[]> = { enacted: [], not_yet_effective: [], pending: [], failed: [] }
  for (const id of ids) {
    const def = defs.get(id)
    const kind = def ? changeKind(def, asOf) : 'enacted'
    groups[kind].push(id)
  }

  return (
    <div className="page paper-page">
      <header className="page-head">
        <button type="button" className="btn" onClick={() => navigate('/')}>
          <ArrowLeft size={16} aria-hidden /> {t.backToMap}
        </button>
        <h1>{t.changesTitle}</h1>
        <p className="mono">
          {t.asOf} {prettyDate(asOf, lang)} · {t.disclaimer} · {mode === 'api' ? t.liveApi : t.bundledData}
        </p>
      </header>
      {error && <p className="fact-error">{error}</p>}
      {!data && !error && <p className="muted" role="status">{t.loading}</p>}
      {data &&
        (Object.keys(groups) as ChangeKind[]).map((kind) => (
          <section key={kind} className={`change-group kind-${kind}`}>
            <h2>{t.kinds[kind]}</h2>
            {groups[kind].length === 0 && <p className="muted">{t.noTestOfKind}</p>}
            {groups[kind].map((id) => {
              const def = defs.get(id)
              const out = data.outputs[id]
              const inn = data.internal[id] ?? {}
              const cat = def ? testCategory(def) : null
              const date = def ? testDate(def) : null
              return (
                <article key={id} className="change-card">
                  <header>
                    <span className="mono test-id">{id}</span>
                    <h3>{def?.title ?? inn.title ?? id}</h3>
                    <span className="mono muted">{def?.type ?? inn.type}</span>
                  </header>
                  <div className="change-cols">
                    <div>
                      <h4>{t.expected}</h4>
                      <p>{def?.expected_behavior ?? inn.expected_behavior ?? 'Not stated'}</p>
                      {def && (
                        <p className="mono small">
                          {def.as_of_before && <>before {def.as_of_before} → after {def.as_of_after}</>}
                          {def.as_of && <>as of {def.as_of}</>}
                        </p>
                      )}
                    </div>
                    <div>
                      <h4>{t.ourResult}</h4>
                      {out ? (
                        <p>
                          <strong>{t.affectedLine(out.affected_address_ids.length, out.conflict_flag_address_ids.length)}</strong>
                        </p>
                      ) : (
                        <p className="muted">{t.noResult}</p>
                      )}
                      <ul className="checks">
                        {(inn.checks ?? []).map((c, i) => (
                          <li key={i} className={c.passed === true ? 'pass' : c.passed === false ? 'fail' : 'na'}>
                            <span className="mono">{c.passed === true ? 'PASS' : c.passed === false ? 'FAIL' : 'NOT TESTABLE'}</span>{' '}
                            {c.name}
                            {c.detail && <span className="muted"> · {c.detail}</span>}
                          </li>
                        ))}
                        {(inn.checks ?? []).length === 0 && <li className="muted">{t.noChecks}</li>}
                      </ul>
                    </div>
                  </div>
                  <details>
                    <summary>{t.testNotes}</summary>
                    <ul className="notes-list">
                      {(inn.notes?.length ? inn.notes : (out?.notes ?? '').split(' | ')).map((n, i) => (
                        <li key={i}>{n}</li>
                      ))}
                    </ul>
                  </details>
                  <button
                    type="button"
                    className="btn btn-ink"
                    onClick={() => {
                      const q = new URLSearchParams()
                      if (cat) q.set('cat', cat)
                      if (date) q.set('date', date)
                      q.set('test', id)
                      navigate(`/?${q.toString()}`)
                    }}
                  >
                    <MapPin size={14} aria-hidden /> {t.showOnMap}
                  </button>
                </article>
              )
            })}
          </section>
        ))}
      <section className="change-group">
        <h2>{t.selfEval}</h2>
        <p className="muted small">{t.selfEvalNote}</p>
        <button type="button" className="btn" onClick={() => setShowReport((s) => !s)}>
          {showReport ? t.hideReport : t.showReport}
        </button>
        {showReport && <pre className="report">{report ?? t.noReport}</pre>}
      </section>
      <Footer asOf={asOf} mode={mode} />
    </div>
  )
}
