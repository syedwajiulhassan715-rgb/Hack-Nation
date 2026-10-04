import { useEffect, useRef, useState } from 'react'
import { motion } from 'motion/react'
import { ExternalLink, X } from 'lucide-react'
import type { LookupRow, RuleSource } from '../api/types'
import { getRuleSource } from '../api/client'
import { prettyDate } from '../lib/dates'
import { useI18n } from '../i18n'
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
  const { t } = useI18n()
  return (
    <div className="boundary-list">
      <h4>{title}</h4>
      <ul lang="en">
        {items.length ? items.map((x, i) => <li key={i}>{x}</li>) : <li className="muted">{t.nothingRecorded}</li>}
      </ul>
    </div>
  )
}

export function SourceDrawer({ row, asOf, onClose, statusText }: Props) {
  const { t, lang } = useI18n()
  const [src, setSrc] = useState<RuleSource | null>(null)
  const [error, setError] = useState<string | null>(null)
  const closeRef = useRef<HTMLButtonElement | null>(null)
  const returnTo = useRef<Element | null>(null)

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

  // Focus the close button on open; give focus back to the citation on close.
  useEffect(() => {
    returnTo.current = document.activeElement
    closeRef.current?.focus({ preventScroll: true })
    return () => {
      const el = returnTo.current as HTMLElement | null
      if (el && document.contains(el)) el.focus({ preventScroll: true })
    }
  }, [])

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
      aria-label={t.sourceText}
      initial={{ y: '100%' }}
      animate={{ y: 0 }}
      exit={{ y: '100%' }}
      transition={{ type: 'spring', stiffness: 300, damping: 34 }}
    >
      <header className="drawer-head mono">
        <div className="drawer-cite" lang="en">
          {row.citation}
        </div>
        <div className="drawer-meta">
          <a href={src?.source_url ?? row.source_url} target="_blank" rel="noreferrer">
            {t.openOfficial} <ExternalLink size={12} aria-hidden />
          </a>
          <span>
            {t.retrievedOn} {src?.retrieved_at ?? row.retrieved_at ?? t.notRecorded}
          </span>
          <span>
            {t.effective} {prettyDate(row.effective_date, lang)}
          </span>
          <span>
            {t.statusLabel} {statusText ?? t.status[row.result]}
          </span>
          {rule?.source_doc_id && (
            <span>
              {t.document} {rule.source_doc_id}
            </span>
          )}
          <span>
            {t.asOf} {prettyDate(asOf, lang)}
          </span>
          <span className="nla">{t.disclaimer}</span>
        </div>
        <button ref={closeRef} type="button" className="icon-btn" onClick={onClose} aria-label={t.closeSource}>
          <X size={20} aria-hidden />
        </button>
      </header>
      <div className="drawer-body">
        <div className="drawer-text" lang="en">
          {lang === 'es' && (
            <p className="lang-note" lang="es">
              {t.sourceLangNote}
            </p>
          )}
          {error && (
            <p className="fact-error" role="alert">
              {error}
            </p>
          )}
          {!src && !error && <p className="muted">{t.loadingSource}</p>}
          {src && src.text && <HighlightedText text={src.text} start={src.span_start} end={src.span_end} />}
          {src && (!src.text || src.span_start == null) && (
            <div>
              <p className="muted" lang={lang}>
                {src.text ? t.quoteNotLocated : t.textNotBundled}
              </p>
              <blockquote className="statute">
                <mark className="hl">{row.quoted_span}</mark>
              </blockquote>
            </div>
          )}
          {error && !src && (
            <blockquote className="statute">
              <mark className="hl">{row.quoted_span}</mark>
            </blockquote>
          )}
        </div>
        <aside className="drawer-side">
          <div className="conf">
            <h4>{t.confidence}</h4>
            <p className="mono">{row.confidence != null ? row.confidence.toFixed(2) : t.notScored}</p>
            <ul lang="en">
              {row.confidence_reasons.length ? (
                row.confidence_reasons.map((r, i) => <li key={i}>{r}</li>)
              ) : (
                <li className="muted" lang={lang}>
                  {t.noReasons}
                </li>
              )}
            </ul>
            {(rule?.review_reasons?.length ?? 0) > 0 && (
              <>
                <h4>{t.flagged}</h4>
                <ul lang="en">
                  {rule!.review_reasons!.map((r, i) => (
                    <li key={i}>{r}</li>
                  ))}
                </ul>
              </>
            )}
          </div>
          <div className="boundary">
            <h3>{t.boundary}</h3>
            <BoundaryList title={t.checked} items={row.checked} />
            <BoundaryList title={t.notChecked} items={row.not_checked} />
          </div>
          {rule && <AuditTrail rule={rule} />}
        </aside>
      </div>
    </motion.div>
  )
}
