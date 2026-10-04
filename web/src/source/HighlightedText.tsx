import { useEffect, useRef } from 'react'

interface Props {
  text: string
  start: number | null
  end: number | null
}

/** Statute text with the quoted span wrapped in a highlighter stroke; scrolls to it. */
export function HighlightedText({ text, start, end }: Props) {
  const ref = useRef<HTMLElement | null>(null)
  useEffect(() => {
    const el = ref.current
    if (!el) return
    const reduce = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
    el.scrollIntoView({ block: 'center', behavior: reduce ? 'auto' : 'smooth' })
  }, [text, start, end])

  if (start == null || end == null || start < 0 || end > text.length || start >= end) {
    return <div className="statute">{text}</div>
  }
  return (
    <div className="statute">
      {text.slice(0, start)}
      <mark ref={ref} className="hl" data-testid="quoted-span">
        {text.slice(start, end)}
      </mark>
      {text.slice(end)}
    </div>
  )
}
