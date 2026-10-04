import { useId, useState } from 'react'
import { EDITABLE_FACTS } from '../copy'
import { useI18n } from '../i18n'

interface Props {
  fact: string
  disabled: boolean
  disabledNote: string
  busy: boolean
  onSubmit: (fact: string, value: number) => void
}

/** Numeric input for one missing fact (FRONTEND_PLAN 4.5). */
export function FactInput({ fact, disabled, disabledNote, busy, onSubmit }: Props) {
  const { t } = useI18n()
  const spec = EDITABLE_FACTS[fact]
  const [value, setValue] = useState('')
  const [error, setError] = useState<string | null>(null)
  const errId = useId()
  if (!spec) return null
  const max = spec.max === 'currentYear' ? new Date().getFullYear() : spec.max
  const label = t.editableFacts[fact] ?? spec.label
  const factName = t.factLabels[fact] ?? fact.replace(/_/g, ' ')

  const submit = (e: React.FormEvent) => {
    e.preventDefault()
    const n = Number(value)
    if (!value.trim() || !Number.isInteger(n)) return setError(t.wholeNumber(factName))
    if (n < spec.min || n > max) return setError(t.range(spec.min, max))
    setError(null)
    onSubmit(fact, n)
  }

  return (
    <form
      className="fact-input"
      onSubmit={submit}
      onClick={(e) => e.stopPropagation()}
      onKeyDown={(e) => e.stopPropagation()}
    >
      <label>
        <span>{label}</span>
        <input
          type="number"
          inputMode="numeric"
          min={spec.min}
          max={max}
          value={value}
          disabled={disabled || busy}
          onChange={(e) => setValue(e.target.value)}
          aria-invalid={!!error}
          aria-describedby={error || disabled ? errId : undefined}
        />
      </label>
      <button type="submit" className="btn btn-ink" disabled={disabled || busy}>
        {busy ? t.checking : t.checkAgain}
      </button>
      {error && (
        <p className="fact-error" id={errId} role="alert">
          {error}
        </p>
      )}
      {disabled && !error && (
        <p className="fact-note" id={errId}>
          {disabledNote}
        </p>
      )}
    </form>
  )
}
