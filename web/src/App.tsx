import { useEffect, useState } from 'react'
import { MotionConfig } from 'motion/react'
import { detectMode, getDefaultAsOf, getMode, onModeChange, type Mode } from './api/client'
import { AppShell } from './layout/AppShell'
import { ChangesPage } from './changes/ChangesPage'
import { StatesPage } from './label/StatesPage'
import { useRoute } from './lib/router'
import { DISCLAIMER } from './copy'

export default function App() {
  const route = useRoute()
  const [mode, setMode] = useState<Mode>(getMode())
  const [defaultAsOf, setDefaultAsOf] = useState<string | null>(null)
  const [ready, setReady] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => onModeChange(setMode), [])
  useEffect(() => {
    Promise.all([detectMode(), getDefaultAsOf()])
      .then(([, d]) => {
        if (!d) setError('No as-of date found in the bundled data. Run npm run sync-data after make lookups.')
        setDefaultAsOf(d)
        setReady(true)
      })
      .catch((e) => {
        setError(e instanceof Error ? e.message : String(e))
        setReady(true)
      })
  }, [])

  if (!ready) return <div className="boot">Loading…</div>
  if (!defaultAsOf)
    return (
      <div className="boot">
        <p>{error}</p>
        <p className="fine">{DISCLAIMER}</p>
      </div>
    )

  return (
    <MotionConfig reducedMotion="user">
      {route.path === '/changes' ? (
        <ChangesPage mode={mode} />
      ) : route.path === '/states' ? (
        <StatesPage mode={mode} defaultAsOf={defaultAsOf} />
      ) : (
        <AppShell mode={mode} defaultAsOf={defaultAsOf} route={route} />
      )}
    </MotionConfig>
  )
}
