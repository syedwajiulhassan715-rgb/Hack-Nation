import { useEffect, useRef, useState } from 'react'
import { Search } from 'lucide-react'
import { search } from '../api/client'
import type { SearchHit } from '../api/types'

interface Props {
  onPick: (hit: SearchHit) => void
  onZip: (hits: SearchHit[]) => void
  placeholder?: string
  variant?: 'dark' | 'paper'
  autoFocus?: boolean
}

export function SearchBox({ onPick, onZip, placeholder = '123 Main St, Hoboken, NJ', variant = 'dark', autoFocus }: Props) {
  const [q, setQ] = useState('')
  const [hits, setHits] = useState<SearchHit[]>([])
  const [open, setOpen] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const seq = useRef(0)

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
          placeholder={placeholder}
          aria-label="Search an address or ZIP"
          autoFocus={autoFocus}
        />
      </form>
      {open && q.trim().length >= 2 && (
        <div className="search-results" role="listbox">
          {error && <p className="fact-error">{error}</p>}
          {!error && hits.length === 0 && <p className="muted">No sample building matches. Try a street name or ZIP.</p>}
          {isZip && <p className="muted small">Sample buildings in this ZIP. Pick one to see its rules.</p>}
          {hits.map((h) => (
            <button
              key={h.address_id}
              type="button"
              role="option"
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
