import { useEffect, useState } from 'react'
import { ArrowLeft, MapPin } from 'lucide-react'
import { getChanges, getEvalReport } from '../api/client'
import type { ChangesBundle } from '../api/types'
import { prettyDate } from '../lib/dates'
import { navigate } from '../lib/router'
import { Footer } from '../layout/Footer'
import type { Mode } from '../api/client'
import { changeKind, testCategory, testDate, type ChangeKind } from '../lib/changes'

const KIND_TITLE: Record<ChangeKind, string> = {
  enacted: 'Enacted and in force',
  not_yet_effective: 'Enacted, not yet effective',
  pending: 'Pending (proposed, not law)',
  failed: 'Failed (did not become law)',
}

interface Props {
  mode: Mode
}

export function ChangesPage({ mode }: Props) {
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
          <ArrowLeft size={16} /> Back to the map
        </button>
        <h1>Change tests</h1>
        <p className="mono">
          As of {prettyDate(asOf)} · Not legal advice · {mode === 'api' ? 'Live API' : 'Bundled data'}
        </p>
      </header>
      {error && <p className="fact-error">{error}</p>}
      {!data && !error && <p className="muted">Loading…</p>}
      {data &&
        (Object.keys(groups) as ChangeKind[]).map((kind) => (
          <section key={kind} className={`change-group kind-${kind}`}>
            <h2>{KIND_TITLE[kind]}</h2>
            {groups[kind].length === 0 && <p className="muted">No supplied test of this kind.</p>}
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
                      <h4>Expected (from the test file)</h4>
                      <p>{def?.expected_behavior ?? inn.expected_behavior ?? 'Not stated'}</p>
                      {def && (
                        <p className="mono small">
                          {def.as_of_before && <>before {def.as_of_before} → after {def.as_of_after}</>}
                          {def.as_of && <>as of {def.as_of}</>}
                        </p>
                      )}
                    </div>
                    <div>
                      <h4>Our result</h4>
                      {out ? (
                        <p>
                          <strong>{out.affected_address_ids.length}</strong> affected addresses ·{' '}
                          <strong>{out.conflict_flag_address_ids.length}</strong> conflict-flagged
                        </p>
                      ) : (
                        <p className="muted">No result in changes.json for this test.</p>
                      )}
                      <ul className="checks">
                        {(inn.checks ?? []).map((c, i) => (
                          <li key={i} className={c.passed === true ? 'pass' : c.passed === false ? 'fail' : 'na'}>
                            <span className="mono">{c.passed === true ? 'PASS' : c.passed === false ? 'FAIL' : 'NOT TESTABLE'}</span>{' '}
                            {c.name}
                            {c.detail && <span className="muted"> · {c.detail}</span>}
                          </li>
                        ))}
                        {(inn.checks ?? []).length === 0 && <li className="muted">No checks recorded.</li>}
                      </ul>
                    </div>
                  </div>
                  <details>
                    <summary>Notes: matched rules, dates used, data limits</summary>
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
                    <MapPin size={14} /> Show on map
                  </button>
                </article>
              )
            })}
          </section>
        ))}
      <section className="change-group">
        <h2>Self-evaluation report</h2>
        <p className="muted small">
          Our own evaluation harness output. The participant pack has no official scoring script.
        </p>
        <button type="button" className="btn" onClick={() => setShowReport((s) => !s)}>
          {showReport ? 'Hide the report' : 'Show the latest report'}
        </button>
        {showReport && <pre className="report">{report ?? 'No report available.'}</pre>}
      </section>
      <Footer asOf={asOf} mode={mode} />
    </div>
  )
}
