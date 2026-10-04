import { useState } from 'react'
import type { AuditEntry, RuleRecord } from '../api/types'
import { getAudit, type Mode } from '../api/client'

export function AuditTrail({ rule }: { rule: RuleRecord }) {
  const [open, setOpen] = useState(false)
  const [state, setState] = useState<{ entries: AuditEntry[]; source: Mode } | null>(null)
  const [error, setError] = useState<string | null>(null)

  const toggle = async () => {
    const next = !open
    setOpen(next)
    if (next && !state) {
      try {
        setState(await getAudit(rule))
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e))
      }
    }
  }

  return (
    <div className="audit">
      <button type="button" className="more" onClick={toggle} aria-expanded={open}>
        {open ? 'Hide audit trail' : 'Audit trail'}
      </button>
      {open && (
        <div className="audit-body">
          {error && <p className="fact-error">{error}</p>}
          {!state && !error && <p className="muted">Loading…</p>}
          {state && state.entries.length === 0 && <p className="muted">No audit entries recorded for this rule.</p>}
          {state && state.entries.length > 0 && (
            <ol>
              {state.entries.map((e, i) => (
                <li key={i} className="mono">
                  {e.ts && <span className="muted">{e.ts} </span>}
                  <strong>{e.stage ?? 'step'}</strong>: {e.decision ?? ''}
                  {e.model && <> · model {e.model}</>}
                  {e.prompt_version && <> · prompt {e.prompt_version}</>}
                  {e.reason && <span className="muted"> · {e.reason}</span>}
                </li>
              ))}
            </ol>
          )}
          {state?.source === 'offline' && (
            <p className="fine">Offline: built from the rule's provenance in the bundled rules file.</p>
          )}
        </div>
      )}
    </div>
  )
}
