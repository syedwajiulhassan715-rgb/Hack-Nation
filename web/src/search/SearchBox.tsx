import { useEffect, useId, useRef, useState } from 'react'
import { Search } from 'lucide-react'
import { search } from '../api/client'
import type { SearchHit } from '../api/types'
import { useI18n } from '../i18n'

interface Props {
  onPick: (hit: SearchHit) => void
  onZip: (hits: SearchHit[]) => void
  placeholder?: string
  variant?: 'dark' | 'paper'
  autoFocus?: boolean
}

export function SearchBox({ onPick, onZip, placeholder, variant = 'dark', autoFocus }: Props) {
  const { t } = useI18n()
  const [q, setQ] = useState('')
  const [hits, setHits] = useState<SearchHit[]>([])
  const [open, setOpen] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const seq = useRef(0)
  const listId = useId()

  useEffect(() => {
    const n = ++seq.current
    if (q.trim().length < 2) {
      setHits([])
      return
    }
    const t = setTimeout(() => {
      search(q)
        .then((h) => {
          if (n !== seq.current) return
          setHits(h)
          setError(null)
          setOpen(true)
          if (h.length && h[0].kind === 'zip') onZip(h)
        })
        .catch((e) => n === seq.current && setError(e instanceof Error ? e.message : String(e)))
    }, 180)
    return () => clearTimeout(t)
  }, [q, onZip])

  const isZip = hits[0]?.kind === 'zip'
  return (
    <div className={`search ${variant}`}>
      <form
        onSubmit={(e) => {
          e.preventDefault()
          if (hits[0] && !isZip) {
            onPick(hits[0])
            setOpen(false)
          }
        }}
      >
        <Search size={16} aria-hidden />
        <input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          onFocus={() => setOpen(true)}
          placeholder={placeholder ?? t.searchPlaceholder}
          aria-label={t.searchLabel}
          aria-controls={listId}
          autoFocus={autoFocus}
          onKeyDown={(e) => {
            if (e.key === 'Escape') setOpen(false)
            if (e.key === 'ArrowDown') {
              e.preventDefault()
              document.getElementById(listId)?.querySelector('button')?.focus()
            }
          }}
        />
      </form>
      {open && q.trim().length >= 2 && (
        <div
          className="search-results"
          id={listId}
          aria-live="polite"
          onKeyDown={(e) => {
            const btns = [...e.currentTarget.querySelectorAll('button')]
            const i = btns.indexOf(document.activeElement as HTMLButtonElement)
            if (e.key === 'ArrowDown' && i >= 0) {
              e.preventDefault()
              btns[Math.min(btns.length - 1, i + 1)]?.focus()
            }
            if (e.key === 'ArrowUp' && i >= 0) {
              e.preventDefault()
              if (i === 0) (e.currentTarget.previousElementSibling?.querySelector('input') as HTMLInputElement | null)?.focus()
              else btns[i - 1]?.focus()
            }
            if (e.key === 'Escape') setOpen(false)
          }}
        >
          {error && <p className="fact-error">{error}</p>}
          {!error && hits.length === 0 && <p className="muted">{t.searchNone}</p>}
          {isZip && <p className="muted small">{t.searchZip}</p>}
          {hits.map((h) => (
            <button
              key={h.address_id}
              type="button"
              onClick={() => {
                onPick(h)
                setOpen(false)
              }}
            >
              <span>{h.label}</span>
              <span className="mono muted">{h.address_id}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
