// UI copy only (FRONTEND_PLAN.md 2.2): navigation, status words, empty states and the six
// category questions used when the API does not send `category.question`.
// No law text, citation, threshold, date or rule name may be added here.
import type { Category, LookupResultValue, Role } from './api/types'

export const DISCLAIMER = 'Not legal advice.'

export const QUESTIONS: Record<Category, Record<Role, string>> = {
  rent_increase_limits: {
    tenant: 'How much can my rent go up?',
    owner: 'What limits apply when I raise the rent?',
  },
  just_cause_eviction: {
    tenant: 'Can I be evicted without a reason?',
    owner: 'What reason do I need to end a tenancy?',
  },
  security_deposits: {
    tenant: 'How big can my deposit be, and when do I get it back?',
    owner: 'What rules apply to the security deposit I collect?',
  },
  application_screening_fees: {
    tenant: 'What can I be charged to apply?',
    owner: 'What can I charge applicants to apply?',
  },
  screening_restrictions: {
    tenant: 'What can a landlord look at when screening me?',
    owner: 'What may I consider when screening applicants?',
  },
  algorithmic_rent_setting: {
    tenant: 'Can my rent be set by pricing software?',
    owner: 'What rules apply to rent-setting software?',
  },
}

export const CATEGORY_SHORT: Record<Category, string> = {
  rent_increase_limits: 'Rent increase',
  just_cause_eviction: 'Eviction',
  security_deposits: 'Deposit',
  application_screening_fees: 'Fees',
  screening_restrictions: 'Screening',
  algorithmic_rent_setting: 'Rent-setting software',
}

export type UiStatus = LookupResultValue | 'conflict' | 'none'

export const STATUS_WORD: Record<UiStatus, string> = {
  applies: 'Applies',
  unknown: 'Unknown',
  superseded: 'Superseded',
  not_yet_effective: 'Starts later',
  pending: 'Proposed',
  conflict: 'Conflict',
  none: 'No rule found',
}

export const FACT_LABEL: Record<string, string> = {
  year_built: 'year built',
  units: 'number of units',
  units_min: 'number of units',
  units_max: 'number of units',
  tenancy_months: 'length of the tenancy',
  owner_type: 'owner type',
  certificate_of_occupancy_date: 'certificate of occupancy date',
  rent_amount: 'rent amount',
  owner_units_owned: 'units the owner holds',
  owner_occupied: 'whether the owner lives there',
  deed_restricted_affordable: 'deed-restricted affordable status',
  government_owned_or_subsidized: 'government ownership or subsidy',
}

export function factLabel(key: string): string {
  return FACT_LABEL[key] ?? key.replace(/_/g, ' ')
}

/** Facts a user can type in (validated numeric input). */
export const EDITABLE_FACTS: Record<string, { min: number; max: number | 'currentYear'; label: string }> = {
  year_built: { min: 1800, max: 'currentYear', label: 'Year built' },
  units: { min: 1, max: 2000, label: 'Units in the building' },
}

/** Postal abbreviations to display names (geography, not law). */
export const STATE_NAMES: Record<string, string> = {
  CA: 'California',
  NJ: 'New Jersey',
  MA: 'Massachusetts',
}

export const ANCHOR_LINE = "Pick any building. See which housing laws apply, and what's about to change."
