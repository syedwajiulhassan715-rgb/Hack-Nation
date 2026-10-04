// Ask Locus: deterministic question matcher. No LLM, no law text.
// A question is matched to an intent by keyword hits (lexicon.ts). The answer is assembled
// from the building's own lookup rows: a lead sentence from the fixed templates below,
// filled only with row fields (results, counts, jurisdiction names, effective dates,
// citations), plus up to three cited rows with verbatim quote excerpts. When nothing in the
// building's data answers the question, it says so (fail closed) and never guesses.
// Owner wording describes obligations only (golden rule 11).
import { CATEGORIES } from '../api/types'
import type { Category, LookupResult, LookupResultValue, LookupRow, Role } from '../api/types'
import { STRINGS } from '../i18n'
import type { Lang } from '../i18n'
import { ASPECTS, CATEGORY_WORDS, INTENT_WORDS, STOPWORDS } from './lexicon'
import type { AskAnswer, AskCitation, AskFn, AskInput, AskIntent, AskIntentKind, SuggestFn } from './types'

// ---------------------------------------------------------------------------------------
// Normalisation and keyword matching

export function stripAccents(s: string): string {
  return s.normalize('NFD').replace(/\p{M}+/gu, '')
}

/** Lowercased tokens, original (with accents) and normalised (without), index-aligned. */
function tokenize(text: string): { orig: string[]; norm: string[] } {
  const orig = text
    .toLowerCase()
    .normalize('NFC')
    .split(/[^\p{L}\p{N}]+/u)
    .filter(Boolean)
  return { orig, norm: orig.map((t) => stripAccents(t)) }
}

function normWords(phrase: string): string[] {
  return tokenize(phrase).norm
}

function wordMatches(token: string, kw: string): boolean {
  return kw.length >= 4 ? token.startsWith(kw) : token === kw
}

interface Hit {
  key: string // intent kind or category
  start: number
  len: number
}

type IntentKey = Category | Exclude<AskIntentKind, 'category' | 'no_match'>

const TABLE: Array<{ key: IntentKey; words: string[][] }> = [
  ...CATEGORIES.map((c) => ({ key: c as IntentKey, words: CATEGORY_WORDS[c].map(normWords) })),
  ...(Object.keys(INTENT_WORDS) as Array<keyof typeof INTENT_WORDS>).map((k) => ({
    key: k as IntentKey,
    words: INTENT_WORDS[k].map(normWords),
  })),
]

const YEAR = /^20\d\d$/

function findHits(norm: string[]): Hit[] {
  const hits: Hit[] = []
  for (const { key, words } of TABLE)
    for (const phrase of words) {
      if (!phrase.length) continue
      for (let i = 0; i + phrase.length <= norm.length; i++)
        if (phrase.every((w, j) => wordMatches(norm[i + j], w))) hits.push({ key, start: i, len: phrase.length })
    }
  // A bare year ("in 2027?") signals a question about what changes, without naming any date here.
  norm.forEach((t, i) => {
    if (YEAR.test(t)) hits.push({ key: 'upcoming', start: i, len: 1 })
  })
  // Longest phrases first; a token counts for one phrase only.
  hits.sort((a, b) => b.len - a.len || a.start - b.start)
  const used = new Set<number>()
  const kept: Hit[] = []
  for (const h of hits) {
    const span = Array.from({ length: h.len }, (_, j) => h.start + j)
    if (span.some((i) => used.has(i))) continue
    span.forEach((i) => used.add(i))
    kept.push(h)
  }
  return kept.sort((a, b) => a.start - b.start)
}

const NON_CATEGORY_PRIORITY: AskIntentKind[] = ['why_unknown', 'conflict', 'upcoming', 'jurisdiction', 'overview']

/** Understand a question. Exported for tests and for the UI's "Understood as" line. */
export function matchIntent(question: string): AskIntent {
  const { orig, norm } = tokenize(question)
  const hits = findHits(norm)
  if (!hits.length) return { kind: 'no_match', matched: [] }

  const score = new Map<string, number>()
  for (const h of hits) score.set(h.key, (score.get(h.key) ?? 0) + h.len)
  const words = (key: string) =>
    hits.filter((h) => h.key === key).map((h) => orig.slice(h.start, h.start + h.len).join(' '))

  let bestCat: Category | undefined
  for (const c of CATEGORIES) if ((score.get(c) ?? 0) > (bestCat ? (score.get(bestCat) ?? 0) : 0)) bestCat = c
  let bestOther: AskIntentKind | undefined
  for (const k of NON_CATEGORY_PRIORITY)
    if ((score.get(k) ?? 0) > (bestOther ? (score.get(bestOther) ?? 0) : 0)) bestOther = k

  const catScore = bestCat ? (score.get(bestCat) ?? 0) : 0
  const otherScore = bestOther ? (score.get(bestOther) ?? 0) : 0
  // Ties prefer the category.
  if (bestCat && catScore >= otherScore) return { kind: 'category', category: bestCat, matched: words(bestCat) }
  if (!bestOther) return { kind: 'no_match', matched: [] }
  // A category named alongside ("why is the deposit unknown?") narrows the rows.
  const intent: AskIntent = { kind: bestOther, matched: [...words(bestOther), ...(bestCat ? words(bestCat) : [])] }
  if (bestCat && bestOther !== 'jurisdiction' && bestOther !== 'overview') intent.category = bestCat
  return intent
}

// ---------------------------------------------------------------------------------------
// Ranking and quotes

const RESULT_RANK: Record<LookupResultValue, number> = {
  applies: 0,
  unknown: 1,
  superseded: 2,
  not_yet_effective: 3,
  pending: 4,
}

function contentTokens(text: string): string[] {
  return tokenize(text).norm.filter((t) => t.length >= 4 && !STOPWORDS.has(t))
}

function hasPhrase(norm: string[], phrase: string): boolean {
  const p = normWords(phrase)
  if (!p.length) return false
  for (let i = 0; i + p.length <= norm.length; i++) if (p.every((w, j) => wordMatches(norm[i + j], w))) return true
  return false
}

/** How well a row's title / key_value fits the question's words. */
export function overlapScore(question: string, row: LookupRow): number {
  const q = tokenize(question).norm
  const rowText = `${row.title ?? ''} ${row.key_value ?? ''}`
  const r = tokenize(rowText).norm
  const rContent = contentTokens(rowText)
  let s = 0
  for (const t of new Set(q.filter((t) => t.length >= 4 && !STOPWORDS.has(t))))
    if (rContent.some((w) => w.startsWith(t) || t.startsWith(w))) s += 1
  for (const a of ASPECTS)
    if (a.question.some((p) => hasPhrase(q, p)) && a.row.some((p) => hasPhrase(r, p))) s += 2
  return s
}

export function rankRows(rows: LookupRow[], question: string): LookupRow[] {
  return rows
    .map((row, i) => ({ row, i, ov: overlapScore(question, row) }))
    .sort(
      (a, b) =>
        RESULT_RANK[a.row.result] - RESULT_RANK[b.row.result] ||
        b.ov - a.ov ||
        (a.row.level === b.row.level ? 0 : a.row.level === 'city' ? -1 : 1) ||
        a.i - b.i,
    )
    .map((x) => x.row)
}

export const QUOTE_MAX = 220

/** Verbatim excerpt of the quote: never alters characters, only trims at a word boundary. */
export function quoteExcerpt(span: string, max = QUOTE_MAX): string {
  const q = span.trim()
  if (q.length <= max) return q
  const cut = q.lastIndexOf(' ', max)
  const head = q.slice(0, cut > max / 2 ? cut : max).trimEnd()
  return `${head}…`
}

function cite(row: LookupRow): AskCitation {
  return { row, answer: row.answer ? row.answer : null, quote: quoteExcerpt(row.quoted_span ?? '') }
}

// ---------------------------------------------------------------------------------------
// Fixed templates (UI copy only; filled with row fields)

interface Place {
  state: string | null
  city: string | null
}

function placeOf(lookup: LookupResult): Place {
  const st = lookup.jurisdiction_stack.find((j) => j.level === 'state')
  const ci = lookup.jurisdiction_stack.find((j) => j.level === 'city' && j.confirmed !== false)
  return { state: st?.name ?? null, city: ci?.name ?? null }
}

type Counts = Partial<Record<LookupResultValue, number>>

function countResults(rows: LookupRow[]): Counts {
  const c: Counts = {}
  for (const r of rows) c[r.result] = (c[r.result] ?? 0) + 1
  return c
}

const ORDER: LookupResultValue[] = ['applies', 'unknown', 'not_yet_effective', 'superseded', 'pending']

const T = {
  en: {
    here: (p: Place) => p.city ?? p.state ?? 'this area',
    countWord: {
      applies: (n: number) => `${n} ${n === 1 ? 'applies' : 'apply'}`,
      unknown: (n: number) => `${n} ${n === 1 ? 'is' : 'are'} unknown`,
      not_yet_effective: (n: number) => `${n} ${n === 1 ? 'starts' : 'start'} later`,
      superseded: (n: number) => `${n} ${n === 1 ? 'steps' : 'step'} aside`,
      pending: (n: number) => `${n} ${n === 1 ? 'is' : 'are'} only proposed`,
    } as Record<LookupResultValue, (n: number) => string>,
    mainVerb: {
      applies: 'applies',
      unknown: 'is unknown, because it depends on facts Locus does not have',
      superseded: 'steps aside for another rule',
      not_yet_effective: 'has not started yet',
      pending: 'is only proposed and is not law',
    } as Record<LookupResultValue, string>,
    category: (role: Role, place: string, cat: string, n: number, counts: string, verb: string, cite: string) =>
      role === 'owner'
        ? `In ${place}, ${n} ${n === 1 ? 'rule sets' : 'rules set'} obligations on ${cat.toLowerCase()} (${counts}). The main one, ${cite}, ${verb}:`
        : `In ${place}, ${n} ${n === 1 ? 'rule answers' : 'rules answer'} this about ${cat.toLowerCase()} (${counts}). The main one, ${cite}, ${verb}:`,
    noRows: (place: string, cat: string) =>
      `Locus has no ${cat.toLowerCase()} rule in its sources for this building in ${place}, so it cannot answer this. That does not mean there is no rule.`,
    conflictTail: ' Sources disagree on it; a human reviewer should decide.',
    unknownLead: (n: number) =>
      `${n} ${n === 1 ? 'rule here is' : 'rules here are'} unknown because Locus is missing facts about the building. These facts would settle ${n === 1 ? 'it' : 'them'}:`,
    unknownNone: 'Nothing here is unknown right now. Every rule shown was checked against the facts on record.',
    upcomingLead: (n: number, p: number, next: string | null, cite: string | null) => {
      const parts: string[] = []
      if (n) parts.push(`${n} ${n === 1 ? 'rule has' : 'rules have'} not started yet for this building`)
      if (p) parts.push(`${p} proposed ${p === 1 ? 'bill is' : 'bills are'} on record, and proposed bills are not law`)
      let s = parts.join('; ') + '.'
      s = s.charAt(0).toUpperCase() + s.slice(1)
      if (next && cite) s += ` The next one starts ${next} (${cite}).`
      return s
    },
    upcomingNone: 'Locus has no rule that starts later and no proposed bill on record for this building.',
    conflictLead: (n: number) =>
      `${n} ${n === 1 ? 'rule here is' : 'rules here are'} flagged because sources disagree. Locus does not pick a winner; a human reviewer should decide.`,
    conflictNone: 'No rule for this building is flagged for a disagreement between sources.',
    jurisdictionLead: (p: Place, s: number, c: number) =>
      p.city
        ? `This building is in ${p.city}${p.state ? `, ${p.state}` : ''}. Locus has ${s} state ${s === 1 ? 'rule' : 'rules'} and ${c} city ${c === 1 ? 'rule' : 'rules'} for it.`
        : `This building is in ${p.state ?? 'a state Locus could not confirm'}. Its city is not confirmed, so only state rules are counted: ${s}.`,
    overviewLead: (place: string, k: number, total: number, counts: string) =>
      `In ${place}, Locus found rules in ${k} of ${total} categories (${counts}). The main rule in each:`,
    overviewNone: (place: string) => `Locus has no rules in its sources for this building in ${place}.`,
    noMatch:
      'I can only answer from the laws Locus has for this building, and none of them covers that. Try one of these:',
    qOverview: { tenant: 'What applies here?', owner: 'What obligations apply here?' } as Record<Role, string>,
    qUnknown: 'Why are some answers unknown?',
    qUpcoming: 'What changes soon?',
    qConflict: 'Do any laws disagree here?',
    qJurisdiction: 'Which city and state cover this address?',
  },
  es: {
    here: (p: Place) => p.city ?? p.state ?? 'esta zona',
    countWord: {
      applies: (n: number) => `${n} ${n === 1 ? 'aplica' : 'aplican'}`,
      unknown: (n: number) => `${n} ${n === 1 ? 'desconocida' : 'desconocidas'}`,
      not_yet_effective: (n: number) => `${n} ${n === 1 ? 'empieza' : 'empiezan'} después`,
      superseded: (n: number) => `${n} ${n === 1 ? 'desplazada' : 'desplazadas'}`,
      pending: (n: number) => `${n} solo ${n === 1 ? 'propuesta' : 'propuestas'}`,
    } as Record<LookupResultValue, (n: number) => string>,
    mainVerb: {
      applies: 'aplica',
      unknown: 'es desconocida, porque depende de datos que Locus no tiene',
      superseded: 'cede ante otra regla',
      not_yet_effective: 'todavía no empieza',
      pending: 'solo está propuesta y no es ley',
    } as Record<LookupResultValue, string>,
    category: (role: Role, place: string, cat: string, n: number, counts: string, verb: string, cite: string) =>
      role === 'owner'
        ? `En ${place}, ${n} ${n === 1 ? 'regla fija' : 'reglas fijan'} obligaciones sobre ${cat.toLowerCase()} (${counts}). La principal, ${cite}, ${verb}:`
        : `En ${place}, ${n} ${n === 1 ? 'regla responde' : 'reglas responden'} a esto sobre ${cat.toLowerCase()} (${counts}). La principal, ${cite}, ${verb}:`,
    noRows: (place: string, cat: string) =>
      `Locus no tiene en sus fuentes ninguna regla de ${cat.toLowerCase()} para este edificio en ${place}, así que no puede responder esto. Eso no significa que no exista una regla.`,
    conflictTail: ' Las fuentes no coinciden; una persona debe revisarlo y decidir.',
    unknownLead: (n: number) =>
      `${n} ${n === 1 ? 'regla aquí es desconocida' : 'reglas aquí son desconocidas'} porque a Locus le faltan datos del edificio. Estos datos lo resolverían:`,
    unknownNone: 'Nada aquí es desconocido ahora. Cada regla se revisó con los datos disponibles.',
    upcomingLead: (n: number, p: number, next: string | null, cite: string | null) => {
      const parts: string[] = []
      if (n) parts.push(`${n} ${n === 1 ? 'regla todavía no empieza' : 'reglas todavía no empiezan'} para este edificio`)
      if (p) parts.push(`hay ${p} ${p === 1 ? 'proyecto de ley propuesto' : 'proyectos de ley propuestos'}, y un proyecto no es ley`)
      let s = parts.join('; ') + '.'
      s = s.charAt(0).toUpperCase() + s.slice(1)
      if (next && cite) s += ` La próxima empieza el ${next} (${cite}).`
      return s
    },
    upcomingNone: 'Locus no tiene reglas que empiecen después ni proyectos de ley para este edificio.',
    conflictLead: (n: number) =>
      `${n} ${n === 1 ? 'regla aquí está marcada' : 'reglas aquí están marcadas'} porque las fuentes no coinciden. Locus no elige una; una persona debe revisarlo y decidir.`,
    conflictNone: 'Ninguna regla de este edificio está marcada por desacuerdo entre fuentes.',
    jurisdictionLead: (p: Place, s: number, c: number) =>
      p.city
        ? `Este edificio está en ${p.city}${p.state ? `, ${p.state}` : ''}. Locus tiene ${s} ${s === 1 ? 'regla estatal' : 'reglas estatales'} y ${c} ${c === 1 ? 'regla municipal' : 'reglas municipales'} para él.`
        : `Este edificio está en ${p.state ?? 'un estado que Locus no pudo confirmar'}. Su ciudad no está confirmada, así que solo se cuentan reglas estatales: ${s}.`,
    overviewLead: (place: string, k: number, total: number, counts: string) =>
      `En ${place}, Locus encontró reglas en ${k} de ${total} categorías (${counts}). La regla principal de cada una:`,
    overviewNone: (place: string) => `Locus no tiene reglas en sus fuentes para este edificio en ${place}.`,
    noMatch:
      'Solo puedo responder con las leyes que Locus tiene para este edificio, y ninguna cubre eso. Pruebe una de estas:',
    qOverview: { tenant: '¿Qué aplica aquí?', owner: '¿Qué obligaciones aplican aquí?' } as Record<Role, string>,
    qUnknown: '¿Por qué algunas respuestas son desconocidas?',
    qUpcoming: '¿Qué cambia pronto?',
    qConflict: '¿Hay leyes en conflicto aquí?',
    qJurisdiction: '¿Qué ciudad y estado cubren esta dirección?',
  },
}

function countsText(lang: Lang, counts: Counts): string {
  const t = T[lang]
  return ORDER.filter((r) => counts[r]).map((r) => t.countWord[r](counts[r] as number)).join(', ')
}

function citationOf(row: LookupRow): string {
  return row.citation || row.team_rule_id
}

// ---------------------------------------------------------------------------------------
// Suggestions

interface Suggestion {
  kind: AskIntentKind
  category?: Category
  text: string
}

function allRows(lookup: LookupResult): Array<{ row: LookupRow; category: Category }> {
  return lookup.categories.flatMap((b) => b.rows.map((row) => ({ row, category: b.category })))
}

function suggestions(lookup: LookupResult, role: Role, lang: Lang): Suggestion[] {
  const t = T[lang]
  const s = STRINGS[lang]
  const rows = allRows(lookup)
  const specials: Suggestion[] = []
  if (rows.some((r) => r.row.result === 'unknown')) specials.push({ kind: 'why_unknown', text: t.qUnknown })
  if (rows.some((r) => r.row.result === 'not_yet_effective' || r.row.result === 'pending'))
    specials.push({ kind: 'upcoming', text: t.qUpcoming })
  if (rows.some((r) => r.row.conflict_flag)) specials.push({ kind: 'conflict', text: t.qConflict })

  // Categories with rows in force first, then the rest that have any non-pending row.
  const cats = lookup.categories
    .filter((b) => b.rows.some((r) => r.result !== 'pending'))
    .map((b) => ({ b, applies: b.rows.some((r) => r.result === 'applies') }))
    .sort((a, b) => Number(b.applies) - Number(a.applies))
    .map(({ b }) => ({
      kind: 'category' as const,
      category: b.category,
      text: s.questions[b.category]?.[role] ?? STRINGS.en.questions[b.category][role],
    }))

  const overview: Suggestion = { kind: 'overview', text: t.qOverview[role] }
  const jurisdiction: Suggestion = { kind: 'jurisdiction', text: t.qJurisdiction }
  const out: Suggestion[] = []
  const push = (x: Suggestion) => {
    if (out.length < 6 && !out.some((o) => o.text === x.text)) out.push(x)
  }
  if (rows.length) push(overview)
  cats.slice(0, 2).forEach(push)
  specials.forEach(push)
  cats.slice(2).forEach(push)
  push(jurisdiction)
  return out
}

export const suggest: SuggestFn = (lookup, role, lang) => suggestions(lookup, role, lang).map((x) => x.text)

function followUpsFor(intent: AskIntent, lookup: LookupResult, role: Role, lang: Lang): string[] {
  return suggestions(lookup, role, lang)
    .filter((x) => !(x.kind === intent.kind && (intent.kind !== 'category' || x.category === intent.category)))
    .slice(0, 3)
    .map((x) => x.text)
}

// ---------------------------------------------------------------------------------------
// Answer assembly

function factLabelFor(lang: Lang, fact: string): string {
  const labels = STRINGS[lang]?.factLabels as Record<string, string> | undefined
  return labels?.[fact] ?? STRINGS.en.factLabels[fact] ?? fact.replace(/_/g, ' ')
}

function missingFactsOf(rows: LookupRow[], lang: Lang): string[] {
  const out: string[] = []
  for (const r of rows)
    if (r.result === 'unknown')
      for (const f of r.missing_facts ?? []) {
        const label = factLabelFor(lang, f)
        if (!out.includes(label)) out.push(label)
      }
  return out
}

function rowsFor(lookup: LookupResult, category: Category | undefined): Array<{ row: LookupRow; category: Category }> {
  const all = allRows(lookup)
  if (!category) return all
  return all.filter((r) => r.category === category)
}

export const ask: AskFn = (input: AskInput): AskAnswer => {
  const { question, lookup, role, lang } = input
  const t = T[lang] ?? T.en
  const s = STRINGS[lang] ?? STRINGS.en
  const intent = matchIntent(question)
  const place = placeOf(lookup)
  const here = t.here(place)
  const base = { intent, asOf: lookup.as_of }

  const noMatch = (): AskAnswer => ({
    ...base,
    intent: { kind: 'no_match', matched: [] },
    lead: t.noMatch,
    citations: [],
    missingFacts: [],
    followUps: suggest(lookup, role, lang),
  })

  const done = (lead: string, rows: LookupRow[], missingFacts: string[] = []): AskAnswer => ({
    ...base,
    lead,
    citations: rows.map(cite),
    missingFacts,
    followUps: followUpsFor(intent, lookup, role, lang),
  })

  switch (intent.kind) {
    case 'no_match':
      return noMatch()

    case 'category': {
      const cat = intent.category as Category
      const block = lookup.categories.find((b) => b.category === cat)
      const rows = (block?.rows ?? []).filter((r) => r.result !== 'pending')
      const catName = s.categoryShort[cat] ?? STRINGS.en.categoryShort[cat]
      if (!rows.length) return done(t.noRows(here, catName), [])
      const top = rankRows(rows, question).slice(0, 3)
      const main = top[0]
      let lead = t.category(
        role,
        here,
        catName,
        rows.length,
        countsText(lang, countResults(rows)),
        t.mainVerb[main.result],
        citationOf(main),
      )
      if (main.conflict_flag) lead += t.conflictTail
      return done(lead, top, missingFactsOf(top, lang))
    }

    case 'why_unknown': {
      const unknown = rowsFor(lookup, intent.category)
        .map((r) => r.row)
        .filter((r) => r.result === 'unknown')
      if (!unknown.length) return done(t.unknownNone, [])
      const facts = missingFactsOf(unknown, lang)
      return done(t.unknownLead(unknown.length), rankRows(unknown, question).slice(0, 3), facts)
    }

    case 'upcoming': {
      const rows = rowsFor(lookup, intent.category).map((r) => r.row)
      const later = rows.filter((r) => r.result === 'not_yet_effective')
      const pending = rows.filter((r) => r.result === 'pending')
      if (!later.length && !pending.length) return done(t.upcomingNone, [])
      const dated = later
        .filter((r) => r.effective_date && /^\d{4}-\d{2}-\d{2}$/.test(r.effective_date))
        .sort((a, b) => (a.effective_date as string).localeCompare(b.effective_date as string))
      const next = dated[0] ?? null
      const lead = t.upcomingLead(later.length, pending.length, next?.effective_date ?? null, next ? citationOf(next) : null)
      const ordered = [...dated, ...later.filter((r) => !dated.includes(r)), ...rankRows(pending, question)]
      return done(lead, ordered.slice(0, 3))
    }

    case 'conflict': {
      const flagged = rowsFor(lookup, intent.category)
        .map((r) => r.row)
        .filter((r) => r.conflict_flag && r.result !== 'pending')
      if (!flagged.length) return done(t.conflictNone, [])
      return done(t.conflictLead(flagged.length), rankRows(flagged, question).slice(0, 3))
    }

    case 'jurisdiction': {
      const rows = allRows(lookup)
        .map((r) => r.row)
        .filter((r) => r.result !== 'pending')
      const stateRows = rows.filter((r) => r.level === 'state')
      const cityRows = rows.filter((r) => r.level === 'city')
      const picks = [rankRows(cityRows, question)[0], rankRows(stateRows, question)[0]].filter(
        (r): r is LookupRow => !!r,
      )
      return done(t.jurisdictionLead(place, stateRows.length, place.city ? cityRows.length : 0), picks)
    }

    case 'overview': {
      const picks: LookupRow[] = []
      const counted: LookupRow[] = []
      for (const b of lookup.categories) {
        const rows = b.rows.filter((r) => r.result !== 'pending')
        counted.push(...rows)
        const best = rankRows(rows, question)[0]
        if (best) picks.push(best)
      }
      if (!picks.length) return done(t.overviewNone(here), [])
      const lead = t.overviewLead(here, picks.length, CATEGORIES.length, countsText(lang, countResults(counted)))
      return done(lead, picks)
    }
  }
  return noMatch()
}
