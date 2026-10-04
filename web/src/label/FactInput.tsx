import { useState } from 'react'
import { EDITABLE_FACTS, factLabel } from '../copy'

interface Props {
  fact: string
  disabled: boolean
  disabledNote: string
  busy: boolean
  onSubmit: (fact: string, value: number) => void
}

/** Numeric input for one missing fact (FRONTEND_PLAN 4.5). */
export function FactInput({ fact, disabled, disabledNote, busy, onSubmit }: Props) {
  const spec = EDITABLE_FACTS[fact]
  const [value, setValue] = useState('')
  const [error, setError] = useState<string | null>(null)
  if (!spec) return null
  const max = spec.max === 'currentYear' ? new Date().getFullYear() : spec.max

  const submit = (e: React.FormEvent) => {
    e.preventDefault()
    const n = Number(value)
    if (!value.trim() || !Number.isInteger(n)) return setError(`Enter a whole number for ${factLabel(fact)}.`)
    if (n < spec.min || n > max) return setError(`Enter a value from ${spec.min} to ${max}.`)
    setError(null)
    onSubmit(fact, n)
  }

  return (
    <form className="fact-input" onSubmit={submit} onClick={(e) => e.stopPropagation()}>
      <label>
        <span>{spec.label}</span>
        <input
          type="number"
          inputMode="numeric"
          min={spec.min}
          max={max}
          value={value}
          disabled={disabled || busy}
          onChange={(e) => setValue(e.target.value)}
          aria-invalid={!!error}
        />
      </label>
      <button type="submit" className="btn btn-ink" disabled={disabled || busy}>
        {busy ? 'Checking' : 'Check again'}
      </button>
      {error && <p className="fact-error">{error}</p>}
      {disabled && <p className="fact-note">{disabledNote}</p>}
    </form>
  )
}
