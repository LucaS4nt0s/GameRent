import { useEffect, useState } from 'react'
import { api } from '../api.js'
import { useAuth } from '../auth.jsx'
import GameImage from '../components/BoxCover.jsx'
import { Icon } from '../components/Brand.jsx'
import { findCity, searchCities } from '../data/cities.js'
import { brl, daysLeft, displayTitle, dueDate, shortDate, STATUS_LABEL } from '../utils/format.js'
import { getGpsPosition } from '../utils/location.js'

const POLL_MS = 5000
const CATEGORIES = ['Estratégia', 'Família', 'Festa', 'Cooperativo', 'Cartas', 'Infantil']

function usePolling(load, deps) {
  useEffect(() => {
    let stopped = false
    let timer
    const tick = async () => {
      if (!document.hidden) await load().catch(() => {})
      if (!stopped) timer = setTimeout(tick, POLL_MS)
    }
    tick()
    return () => {
      stopped = true
      clearTimeout(timer)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps)
}

export default function Account({ section, notify }) {
  const { user, logout } = useAuth()
  const tabs = [
    ['locacoes', 'Minhas locações', '#/conta'],
    ['jogos', 'Meus jogos anunciados', '#/conta/jogos'],
    ['dados', 'Minha conta', '#/conta/dados'],
  ]
  return (
    <main className="wrap acct">
      <aside className="side">
        <div className="who">
          <b>{user.name}</b>
          <small>{user.email}</small>
        </div>
        {tabs.map(([id, label, href]) => (
          <a key={id} href={href} className={section === id ? 'on' : ''} aria-current={section === id ? 'page' : undefined}>
            {label}
          </a>
        ))}
        {user.isAdmin && (
          <a href="#/admin" className="side-admin">
            Área do administrador
          </a>
        )}
        <button
          type="button"
          className="side-out"
          onClick={() => {
            // Sai da área logada antes de encerrar a sessão, senão a rota manda para o login
            window.location.hash = '/'
            setTimeout(logout, 0)
          }}
        >
          Sair
        </button>
      </aside>
      <section>
        {section === 'jogos' ? <MyGames user={user} notify={notify} /> : section === 'dados' ? <Profile /> : <MyRentals user={user} notify={notify} />}
      </section>
    </main>
  )
}

function MyRentals({ user, notify }) {
  const [rentals, setRentals] = useState(null)
  const [tab, setTab] = useState('now')
  const [busy, setBusy] = useState('')

  const load = async () => {
    const data = await api.rental.listRentals({ renterEmail: user.email })
    setRentals(data.items.sort((a, b) => String(b.created_at).localeCompare(String(a.created_at))))
  }
  usePolling(load, [user.email])

  const active = (rentals || []).filter((r) => r.status === 'CONFIRMED')
  const past = (rentals || []).filter((r) => r.status !== 'CONFIRMED')
  const list = tab === 'now' ? active : past

  async function giveBack(rental) {
    setBusy(rental.rental_id)
    try {
      await api.rental.returnRental(rental.rental_id)
      notify(`Devolução de ${displayTitle(rental.game_title)} registrada. Obrigado!`)
      await load()
    } catch (err) {
      notify(err.message, 'error')
    } finally {
      setBusy('')
    }
  }

  return (
    <>
      <h1>Minhas locações</h1>
      <p className="lead">O que está com você agora e o que você já devolveu.</p>
      <div className="tabs-mini" role="tablist">
        <button type="button" role="tab" aria-selected={tab === 'now'} className={`f ${tab === 'now' ? 'on' : ''}`} onClick={() => setTab('now')}>
          Com você ({active.length})
        </button>
        <button type="button" role="tab" aria-selected={tab === 'past'} className={`f ${tab === 'past' ? 'on' : ''}`} onClick={() => setTab('past')}>
          Histórico ({past.length})
        </button>
      </div>
      {rentals === null && <div className="rental skeleton" />}
      {rentals !== null && list.length === 0 && (
        <div className="empty-state small">
          <h3>{tab === 'now' ? 'Nenhum jogo com você agora' : 'Nada no histórico ainda'}</h3>
          <p>Que tal escolher um jogo para a próxima partida?</p>
          <a className="btn btn-ink" href="#/">
            Ver jogos perto de mim
          </a>
        </div>
      )}
      {list.map((rental) => {
        const left = daysLeft(rental)
        const isActive = rental.status === 'CONFIRMED'
        const title = displayTitle(rental.game_title)
        return (
          <article className="rental" key={rental.rental_id}>
            <div className="th">
              <GameImage game={{ id: rental.game_id, title: rental.game_title }} title={title} crop />
            </div>
            <div>
              <h3>{title}</h3>
              <div className="meta">
                {rental.rental_days} {rental.rental_days === 1 ? 'dia' : 'dias'} · alugado em {shortDate(rental.created_at)}
                {!isActive && rental.returned_at && ` · devolvido em ${shortDate(rental.returned_at)}`}
              </div>
              {isActive && (
                <>
                  <div className="prog">
                    <i style={{ width: `${Math.min(100, Math.max(4, (1 - left / rental.rental_days) * 100))}%` }} />
                  </div>
                  <div className={`meta ${left < 0 ? 'late' : ''}`}>
                    {left > 1 ? `${left} dias restantes` : left === 1 ? 'Último dia: devolva até amanhã' : left === 0 ? 'Devolver hoje' : `Atrasado desde ${shortDate(dueDate(rental).toISOString())}`}
                  </div>
                </>
              )}
            </div>
            <div className="r">
              <span className={`pill ${isActive ? 'act' : 'done'}`}>{isActive ? 'Com você' : rental.status === 'CANCELLED' ? 'Cancelado' : 'Devolvido'}</span>
              <span className="price">{brl(rental.total_price)}</span>
              {isActive && (
                <button className="btn btn-line small" type="button" disabled={busy === rental.rental_id} onClick={() => giveBack(rental)}>
                  {busy === rental.rental_id ? 'Devolvendo…' : 'Devolver'}
                </button>
              )}
            </div>
          </article>
        )
      })}
    </>
  )
}

const EMPTY_FORM = { title: '', category: 'Estratégia', price_per_day: '', description: '', image_url: '' }

function MyGames({ user, notify }) {
  const [games, setGames] = useState(null)
  const [form, setForm] = useState(EMPTY_FORM)
  const [where, setWhere] = useState(null)
  const [cityText, setCityText] = useState('')
  const [locating, setLocating] = useState(false)
  const [locError, setLocError] = useState('')
  const [saving, setSaving] = useState(false)
  const [open, setOpen] = useState(false)
  const [imgOk, setImgOk] = useState(true)

  const load = async () => {
    const data = await api.catalog.listGames({ ownerId: user.id })
    setGames(data.items)
  }
  usePolling(load, [user.id])

  async function gps() {
    setLocating(true)
    setLocError('')
    try {
      const pos = await getGpsPosition()
      setWhere({ ...pos, label: 'Localização do GPS' })
    } catch (err) {
      setLocError(err.message)
    } finally {
      setLocating(false)
    }
  }

  async function submit(event) {
    event.preventDefault()
    let place = where
    if (!place && cityText) {
      const city = findCity(cityText)
      if (city) place = { lat: city.lat, lon: city.lon, label: city.label }
    }
    if (!place) {
      setLocError('Use o GPS ou escolha a cidade onde o jogo fica.')
      return
    }
    setSaving(true)
    try {
      await api.catalog.createGame({
        title: form.title.trim(),
        category: form.category,
        price_per_day: Number(form.price_per_day),
        description: form.description.trim(),
        image_url: form.image_url.trim() || undefined,
        owner_id: user.id,
        owner_name: user.name,
        latitude: place.lat,
        longitude: place.lon,
      })
      notify(`${form.title.trim()} já aparece no catálogo.`)
      setForm(EMPTY_FORM)
      setOpen(false)
      await load()
    } catch (err) {
      notify(err.message, 'error')
    } finally {
      setSaving(false)
    }
  }

  async function toggle(game) {
    const next = game.status === 'MAINTENANCE' ? 'AVAILABLE' : 'MAINTENANCE'
    try {
      await api.catalog.updateStatus(game.id, next)
      notify(next === 'AVAILABLE' ? `${displayTitle(game.title)} voltou ao catálogo.` : `${displayTitle(game.title)} foi pausado e não aparece para aluguel.`)
      await load()
    } catch (err) {
      notify(err.message, 'error')
    }
  }

  const citySuggestions = cityText && !where ? searchCities(cityText, 4) : []

  return (
    <>
      <div className="head-row">
        <div>
          <h1>Meus jogos</h1>
          <p className="lead">Anuncie os jogos da sua estante e pause quando quiser jogar.</p>
        </div>
        {!open && (
          <button className="btn btn-brick" type="button" onClick={() => setOpen(true)}>
            Anunciar um jogo
          </button>
        )}
      </div>

      {open && (
        <form className="lend-form" onSubmit={submit}>
          <div className="lend-grid">
            <div className="lend-fields">
              <label className="field wide">
                <span>Nome do jogo</span>
                <input value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} required placeholder="Ex.: Dixit" />
              </label>
              <label className="field">
                <span>Categoria</span>
                <select value={form.category} onChange={(e) => setForm({ ...form, category: e.target.value })}>
                  {CATEGORIES.map((c) => (
                    <option key={c}>{c}</option>
                  ))}
                </select>
              </label>
              <label className="field">
                <span>Preço por dia (R$)</span>
                <input type="number" min="1" step="0.5" value={form.price_per_day} onChange={(e) => setForm({ ...form, price_per_day: e.target.value })} required placeholder="15" />
              </label>
              <label className="field wide">
                <span>Descrição</span>
                <textarea rows="3" value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} required placeholder="Para quantas pessoas, quanto tempo dura, estado da caixa…" />
              </label>
              <label className="field wide">
                <span>Link da foto da caixa (opcional)</span>
                <input
                  type="url"
                  pattern="https?://.+"
                  value={form.image_url}
                  onChange={(e) => {
                    setImgOk(true)
                    setForm({ ...form, image_url: e.target.value })
                  }}
                  placeholder="https://…/foto.jpg"
                />
              </label>
              <div className="field wide">
                <span>Onde o jogo fica</span>
                <div className="where">
                  <button type="button" className="btn btn-line small" onClick={gps} disabled={locating}>
                    <Icon id="target" />
                    {locating ? 'Localizando…' : 'Usar meu GPS'}
                  </button>
                  <span className="or">ou</span>
                  <div className="city-mini">
                    <input
                      value={where ? where.label : cityText}
                      onChange={(e) => {
                        setWhere(null)
                        setCityText(e.target.value)
                      }}
                      placeholder="Cidade"
                      aria-label="Cidade onde o jogo fica"
                    />
                    {citySuggestions.length > 0 && (
                      <ul className="suggest open">
                        {citySuggestions.map((city) => (
                          <li
                            key={city.label}
                            onMouseDown={(e) => {
                              e.preventDefault()
                              setWhere({ lat: city.lat, lon: city.lon, label: city.label })
                              setLocError('')
                            }}
                          >
                            <span>{city.name}</span>
                            <small>{city.uf}</small>
                          </li>
                        ))}
                      </ul>
                    )}
                  </div>
                </div>
                <small className="hint">Quem busca vê só a distância até o jogo, nunca o seu endereço.</small>
                {locError && <p className="form-error">{locError}</p>}
              </div>
            </div>
            <div className="lend-preview">
              <span className="hint">Como vai aparecer</span>
              <div className="art">
                {form.image_url && imgOk ? (
                  <img className="photo" src={form.image_url} alt="" referrerPolicy="no-referrer" onError={() => setImgOk(false)} />
                ) : (
                  <GameImage game={{ id: 0, title: form.title || 'Seu jogo' }} title={form.title || 'Seu jogo'} />
                )}
              </div>
              <b>{form.title || 'Nome do jogo'}</b>
              <span className="meta">
                {form.category} · {form.price_per_day ? `${brl(form.price_per_day)}/dia` : 'preço por dia'}
              </span>
              {form.image_url && !imgOk && <p className="form-error">Não conseguimos abrir essa imagem. Confira o link.</p>}
            </div>
          </div>
          <div className="lend-actions">
            <button className="btn btn-ghost" type="button" onClick={() => setOpen(false)}>
              Cancelar
            </button>
            <button className="btn btn-brick" type="submit" disabled={saving}>
              {saving ? 'Publicando…' : 'Publicar anúncio'}
            </button>
          </div>
        </form>
      )}

      {games === null && <div className="rental skeleton" />}
      {games !== null && games.length === 0 && !open && (
        <div className="empty-state small">
          <h3>Você ainda não anunciou nenhum jogo</h3>
          <p>Leva um minuto: nome, preço por dia, uma foto e pronto.</p>
        </div>
      )}
      {(games || []).map((game) => {
        const title = displayTitle(game.title)
        return (
          <article className="rental" key={game.id}>
            <div className="th">
              <GameImage game={game} title={title} crop />
            </div>
            <div>
              <h3>{title}</h3>
              <div className="meta">
                {game.category} · {brl(game.price_per_day)}/dia
              </div>
            </div>
            <div className="r">
              <span className={`pill ${game.status === 'AVAILABLE' ? 'act' : game.status === 'RENTED' ? 'rented' : 'done'}`}>
                {game.status === 'RENTED' ? `Alugado${game.current_renter_name ? ` por ${game.current_renter_name.split(' ')[0]}` : ''}` : STATUS_LABEL[game.status]}
              </span>
              {game.status !== 'RENTED' && (
                <button className="btn btn-line small" type="button" onClick={() => toggle(game)}>
                  {game.status === 'MAINTENANCE' ? 'Reativar anúncio' : 'Pausar anúncio'}
                </button>
              )}
            </div>
          </article>
        )
      })}
    </>
  )
}

function Profile() {
  const { user, updateName, provider } = useAuth()
  const [name, setName] = useState(user.name)
  const [saved, setSaved] = useState(false)
  return (
    <>
      <h1>Minha conta</h1>
      <p className="lead">Seus dados de acesso ao Jogaí.</p>
      <form
        className="profile"
        onSubmit={(e) => {
          e.preventDefault()
          updateName(name.trim())
          setSaved(true)
        }}
      >
        <label className="field">
          <span>Nome</span>
          <input value={name} onChange={(e) => (setName(e.target.value), setSaved(false))} disabled={provider === 'cognito'} required />
        </label>
        <label className="field">
          <span>E-mail</span>
          <input value={user.email} disabled />
        </label>
        <div className="field">
          <span>Tipo de conta</span>
          <p className="plain">{user.isAdmin ? 'Administrador' : 'Cliente'}</p>
        </div>
        {provider !== 'cognito' && (
          <button className="btn btn-ink" type="submit">
            {saved ? 'Salvo' : 'Salvar'}
          </button>
        )}
      </form>
    </>
  )
}
