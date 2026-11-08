import { createContext, useContext, useEffect, useMemo, useState } from 'react'
import { setAuthToken } from './api.js'

/*
 * Autenticação com dois provedores, escolhidos por VITE_AUTH_PROVIDER:
 *  - "local" (padrão): login de demonstração guardado no navegador. Não é segurança real;
 *    serve para desenvolvimento e para a apresentação enquanto o Cognito não existe.
 *  - "cognito": Hosted UI do Amazon Cognito com Authorization Code + PKCE (sem bibliotecas extras).
 *    Admin = usuário no grupo "admin" do User Pool (claim cognito:groups do id_token).
 */
const PROVIDER = (import.meta.env.VITE_AUTH_PROVIDER || 'local').toLowerCase()
const ADMIN_EMAILS = (import.meta.env.VITE_ADMIN_EMAILS || 'admin@jogai.test')
  .split(',')
  .map((email) => email.trim().toLowerCase())
  .filter(Boolean)
const COGNITO = {
  domain: (import.meta.env.VITE_COGNITO_DOMAIN || '').replace(/^https?:\/\//, '').replace(/\/$/, ''),
  clientId: import.meta.env.VITE_COGNITO_CLIENT_ID || '',
  redirectUri: import.meta.env.VITE_COGNITO_REDIRECT_URI || `${window.location.origin}/`,
}
const SESSION_KEY = 'jogai.session'
const VERIFIER_KEY = 'jogai.pkce'

const AuthContext = createContext(null)

function readSession() {
  try {
    const session = JSON.parse(localStorage.getItem(SESSION_KEY) || 'null')
    if (session?.expiresAt && Date.now() > session.expiresAt) return null
    return session
  } catch {
    return null
  }
}

function saveSession(session) {
  try {
    if (session) localStorage.setItem(SESSION_KEY, JSON.stringify(session))
    else localStorage.removeItem(SESSION_KEY)
  } catch {
    // navegador sem armazenamento: a sessão dura até recarregar a página
  }
}

function base64url(bytes) {
  return btoa(String.fromCharCode(...new Uint8Array(bytes)))
    .replace(/\+/g, '-')
    .replace(/\//g, '_')
    .replace(/=+$/, '')
}

function decodeJwt(token) {
  const payload = token.split('.')[1].replace(/-/g, '+').replace(/_/g, '/')
  const json = decodeURIComponent(
    atob(payload)
      .split('')
      .map((c) => `%${c.charCodeAt(0).toString(16).padStart(2, '0')}`)
      .join('')
  )
  return JSON.parse(json)
}

async function cognitoRedirect() {
  const verifier = base64url(crypto.getRandomValues(new Uint8Array(48)))
  const challenge = base64url(await crypto.subtle.digest('SHA-256', new TextEncoder().encode(verifier)))
  sessionStorage.setItem(VERIFIER_KEY, verifier)
  sessionStorage.setItem('jogai.after', window.location.hash || '#/')
  const params = new URLSearchParams({
    response_type: 'code',
    client_id: COGNITO.clientId,
    redirect_uri: COGNITO.redirectUri,
    scope: 'openid email profile',
    code_challenge_method: 'S256',
    code_challenge: challenge,
  })
  window.location.assign(`https://${COGNITO.domain}/oauth2/authorize?${params}`)
}

async function cognitoExchange(code) {
  const body = new URLSearchParams({
    grant_type: 'authorization_code',
    client_id: COGNITO.clientId,
    code,
    redirect_uri: COGNITO.redirectUri,
    code_verifier: sessionStorage.getItem(VERIFIER_KEY) || '',
  })
  const res = await fetch(`https://${COGNITO.domain}/oauth2/token`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body,
  })
  if (!res.ok) throw new Error('Não foi possível concluir o login no Cognito.')
  const tokens = await res.json()
  const claims = decodeJwt(tokens.id_token)
  const groups = claims['cognito:groups'] || []
  return {
    provider: 'cognito',
    id: claims.sub,
    email: claims.email,
    name: claims.name || claims.given_name || claims.email,
    isAdmin: groups.includes('admin'),
    token: tokens.id_token,
    expiresAt: claims.exp * 1000,
  }
}

export function AuthProvider({ children }) {
  const [user, setUser] = useState(readSession)
  const [error, setError] = useState('')

  useEffect(() => {
    setAuthToken(user?.token || null)
  }, [user])

  // Volta do Hosted UI do Cognito com ?code=
  useEffect(() => {
    if (PROVIDER !== 'cognito') return
    const code = new URLSearchParams(window.location.search).get('code')
    if (!code) return
    cognitoExchange(code)
      .then((session) => {
        saveSession(session)
        setUser(session)
      })
      .catch((err) => setError(err.message))
      .finally(() => {
        const after = sessionStorage.getItem('jogai.after') || '#/'
        window.history.replaceState({}, '', `${window.location.pathname}${after}`)
        window.dispatchEvent(new HashChangeEvent('hashchange'))
      })
  }, [])

  const value = useMemo(
    () => ({
      user,
      provider: PROVIDER,
      error,
      loginLocal({ name, email }) {
        const cleanEmail = email.trim().toLowerCase()
        const session = {
          provider: 'local',
          id: cleanEmail,
          email: cleanEmail,
          name: name.trim(),
          isAdmin: ADMIN_EMAILS.includes(cleanEmail),
          token: null,
        }
        saveSession(session)
        setUser(session)
        return session
      },
      updateName(name) {
        setUser((current) => {
          const next = { ...current, name }
          saveSession(next)
          return next
        })
      },
      loginCognito: cognitoRedirect,
      logout() {
        saveSession(null)
        setUser(null)
        if (PROVIDER === 'cognito' && COGNITO.domain) {
          const params = new URLSearchParams({ client_id: COGNITO.clientId, logout_uri: COGNITO.redirectUri })
          window.location.assign(`https://${COGNITO.domain}/logout?${params}`)
        }
      },
    }),
    [user, error]
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth() {
  return useContext(AuthContext)
}

export const DEMO_USERS = [
  { name: 'Cliente Demo', email: 'cliente@jogai.test', label: 'Entrar como cliente' },
  { name: 'Admin Demo', email: ADMIN_EMAILS[0] || 'admin@jogai.test', label: 'Entrar como admin' },
]
