import type { ChangeTestDef } from '../api/types'

export type ChangeKind = 'enacted' | 'not_yet_effective' | 'pending' | 'failed'

/** Group a supplied change test by what it tests, from its own fields (type and dates). */
export function changeKind(t: Pick<ChangeTestDef, 'type' | 'as_of_after'>, defaultAsOf: string | null): ChangeKind {
  if (t.type === 'negative') return 'failed'
  if (t.type === 'pending') return 'pending'
  if (t.type === 'as_of' && t.as_of_after && defaultAsOf && t.as_of_after > defaultAsOf) return 'not_yet_effective'
  return 'enacted'
}

/** Category named by the organizers' rule id pattern (CONTRACT.md 5: ALG, RENT). */
export function testCategory(t: Pick<ChangeTestDef, 'rule_ids'>): string | null {
  const ids = t.rule_ids.join(' ')
  if (/ALG/.test(ids)) return 'algorithmic_rent_setting'
  if (/RENT/.test(ids)) return 'rent_increase_limits'
  return null
}

export function testDate(t: ChangeTestDef): string | null {
  return t.as_of_after ?? t.as_of ?? null
}

