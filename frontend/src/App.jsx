import { useEffect, useMemo, useState } from 'react'
import { api } from './api.js'

const STATUS_LABEL = {
  AVAILABLE: 'Disponível',
  RENTED: 'Alugado',
  MAINTENANCE: 'Manutenção',
}

const THUMBS = [
  'linear-gradient(135deg,#00A650,#00D26A)',
  'linear-gradient(135deg,#0B7A3B,#12B76A)',
  'linear-gradient(135deg,#047857,#34D399)',
  'linear-gradient(135deg,#065F46,#10B981)',
  'linear-gradient(135deg,#166534,#4ADE80)',
  'linear-gradient(135deg,#0F766E,#2DD4BF)',
]

function initials(title) {
  return title
    .replace(/[^\p{L}\p{N} ]/gu, '')
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((w) => w[0].toUpperCase())
    .join('')
}

export default function App() {
  const [tab, setTab] = useState('home')
  const [games, setGames] = useState([])
  const [rentals, setRentals] = useState([])
  const [health, setHealth] = useState({ catalog: null, rental: null })
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')
  const [loading, setLoading] = useState(false)

  const [query, setQuery] = useState('')
  const [category, setCategory] = useState('Todas')

  const [nearby, setNearby] = useState(null)
  const [locating, setLocating] = useState(false)

  const [renting, setRenting] = useState(null)
  const [form, setForm] = useState({ renter_name: '', renter_email: '', rental_days: '1' })

  const categories = useMemo(() => {
    const set = new Set(games.map((g) => g.category))
    return ['Todas', ...set]
  }, [games])

  const filtered = useMemo(() => {
    return games.filter((g) => {
      const byCat = category === 'Todas' || g.category === category
      const byText = g.title.toLowerCase().includes(query.trim().toLowerCase())
      return byCat && byText
    })
  }, [games, category, query])

  async function run(fn) {
    setError('')
    setMessage('')
    setLoading(true)
    try {
      return await fn()
    } catch (e) {
      setError(e.message)
      return null
    } finally {
      setLoading(false)
    }
  }

  async function loadHealth() {
    try {
      const data = await api.catalog.health()
      setHealth((h) => ({ ...h, catalog: data.status }))
    } catch {
      setHealth((h) => ({ ...h, catalog: 'DOWN' }))
    }
    try {
      const data = await api.rental.health()
      setHealth((h) => ({ ...h, rental: data.status }))
    } catch {
      setHealth((h) => ({ ...h, rental: 'DOWN' }))
    }
  }

  async function loadGames() {
    const data = await run(() => api.catalog.listGames())
    if (data) setGames(data)
  }

  async function loadRentals() {
    const data = await run(() => api.rental.listRentals())
    if (data) setRentals(data)
  }

  useEffect(() => {
    loadHealth()
    loadGames()
    loadRentals()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  function openRent(game) {
    setRenting(game)
    setForm({ renter_name: '', renter_email: '', rental_days: '1' })
    setError('')
    setMessage('')
  }

  async function submitRental(e) {
    e.preventDefault()
    const payload = {
      game_id: renting.id,
      renter_name: form.renter_name,
      renter_email: form.renter_email,
      rental_days: Number(form.rental_days),
    }
    const data = await run(() => api.rental.createRental(payload))
    if (data) {
      setRenting(null)
      setMessage(`Pedido confirmado! "${data.game_title}" por ${data.rental_days} dia(s) — R$ ${data.total_price.toFixed(2)}`)
      setTab('orders')
      loadGames()
      loadRentals()
    }
  }

  async function doReturn(id) {
    const data = await run(() => api.rental.returnRental(id))
    if (data) {
      setMessage('Devolução registrada. Jogo liberado no catálogo.')
      loadGames()
      loadRentals()
    }
  }

  async function searchNearby() {
    setLocating(true)
    setError('')
    if (!navigator.geolocation) {
      setError('Geolocalização não é suportada neste navegador.')
      setLocating(false)
      return
    }
    navigator.geolocation.getCurrentPosition(
      async (pos) => {
        const lat = pos.coords.latitude
        const lon = pos.coords.longitude
        const data = await run(() => api.catalog.nearby(lat, lon, 50))
        if (data) {
          setNearby(data)
          setTab('nearby')
        }
        setLocating(false)
      },
      (err) => {
        setError('Não foi possível obter a localização: ' + err.message)
        setLocating(false)
      }
    )
  }

  const serviceUp = health.catalog === 'HEALTHY' && health.rental === 'HEALTHY'

  return (
    <div className="app">
      <header className="topbar">
        <div className="topbar-inner">
          <div className="brand">
            <span className="logo">GR</span>
            <div>
              <strong>GameRent</strong>
              <span className="tagline">alugue jogos perto de você</span>
            </div>
          </div>
          <label className="search">
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Buscar jogo pelo nome…"
            />
          </label>
          <span className={`pulse ${serviceUp ? 'ok' : 'down'}`} title={serviceUp ? 'Serviços online' : 'Serviço indisponível'} />
        </div>
      </header>

      <main className="content">
        {error && <div className="alert error">{error}</div>}
        {message && <div className="alert success">{message}</div>}
        {loading && <div className="alert info">Carregando…</div>}

        {tab === 'home' && (
          <>
            <section className="hero">
              <div>
                <h1>Jogos de tabuleiro a um toque</h1>
                <p>Os melhores títulos do seu bairro, alugados por dia.</p>
              </div>
              <button className="cta" onClick={searchNearby} disabled={locating}>
                {locating ? 'Buscando…' : 'Jogos perto de mim'}
              </button>
            </section>

            <div className="chips">
              {categories.map((c) => (
                <button
                  key={c}
                  className={category === c ? 'chip active' : 'chip'}
                  onClick={() => setCategory(c)}
                >
                  {c}
                </button>
              ))}
            </div>

            <h2 className="section-title">
              {query ? `Resultados para "${query}"` : 'Destaques'}
              <span className="count">{filtered.length}</span>
            </h2>

            <div className="grid">
              {filtered.map((g, i) => (
                <GameCard key={g.id} game={g} thumb={THUMBS[i % THUMBS.length]} onRent={openRent} />
              ))}
              {filtered.length === 0 && <p className="empty">Nenhum jogo encontrado.</p>}
            </div>
          </>
        )}

        {tab === 'nearby' && (
          <>
            <h2 className="section-title">Perto de você {nearby && <span className="count">{nearby.length}</span>}</h2>
            <button className="cta wide" onClick={searchNearby} disabled={locating}>
              {locating ? 'Buscando…' : 'Usar minha localização'}
            </button>
            <div className="grid">
              {nearby &&
                nearby.map((g, i) => (
                  <article className="card" key={g.id}>
                    <div className="thumb" style={{ background: THUMBS[i % THUMBS.length] }}>
                      <span>{initials(g.title)}</span>
                      <span className="distance">{g.distance_km} km</span>
                    </div>
                    <div className="card-body">
                      <div className="card-top">
                        <h3>{g.title}</h3>
                        <StatusPill status={g.status} />
                      </div>
                      <p className="muted">{g.category}</p>
                      <div className="card-foot">
                        <span className="price">R$ {g.price_per_day.toFixed(2)}<small>/dia</small></span>
                        <button onClick={() => openRent(g)} disabled={g.status !== 'AVAILABLE'}>
                          Alugar
                        </button>
                      </div>
                    </div>
                  </article>
                ))}
              {nearby && nearby.length === 0 && <p className="empty">Nenhum jogo num raio de 50 km.</p>}
              {!nearby && <p className="empty">Toque em "Usar minha localização" para ver jogos por perto.</p>}
            </div>
          </>
        )}

        {tab === 'orders' && (
          <>
            <h2 className="section-title">Meus pedidos <span className="count">{rentals.length}</span></h2>
            <div className="orders">
              {rentals.map((r) => (
                <article className="order" key={r.rental_id}>
                  <div className="order-thumb">{initials(r.game_title)}</div>
                  <div className="order-info">
                    <strong>{r.game_title}</strong>
                    <span className="muted">{r.rental_days} dia(s) · {r.renter_name}</span>
                    <span className="muted mono">{r.rental_id.slice(0, 8)}</span>
                  </div>
                  <div className="order-right">
                    <span className="price">R$ {r.total_price.toFixed(2)}</span>
                    <span className={`status-text ${r.status}`}>{r.status}</span>
                    {r.status === 'CONFIRMED' && (
                      <button className="ghost" onClick={() => doReturn(r.rental_id)}>Devolver</button>
                    )}
                  </div>
                </article>
              ))}
              {rentals.length === 0 && <p className="empty">Você ainda não fez nenhum pedido.</p>}
            </div>
          </>
        )}
      </main>

      <nav className="bottom-nav">
        <NavItem id="home" tab={tab} setTab={setTab} label="Início">
          <svg viewBox="0 0 24 24"><path d="M3 10.5 12 3l9 7.5V21H3z" /></svg>
        </NavItem>
        <NavItem id="nearby" tab={tab} setTab={setTab} label="Perto">
          <svg viewBox="0 0 24 24"><path d="M12 2a7 7 0 0 0-7 7c0 5 7 13 7 13s7-8 7-13a7 7 0 0 0-7-7zm0 9.5A2.5 2.5 0 1 1 12 6a2.5 2.5 0 0 1 0 5.5z" /></svg>
        </NavItem>
        <NavItem id="orders" tab={tab} setTab={setTab} label="Pedidos">
          <svg viewBox="0 0 24 24"><path d="M4 4h16v3H4zM5 9h14l-1 11H6z" /></svg>
        </NavItem>
      </nav>

      {renting && (
        <div className="overlay" onClick={() => setRenting(null)}>
          <div className="sheet" onClick={(e) => e.stopPropagation()}>
            <div className="sheet-thumb" style={{ background: THUMBS[renting.id % THUMBS.length] }}>
              <span>{initials(renting.title)}</span>
            </div>
            <h3>{renting.title}</h3>
            <p className="muted">
              {renting.category} · R$ {renting.price_per_day.toFixed(2)}/dia
            </p>
            <form onSubmit={submitRental} className="sheet-form">
              <label>
                Seu nome
                <input
                  value={form.renter_name}
                  onChange={(e) => setForm({ ...form, renter_name: e.target.value })}
                  placeholder="João da Silva"
                  required
                />
              </label>
              <label>
                E-mail
                <input
                  type="email"
                  value={form.renter_email}
                  onChange={(e) => setForm({ ...form, renter_email: e.target.value })}
                  placeholder="joao@exemplo.com"
                  required
                />
              </label>
              <label>
                Dias
                <input
                  type="number"
                  min="1"
                  value={form.rental_days}
                  onChange={(e) => setForm({ ...form, rental_days: e.target.value })}
                  required
                />
              </label>
              <div className="sheet-total">
                Total estimado
                <strong>R$ {(renting.price_per_day * Number(form.rental_days || 0)).toFixed(2)}</strong>
              </div>
              <button className="cta wide" type="submit">Confirmar aluguel</button>
              <button className="ghost wide" type="button" onClick={() => setRenting(null)}>Cancelar</button>
            </form>
          </div>
        </div>
      )}
    </div>
  )
}

function GameCard({ game, thumb, onRent }) {
  return (
    <article className="card">
      <div className="thumb" style={{ background: thumb }}>
        <span>{initials(game.title)}</span>
      </div>
      <div className="card-body">
        <div className="card-top">
          <h3>{game.title}</h3>
          <StatusPill status={game.status} />
        </div>
        <p className="muted">{game.category} · {game.owner_name}</p>
        <p className="desc">{game.description}</p>
        <div className="card-foot">
          <span className="price">R$ {game.price_per_day.toFixed(2)}<small>/dia</small></span>
          <button onClick={() => onRent(game)} disabled={game.status !== 'AVAILABLE'}>
            {game.status === 'AVAILABLE' ? 'Alugar' : 'Indisponível'}
          </button>
        </div>
      </div>
    </article>
  )
}

function StatusPill({ status }) {
  return <span className={`badge ${status}`}>{STATUS_LABEL[status] || status}</span>
}

function NavItem({ id, tab, setTab, label, children }) {
  return (
    <button className={tab === id ? 'nav-item active' : 'nav-item'} onClick={() => setTab(id)}>
      {children}
      <span>{label}</span>
    </button>
  )
}
