import { useEffect, useState } from 'react'
import { motion } from 'motion/react'
import { ExternalLink, X } from 'lucide-react'
import type { LookupRow, RuleSource } from '../api/types'
import { getRuleSource } from '../api/client'
import { STATUS_WORD } from '../copy'
import { prettyDate } from '../lib/dates'
import { AuditTrail } from './AuditTrail'
import { HighlightedText } from './HighlightedText'

interface Props {
  row: LookupRow
  asOf: string
  onClose: () => void
  /** overrides the status word when the row is a bare rule, not a building result */
  statusText?: string
}

function BoundaryList({ title, items }: { title: string; items: string[] }) {
  return (
    <div className="boundary-list">
      <h4>{title}</h4>
      <ul>{items.length ? items.map((t, i) => <li key={i}>{t}</li>) : <li className="muted">Nothing recorded for this row</li>}</ul>
    </div>
  )
}

export function SourceDrawer({ row, asOf, onClose, statusText }: Props) {
  const [src, setSrc] = useState<RuleSource | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let live = true
    setSrc(null)
    setError(null)
    getRuleSource(row.team_rule_id, asOf)
      .then((s) => live && setSrc(s))
      .catch((e) => live && setError(e instanceof Error ? e.message : String(e)))
    return () => {
      live = false
    }
  }, [row.team_rule_id, asOf])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  const rule = src?.rule
  return (
    <motion.div
      className="drawer"
      role="dialog"
      aria-label="Source text"
      initial={{ y: '100%' }}
      animate={{ y: 0 }}
      exit={{ y: '100%' }}
      transition={{ duration: 0.3 }}
    >
      <header className="drawer-head mono">
        <div className="drawer-cite">{row.citation}</div>
        <div className="drawer-meta">
          <a href={src?.source_url ?? row.source_url} target="_blank" rel="noreferrer">
            Open official text <ExternalLink size={12} />
          </a>
          <span>Retrieved {src?.retrieved_at ?? row.retrieved_at ?? 'date not recorded'}</span>
          <span>Effective {prettyDate(row.effective_date)}</span>
          <span>Status {statusText ?? STATUS_WORD[row.result]}</span>
          {rule?.source_doc_id && <span>Document {rule.source_doc_id}</span>}
          <span>As of {prettyDate(asOf)}</span>
          <span className="nla">Not legal advice</span>
        </div>
        <button type="button" className="icon-btn" onClick={onClose} aria-label="Close source">
          <X size={20} />
        </button>
      </header>
      <div className="drawer-body">
        <div className="drawer-text">
          {error && <p className="fact-error">{error}</p>}
          {!src && !error && <p className="muted">Loading the source text…</p>}
          {src && src.text && <HighlightedText text={src.text} start={src.span_start} end={src.span_end} />}
          {src && (!src.text || src.span_start == null) && (
            <div>
              <p className="muted">
                {src.text
                  ? 'The quote could not be located in this text window. The verified quote is:'
                  : 'The source text is not bundled here. The verified quote is:'}
              </p>
              <blockquote className="statute">
                <mark className="hl">{row.quoted_span}</mark>
              </blockquote>
            </div>
          )}
        </div>
        <aside className="drawer-side">
          <div className="conf">
            <h4>Confidence</h4>
            <p className="mono">{row.confidence != null ? row.confidence.toFixed(2) : 'not scored'}</p>
            <ul>
              {row.confidence_reasons.length ? (
                row.confidence_reasons.map((r, i) => <li key={i}>{r}</li>)
              ) : (
                <li className="muted">No reasons recorded</li>
              )}
            </ul>
            {(rule?.review_reasons?.length ?? 0) > 0 && (
              <>
                <h4>Flagged for review</h4>
                <ul>
                  {rule!.review_reasons!.map((r, i) => (
                    <li key={i}>{r}</li>
                  ))}
                </ul>
              </>
            )}
          </div>
          <div className="boundary">
            <h3>Reasoning boundary</h3>
            <BoundaryList title="What we checked" items={row.checked} />
            <BoundaryList title="What we couldn't check" items={row.not_checked} />
          </div>
          {rule && <AuditTrail rule={rule} />}
        </aside>
      </div>
    </motion.div>
  )
}
