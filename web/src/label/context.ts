import { createContext, useContext } from 'react'
import type { LookupRow, Role, RuleRecord } from '../api/types'

export interface LabelCtx {
  asOf: string
  role: Role
  rulesById: Map<string, RuleRecord>
  onOpenSource: (row: LookupRow) => void
  /** null when user-entered facts cannot be evaluated (offline) */
  onSubmitFact: ((fact: string, value: number) => void) | null
  factBusy: boolean
  offlineNote: string
}

export const LabelContext = createContext<LabelCtx | null>(null)

export function useLabel(): LabelCtx {
  const c = useContext(LabelContext)
  if (!c) throw new Error('LabelContext missing')
  return c
}
