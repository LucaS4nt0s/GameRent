import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from './api.js'
import { AuthProvider, useAuth } from './auth.jsx'
import { Icons } from './components/Brand.jsx'
import Header from './components/Header.jsx'
import RentModal from './components/RentModal.jsx'
import { useUserLocation } from './utils/location.js'
import { brl, displayTitle } from './utils/format.js'
import { navigate, useRoute } from './router.js'
import Account from './pages/Account.jsx'
import Admin from './pages/Admin.jsx'
import Home from './pages/Home.jsx'
import Login from './pages/Login.jsx'

export default function App() {
  return (
    <AuthProvider>
      <Icons />
      <Shell />
    </AuthProvider>
  )
}

function Shell() {
  const { path, params } = useRoute()
  const { user, logout } = useAuth()
  const loc = useUserLocation()
  const [renting, setRenting] = useState(null)
  const [busy, setBusy] = useState(false)
  const [refreshKey, setRefreshKey] = useState(0)
  const [myRentals, setMyRentals] = useState([])
  const [returning, setReturning] = useState('')
  const [toasts, setToasts] = useState([])
  const toastId = useRef(0)

  const notify = useCallback((text, kind = 'ok') => {
    const id = ++toastId.current
    setToasts((list) => [...list, { id, text, kind }])
    setTimeout(() => setToasts((list) => list.filter((t) => t.id !== id)), kind === 'error' ? 7000 : 4500)
  }, [])

  // Locações em andamento do usuário: o card do jogo e o cabeçalho mostram "com você" e o botão Devolver
  useEffect(() => {
    if (!user) {
      setMyRentals([])
      return undefined
    }
    let stopped = false
    let timer
    const load = async () => {
      if (!document.hidden) {
        try {
          const data = await api.rental.listRentals({ renterEmail: user.email, status: 'CONFIRMED' })
          if (!stopped) setMyRentals(data.items.filter((r) => r.status === 'CONFIRMED'))
        } catch {
          // mantém a última lista; o erro aparece nas próprias telas
        }
      }
      if (!stopped) timer = setTimeout(load, 5000)
    }
    load()
    return () => {
      stopped = true
      clearTimeout(timer)
    }
  }, [user, refreshKey])

  async function giveBack(rental) {
    setReturning(rental.rental_id)
    try {
      await api.rental.returnRental(rental.rental_id)
      notify(`Devolução de ${displayTitle(rental.game_title)} registrada. Obrigado!`)
      setRefreshKey((k) => k + 1)
    } catch (err) {
      notify(err.message, 'error')
    } finally {
      setReturning('')
    }
  }

  // Volta para o aluguel pendente depois do login
  useEffect(() => {
    if (!user) return
    try {
      const pending = JSON.parse(sessionStorage.getItem('jogai.pendingRent') || 'null')
      if (pending && path === '/') {
        sessionStorage.removeItem('jogai.pendingRent')
        setRenting(pending)
      }
    } catch {
      // ignora
    }
  }, [user, path])

  async function confirmRent(days) {
    if (!user) {
      try {
        sessionStorage.setItem('jogai.pendingRent', JSON.stringify(renting))
      } catch {
        // ignora
      }
      setRenting(null)
      navigate('/entrar?next=/')
      return
    }
    setBusy(true)
    try {
      const data = await api.rental.createRental({
        game_id: renting.id,
        renter_name: user.name,
        renter_email: user.email,
        rental_days: days,
      })
      setRenting(null)
      setRefreshKey((k) => k + 1)
      notify(`Pronto! ${displayTitle(data.game_title)} é seu por ${data.rental_days} ${data.rental_days === 1 ? 'dia' : 'dias'} (${brl(data.total_price)}). Acompanhe em Minhas locações.`)
    } catch (err) {
      notify(err.status === 409 ? 'Alguém acabou de reservar esse jogo. Escolha outro ou tente mais tarde.' : err.message, 'error')
      setRefreshKey((k) => k + 1)
      if (err.status === 409) setRenting(null)
    } finally {
      setBusy(false)
    }
  }

  let page
  let variant = 'light'
  if (path === '/entrar') {
    page = user ? <Redirect to={params.get('next') || '/'} /> : <Login next={params.get('next') || '/'} />
  } else if (path.startsWith('/conta')) {
    const section = path.split('/')[2] || 'locacoes'
    page = user ? <Account section={section} notify={notify} /> : <Redirect to={`/entrar?next=${path}`} />
  } else if (path === '/admin') {
    variant = 'admin'
    page = !user ? (
      <Redirect to="/entrar?next=/admin" />
    ) : user.isAdmin ? (
      <Admin notify={notify} />
    ) : (
      <main className="wrap denied">
        <h1>Área restrita</h1>
        <p className="lead">Esta página é só para administradores do Jogaí.</p>
        <a className="btn btn-ink" href="#/">
          Voltar ao catálogo
        </a>
      </main>
    )
  } else {
    page = (
      <Home
        loc={loc}
        onRent={setRenting}
        refreshKey={refreshKey}
        myRentals={myRentals}
        onReturn={giveBack}
        returning={returning}
      />
    )
  }

  return (
    <div className={`app ${variant === 'admin' ? 'admin' : ''}`}>
      <Header
        user={user}
        withYou={myRentals.length}
        cityLabel={loc.location.label}
        onLogout={() => {
          navigate('/')
          setTimeout(logout, 0)
        }}
        variant={variant}
      />
      {page}
      {renting && <RentModal game={renting} user={user} busy={busy} onClose={() => setRenting(null)} onConfirm={confirmRent} />}
      <div className="toasts" aria-live="polite">
        {toasts.map((t) => (
          <div key={t.id} className={`toast ${t.kind}`}>
            {t.text}
          </div>
        ))}
      </div>
    </div>
  )
}

function Redirect({ to }) {
  useEffect(() => navigate(to), [to])
  return null
}
