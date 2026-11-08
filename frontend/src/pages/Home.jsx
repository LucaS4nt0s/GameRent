import { useEffect, useMemo, useState } from 'react'
import { api } from '../api.js'
import BoxStory from '../components/BoxStory.jsx'
import CitySearch from '../components/CitySearch.jsx'
import GameCard from '../components/GameCard.jsx'
import Reveal from '../components/Reveal.jsx'
import Steps from '../components/Steps.jsx'
import { Logo } from '../components/Brand.jsx'
import { navigate } from '../router.js'

const POLL_MS = 5000

export default function Home({ loc, onRent, refreshKey }) {
  const { location } = loc
  const [radius, setRadius] = useState(10)
  const [games, setGames] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [category, setCategory] = useState('Todos')

  useEffect(() => {
    let stopped = false
    let timer
    async function load(first) {
      if (!first && document.hidden) {
        timer = setTimeout(() => load(false), POLL_MS)
        return
      }
      if (first) setLoading(true)
      try {
        const data = await api.catalog.nearby({ lat: location.lat, lon: location.lon, maxKm: radius })
        if (!stopped) {
          setGames(data.items)
          setError('')
        }
      } catch (err) {
        if (!stopped && first) setError('Não conseguimos carregar o catálogo agora. Tente de novo em instantes.')
      } finally {
        if (!stopped && first) setLoading(false)
        if (!stopped) timer = setTimeout(() => load(false), POLL_MS)
      }
    }
    load(true)
    return () => {
      stopped = true
      clearTimeout(timer)
    }
  }, [location.lat, location.lon, radius, refreshKey])

  const categories = useMemo(() => ['Todos', ...new Set(games.map((g) => g.category))], [games])
  // Disponíveis primeiro (mantendo a ordem por distância), para o destaque ser um jogo alugável
  const shown = (category === 'Todos' ? games : games.filter((g) => g.category === category))
    .map((g, i) => [g, i])
    .sort(([a, i], [b, j]) => (a.status === 'AVAILABLE' ? 0 : 1) - (b.status === 'AVAILABLE' ? 0 : 1) || i - j)
    .map(([g]) => g)
  const available = games.filter((g) => g.status === 'AVAILABLE').length
  const city = location.source === 'gps' ? `perto de ${location.label}` : `em ${location.label.split(',')[0]}`

  useEffect(() => {
    if (!categories.includes(category)) setCategory('Todos')
  }, [categories, category])

  return (
    <>
      <BoxStory cityLabel={location.label.split(',')[0]} onFindGames={() => document.getElementById('buscar')?.scrollIntoView({ behavior: 'smooth' })} />

      <section className="search-band" id="buscar">
        <div className="wrap">
          <Reveal className="search-card">
            <div>
              <span className="kicker on-dark">Busca por cidade</span>
              <h2>
                Em que cidade é <em>a mesa</em> hoje?
              </h2>
              <p className="search-sub">Use o GPS do celular ou escolha a cidade. Mostramos só a distância, nunca o endereço de quem aluga.</p>
            </div>
            <CitySearch
              location={location}
              locating={loc.locating}
              gpsError={loc.gpsError}
              onGps={loc.useGps}
              onCity={loc.useCity}
              radius={radius}
              onRadius={setRadius}
              onSearch={() => document.getElementById('catalogo')?.scrollIntoView({ behavior: 'smooth' })}
            />
          </Reveal>
        </div>
      </section>

      <section className="wrap" id="catalogo">
        <Reveal className="sec-head">
          <div>
            <span className="kicker">
              {loading ? 'Procurando jogos…' : `${available} ${available === 1 ? 'jogo disponível' : 'jogos disponíveis'} ${city}`}
            </span>
            <h2>Perto de você, até {radius} km</h2>
          </div>
          {categories.length > 2 && (
            <div className="filters" role="tablist" aria-label="Categoria">
              {categories.map((c) => (
                <button key={c} type="button" role="tab" aria-selected={category === c} className={`f ${category === c ? 'on' : ''}`} onClick={() => setCategory(c)}>
                  {c}
                </button>
              ))}
            </div>
          )}
        </Reveal>

        {error && <p className="empty">{error}</p>}
        {!error && !loading && shown.length === 0 && (
          <div className="empty-state">
            <h3>Nenhum jogo nesse raio ainda</h3>
            <p>Aumente a distância ou tente outra cidade. Se você tem jogos parados, que tal ser o primeiro a anunciar por aqui?</p>
            <div className="empty-actions">
              {radius < 50 && (
                <button className="btn btn-ink" type="button" onClick={() => setRadius(50)}>
                  Buscar até 50 km
                </button>
              )}
              <a className="btn btn-line" href="#/conta/jogos">
                Anunciar meu jogo
              </a>
            </div>
          </div>
        )}
        {loading && games.length === 0 && (
          <div className="grid">
            {Array.from({ length: 4 }, (_, i) => (
              <div className="game skeleton" key={i} />
            ))}
          </div>
        )}
        {shown.length > 0 && (
          <div className="grid">
            {shown.map((game, i) => (
              <GameCard key={game.id} game={game} featured={i === 0 && shown.length >= 4} delay={(i % 4) * 0.07} onRent={onRent} />
            ))}
          </div>
        )}
      </section>

      <Steps />

      <section className="wrap">
        <Reveal className="cta-band" id="anunciar">
          <h2>Tem jogo parado na estante? Deixe outra mesa jogar e ganhe com isso.</h2>
          <button className="btn" type="button" onClick={() => navigate('/conta/jogos')}>
            Anunciar meu jogo
          </button>
          <div className="meeples" aria-hidden="true">
            {[0, 1, 2].map((i) => (
              <svg key={i} width="60" height="60">
                <use href="#meeple" />
              </svg>
            ))}
          </div>
        </Reveal>
        <footer className="site-footer">
          <div>
            <Logo />
            <p>Aluguel de jogos de tabuleiro entre pessoas da mesma cidade. Projeto de Sistemas Distribuídos, Unicamp, 2026.</p>
          </div>
          <div>
            <b>Alugar</b>
            <a href="#/" onClick={(e) => (e.preventDefault(), document.getElementById('catalogo')?.scrollIntoView({ behavior: 'smooth' }))}>
              Catálogo
            </a>
            <a href="#/" onClick={(e) => (e.preventDefault(), document.getElementById('como')?.scrollIntoView({ behavior: 'smooth' }))}>
              Como funciona
            </a>
          </div>
          <div>
            <b>Anunciar</b>
            <a href="#/conta/jogos">Anunciar um jogo</a>
            <a href="#/conta/jogos">Meus jogos</a>
          </div>
          <div>
            <b>Conta</b>
            <a href="#/conta">Minhas locações</a>
            <a href="#/conta/dados">Minha conta</a>
          </div>
        </footer>
      </section>
    </>
  )
}
