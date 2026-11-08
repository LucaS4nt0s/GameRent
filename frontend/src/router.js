import { useEffect, useState } from 'react'

// Roteamento por hash (#/conta, #/admin...): funciona no nginx e no Vite sem configurar rotas no servidor.
function current() {
  const raw = window.location.hash.replace(/^#/, '') || '/'
  const [path, search = ''] = raw.split('?')
  return { path: path || '/', params: new URLSearchParams(search) }
}

export function useRoute() {
  const [route, setRoute] = useState(current)
  useEffect(() => {
    const onChange = () => {
      setRoute(current())
      window.scrollTo(0, 0)
    }
    window.addEventListener('hashchange', onChange)
    return () => window.removeEventListener('hashchange', onChange)
  }, [])
  return route
}

export function navigate(path) {
  if (window.location.hash === `#${path}`) return
  window.location.hash = path
}
