import { useEffect, useMemo, useState } from 'react'
import { api } from './api.js'

const STATUS_LABEL = {
  AVAILABLE: 'Disponível',
  RENTED: 'Alugado',
  MAINTENANCE: 'Manutenção',
}

const SP_NEIGHBORHOODS = [
  { name: 'Centro', lat: -23.5505, lon: -46.6333 },
  { name: 'Av. Paulista', lat: -23.5615, lon: -46.656 },
  { name: 'Itaim Bibi', lat: -23.5874, lon: -46.6795 },
  { name: 'Pinheiros', lat: -23.567, lon: -46.691 },
]

const THUMBS = [
  'linear-gradient(135deg,#00A650,#00D26A)',
  'linear-gradient(135deg,#0B7A3B,#12B76A)',
  'linear-gradient(135deg,#047857,#34D399)',
  'linear-gradient(135deg,#065F46,#10B981)',
  'linear-gradient(135deg,#166534,#4ADE80)',
  'linear-gradient(135deg,#0F766E,#2DD4BF)',
]

const DEFAULT_SEARCH = {
  lat: String(SP_NEIGHBORHOODS[0].lat),
  lon: String(SP_NEIGHBORHOODS[0].lon),
  maxKm: '10',
}

const POLL_MS = 3000
const DISCOVERY_POLL_MS = 5000

const DEFAULT_OWNER_FORM = {
  title: '',
  description: '',
  category: '',
  price_per_day: '',
  owner_id: '',
  owner_name: '',
  latitude: String(SP_NEIGHBORHOODS[0].lat),
  longitude: String(SP_NEIGHBORHOODS[0].lon),
}

function initials(title = '') {
  return String(title)
    .replace(/[^\p{L}\p{N} ]/gu, '')
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((word) => word[0].toUpperCase())
    .join('') || 'GR'
}

function money(value) {
  return Number(value || 0).toFixed(2)
}

function modeLabel(mode) {
  return mode === 'eventual' ? 'Eventual' : 'Forte'
}

function shortError(value) {
  if (!value) return ''
  return typeof value === 'string' ? value : JSON.stringify(value)
}

export default function App() {
  const [tab, setTab] = useState('renter')
  const [health, setHealth] = useState({ catalog: null, rental: null })
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')
  const [loading, setLoading] = useState(false)

  const [consistency, setConsistency] = useState('strong')
  const [textQuery, setTextQuery] = useState('')
  const [search, setSearch] = useState(DEFAULT_SEARCH)
  const [nearby, setNearby] = useState({ items: [], meta: null })
  const [locating, setLocating] = useState(false)

  const [rentals, setRentals] = useState([])
  const [renterEmailFilter, setRenterEmailFilter] = useState('')
  const [renting, setRenting] = useState(null)
  const [form, setForm] = useState({ renter_name: '', renter_email: '', rental_days: '1' })

  const [ownerForm, setOwnerForm] = useState(DEFAULT_OWNER_FORM)
  const [ownerFilter, setOwnerFilter] = useState('')
  const [ownerGames, setOwnerGames] = useState([])
  const [ownerMeta, setOwnerMeta] = useState(null)
  const [labGames, setLabGames] = useState([])

  const [discovery, setDiscovery] = useState({
    catalog: null,
    rental: null,
    errors: {},
    updatedAt: null,
  })
  const [loadingDiscovery, setLoadingDiscovery] = useState(false)

  const [labGameId, setLabGameId] = useState('')
  const [simRunning, setSimRunning] = useState(false)
  const [simResults, setSimResults] = useState([])

  const [benchRunning, setBenchRunning] = useState(false)
  const [benchmark, setBenchmark] = useState(null)

  const availableGames = useMemo(
    () => labGames.filter((game) => game.status === 'AVAILABLE'),
    [labGames]
  )

  const renterGames = useMemo(() => {
    const term = textQuery.trim().toLowerCase()
    if (!term) return nearby.items
    return nearby.items.filter((game) =>
      `${game.title} ${game.category} ${game.owner_name}`.toLowerCase().includes(term)
    )
  }, [nearby.items, textQuery])

  const serviceUp = health.catalog === 'HEALTHY' && health.rental === 'HEALTHY'

  async function run(fn) {
    setError('')
    setMessage('')
    setLoading(true)
    try {
      return await fn()
    } catch (err) {
      setError(err.message)
      return null
    } finally {
      setLoading(false)
    }
  }

  async function loadHealth() {
    const [catalog, rental] = await Promise.allSettled([
      api.catalog.health(),
      api.rental.health(),
    ])
    setHealth({
      catalog: catalog.status === 'fulfilled' ? catalog.value.status : 'DOWN',
      rental: rental.status === 'fulfilled' ? rental.value.status : 'DOWN',
    })
  }

  async function loadNearby(options = {}) {
    const lat = options.lat ?? search.lat
    const lon = options.lon ?? search.lon
    const maxKm = options.maxKm ?? search.maxKm
    const mode = options.consistency ?? consistency
    const data = await api.catalog.nearby({ lat, lon, maxKm, consistency: mode })
    setNearby(data)
    return data
  }

  async function loadRentals(email = renterEmailFilter) {
    const data = await api.rental.listRentals({ renterEmail: email.trim() || undefined })
    setRentals(data.items)
    return data
  }

  async function loadOwnerGames(ownerId = ownerFilter, mode = consistency) {
    const data = await api.catalog.listGames({
      consistency: mode,
      ownerId: ownerId.trim() || undefined,
    })
    setOwnerGames(data.items)
    setOwnerMeta(data.meta)
    return data
  }

  async function loadLabGames(mode = consistency) {
    const data = await api.catalog.listGames({ consistency: mode })
    setLabGames(data.items)
    return data
  }

  async function refreshCatalog(mode = consistency) {
    const [near, owner, lab] = await Promise.allSettled([
      loadNearby({ consistency: mode }),
      loadOwnerGames(ownerFilter, mode),
      loadLabGames(mode),
    ])
    if (near.status === 'rejected') throw near.reason
    if (owner.status === 'rejected') throw owner.reason
    if (lab.status === 'rejected') throw lab.reason
  }

  useEffect(() => {
    let active = true
    async function boot() {
      setLoading(true)
      try {
        const [near, rentalsData, ownerData] = await Promise.all([
          api.catalog.nearby({
            lat: DEFAULT_SEARCH.lat,
            lon: DEFAULT_SEARCH.lon,
            maxKm: DEFAULT_SEARCH.maxKm,
            consistency: 'strong',
          }),
          api.rental.listRentals(),
          api.catalog.listGames({ consistency: 'strong' }),
        ])
        if (!active) return
        setNearby(near)
        setRentals(rentalsData.items)
        setOwnerGames(ownerData.items)
        setOwnerMeta(ownerData.meta)
        setLabGames(ownerData.items)
      } catch (err) {
        if (active) setError(err.message)
      } finally {
        if (active) setLoading(false)
      }
      loadHealth()
    }
    boot()
    return () => {
      active = false
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    let stopped = false
    let timer
    async function tick() {
      if (!document.hidden) {
        await Promise.allSettled([
          loadHealth(),
          api.catalog
            .nearby({ ...search, consistency })
            .then((data) => setNearby(data)),
          api.rental
            .listRentals({ renterEmail: renterEmailFilter.trim() || undefined })
            .then((data) => setRentals(data.items)),
          api.catalog
            .listGames({ consistency, ownerId: ownerFilter.trim() || undefined })
            .then((data) => {
              setOwnerGames(data.items)
              setOwnerMeta(data.meta)
            }),
          api.catalog.listGames({ consistency }).then((data) => setLabGames(data.items)),
        ])
      }
      if (!stopped) timer = setTimeout(tick, POLL_MS)
    }
    timer = setTimeout(tick, POLL_MS)
    return () => {
      stopped = true
      clearTimeout(timer)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [search.lat, search.lon, search.maxKm, consistency, renterEmailFilter, ownerFilter])

  useEffect(() => {
    if (tab !== 'lab') return undefined
    let stopped = false
    let timer
    async function tick() {
      await refreshDiscovery(true)
      if (!stopped) timer = setTimeout(tick, DISCOVERY_POLL_MS)
    }
    tick()
    return () => {
      stopped = true
      clearTimeout(timer)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tab])

  async function searchNearby(coords) {
    const next = coords
      ? {
          lat: String(coords.lat),
          lon: String(coords.lon),
          maxKm: coords.maxKm ?? search.maxKm,
        }
      : search
    if (coords) setSearch(next)
    await run(async () => {
      await loadNearby({ ...next, consistency })
      setMessage(`Busca concluída com consistência ${modeLabel(consistency)}.`)
    })
  }

  async function changeConsistency(mode) {
    setConsistency(mode)
    await run(async () => {
      await loadNearby({ consistency: mode })
      setMessage(`Busca atualizada com consistência ${modeLabel(mode)}.`)
    })
  }

  async function useMyLocation() {
    if (!navigator.geolocation) {
      setError('Geolocalização não é suportada neste navegador.')
      return
    }
    setLocating(true)
    navigator.geolocation.getCurrentPosition(
      async (position) => {
        const coords = {
          lat: position.coords.latitude,
          lon: position.coords.longitude,
        }
        await searchNearby(coords)
        setLocating(false)
      },
      (err) => {
        setError('Não foi possível obter a localização: ' + err.message)
        setLocating(false)
      }
    )
  }

  function openRent(game) {
    setRenting(game)
    setForm({ renter_name: '', renter_email: '', rental_days: '1' })
    setError('')
    setMessage('')
  }

  async function submitRental(event) {
    event.preventDefault()
    const data = await run(() =>
      api.rental.createRental({
        game_id: renting.id,
        renter_name: form.renter_name,
        renter_email: form.renter_email,
        rental_days: Number(form.rental_days),
      })
    )
    if (!data) return
    setRenting(null)
    const success =
      `Locação confirmada: "${data.game_title}" por ${data.rental_days} dia(s) — R$ ${money(
        data.total_price
      )}. Lamport ${data.lamport_clock}.`
    await run(async () => {
      await refreshCatalog()
      await loadRentals()
    })
    setMessage(success)
  }

  async function doReturn(id) {
    const data = await run(() => api.rental.returnRental(id))
    if (!data) return
    const success = `Devolução registrada. Jogo liberado no catálogo (Lamport ${data.lamport_clock}).`
    await run(async () => {
      await refreshCatalog()
      await loadRentals()
    })
    setMessage(success)
  }

  async function submitGame(event) {
    event.preventDefault()
    const payload = {
      title: ownerForm.title.trim(),
      description: ownerForm.description.trim(),
      category: ownerForm.category.trim(),
      price_per_day: Number(ownerForm.price_per_day),
      owner_id: ownerForm.owner_id.trim(),
      owner_name: ownerForm.owner_name.trim(),
      latitude: Number(ownerForm.latitude),
      longitude: Number(ownerForm.longitude),
    }
    const data = await run(() => api.catalog.createGame(payload))
    if (!data) return
    const success = `Jogo cadastrado com URN ${data.urn} (versão ${data.version}).`
    setOwnerForm((current) => ({
      ...DEFAULT_OWNER_FORM,
      owner_id: current.owner_id,
      owner_name: current.owner_name,
      latitude: current.latitude,
      longitude: current.longitude,
    }))
    await run(async () => {
      await refreshCatalog()
      setLabGameId(String(data.id))
    })
    setMessage(success)
  }

  async function toggleGameStatus(game) {
    if (game.status === 'RENTED') {
      setError('Um jogo alugado só pode voltar a DISPONÍVEL após a devolução da locação.')
      return
    }
    const nextStatus = game.status === 'MAINTENANCE' ? 'AVAILABLE' : 'MAINTENANCE'
    const data = await run(() => api.catalog.updateStatus(game.id, nextStatus))
    if (!data) return
    const success = `Status de "${data.title}" alterado para ${STATUS_LABEL[data.status]} (v${data.version}).`
    await run(refreshCatalog)
    setMessage(success)
  }

  async function refreshDiscovery(silent = false) {
    if (!silent) {
      setLoadingDiscovery(true)
      setError('')
    }
    const errors = {}
    const [catalog, rental] = await Promise.allSettled([
      api.catalog.discovery(),
      api.rental.discovery(),
    ])
    if (catalog.status === 'rejected') errors.catalog = catalog.reason.message
    if (rental.status === 'rejected') errors.rental = rental.reason.message
    setDiscovery({
      catalog: catalog.status === 'fulfilled' ? catalog.value : null,
      rental: rental.status === 'fulfilled' ? rental.value : null,
      errors,
      updatedAt: new Date(),
    })
    if (!silent) setLoadingDiscovery(false)
  }

  async function runDoubleBooking() {
    const selected = labGames.find((game) => String(game.id) === String(labGameId))
    const game = selected && selected.status === 'AVAILABLE' ? selected : availableGames[0]
    if (!game) {
      setError('Nenhum jogo disponível para simular. Cadastre ou devolva um jogo primeiro.')
      return
    }

    setError('')
    setMessage('')
    setSimRunning(true)
    setSimResults([])
    setLabGameId(String(game.id))

    try {
      const requests = Array.from({ length: 10 }, (_, index) =>
        api.rental.createRentalRaw({
          game_id: game.id,
          renter_name: `Locatário Simultâneo ${index + 1}`,
          renter_email: `simulador${index + 1}@gamerent.test`,
          rental_days: 1,
        })
      )
      const settled = await Promise.allSettled(requests)
      const responses = settled.map((result) =>
        result.status === 'fulfilled'
          ? result.value
          : {
              ok: false,
              status: 'NETWORK',
              body: null,
              error: result.reason?.message || 'Falha de rede',
              meta: null,
            }
      )
      setSimResults(
        responses.map((response, index) => ({
          index: index + 1,
          gameTitle: game.title,
          ...response,
        }))
      )
      await run(async () => {
        await refreshCatalog()
        await loadRentals()
      })
      setMessage(`Simulação concluída para "${game.title}".`)
    } catch (err) {
      setError(err.message)
    } finally {
      setSimRunning(false)
    }
  }

  async function runBenchmark() {
    setBenchRunning(true)
    setError('')
    setMessage('')
    try {
      const runs = { strong: [], eventual: [] }
      let source = 'db_read_latency_ms'

      const warmup = await api.catalog.listGames({ consistency: 'eventual' })
      if (warmup.meta.db_read_latency_ms === null) source = 'tempo_total'

      const order = Array.from({ length: 5 }, (_, index) =>
        index % 2 === 0 ? ['strong', 'eventual'] : ['eventual', 'strong']
      ).flat()

      for (const mode of order) {
        const startedAt = performance.now()
        const data = await api.catalog.listGames({ consistency: mode })
        const elapsed = performance.now() - startedAt
        const dbLatency = data.meta.db_read_latency_ms
        if (dbLatency === null) source = 'tempo_total'
        runs[mode].push({
          latency: dbLatency ?? elapsed,
          served_by_node: data.meta.served_by_node,
          games: data.items.length,
        })
      }

      function summarize(mode) {
        const items = runs[mode]
        const total = items.reduce((sum, item) => sum + item.latency, 0)
        return {
          mode,
          runs: items,
          avg: total / items.length,
          served_by_node: items[0]?.served_by_node || '',
        }
      }

      setBenchmark({ strong: summarize('strong'), eventual: summarize('eventual'), source })
    } catch (err) {
      setError(err.message)
    } finally {
      setBenchRunning(false)
    }
  }

  return (
    <div className="app">
      <header className="topbar">
        <div className="topbar-inner">
          <div className="brand">
            <span className="logo">GR</span>
            <div>
              <strong>GameRent</strong>
              <span className="tagline">alugue jogos de tabuleiro perto de você</span>
            </div>
          </div>
          <div className="topbar-status">
            <span className="topbar-label">Consistência</span>
            <span className={`mode-badge ${consistency}`}>{modeLabel(consistency)}</span>
            <span
              className={`pulse ${serviceUp ? 'ok' : 'down'}`}
              title={serviceUp ? 'Serviços online' : 'Serviço indisponível'}
            />
          </div>
        </div>
      </header>

      <main className="content">
        {error && <div className="alert error">{error}</div>}
        {message && <div className="alert success">{message}</div>}
        {loading && <div className="alert info">Carregando…</div>}

        {tab === 'renter' && (
          <RenterTab
            search={search}
            setSearch={setSearch}
            consistency={consistency}
            onConsistencyChange={changeConsistency}
            onSearch={() => searchNearby()}
            onPickNeighborhood={(neighborhood) =>
              searchNearby({ lat: neighborhood.lat, lon: neighborhood.lon })
            }
            onUseMyLocation={useMyLocation}
            locating={locating}
            meta={nearby.meta}
            games={renterGames}
            total={nearby.items.length}
            textQuery={textQuery}
            setTextQuery={setTextQuery}
            onRent={openRent}
            rentals={rentals}
            renterEmailFilter={renterEmailFilter}
            setRenterEmailFilter={setRenterEmailFilter}
            onFilterRentals={async () => run(() => loadRentals())}
            onReturn={doReturn}
          />
        )}

        {tab === 'owner' && (
          <OwnerTab
            form={ownerForm}
            setForm={setOwnerForm}
            onSubmit={submitGame}
            onPickNeighborhood={(neighborhood) =>
              setOwnerForm((current) => ({
                ...current,
                latitude: String(neighborhood.lat),
                longitude: String(neighborhood.lon),
              }))
            }
            games={ownerGames}
            meta={ownerMeta}
            ownerFilter={ownerFilter}
            setOwnerFilter={setOwnerFilter}
            onFilter={async () => run(() => loadOwnerGames())}
            onToggleStatus={toggleGameStatus}
            consistency={consistency}
          />
        )}

        {tab === 'lab' && (
          <LabTab
            games={labGames}
            labGameId={labGameId}
            setLabGameId={setLabGameId}
            simRunning={simRunning}
            simResults={simResults}
            onRunSimulation={runDoubleBooking}
            discovery={discovery}
            loadingDiscovery={loadingDiscovery}
            onRefreshDiscovery={refreshDiscovery}
            benchmark={benchmark}
            benchRunning={benchRunning}
            onRunBenchmark={runBenchmark}
            consistency={consistency}
          />
        )}
      </main>

      <nav className="bottom-nav">
        <NavItem id="renter" tab={tab} setTab={setTab} label="Locatário">
          <svg viewBox="0 0 24 24"><path d="M3 10.5 12 3l9 7.5V21H3z" /></svg>
        </NavItem>
        <NavItem id="owner" tab={tab} setTab={setTab} label="Locador">
          <svg viewBox="0 0 24 24"><path d="M4 4h16v3H4zM5 9h14l-1 11H6z" /></svg>
        </NavItem>
        <NavItem id="lab" tab={tab} setTab={setTab} label="Laboratório">
          <svg viewBox="0 0 24 24"><path d="M9 2h6v3l4 9v5a3 3 0 0 1-3 3H8a3 3 0 0 1-3-3v-5l4-9zM8 15h8" /></svg>
        </NavItem>
      </nav>

      {renting && (
        <RentModal
          game={renting}
          form={form}
          setForm={setForm}
          onClose={() => setRenting(null)}
          onSubmit={submitRental}
        />
      )}
    </div>
  )
}

function RenterTab({
  search,
  setSearch,
  consistency,
  onConsistencyChange,
  onSearch,
  onPickNeighborhood,
  onUseMyLocation,
  locating,
  meta,
  games,
  total,
  textQuery,
  setTextQuery,
  onRent,
  rentals,
  renterEmailFilter,
  setRenterEmailFilter,
  onFilterRentals,
  onReturn,
}) {
  return (
    <>
      <section className="hero">
        <div>
          <span className="hero-kicker">Aba 1 · Visão do Locatário</span>
          <h1>Encontre jogos por perto e alugue em segundos</h1>
          <p>Busca geoespacial com privacidade de GPS, consistência configurável e devolução pela interface.</p>
        </div>
        <button className="cta" onClick={onUseMyLocation} disabled={locating}>
          {locating ? 'Buscando…' : 'Usar meu GPS'}
        </button>
      </section>

      <section className="panel">
        <div className="panel-head">
          <div>
            <h2>Busca geográfica</h2>
            <p className="panel-sub">Escolha um bairro de São Paulo ou informe latitude/longitude.</p>
          </div>
          <span className="count">{total} jogo(s)</span>
        </div>

        <div className="quick-row">
          {SP_NEIGHBORHOODS.map((neighborhood) => (
            <button
              key={neighborhood.name}
              className="chip"
              type="button"
              onClick={() => onPickNeighborhood(neighborhood)}
            >
              {neighborhood.name}
            </button>
          ))}
        </div>

        <div className="form-grid search-grid">
          <Field label="Latitude">
            <input
              type="number"
              step="any"
              value={search.lat}
              onChange={(event) => setSearch({ ...search, lat: event.target.value })}
            />
          </Field>
          <Field label="Longitude">
            <input
              type="number"
              step="any"
              value={search.lon}
              onChange={(event) => setSearch({ ...search, lon: event.target.value })}
            />
          </Field>
          <Field label="Raio máximo (km)">
            <input
              type="number"
              min="0.1"
              step="0.1"
              value={search.maxKm}
              onChange={(event) => setSearch({ ...search, maxKm: event.target.value })}
            />
          </Field>
          <Field label="Modo de consistência">
            <select
              value={consistency}
              onChange={(event) => onConsistencyChange(event.target.value)}
            >
              <option value="strong">Forte (strong)</option>
              <option value="eventual">Eventual (eventual)</option>
            </select>
          </Field>
          <button className="cta solid" type="button" onClick={onSearch}>
            Buscar jogos
          </button>
        </div>

        <MetaBadges meta={meta} />
      </section>

      <section className="section-block">
        <div className="section-head">
          <h2 className="section-title">
            Jogos próximos <span className="count">{games.length}</span>
          </h2>
          <label className="inline-search">
            <input
              value={textQuery}
              onChange={(event) => setTextQuery(event.target.value)}
              placeholder="Filtrar por título, categoria ou dono…"
            />
          </label>
        </div>

        <div className="grid">
          {games.map((game, index) => (
            <GameCard
              key={game.id}
              game={game}
              thumb={THUMBS[index % THUMBS.length]}
              onRent={onRent}
            />
          ))}
          {games.length === 0 && (
            <p className="empty">Nenhum jogo encontrado com os filtros atuais.</p>
          )}
        </div>
      </section>

      <section className="section-block">
        <div className="section-head">
          <h2 className="section-title">
            Minhas locações <span className="count">{rentals.length}</span>
          </h2>
          <div className="inline-actions">
            <input
              value={renterEmailFilter}
              onChange={(event) => setRenterEmailFilter(event.target.value)}
              placeholder="Filtrar por e-mail"
            />
            <button className="ghost" type="button" onClick={onFilterRentals}>
              Filtrar
            </button>
          </div>
        </div>

        <div className="orders">
          {rentals.map((rental) => (
            <article className="order" key={rental.rental_id}>
              <div className="order-thumb">{initials(rental.game_title)}</div>
              <div className="order-info">
                <strong>{rental.game_title}</strong>
                <span className="muted">
                  {rental.rental_days} dia(s) · {rental.renter_name} · {rental.renter_email}
                </span>
                <span className="mono">URN {rental.urn}</span>
                <span className="mono">Lamport {rental.lamport_clock}</span>
              </div>
              <div className="order-right">
                <span className="price">R$ {money(rental.total_price)}</span>
                <span className={`status-text ${rental.status}`}>{rental.status}</span>
                {rental.status === 'CONFIRMED' && (
                  <button className="ghost" type="button" onClick={() => onReturn(rental.rental_id)}>
                    Devolver jogo
                  </button>
                )}
              </div>
            </article>
          ))}
          {rentals.length === 0 && (
            <p className="empty">Você ainda não fez nenhuma locação.</p>
          )}
        </div>
      </section>
    </>
  )
}

function OwnerTab({
  form,
  setForm,
  onSubmit,
  onPickNeighborhood,
  games,
  meta,
  ownerFilter,
  setOwnerFilter,
  onFilter,
  onToggleStatus,
}) {
  return (
    <>
      <section className="hero owner-hero">
        <div>
          <span className="hero-kicker">Aba 2 · Visão do Locador</span>
          <h1>Cadastre jogos e gerencie seu acervo</h1>
          <p>Publique novos títulos no catálogo e alterne entre disponível e manutenção.</p>
        </div>
      </section>

      <section className="panel">
        <div className="panel-head">
          <div>
            <h2>Cadastrar novo jogo de tabuleiro</h2>
            <p className="panel-sub">As coordenadas são usadas apenas no servidor para calcular distâncias.</p>
          </div>
        </div>

        <div className="privacy-note">
          <strong>Privacidade geográfica</strong>
          <p>
            Latitude e longitude ficam restritas ao servidor. As respostas públicas do catálogo
            nunca expõem as coordenadas reais do locador — apenas a distância relativa em km.
          </p>
        </div>

        <form onSubmit={onSubmit} className="owner-form">
          <div className="form-grid">
            <Field label="Título">
              <input
                value={form.title}
                onChange={(event) => setForm({ ...form, title: event.target.value })}
                placeholder="Catan"
                required
              />
            </Field>
            <Field label="Categoria">
              <input
                value={form.category}
                onChange={(event) => setForm({ ...form, category: event.target.value })}
                placeholder="Estratégia"
                required
              />
            </Field>
            <Field label="Preço por dia (R$)">
              <input
                type="number"
                min="0.01"
                step="0.01"
                value={form.price_per_day}
                onChange={(event) => setForm({ ...form, price_per_day: event.target.value })}
                placeholder="15.00"
                required
              />
            </Field>
            <Field label="Nome do locador">
              <input
                value={form.owner_name}
                onChange={(event) => setForm({ ...form, owner_name: event.target.value })}
                placeholder="Ana Paula"
                required
              />
            </Field>
            <Field label="ID do locador">
              <input
                value={form.owner_id}
                onChange={(event) => setForm({ ...form, owner_id: event.target.value })}
                placeholder="locador-001"
                required
              />
            </Field>
            <Field label="Latitude (GPS)">
              <input
                type="number"
                step="any"
                value={form.latitude}
                onChange={(event) => setForm({ ...form, latitude: event.target.value })}
                required
              />
            </Field>
            <Field label="Longitude (GPS)">
              <input
                type="number"
                step="any"
                value={form.longitude}
                onChange={(event) => setForm({ ...form, longitude: event.target.value })}
                required
              />
            </Field>
            <Field label="Descrição" wide>
              <textarea
                value={form.description}
                onChange={(event) => setForm({ ...form, description: event.target.value })}
                placeholder="Clássico jogo de negociação, comércio e colonização."
                rows="3"
                required
              />
            </Field>
          </div>

          <div className="quick-row">
            <span className="quick-label">Preenchimento rápido:</span>
            {SP_NEIGHBORHOODS.map((neighborhood) => (
              <button
                key={neighborhood.name}
                className="chip"
                type="button"
                onClick={() => onPickNeighborhood(neighborhood)}
              >
                {neighborhood.name}
              </button>
            ))}
          </div>

          <button className="cta solid wide" type="submit">
            Cadastrar jogo no catálogo
          </button>
        </form>
      </section>

      <section className="section-block">
        <div className="section-head">
          <h2 className="section-title">Acervo de jogos</h2>
          <div className="inline-actions">
            <input
              value={ownerFilter}
              onChange={(event) => setOwnerFilter(event.target.value)}
              placeholder="Filtrar por owner_id"
            />
            <button className="ghost" type="button" onClick={onFilter}>
              Filtrar acervo
            </button>
          </div>
        </div>

        <MetaBadges meta={meta} />

        <div className="owner-list">
          {games.map((game) => (
            <article className="owner-item" key={game.id}>
              <div className="owner-item-main">
                <div className="owner-item-top">
                  <h3>{game.title}</h3>
                  <StatusPill status={game.status} />
                </div>
                <p className="muted">
                  {game.category} · {game.owner_name} ({game.owner_id}) · R$ {money(game.price_per_day)}/dia
                </p>
                <p className="mono">
                  URN {game.urn} · versão {game.version} · Lamport {game.lamport_clock}
                </p>
              </div>
              <button
                type="button"
                className={game.status === 'MAINTENANCE' ? 'ghost' : 'danger'}
                onClick={() => onToggleStatus(game)}
                disabled={game.status === 'RENTED'}
              >
                {game.status === 'RENTED'
                  ? 'Alugado'
                  : game.status === 'MAINTENANCE'
                    ? 'Voltar para disponível'
                    : 'Colocar em manutenção'}
              </button>
            </article>
          ))}
          {games.length === 0 && <p className="empty">Nenhum jogo encontrado para este locador.</p>}
        </div>
      </section>
    </>
  )
}

function LabTab({
  games,
  labGameId,
  setLabGameId,
  simRunning,
  simResults,
  onRunSimulation,
  discovery,
  loadingDiscovery,
  onRefreshDiscovery,
  benchmark,
  benchRunning,
  onRunBenchmark,
  consistency,
}) {
  const winners = simResults.filter((result) => result.status === 201).length
  const conflicts = simResults.filter((result) => result.status === 409).length
  const failures = simResults.filter((result) => result.status !== 201 && result.status !== 409).length
  const selectedGame = games.find((game) => String(game.id) === String(labGameId))

  return (
    <>
      <section className="hero lab-hero">
        <div>
          <span className="hero-kicker">Aba 3 · Laboratório de Sistemas Distribuídos</span>
          <h1>Coordenação, nomeação e consistência ao vivo</h1>
          <p>Execute a disputa concorrente, inspecione o service discovery e compare os modos de leitura.</p>
        </div>
        <button className="cta" onClick={onRefreshDiscovery} disabled={loadingDiscovery}>
          {loadingDiscovery ? 'Atualizando…' : 'Atualizar discovery'}
        </button>
      </section>

      <section className="panel">
        <div className="panel-head">
          <div>
            <h2>Simulador de disputa concorrente</h2>
            <p className="panel-sub">
              Dispara 10 reservas simultâneas para o mesmo jogo via Promise.all. A exclusão mútua
              deve produzir 1 vencedor e 9 conflitos.
            </p>
          </div>
          <span className="mode-badge neutral">{consistency === 'strong' ? 'Leitura forte' : 'Leitura eventual'}</span>
        </div>

        <div className="lab-controls">
          <Field label="Jogo alvo">
            <select value={labGameId} onChange={(event) => setLabGameId(event.target.value)}>
              <option value="">Selecione um jogo disponível…</option>
              {games.map((game) => (
                <option key={game.id} value={game.id} disabled={game.status !== 'AVAILABLE'}>
                  #{game.id} — {game.title} ({STATUS_LABEL[game.status] || game.status})
                </option>
              ))}
            </select>
          </Field>
          <button className="cta solid" type="button" onClick={onRunSimulation} disabled={simRunning}>
            {simRunning ? 'Disparando 10 reservas…' : 'Disparar 10 reservas simultâneas'}
          </button>
        </div>

        {selectedGame && (
          <p className="hint">
            Alvo selecionado: <strong>#{selectedGame.id} {selectedGame.title}</strong> · URN{' '}
            <span className="mono">{selectedGame.urn}</span>
          </p>
        )}

        {simResults.length > 0 && (
          <>
            <div className="summary-row">
              <span className="summary-chip success">{winners} × 201 Created</span>
              <span className="summary-chip conflict">{conflicts} × 409 Conflict</span>
              {failures > 0 && <span className="summary-chip failure">{failures} × outro erro</span>}
            </div>
            <div className="result-grid">
              {simResults.map((result) => (
                <article key={result.index} className={`result-card result-${result.status}`}>
                  <div className="result-head">
                    <strong>Requisição #{result.index}</strong>
                    <span className="result-status">{result.status}</span>
                  </div>
                  <p className="result-body">
                    {result.status === 201
                      ? `Vencedora: ${result.body?.game_title} · locação ${String(
                          result.body?.rental_id || ''
                        ).slice(0, 8)}`
                      : shortError(result.error) || 'Requisição bloqueada.'}
                  </p>
                  <span className="mono">Lamport {result.meta?.lamport_clock ?? '—'}</span>
                </article>
              ))}
            </div>
          </>
        )}
      </section>

      <section className="panel">
        <div className="panel-head">
          <div>
            <h2>Nomeação e service discovery</h2>
            <p className="panel-sub">
              URNs dos nós ativos, hostname DNS, IP resolvido e relógio de Lamport em atualização automática.
            </p>
          </div>
          <span className="meta-pill">
            {discovery.updatedAt
              ? `ao vivo · ${discovery.updatedAt.toLocaleTimeString('pt-BR')}`
              : 'aguardando discovery'}
          </span>
        </div>

        <div className="discovery-grid">
          <DiscoveryCard
            title="catalog-service"
            data={discovery.catalog}
            error={discovery.errors.catalog}
          />
          <DiscoveryCard
            title="rental-service"
            data={discovery.rental}
            error={discovery.errors.rental}
          />
        </div>
        {!discovery.catalog && !discovery.rental && !loadingDiscovery && (
          <p className="empty">Clique em "Atualizar discovery" para consultar os microsserviços.</p>
        )}
      </section>

      <section className="panel">
        <div className="panel-head">
          <div>
            <h2>Comparador visual de consistência</h2>
            <p className="panel-sub">
              Executa 5 leituras em cada modo, alternando a ordem, e calcula a latência média.
            </p>
          </div>
        </div>

        <button className="cta solid" type="button" onClick={onRunBenchmark} disabled={benchRunning}>
          {benchRunning ? 'Executando leituras…' : 'Comparar Forte vs. Eventual'}
        </button>

        {benchmark && (
          <div className="discovery-grid bench-grid">
            <BenchmarkCard title="Consistência Forte" data={benchmark.strong} source={benchmark.source} />
            <BenchmarkCard title="Consistência Eventual" data={benchmark.eventual} source={benchmark.source} />
          </div>
        )}
        {benchmark && (
          <p className="hint">
            Diferença de latência média: <strong>{Math.abs(benchmark.strong.avg - benchmark.eventual.avg).toFixed(2)} ms</strong>
            {' '}a favor da modalidade {benchmark.strong.avg <= benchmark.eventual.avg ? 'forte' : 'eventual'}.
            {' '}Fonte: {benchmark.source === 'db_read_latency_ms'
              ? 'latência de leitura do banco (X-DB-Read-Latency-Ms)'
              : 'tempo total da requisição (header indisponível)'}.
          </p>
        )}
      </section>
    </>
  )
}

function GameCard({ game, thumb, onRent }) {
  return (
    <article className="card">
      <div className="thumb" style={{ background: thumb }}>
        <span>{initials(game.title)}</span>
        {game.distance_km !== undefined && (
          <span className="distance">{Number(game.distance_km).toFixed(2)} km</span>
        )}
      </div>
      <div className="card-body">
        <div className="card-top">
          <h3>{game.title}</h3>
          <StatusPill status={game.status} />
        </div>
        <p className="muted">
          {game.category} · {game.owner_name}
        </p>
        <p className="desc">{game.description}</p>
        <div className="card-meta">
          <span className="mono" title={game.urn}>URN {game.urn}</span>
          <span>v{game.version}</span>
          <span>Lamport {game.lamport_clock}</span>
        </div>
        <div className="card-foot">
          <span className="price">
            R$ {money(game.price_per_day)}
            <small>/dia</small>
          </span>
          <button
            type="button"
            onClick={() => onRent(game)}
            disabled={game.status !== 'AVAILABLE'}
          >
            {game.status === 'AVAILABLE' ? 'Alugar Agora' : 'Indisponível'}
          </button>
        </div>
      </div>
    </article>
  )
}

function RentModal({ game, form, setForm, onClose, onSubmit }) {
  return (
    <div className="overlay" onClick={onClose}>
      <div className="sheet" onClick={(event) => event.stopPropagation()}>
        <div className="sheet-thumb" style={{ background: THUMBS[game.id % THUMBS.length] }}>
          <span>{initials(game.title)}</span>
        </div>
        <h3>{game.title}</h3>
        <p className="muted">
          {game.category} · R$ {money(game.price_per_day)}/dia · URN{' '}
          <span className="mono">{game.urn}</span>
        </p>
        <form onSubmit={onSubmit} className="sheet-form">
          <label>
            Seu nome
            <input
              value={form.renter_name}
              onChange={(event) => setForm({ ...form, renter_name: event.target.value })}
              placeholder="João da Silva"
              required
            />
          </label>
          <label>
            E-mail
            <input
              type="email"
              value={form.renter_email}
              onChange={(event) => setForm({ ...form, renter_email: event.target.value })}
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
              onChange={(event) => setForm({ ...form, rental_days: event.target.value })}
              required
            />
          </label>
          <div className="sheet-total">
            Total estimado
            <strong>R$ {money(game.price_per_day * Number(form.rental_days || 0))}</strong>
          </div>
          <button className="cta solid wide" type="submit">
            Confirmar aluguel
          </button>
          <button className="ghost wide" type="button" onClick={onClose}>
            Cancelar
          </button>
        </form>
      </div>
    </div>
  )
}

function DiscoveryCard({ title, data, error }) {
  if (error) {
    return (
      <article className="discovery-card">
        <h3>{title}</h3>
        <p className="alert error">{error}</p>
      </article>
    )
  }
  if (!data) {
    return (
      <article className="discovery-card">
        <h3>{title}</h3>
        <p className="empty">Sem dados de discovery.</p>
      </article>
    )
  }
  const ips = data.dns_resolution?.resolved_ips || []
  return (
    <article className="discovery-card">
      <h3>{title}</h3>
      <dl className="discovery-list">
        <DlItem term="URN do nó" value={data.node_urn} mono />
        <DlItem term="Instância" value={data.instance_id} mono />
        <DlItem term="Hostname DNS" value={data.dns_target} mono />
        <DlItem term="Resolução DNS" value={data.dns_resolution?.status} />
        <DlItem term="IP resolvido" value={ips.length ? ips.join(', ') : '—'} mono />
        <DlItem term="Relógio de Lamport" value={data.lamport_clock} />
        <DlItem
          term="DynamoDB"
          value={
            data.dynamodb
              ? `${data.dynamodb.mode} · ${data.dynamodb.table_name}`
              : '—'
          }
        />
      </dl>
    </article>
  )
}

function BenchmarkCard({ title, data, source }) {
  return (
    <article className="discovery-card bench-card">
      <div className="bench-head">
        <h3>{title}</h3>
        <span className={`mode-badge ${data.mode}`}>{modeLabel(data.mode)}</span>
      </div>
      <strong className="bench-value">{Number(data.avg).toFixed(2)} ms</strong>
      <p className="muted">
        Média de {data.runs.length} leituras ·{' '}
        {source === 'db_read_latency_ms' ? 'latência do banco' : 'tempo total da requisição'}
      </p>
      <p className="mono">served_by_node: {data.served_by_node || '—'}</p>
      <div className="bench-runs">
        {data.runs.map((run, index) => (
          <span key={index} className="bench-run" title={`${run.games} jogo(s)`}>
            {Number(run.latency).toFixed(2)} ms
          </span>
        ))}
      </div>
    </article>
  )
}

function DlItem({ term, value, mono }) {
  return (
    <div>
      <dt>{term}</dt>
      <dd className={mono ? 'mono' : undefined}>{value ?? '—'}</dd>
    </div>
  )
}

function MetaBadges({ meta }) {
  if (!meta) return null
  return (
    <div className="meta-row">
      <span className={`mode-badge ${meta.consistency_mode || 'neutral'}`}>
        Consistência {modeLabel(meta.consistency_mode)}
      </span>
      {meta.db_read_latency_ms !== null && meta.db_read_latency_ms !== undefined && (
        <span className="meta-pill">Leitura {Number(meta.db_read_latency_ms).toFixed(2)} ms</span>
      )}
      {meta.served_by_node && (
        <span className="meta-pill mono">served_by_node: {meta.served_by_node}</span>
      )}
      {meta.lamport_clock !== null && meta.lamport_clock !== undefined && (
        <span className="meta-pill">Lamport {meta.lamport_clock}</span>
      )}
    </div>
  )
}

function Field({ label, children, wide }) {
  return (
    <label className={wide ? 'field wide' : 'field'}>
      <span>{label}</span>
      {children}
    </label>
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
