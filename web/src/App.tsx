import { useCallback, useEffect, useMemo, useState } from 'react'
import { MotionConfig } from 'motion/react'
import { detectMode, getDefaultAsOf, getMode, onModeChange, type Mode } from './api/client'
import { AppShell } from './layout/AppShell'
import { ChangesPage } from './changes/ChangesPage'
import { StatesPage } from './label/StatesPage'
import { useRoute } from './lib/router'
import { LangContext, STRINGS, initialLang, saveLang, type Lang } from './i18n'

export default function App() {
  const route = useRoute()
  const [mode, setMode] = useState<Mode>(getMode())
  const [defaultAsOf, setDefaultAsOf] = useState<string | null>(null)
  const [ready, setReady] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [lang, setLangState] = useState<Lang>(initialLang)
  const [attempt, setAttempt] = useState(0)

  const setLang = useCallback((l: Lang) => {
    setLangState(l)
    saveLang(l)
  }, [])
  useEffect(() => saveLang(lang), [lang])
  const langValue = useMemo(() => ({ lang, setLang }), [lang, setLang])
  const t = STRINGS[lang]

  useEffect(() => onModeChange(setMode), [])
  useEffect(() => {
    Promise.all([detectMode(), getDefaultAsOf()])
      .then(([, d]) => {
        if (!d) setError('No as-of date found in the bundled data (public/data/meta.json).')
        setDefaultAsOf(d)
        setReady(true)
      })
      .catch((e) => {
        setError(e instanceof Error ? e.message : String(e))
        setReady(true)
      })
  }, [attempt])

  if (!ready || !defaultAsOf)
    return (
      <div className="boot" role={ready ? 'alert' : 'status'} aria-live="polite">
        <div className="boot-card">
          <p className="boot-title"><img className="brand-mark" src="/favicon.svg" alt="" aria-hidden="true" />{t.rightsLabel}</p>
          {!ready ? (
            <p>{t.loadingApp}</p>
          ) : (
            <>
              <p>{t.dataMissing}</p>
              {error && <p className="mono small">{error}</p>}
              <button type="button" className="btn btn-ink" onClick={() => {
                  setReady(false)
                  setError(null)
                  setAttempt((a) => a + 1)
                }}
              >
                {t.retry}
              </button>
            </>
          )}
          <p className="fine">{t.disclaimer}</p>
        </div>
      </div>
    )

  return (
    <LangContext.Provider value={langValue}>
      <MotionConfig reducedMotion="user">
        {route.path === '/changes' ? (
          <ChangesPage mode={mode} />
        ) : route.path === '/states' ? (
          <StatesPage mode={mode} defaultAsOf={defaultAsOf} />
        ) : (
          <AppShell mode={mode} defaultAsOf={defaultAsOf} route={route} />
        )}
      </MotionConfig>
    </LangContext.Provider>
  )
}
