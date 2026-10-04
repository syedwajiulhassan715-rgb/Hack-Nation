import { useRef, useState } from 'react'
import { motion } from 'motion/react'
import { AlertTriangle, Check, Circle, Loader2, Upload, X } from 'lucide-react'
import { ApiError, getRuleSource, ingest, type IngestEvent, type IngestSummary, type Mode } from '../api/client'
import type { RuleRecord } from '../api/types'
import { prettyDate } from '../lib/dates'

interface Props {
  mode: Mode
  asOf: string
  onClose: () => void
  /** called after a finished run: ripple from the law's jurisdiction, refresh the label */
  onDone: (r: { jurisdiction: string | null; affected: string[] }) => void
  onShowRule: (rule: RuleRecord) => void
}

/** Pipeline steps reported by POST /ingest, grouped under the plan's checklist wording. */
const STEP_LABEL: Record<string, string> = {
  validate: 'Reading document: checking the SOURCE / RETRIEVED header',
  register: 'Reading document: registering it as a supplement',
  ingest: 'Reading document',
  chunk: 'Reading document: splitting into chunks',
  extract: 'Extracting rules',
  verify: 'Verifying quotes',
  lookups: 'Recomputing buildings',
  changes: 'Recomputing change tests',
}
const STEP_ORDER = Object.keys(STEP_LABEL)

type Phase = 'idle' | 'running' | 'done' | 'error' | 'unavailable'
type StepState = { status: 'start' | 'done' | 'error'; message?: string }

const STATUS_WORD: Record<string, string> = {
  in_force: 'In force',
  not_yet_effective: 'Starts later',
  pending: 'Proposed',
  failed: 'Did not become law',
}

export function IngestPanel({ mode, asOf, onClose, onDone, onShowRule }: Props) {
  const [file, setFile] = useState<File | null>(null)
  const [live, setLive] = useState(true)
  const [jurisdiction, setJurisdiction] = useState('')
  const [phase, setPhase] = useState<Phase>('idle')
  const [error, setError] = useState<string | null>(null)
  const [events, setEvents] = useState<IngestEvent[]>([])
  const [steps, setSteps] = useState<Record<string, StepState>>({})
  const [summary, setSummary] = useState<IngestSummary | null>(null)
  const [newRules, setNewRules] = useState<RuleRecord[]>([])
  const [drag, setDrag] = useState(false)
  const input = useRef<HTMLInputElement | null>(null)

  const offline = mode !== 'api'

  const run = async () => {
    if (!file) return
    setPhase('running')
    setError(null)
    setEvents([])
    setSteps({})
    setSummary(null)
    setNewRules([])
    let final: IngestEvent | null = null
    try {
      await ingest(
        file,
        (e) => {
          setEvents((list) => [...list, e])
          if (e.step && (e.status === 'start' || e.status === 'done' || e.status === 'error')) {
            setSteps((s) => ({ ...s, [e.step!]: { status: e.status as StepState['status'], message: e.message } }))
          }
          if (e.status === 'finished' || e.status === 'failed') final = e
        },
        { live, jurisdiction },
      )
      const f = final as IngestEvent | null
      if (!f) throw new Error('The stream ended without a final result. Nothing is confirmed.')
      if (f.status === 'failed') {
        throw new Error(`Failed at ${f.step ?? 'an unknown step'}: ${f.reason ?? 'no reason given'}`)
      }
      const sum = f.summary ?? {}
      setSummary(sum)
      setPhase('done')
      const ids = [...new Set([...(sum.rules_new ?? []), ...(sum.rules_from_doc ?? [])])].slice(0, 12)
      const recs = await Promise.all(
        ids.map((id) =>
          getRuleSource(id, asOf)
            .then((s) => s.rule)
            .catch(() => null),
        ),
      )
      setNewRules(recs.filter((r): r is RuleRecord => !!r))
      onDone({ jurisdiction: sum.jurisdiction ?? null, affected: [] })
    } catch (e) {
      if (e instanceof ApiError && e.status === 501) {
        setPhase('unavailable')
        setError(e.message)
      } else {
        setPhase('error')
        const prefix = e instanceof ApiError && e.status ? `${e.status}: ` : ''
        setError(prefix + (e instanceof Error ? e.message : String(e)))
      }
    }
  }

  const seen = STEP_ORDER.filter((s) => steps[s])
  const shown = phase === 'idle' ? [] : STEP_ORDER

  return (
    <motion.div
      className="ingest"
      role="dialog"
      aria-label="Add a new law"
      initial={{ opacity: 0, y: -8 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -8 }}
    >
      <header className="ingest-head">
        <h2>Add a new law</h2>
        <button type="button" className="icon-btn" onClick={onClose} aria-label="Close">
          <X size={18} />
        </button>
      </header>
      <p className="muted small">
        Drop a text file in the corpus format (a <span className="mono">SOURCE:</span> line and a{' '}
        <span className="mono">RETRIEVED:</span> line, a blank line, then the text). The pipeline extracts rules,
        checks every quote against the text and recomputes the buildings. A run takes a minute or two.
      </p>

      {offline && (
        <p className="state-note">Adding a law needs the API. The app is running on bundled data, so this is turned off.</p>
      )}

      <div
        className={`drop${drag ? ' over' : ''}${offline ? ' disabled' : ''}`}
        onDragOver={(e) => {
          e.preventDefault()
          setDrag(true)
        }}
        onDragLeave={() => setDrag(false)}
        onDrop={(e) => {
          e.preventDefault()
          setDrag(false)
          const f = e.dataTransfer.files?.[0]
          if (f && !offline) setFile(f)
        }}
        onClick={() => !offline && input.current?.click()}
      >
        <Upload size={18} />
        <span>{file ? file.name : 'Drop a .txt file here, or click to choose one'}</span>
        <input ref={input} type="file" accept=".txt,text/plain" hidden onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
      </div>
      <label className="field">
        <span>Jurisdiction (needed for a document not in the manifest)</span>
        <input
          value={jurisdiction}
          onChange={(e) => setJurisdiction(e.target.value)}
          placeholder="ST or City, ST"
          disabled={offline}
        />
      </label>
      <label className="check">
        <input type="checkbox" checked={live} onChange={(e) => setLive(e.target.checked)} disabled={offline} /> Run with the
        model cache off (live extraction)
      </label>
      <div className="ingest-actions">
        <button type="button" className="btn btn-ink" disabled={!file || offline || phase === 'running'} onClick={run}>
          {phase === 'error' || phase === 'unavailable' ? 'Try again' : phase === 'running' ? 'Running' : 'Run the pipeline'}
        </button>
      </div>

      {shown.length > 0 && (
        <ol className="steps">
          {shown.map((s) => {
            const st = steps[s]
            const icon =
              st?.status === 'done' ? (
                <Check size={16} />
              ) : st?.status === 'error' ? (
                <AlertTriangle size={16} />
              ) : st?.status === 'start' ? (
                <Loader2 size={16} className="spin" />
              ) : (
                <Circle size={16} />
              )
            return (
              <li key={s} className={st ? (st.status === 'start' ? 'active' : st.status) : ''}>
                {icon}
                <span>
                  {STEP_LABEL[s]}
                  {st?.message && <span className="mono muted step-msg"> · {st.message}</span>}
                </span>
              </li>
            )
          })}
          {seen.length === 0 && phase === 'running' && <li className="active">Waiting for the server…</li>}
        </ol>
      )}

      {phase === 'unavailable' && (
        <div className="state-note">
          <p>
            <strong>Live ingest is not available on this server.</strong>
          </p>
          {error && <p className="mono small">{error}</p>}
          <p className="small">Nothing was added. The rules on the map are unchanged.</p>
        </div>
      )}
      {phase === 'error' && (
        <div className="state-note error">
          <p>
            <strong>The run did not finish.</strong> Nothing new is shown.
          </p>
          {error && <p className="mono small">{error}</p>}
        </div>
      )}

      {phase === 'done' && summary && (
        <div className="result-card">
          <h3>Result</h3>
          <p className="small">
            Document <span className="mono">{summary.doc_id}</span> ({summary.jurisdiction}) · {summary.n_candidates ?? 0}{' '}
            candidates · {summary.rules_new?.length ?? 0} new, {summary.rules_changed?.length ?? 0} changed,{' '}
            {summary.rules_removed?.length ?? 0} removed rules
          </p>
          {newRules.length === 0 ? (
            <p className="muted small">No rule from this document passed verification.</p>
          ) : (
            <ul>
              {newRules.map((r) => (
                <li key={r.team_rule_id}>
                  <span className="mono">{r.citation}</span> · {STATUS_WORD[r.status] ?? r.status} · effective{' '}
                  {prettyDate(r.effective_date)}{' '}
                  <button type="button" className="link" onClick={() => onShowRule(r)}>
                    Show source
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      {events.length > 0 && (
        <details className="events">
          <summary>Progress log ({events.length})</summary>
          <pre>{events.map((e) => JSON.stringify(e)).join('\n')}</pre>
        </details>
      )}
      <p className="fine">As of {prettyDate(asOf)} · Not legal advice.</p>
    </motion.div>
  )
}
