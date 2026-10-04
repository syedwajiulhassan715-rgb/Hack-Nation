// Frontend contract, written from BACKEND_PLAN.md section 3 (LookupResult) and
// docs/CONTRACT.md. When the API is running, `npm run gen:types` writes the generated
// OpenAPI types to src/api/openapi.gen.ts; keep these in line with them.

export const CATEGORIES = [
  'rent_increase_limits',
  'just_cause_eviction',
  'security_deposits',
  'application_screening_fees',
  'screening_restrictions',
  'algorithmic_rent_setting',
] as const
export type Category = (typeof CATEGORIES)[number]

export type LookupResultValue = 'applies' | 'unknown' | 'superseded' | 'not_yet_effective' | 'pending'
export type RuleStatus = 'in_force' | 'not_yet_effective' | 'pending' | 'failed'
export type Level = 'state' | 'city'
export type Role = 'tenant' | 'owner'

export interface JurisdictionLevel {
  level: Level
  jurisdiction: string
  name: string
  /** navigator/api: false when the legal city is not confirmed */
  confirmed?: boolean
}

export interface Facts {
  year_built?: number | null
  units?: number | null
  units_min?: number | null
  units_max?: number | null
  units_source?: string | null
  postal_city?: string | null
  jurisdiction_confidence?: string | null
  [k: string]: unknown
}

export interface LookupRow {
  team_rule_id: string
  result: LookupResultValue
  level: Level
  title: string
  answer: string | null
  explanation: string
  key_value: string | null
  quoted_span: string
  citation: string
  source_doc_id: string | null
  source_url: string
  retrieved_at: string | null
  effective_date: string | null
  missing_facts: string[]
  superseded_by: string | null
  /** navigator/api extra */
  superseded_by_citation?: string | null
  conflict_flag: boolean
  conflict_note: string | null
  confidence: number | null
  confidence_reasons: string[]
  needs_review: boolean
  review_reasons?: string[]
  checked: string[]
  not_checked: string[]
  /** UI-only: true when the row was computed in the browser for a date other than the precomputed as_of */
  derived_for_date?: boolean
}

export interface CategoryBlock {
  category: Category
  question: string | null
  rows: LookupRow[]
  no_rule_note: string | null
}

export interface LookupNote {
  jurisdiction: string
  text: string
  date: string | null
  team_rule_id: string | null
  source_url: string | null
  retrieved_at: string | null
}

export interface LookupResult {
  address_id: string | null
  address: string
  as_of: string
  generated_at?: string
  disclaimer: string
  jurisdiction_stack: JurisdictionLevel[]
  facts: Facts
  missing_facts: string[]
  categories: CategoryBlock[]
  notes: LookupNote[]
  /** UI-only provenance of this result */
  _source?: 'api' | 'offline'
  /** UI-only: facts the user typed in (never merged silently with source data) */
  _user_facts?: Record<string, number>
  /** UI-only: postal (mailing) city, to show "Mailing city ... Legal city ..." */
  _postal_city?: string | null
  _jurisdiction_confidence?: string | null
  /** navigator/api `computed`: precomputed | live */
  _computed?: string | null
}

/** Rule record (schema fields + internal fields from rules_internal.json). */
export interface RuleRecord {
  team_rule_id: string
  jurisdiction: string
  level: Level
  category: Category
  status: RuleStatus
  title: string
  requirement: string
  key_value: string | null
  coverage_conditions: unknown
  exemptions: string | null
  overrides: string[]
  interaction: string | null
  effective_date: string | null
  citation: string
  source_doc_id: string | null
  source_url: string
  quoted_span: string
  confidence: number | null
  conflict_flag: boolean
  conflict_note: string | null
  span_start?: number
  span_end?: number
  span_match?: string
  retrieved_at?: string | null
  effective_date_phrase?: string | null
  effective_date_anchor?: string | null
  effective_date_method?: string | null
  needs_review?: boolean
  review_reasons?: string[]
  notes?: string[]
  provenance?: Array<Record<string, unknown>>
}

export interface Parcel {
  address_id: string
  street_address: string
  postal_city: string
  state: string
  city: string | null
  lat: number | null
  lng: number | null
  jurisdiction_confidence?: string
  year_built: number | null
  units: number | null
  units_min: number | null
  units_max: number | null
  units_source: string | null
  use_code?: string | null
  use_description?: string | null
  missing_facts?: string[]
  needs_review?: boolean
  review_reasons?: string[]
  zip?: string | null
}

/** GET /rule/{id}, normalized by the client. Offsets are relative to `text`. */
export interface RuleSource {
  rule: RuleRecord
  text: string | null
  span_start: number | null
  span_end: number | null
  source_url: string
  retrieved_at: string | null
  as_of: string
}

export interface AuditEntry {
  ts?: string
  stage?: string
  decision?: string
  reason?: string
  model?: string
  prompt_version?: string
  [k: string]: unknown
}

export interface ChangeTestOutput {
  affected_address_ids: string[]
  conflict_flag_address_ids: string[]
  notes: string
}

export interface ChangeCheck {
  name: string
  passed: boolean | null
  detail?: string
}

export interface ChangeTestInternal {
  title?: string
  type?: string
  expected_behavior?: string
  affected?: number
  conflicts?: number
  checks?: ChangeCheck[]
  notes?: string[]
}

export interface ChangeTestDef {
  test_id: string
  title: string
  type: string
  rule_ids: string[]
  as_of?: string
  as_of_before?: string
  as_of_after?: string
  states?: string[]
  conflict_with?: string[]
  expected_behavior: string
}

export interface ChangesBundle {
  outputs: Record<string, ChangeTestOutput>
  internal: Record<string, ChangeTestInternal>
  tests: ChangeTestDef[]
  as_of: string | null
}

export interface SearchHit {
  address_id: string
  label: string
  lat: number | null
  lng: number | null
  kind: 'address' | 'zip'
}

export interface ResolveResult {
  state: string | null
  city: string | null
  nearest_address_id: string | null
}
