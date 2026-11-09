import { useEffect, useMemo, useState } from 'react'
import { api } from '../api.js'
import { STATUS_LABEL, brl } from '../utils/format.js'

/*
 * Área do administrador: o Laboratório de Sistemas Distribuídos da apresentação.
 * Aqui (e só aqui) aparecem URN, relógio de Lamport, versão, nó que atendeu e modo de consistência.
 */
const DISCOVERY_POLL_MS = 5000
const TABS = [
  ['sim', 'Disputa concorrente'],
  ['discovery', 'Service discovery'],
  ['bench', 'Forte × Eventual'],
  ['acervo', 'Acervo (técnico)'],
]

function modeLabel(mode) {
  return mode === 'eventual' ? 'Eventual' : 'Forte'
}

function shortError(value) {
  if (!value) return ''
  return typeof value === 'string' ? value : JSON.stringify(value)
}

export default function Admin({ notify }) {
  const [tab, setTab] = useState('sim')
  const [consistency, setConsistency] = useState('strong')
  const [games, setGames] = useState([])
  const [meta, setMeta] = useState(null)
  const [health, setHealth] = useState({ catalog: null, rental: null })

  async function loadGames(mode = consistency) {
    const data = await api.catalog.listGames({ consistency: mode })
    setGames(data.items)
    setMeta(data.meta)
    return data
  }

  useEffect(() => {
    let stopped = false
    let timer
    const tick = async () => {
      if (!document.hidden) {
        const [catalog, rental] = await Promise.allSettled([api.catalog.health(), api.rental.health(), loadGames().catch(() => {})])
        if (!stopped)
          setHealth({
            catalog: catalog.status === 'fulfilled' ? catalog.value.status : 'DOWN',
            rental: rental.status === 'fulfilled' ? rental.value.status : 'DOWN',
          })
      }
      if (!stopped) timer = setTimeout(tick, 3000)
    }
    tick()
    return () => {
      stopped = true
      clearTimeout(timer)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [consistency])

  return (
    <main className="wrap adm-in">
      <div className="adm-head">
        <div>
          <h1>Laboratório de Sistemas Distribuídos</h1>
          <p className="lead">Só para o grupo admin. URN, Lamport, réplicas e modos de consistência ficam aqui.</p>
        </div>
        <div className="adm-status">
          <span className={`dot ${health.catalog === 'HEALTHY' ? 'ok' : health.catalog ? 'down' : ''}`} /> catalog-service
          <span className={`dot ${health.rental === 'HEALTHY' ? 'ok' : health.rental ? 'down' : ''}`} /> rental-service
          <label className="mode-select">
            Leitura
            <select value={consistency} onChange={(e) => setConsistency(e.target.value)}>
              <option value="strong">Forte (strong)</option>
              <option value="eventual">Eventual (eventual)</option>
            </select>
          </label>
        </div>
      </div>
      <div className="adm-tabs" role="tablist">
        {TABS.map(([id, label]) => (
          <button key={id} type="button" role="tab" aria-selected={tab === id} className={tab === id ? 'on' : ''} onClick={() => setTab(id)}>
            {label}
          </button>
        ))}
      </div>
      {tab === 'sim' && <Simulator games={games} reload={loadGames} notify={notify} />}
      {tab === 'discovery' && <Discovery />}
      {tab === 'bench' && <Benchmark notify={notify} />}
      {tab === 'acervo' && <Inventory games={games} meta={meta} reload={loadGames} notify={notify} />}
    </main>
  )
}

function Simulator({ games, reload, notify }) {
  const [gameId, setGameId] = useState('')
  const [running, setRunning] = useState(false)
  const [results, setResults] = useState([])
  const available = useMemo(() => games.filter((g) => g.status === 'AVAILABLE'), [games])
  const selected = games.find((g) => String(g.id) === String(gameId))
  const winners = results.filter((r) => r.status === 201).length
  const conflicts = results.filter((r) => r.status === 409).length
  const failures = results.length - winners - conflicts
  const clocks = results.map((r) => r.meta?.lamport_clock).filter((c) => c !== null && c !== undefined)

  async function run() {
    const game = selected && selected.status === 'AVAILABLE' ? selected : available[0]
    if (!game) {
      notify('Nenhum jogo disponível para simular. Cadastre ou devolva um jogo primeiro.', 'error')
      return
    }
    setGameId(String(game.id))
    setRunning(true)
    setResults([])
    try {
      const settled = await Promise.allSettled(
        Array.from({ length: 10 }, (_, i) =>
          api.rental.createRentalRaw({
            game_id: game.id,
            renter_name: `Locatário Simultâneo ${i + 1}`,
            renter_email: `simulador${i + 1}@gamerent.test`,
            rental_days: 1,
          })
        )
      )
      setResults(
        settled.map((r, i) => ({
          index: i + 1,
          ...(r.status === 'fulfilled' ? r.value : { ok: false, status: 'NETWORK', error: r.reason?.message || 'Falha de rede', meta: null }),
        }))
      )
      await reload()
    } finally {
      setRunning(false)
    }
  }

  return (
    <div className="adm-grid">
      <div className="panel">
        <div className="panel-top">
          <div>
            <b>10 reservas simultâneas</b>
            <p className="muted">Dispara 10 POST /rentals para o mesmo jogo via Promise.all. A exclusão mútua deve produzir 1 vencedor e 9 conflitos.</p>
          </div>
        </div>
        <div className="sim-controls">
          <select value={gameId} onChange={(e) => setGameId(e.target.value)} aria-label="Jogo alvo">
            <option value="">Primeiro jogo disponível</option>
            {games.map((g) => (
              <option key={g.id} value={g.id} disabled={g.status !== 'AVAILABLE'}>
                #{g.id} {g.title} ({STATUS_LABEL[g.status] || g.status})
              </option>
            ))}
          </select>
          <button className="adm-btn" type="button" onClick={run} disabled={running}>
            {running ? 'Disparando…' : results.length ? 'Disparar de novo' : 'Disparar 10 reservas'}
          </button>
        </div>
        {selected && <p className="mono muted">alvo {selected.urn}</p>}
        {results.length > 0 && (
          <>
            <div className="reqs">
              {results.map((r) => (
                <div key={r.index} className={`req ${r.status === 201 ? 'win' : 'lose'}`} style={{ '--i': r.index - 1 }} title={r.status === 201 ? `Locação ${String(r.body?.rental_id || '').slice(0, 8)}` : shortError(r.error)}>
                  <b>{r.status}</b>
                  <span className="mono muted">req #{r.index}</span>
                  <span className="mono muted">L {r.meta?.lamport_clock ?? '—'}</span>
                </div>
              ))}
            </div>
            <p className="mono muted sum">
              {winners} × 201 Created · {conflicts} × 409 Conflict{failures > 0 ? ` · ${failures} × outro erro` : ''}
              {clocks.length > 0 && ` · Lamport ${Math.min(...clocks)} → ${Math.max(...clocks)}`}
            </p>
          </>
        )}
      </div>
      <div className="panel">
        <b>Como ler</b>
        <ul className="explain">
          <li>
            <span className="tagc win">201</span> a única requisição que conseguiu a trava condicional no DynamoDB (ou o lock do serviço).
          </li>
          <li>
            <span className="tagc lose">409</span> requisições que chegaram com o jogo já reservado: o catálogo recusa sem criar locação.
          </li>
          <li>O relógio de Lamport de cada resposta mostra a ordem causal dos eventos entre os serviços.</li>
          <li>Para repetir, devolva a locação vencedora em Minha conta ou escolha outro jogo disponível.</li>
        </ul>
      </div>
    </div>
  )
}

function DlItem({ term, value, mono }) {
  return (
    <>
      <dt>{term}</dt>
      <dd className={mono ? 'mono' : undefined}>{value ?? '—'}</dd>
    </>
  )
}

function Discovery() {
  const [state, setState] = useState({ catalog: null, rental: null, errors: {}, updatedAt: null })

  useEffect(() => {
    let stopped = false
    let timer
    const tick = async () => {
      const [catalog, rental] = await Promise.allSettled([api.catalog.discovery(), api.rental.discovery()])
      if (stopped) return
      setState({
        catalog: catalog.status === 'fulfilled' ? catalog.value : null,
        rental: rental.status === 'fulfilled' ? rental.value : null,
        errors: {
          catalog: catalog.status === 'rejected' ? catalog.reason.message : null,
          rental: rental.status === 'rejected' ? rental.reason.message : null,
        },
        updatedAt: new Date(),
      })
      timer = setTimeout(tick, DISCOVERY_POLL_MS)
    }
    tick()
    return () => {
      stopped = true
      clearTimeout(timer)
    }
  }, [])

  return (
    <>
      <p className="mono muted live">{state.updatedAt ? `ao vivo · atualizado às ${state.updatedAt.toLocaleTimeString('pt-BR')}` : 'consultando /discovery…'}</p>
      <div className="adm-grid even">
        {[
          ['catalog-service', state.catalog, state.errors.catalog],
          ['rental-service', state.rental, state.errors.rental],
        ].map(([title, data, error]) => (
          <div className="panel" key={title}>
            <b>{title}</b>
            {error && <p className="form-error">{error}</p>}
            {!error && !data && <p className="muted">Sem dados de discovery.</p>}
            {data && (
              <dl className="kv">
                <DlItem term="URN do nó" value={data.node_urn} mono />
                <DlItem term="Instância" value={data.instance_id} mono />
                <DlItem term="Hostname DNS" value={data.dns_target} mono />
                <DlItem term="Resolução DNS" value={data.dns_resolution?.status} />
                <DlItem term="IP resolvido" value={(data.dns_resolution?.resolved_ips || []).join(', ') || '—'} mono />
                <DlItem term="Lamport" value={data.lamport_clock} mono />
                <DlItem term="DynamoDB" value={data.dynamodb ? `${data.dynamodb.mode} · ${data.dynamodb.table_name}` : '—'} />
              </dl>
            )}
          </div>
        ))}
      </div>
    </>
  )
}

function Benchmark({ notify }) {
  const [running, setRunning] = useState(false)
  const [result, setResult] = useState(null)

  async function run() {
    setRunning(true)
    try {
      const runs = { strong: [], eventual: [] }
      let source = 'db_read_latency_ms'
      const warmup = await api.catalog.listGames({ consistency: 'eventual' })
      if (warmup.meta.db_read_latency_ms === null) source = 'tempo_total'
      const order = Array.from({ length: 5 }, (_, i) => (i % 2 === 0 ? ['strong', 'eventual'] : ['eventual', 'strong'])).flat()
      for (const mode of order) {
        const started = performance.now()
        const data = await api.catalog.listGames({ consistency: mode })
        const elapsed = performance.now() - started
        const db = data.meta.db_read_latency_ms
        if (db === null) source = 'tempo_total'
        runs[mode].push({ latency: db ?? elapsed, node: data.meta.served_by_node })
      }
      const sum = (mode) => ({
        mode,
        runs: runs[mode],
        avg: runs[mode].reduce((s, r) => s + r.latency, 0) / runs[mode].length,
        node: runs[mode][0]?.node || '',
      })
      setResult({ strong: sum('strong'), eventual: sum('eventual'), source })
    } catch (err) {
      notify(err.message, 'error')
    } finally {
      setRunning(false)
    }
  }

  const max = result ? Math.max(result.strong.avg, result.eventual.avg) || 1 : 1
  return (
    <div className="panel">
      <div className="panel-top">
        <div>
          <b>Comparador de consistência</b>
          <p className="muted">5 leituras em cada modo, alternando a ordem, e a latência média de leitura do banco.</p>
        </div>
        <button className="adm-btn" type="button" onClick={run} disabled={running}>
          {running ? 'Executando leituras…' : 'Comparar Forte × Eventual'}
        </button>
      </div>
      {result && (
        <>
          <div className="bars">
            {['strong', 'eventual'].map((mode) => (
              <div className="bar" key={mode}>
                <label>
                  <span>
                    Leitura {modeLabel(mode).toLowerCase()} <span className="mono muted">· {result[mode].node}</span>
                  </span>
                  <span className="mono">{result[mode].avg.toFixed(2)} ms</span>
                </label>
                <div>
                  <i style={{ width: `${(result[mode].avg / max) * 100}%`, background: mode === 'strong' ? 'var(--brick)' : '#4F8A63' }} />
                </div>
                <div className="runs mono muted">{result[mode].runs.map((r) => r.latency.toFixed(2)).join(' · ')} ms</div>
              </div>
            ))}
          </div>
          <p className="muted">
            Diferença média de <b className="mono">{Math.abs(result.strong.avg - result.eventual.avg).toFixed(2)} ms</b> a favor da leitura{' '}
            {result.strong.avg <= result.eventual.avg ? 'forte' : 'eventual'}. Fonte:{' '}
            {result.source === 'db_read_latency_ms' ? 'latência de leitura do banco (X-DB-Read-Latency-Ms)' : 'tempo total da requisição'}.
          </p>
        </>
      )}
    </div>
  )
}

function Inventory({ games, meta, reload, notify }) {
  async function toggle(game) {
    const next = game.status === 'MAINTENANCE' ? 'AVAILABLE' : 'MAINTENANCE'
    try {
      const data = await api.catalog.updateStatus(game.id, next)
      notify(`Status de "${data.title}" alterado para ${STATUS_LABEL[data.status]} (v${data.version}).`)
      await reload()
    } catch (err) {
      notify(err.message, 'error')
    }
  }
  async function endRental(game) {
    if (!game.current_rental_id) {
      notify('Esse jogo está alugado, mas o catálogo não informa qual locação. Use a liberação forçada.', 'error')
      return
    }
    try {
      await api.rental.returnRental(game.current_rental_id)
      notify(`Locação de "${game.title}" encerrada e jogo liberado.`)
      await reload()
    } catch (err) {
      notify(err.message, 'error')
    }
  }
  return (
    <div className="panel">
      {meta && (
        <p className="mono muted">
          consistência {modeLabel(meta.consistency_mode)} · leitura {meta.db_read_latency_ms ?? '—'} ms · served_by_node {meta.served_by_node || '—'} · Lamport {meta.lamport_clock ?? '—'}
        </p>
      )}
      <div className="table-wrap">
        <table className="tech">
          <thead>
            <tr>
              <th>Jogo</th>
              <th>URN</th>
              <th>Dono</th>
              <th>Preço</th>
              <th>Status</th>
              <th>v</th>
              <th>Lamport</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {games.map((g) => (
              <tr key={g.id}>
                <td>
                  #{g.id} {g.title}
                </td>
                <td className="mono">{g.urn}</td>
                <td>
                  {g.owner_name} <span className="mono muted">{g.owner_id}</span>
                </td>
                <td>{brl(g.price_per_day)}</td>
                <td>
                  <span className={`st ${g.status}`}>{STATUS_LABEL[g.status]}</span>
                </td>
                <td className="mono">{g.version}</td>
                <td className="mono">{g.lamport_clock}</td>
                <td>
                  {g.status === 'RENTED' ? (
                    <button type="button" className="link-btn" onClick={() => endRental(g)}>
                      Encerrar locação
                    </button>
                  ) : (
                    <button type="button" className="link-btn" onClick={() => toggle(g)}>
                      {g.status === 'MAINTENANCE' ? 'Liberar' : 'Manutenção'}
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
