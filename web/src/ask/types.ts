// Contract between the "Ask Locus" matcher (src/ask/matcher.ts) and its UI (src/ask/AskPanel.tsx).
// Deterministic only: an answer is assembled from the building's own lookup rows (verified
// quotes, citations, plain-language answers that passed the number guards). No LLM, no law text.
import type { Category, LookupResult, LookupRow, Role } from '../api/types'
import type { Lang } from '../i18n'

/** What the question was understood to be about. */
export type AskIntentKind =
  | 'category' // one of the six categories ("can my rent go up?")
  | 'why_unknown' // "why is this unknown?", "what facts are missing?"
  | 'upcoming' // "what changes next year?", "anything pending?", not_yet_effective / pending rows
  | 'jurisdiction' // "which city is this in?", "which laws apply here?" (state + city stack)
  | 'conflict' // "do any laws disagree?", conflict-flagged rows
  | 'overview' // "what applies here?", "summarise", "tell me about this building"
  | 'no_match' // nothing in the building's data answers it (fail closed, say so)

export interface AskIntent {
  kind: AskIntentKind
  category?: Category
  /** Matched words, shown as "Understood as: deposit" so the user sees why. */
  matched: string[]
}

/** One cited piece of an answer. Every field is copied from a LookupRow, never written. */
export interface AskCitation {
  row: LookupRow
  /** The row's plain-language answer when present (already guarded), else null: UI shows the quote. */
  answer: string | null
  /** Short quote excerpt from row.quoted_span (verbatim substring, may be trimmed with an ellipsis). */
  quote: string
}

export interface AskAnswer {
  intent: AskIntent
  /** Lead sentence built from fixed UI templates + row fields (result, counts, city name, dates). */
  lead: string
  /** Up to ~3 rows, best first. Empty for no_match. */
  citations: AskCitation[]
  /** Facts that would change the answer (from row.missing_facts), human labels. */
  missingFacts: string[]
  /** Follow-up question chips. */
  followUps: string[]
  asOf: string
}

export interface AskInput {
  question: string
  lookup: LookupResult
  role: Role
  lang: Lang
}

/** Implemented in matcher.ts. Pure function, unit-tested. */
export type AskFn = (input: AskInput) => AskAnswer

/** Implemented in matcher.ts: starter chips built from what this building actually has. */
export type SuggestFn = (lookup: LookupResult, role: Role, lang: Lang) => string[]
