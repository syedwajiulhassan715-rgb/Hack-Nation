import { useEffect, useRef, useState } from 'react'
import { motion } from 'motion/react'
import { AlertTriangle, Check, Circle, Loader2, Upload, X } from 'lucide-react'
import { ApiError, getRuleSource, ingest, type IngestEvent, type IngestSummary, type Mode } from '../api/client'
import type { RuleRecord } from '../api/types'
import { prettyDate } from '../lib/dates'
import { useI18n } from '../i18n'

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

/** The local command that runs the same live extraction (BACKEND_PLAN make rerun-live). */
const RERUN_COMMAND = 'python -m navigator rerun-live <file> --jurisdiction "City, ST"'

type Phase = 'idle' | 'running' | 'done' | 'error' | 'unavailable' | 'disabled'
type StepState = { status: 'start' | 'done' | 'error'; message?: string }

const STATUS_WORD: Record<string, string> = {
  in_force: 'In force',
  not_yet_effective: 'Starts later',
  pending: 'Proposed',
  failed: 'Did not become law',
}

/** Shown when live extraction cannot run here (403 from the API, or no API at all). */
function RunLocally({ lead }: { lead: string }) {
  const { t } = useI18n()
  return (
    <div className="state-note calm" role="status">
      <p>
        <strong>{lead}</strong>
      </p>
      <p className="small">{t.ingestLocal}</p>
      <pre className="cmd">{RERUN_COMMAND}</pre>
      <p className="small">{t.ingestUnchanged}</p>
    </div>
  )
}

export function IngestPanel({ mode, asOf, onClose, onDone, onShowRule }: Props) {
  const { t, lang } = useI18n()
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
  const closeRef = useRef<HTMLButtonElement | null>(null)

  const offline = mode !== 'api'
  const locked = offline || phase === 'disabled'

  useEffect(() => {
    closeRef.current?.focus({ preventScroll: true })
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

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
      if (e instanceof ApiError && e.status === 403) {
        // POST /ingest is turned off on the public deployment (NAVIGATOR_DISABLE_INGEST).
        setPhase('disabled')
        setError(e.message)
      } else if (e instanceof ApiError && e.status === 501) {
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
  const shown = phase === 'idle' || phase === 'disabled' ? [] : STEP_ORDER
  const pick = () => !locked && input.current?.click()

  return (
    <motion.div
      className="ingest"
      role="dialog"
      aria-labelledby="ingest-title"
      initial={{ opacity: 0, y: -8 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -8 }}
      transition={{ type: 'spring', stiffness: 340, damping: 30 }}
    >
      <header className="ingest-head">
        <h2 id="ingest-title">{t.addLaw}</h2>
        <button ref={closeRef} type="button" className="icon-btn" onClick={onClose} aria-label={t.close}>
          <X size={18} aria-hidden />
        </button>
      </header>
      <p className="small ingest-intro">
        {t.ingestIntro} (<span className="mono">SOURCE:</span> / <span className="mono">RETRIEVED:</span>)
      </p>

      {offline && phase !== 'disabled' && <RunLocally lead={t.ingestOffline} />}
      {phase === 'disabled' && <RunLocally lead={t.ingestDisabled} />}

      <div
        className={`drop${drag ? ' over' : ''}${locked ? ' disabled' : ''}`}
        role="button"
        tabIndex={locked ? -1 : 0}
        aria-disabled={locked}
        onDragOver={(e) => {
          e.preventDefault()
          setDrag(true)
        }}
        onDragLeave={() => setDrag(false)}
        onDrop={(e) => {
          e.preventDefault()
          setDrag(false)
          const f = e.dataTransfer.files?.[0]
          if (f && !locked) setFile(f)
        }}
        onClick={pick}
        onKeyDown={(e) => {
          if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault()
            pick()
          }
        }}
      >
        <Upload size={18} aria-hidden />
        <span>{file ? file.name : t.ingestDrop}</span>
        <input
          ref={input}
          type="file"
          accept=".txt,text/plain"
          hidden
          onChange={(e) => setFile(e.target.files?.[0] ?? null)}
        />
      </div>
      <label className="field">
        <span>{t.ingestJurisdiction}</span>
        <input
          value={jurisdiction}
          onChange={(e) => setJurisdiction(e.target.value)}
          placeholder="ST or City, ST"
          disabled={locked}
        />
      </label>
      <label className="check">
        <input type="checkbox" checked={live} onChange={(e) => setLive(e.target.checked)} disabled={locked} />{' '}
        {t.ingestLive}
      </label>
      <div className="ingest-actions">
        <button type="button" className="btn btn-ink" disabled={!file || locked || phase === 'running'} onClick={run}>
          {phase === 'error' || phase === 'unavailable' ? t.retry : phase === 'running' ? t.ingestRunning : t.ingestRun}
        </button>
      </div>

      {shown.length > 0 && (
        <ol className="steps" aria-live="polite" lang="en">
          {shown.map((s) => {
            const st = steps[s]
            const icon =
              st?.status === 'done' ? (
                <Check size={16} aria-hidden />
              ) : st?.status === 'error' ? (
                <AlertTriangle size={16} aria-hidden />
              ) : st?.status === 'start' ? (
                <Loader2 size={16} className="spin" aria-hidden />
              ) : (
                <Circle size={16} aria-hidden />
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
          <p className="small">{t.ingestUnchanged}</p>
        </div>
      )}
      {phase === 'error' && (
        <div className="state-note error" role="alert">
          <p>
            <strong>The run did not finish.</strong> Nothing new is shown.
          </p>
          {error && <p className="mono small">{error}</p>}
        </div>
      )}

      {phase === 'done' && summary && (
        <div className="result-card" lang="en">
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
                    {t.showSource}
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
      <p className="fine">
        {t.asOf} {prettyDate(asOf, lang)} · {t.disclaimer}
      </p>
    </motion.div>
  )
}
