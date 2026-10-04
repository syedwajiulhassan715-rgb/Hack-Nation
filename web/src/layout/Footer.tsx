import { useEffect, useRef, useState } from 'react'
import type { Mode } from '../api/client'
import { prettyDate } from '../lib/dates'
import { navigate } from '../lib/router'
import { useI18n } from '../i18n'
import { LangSwitch } from './LangSwitch'

interface Props {
  asOf: string | null
  mode: Mode
}

export function Footer({ asOf, mode }: Props) {
  const { t, lang } = useI18n()
  const [how, setHow] = useState(false)
  const closeRef = useRef<HTMLButtonElement | null>(null)

  useEffect(() => {
    if (!how) return
    closeRef.current?.focus()
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && setHow(false)
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [how])

  return (
    <>
      <footer className="footer-strip">
        <span>
          {t.asOf} <span className="mono">{prettyDate(asOf, lang)}</span>
        </span>
        <span className="dot" aria-hidden>
          ·
        </span>
        <strong>{t.disclaimerShort}</strong>
        <span className="dot hide-phone" aria-hidden>
          ·
        </span>
        <span className="hide-phone">{t.sources}</span>
        <span className="dot" aria-hidden>
          ·
        </span>
        <button type="button" className="link" onClick={() => setHow((h) => !h)} aria-expanded={how}>
          {t.howThisWorks}
        </button>
        <span className="dot hide-phone" aria-hidden>
          ·
        </span>
        <button type="button" className="link hide-phone" onClick={() => navigate('/changes')}>
          {t.changeTests}
        </button>
        <span className="footer-end">
          {mode === 'offline' && (
            <span className="offline" title={t.offlineTitle}>
              {t.offlineData}
            </span>
          )}
          <LangSwitch />
        </span>
      </footer>
      {how && (
        <div className="how" role="dialog" aria-modal="false" aria-labelledby="how-title">
          <h3 id="how-title">{t.howThisWorks}</h3>
          <ol>
            {t.howSteps.map((s, i) => (
              <li key={i}>{s}</li>
            ))}
          </ol>
          {mode === 'offline' && <p className="fine">{t.offlineTitle}</p>}
          <p className="fine">{t.howFine}</p>
          <button ref={closeRef} type="button" className="btn btn-ink" onClick={() => setHow(false)}>
            {t.close}
          </button>
        </div>
      )}
    </>
  )
}
