// "Ask Locus": a question box inside the building panel. Answers are assembled by the
// deterministic matcher (./matcher) from this building's own lookup rows; this file only
// renders them. No law text is written here: every quote, citation, date and status shown
// comes from AskAnswer / LookupRow fields.
import { useEffect, useId, useMemo, useRef, useState } from 'react'
import { AnimatePresence, motion, useReducedMotion } from 'motion/react'
import { ChevronDown, CornerDownLeft, X } from 'lucide-react'
import type { LookupResult, Role } from '../api/types'
import { useI18n } from '../i18n'
import { useLabel } from '../label/context'
import { StatusChip } from '../label/StatusChip'
import { prettyDate } from '../lib/dates'
import { ask, suggest } from './matcher'
import { Mascot, type MascotMood } from './Mascot'
import { ASK_STRINGS } from './strings'
import type { AskAnswer, AskCitation } from './types'

interface Props {
  lookup: LookupResult
  role: Role
}

interface Turn {
  id: number
  question: string
  answer: AskAnswer
  ready: boolean
}

const WORD_STEP = 0.028 // seconds between words of the lead

function moodOf(turn: Turn | undefined): MascotMood {
  if (!turn) return 'idle'
  if (!turn.ready) return 'thinking'
  return turn.answer.intent.kind === 'no_match' ? 'unsure' : 'answer'
}

export function AskPanel({ lookup, role }: Props) {
  const { t: base, lang } = useI18n()
  const s = ASK_STRINGS[lang]
  const reduce = useReducedMotion() ?? false
  const [open, setOpen] = useState(false)
  const [turns, setTurns] = useState<Turn[]>([])
  const [draft, setDraft] = useState('')
  const [forAddress, setForAddress] = useState(lookup.address_id)
  const nextId = useRef(1)
  const timers = useRef<ReturnType<typeof setTimeout>[]>([])
  const threadRef = useRef<HTMLDivElement | null>(null)
  const inputRef = useRef<HTMLInputElement | null>(null)
  const inputId = useId()
  const regionId = useId()

  // New building: start a fresh conversation.
  if (forAddress !== lookup.address_id) {
    setForAddress(lookup.address_id)
    setTurns([])
    setDraft('')
  }
  useEffect(() => {
    const pending = timers.current
    return () => {
      pending.forEach(clearTimeout)
      pending.length = 0
    }
  }, [lookup.address_id])

  const chips = useMemo(() => suggest(lookup, role, lang), [lookup, role, lang])
  const last = turns[turns.length - 1]
  const busy = !!last && !last.ready

  // While Locus reads, show the newest message; once the reply lands, bring the question that
  // started it to the top so the lead sentence is read first (not the end of a long reply).
  const lastId = last?.id
  const lastReady = last?.ready
  useEffect(() => {
    const el = threadRef.current
    if (!el || lastId == null) return
    const q = el.querySelector<HTMLElement>(`[data-turn="${lastId}"]`)
    const top = lastReady && q ? q.offsetTop - 8 : el.scrollHeight
    el.scrollTo({ top, behavior: reduce ? 'auto' : 'smooth' })
  }, [lastId, lastReady, reduce])

  const submit = (raw: string) => {
    const question = raw.trim()
    if (!question || busy) return
    const answer = ask({ question, lookup, role, lang })
    const id = nextId.current++
    setTurns((ts) => [...ts, { id, question, answer, ready: false }])
    setDraft('')
    // A short "reading" beat so the reply reads as a reply (600-900 ms, longer for longer questions).
    const delay = 600 + Math.min(300, question.length * 6)
    timers.current.push(setTimeout(() => setTurns((ts) => ts.map((x) => (x.id === id ? { ...x, ready: true } : x))), delay))
  }

  // Opening the panel puts the cursor in the question box.
  useEffect(() => {
    if (open) inputRef.current?.focus({ preventScroll: true })
  }, [open])

  return (
    <section className={`ask${open ? ' ask-open' : ''}`} aria-label={s.title}>
      <button type="button" className="ask-pill" aria-expanded={open} aria-controls={regionId} onClick={() => setOpen((o) => !o)}>
        <span className="ask-pill-mascot">
          <Mascot mood={open ? moodOf(last) : 'idle'} size={34} />
        </span>
        <span className="ask-pill-text">
          <span className="ask-pill-title">{open ? s.title : s.pill}</span>
          {!open && <span className="ask-pill-sub">{s.pillSub}</span>}
        </span>
        <ChevronDown className="ask-pill-chev" size={18} aria-hidden />
      </button>

      <AnimatePresence initial={false}>
        {open && (
          <motion.div
            id={regionId}
            className="ask-body"
            initial={reduce ? false : { height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={reduce ? { opacity: 0, transition: { duration: 0 } } : { height: 0, opacity: 0 }}
            transition={{ type: 'spring', stiffness: 320, damping: 34 }}
          >
            <div className="ask-thread" ref={threadRef} role="log" aria-live="polite" aria-label={s.thread} tabIndex={0}>
              {turns.length === 0 && (
                <div className="ask-msg ask-locus ask-intro">
                  <span className="ask-avatar">
                    <Mascot mood="idle" size={40} />
                  </span>
                  <div className="ask-bubble">
                    <p className="ask-lead ask-intro-text">{s.intro}</p>
                  </div>
                </div>
              )}
              {turns.map((turn) => (
                <TurnView
                  key={turn.id}
                  turn={turn}
                  latest={turn === last}
                  onAsk={submit}
                  busy={busy}
                  checkAgain={base.checkAgain}
                />
              ))}
            </div>

            {turns.length === 0 && chips.length > 0 && (
              <div className="ask-chips" role="group" aria-label={s.suggestions}>
                <span className="ask-chips-label">{s.suggestions}</span>
                {chips.map((c) => (
                  <button key={c} type="button" className="ask-chip" disabled={busy} onClick={() => submit(c)}>
                    {c}
                  </button>
                ))}
              </div>
            )}

            <form
              className="ask-form"
              onSubmit={(e) => {
                e.preventDefault()
                submit(draft)
              }}
            >
              <label htmlFor={inputId} className="sr-only">
                {s.inputLabel}
              </label>
              <input
                id={inputId}
                ref={inputRef}
                className="ask-input"
                type="text"
                autoComplete="off"
                value={draft}
                placeholder={s.placeholder}
                onChange={(e) => setDraft(e.target.value)}
                maxLength={240}
              />
              <button type="submit" className="ask-send" disabled={busy || !draft.trim()}>
                <span>{s.send}</span>
                <CornerDownLeft size={15} aria-hidden />
              </button>
              {turns.length > 0 && (
                <button
                  type="button"
                  className="ask-clear"
                  onClick={() => {
                    timers.current.forEach(clearTimeout)
                    timers.current.length = 0
                    setTurns([])
                    inputRef.current?.focus()
                  }}
                  aria-label={s.clear}
                  title={s.clear}
                >
                  <X size={15} aria-hidden />
                </button>
              )}
            </form>
          </motion.div>
        )}
      </AnimatePresence>
    </section>
  )
}

function TurnView({
  turn,
  latest,
  onAsk,
  busy,
  checkAgain,
}: {
  turn: Turn
  latest: boolean
  onAsk: (q: string) => void
  busy: boolean
  checkAgain: string
}) {
  const { lang } = useI18n()
  const s = ASK_STRINGS[lang]
  const reduce = useReducedMotion() ?? false
  const a = turn.answer
  const words = a.lead.split(/\s+/).filter(Boolean)
  const leadDur = reduce ? 0 : Math.min(words.length * WORD_STEP, 1.2)
  const pop = (delay: number) =>
    reduce
      ? { initial: false as const }
      : {
          initial: { opacity: 0, y: 10, scale: 0.98 },
          animate: { opacity: 1, y: 0, scale: 1 },
          transition: { type: 'spring' as const, stiffness: 380, damping: 28, delay },
        }

  return (
    <>
      <motion.div className="ask-msg ask-you" data-turn={turn.id} {...pop(0)}>
        <span className="sr-only">{s.you}: </span>
        <p className="ask-bubble-you">{turn.question}</p>
      </motion.div>

      <div className="ask-msg ask-locus">
        <span className="ask-avatar">
          <Mascot mood={moodOf(turn)} size={40} still={!latest} />
        </span>
        {!turn.ready ? (
          <div className="ask-bubble ask-thinking" aria-busy="true">
            <span className="sr-only">{s.locus}: </span>
            <span className="ask-dots" aria-hidden>
              <i />
              <i />
              <i />
            </span>
            <span className="ask-thinking-text">{s.thinking}</span>
          </div>
        ) : (
          <div className="ask-bubble">
            <span className="sr-only">{s.locus}: </span>
            {a.intent.matched.length > 0 && (
              <p className="ask-understood">
                {s.understood} <span className="mono">{a.intent.matched.join(', ')}</span>
              </p>
            )}
            <p className="ask-lead">
              {reduce
                ? a.lead
                : words.map((w, i) => (
                    <motion.span
                      key={i}
                      initial={{ opacity: 0, y: 3 }}
                      animate={{ opacity: 1, y: 0 }}
                      transition={{ delay: i * WORD_STEP, duration: 0.18 }}
                    >
                      {w}{' '}
                    </motion.span>
                  ))}
            </p>

            {a.citations.length > 0 && (
              <ol className="ask-cites">
                {a.citations.map((c, i) => (
                  <motion.li key={`${c.row.team_rule_id}-${i}`} {...pop(leadDur + 0.08 * i)}>
                    <CitationCard c={c} />
                  </motion.li>
                ))}
              </ol>
            )}

            {a.missingFacts.length > 0 && (
              <motion.div className="ask-missing" {...pop(leadDur + 0.08 * a.citations.length)}>
                <StatusChip status="unknown" small /> {s.missing} <strong>{a.missingFacts.join(', ')}</strong>
                <span className="ask-missing-hint">{s.missingHint(checkAgain)}</span>
              </motion.div>
            )}

            <p className="ask-foot">
              {s.asOf} <span className="mono">{prettyDate(a.asOf, lang)}</span> · <strong>{s.notAdvice}</strong>
            </p>

            {latest && a.followUps.length > 0 && (
              <motion.div className="ask-chips ask-followups" role="group" aria-label={s.followUps} {...pop(leadDur + 0.15)}>
                {a.followUps.map((f) => (
                  <button key={f} type="button" className="ask-chip" disabled={busy} onClick={() => onAsk(f)}>
                    {f}
                  </button>
                ))}
              </motion.div>
            )}
          </div>
        )}
      </div>
    </>
  )
}

function CitationCard({ c }: { c: AskCitation }) {
  const { lang } = useI18n()
  const s = ASK_STRINGS[lang]
  const { onOpenSource } = useLabel()
  const [showQuote, setShowQuote] = useState(false)
  const quoteId = useId()
  const { row } = c
  return (
    <article className={`ask-card ask-card-${row.result}${row.conflict_flag ? ' ask-card-conflict' : ''}`}>
      {c.answer ? (
        <p className="ask-card-answer">{c.answer}</p>
      ) : (
        <p className="ask-card-answer is-quote" lang="en">
          <span className="ask-quote-tag">{s.quoteTag}</span> “{c.quote}”
        </p>
      )}
      {c.answer && (
        <>
          <button
            type="button"
            className="ask-toggle"
            aria-expanded={showQuote}
            aria-controls={quoteId}
            onClick={() => setShowQuote((v) => !v)}
          >
            {showQuote ? s.hideSentence : s.showSentence}
          </button>
          {showQuote && (
            <blockquote id={quoteId} className="ask-quote" lang="en">
              “{c.quote}”
            </blockquote>
          )}
        </>
      )}
      {row.conflict_flag && <p className="ask-conflict">{s.conflict}</p>}
      <div className="ask-card-meta">
        <StatusChip status={row.result} small />
        {row.conflict_flag && <StatusChip status="conflict" small />}
        <button type="button" className="ask-cite" onClick={() => onOpenSource(row)} title={s.openSource} lang="en">
          {row.citation || s.citationMissing}
        </button>
        <span className="ask-retrieved">
          {s.retrieved}{' '}
          {row.retrieved_at ? <span className="mono">{prettyDate(row.retrieved_at.slice(0, 10), lang)}</span> : s.retrievedMissing}
        </span>
      </div>
    </article>
  )
}
