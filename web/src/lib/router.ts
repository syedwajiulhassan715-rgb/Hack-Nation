import { useEffect, useState } from 'react'

export interface Route {
  path: string
  params: URLSearchParams
}

function current(): Route {
  return { path: window.location.pathname.replace(/\/+$/, '') || '/', params: new URLSearchParams(window.location.search) }
}

export function navigate(to: string) {
  window.history.pushState({}, '', to)
  window.dispatchEvent(new PopStateEvent('popstate'))
}

export function useRoute(): Route {
  const [route, setRoute] = useState<Route>(current)
  useEffect(() => {
    const on = () => setRoute(current())
    window.addEventListener('popstate', on)
    return () => window.removeEventListener('popstate', on)
  }, [])
  return route
}
