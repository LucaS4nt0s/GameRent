const CATALOG = import.meta.env.VITE_CATALOG_URL || '/api/catalog'
const RENTAL = import.meta.env.VITE_RENTAL_URL || '/api/rental'

// Token do Cognito (id_token) quando o login real estiver ligado; os serviços podem validá-lo depois.
let authToken = null
export function setAuthToken(token) {
  authToken = token
}

function withAuth(options = {}) {
  if (!authToken) return options
  return { ...options, headers: { ...(options.headers || {}), Authorization: `Bearer ${authToken}` } }
}

function readMeta(res) {
  const latency = res.headers.get('X-DB-Read-Latency-Ms')
  const lamport = res.headers.get('X-Lamport-Clock')
  return {
    consistency_mode: res.headers.get('X-Consistency-Mode') || 'strong',
    db_read_latency_ms: latency === null ? null : Number(latency),
    served_by_node: res.headers.get('X-Served-By-Node') || '',
    lamport_clock: lamport === null ? null : Number(lamport),
  }
}

async function parseBody(res) {
  const text = await res.text()
  if (!text) return null
  try {
    return JSON.parse(text)
  } catch {
    return text
  }
}

function errorMessage(body, status) {
  if (body && body.detail) {
    return typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail)
  }
  return `Erro HTTP ${status}`
}

async function request(url, options) {
  const res = await fetch(url, withAuth(options))
  const body = await parseBody(res)
  if (!res.ok) {
    const error = new Error(errorMessage(body, res.status))
    error.status = res.status
    error.body = body
    error.meta = readMeta(res)
    throw error
  }
  return { body, meta: readMeta(res), status: res.status }
}

async function requestData(url, options) {
  return (await request(url, options)).body
}

function query(params) {
  const search = new URLSearchParams()
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== '') {
      search.set(key, String(value))
    }
  })
  const text = search.toString()
  return text ? `?${text}` : ''
}

export const api = {
  catalog: {
    health: () => requestData(`${CATALOG}/health`),
    discovery: () => requestData(`${CATALOG}/discovery`),
    listGames: async ({ consistency = 'strong', status, category, ownerId } = {}) => {
      const response = await request(
        `${CATALOG}/games${query({
          consistency,
          status_filter: status,
          category,
          owner_id: ownerId,
        })}`
      )
      const items = Array.isArray(response.body) ? response.body : []
      const first = items[0] || {}
      return {
        items,
        meta: {
          consistency_mode: first.consistency_mode || response.meta.consistency_mode,
          db_read_latency_ms:
            first.db_read_latency_ms ?? response.meta.db_read_latency_ms,
          served_by_node: first.served_by_node || response.meta.served_by_node,
          lamport_clock: response.meta.lamport_clock,
        },
      }
    },
    getGame: (id) => requestData(`${CATALOG}/games/${id}`),
    nearby: async ({ lat, lon, maxKm = 10, consistency = 'strong' } = {}) => {
      const response = await request(
        `${CATALOG}/games/nearby${query({
          lat,
          lon,
          max_km: maxKm,
          consistency,
        })}`
      )
      const items = Array.isArray(response.body) ? response.body : []
      const first = items[0] || {}
      return {
        items,
        meta: {
          consistency_mode: first.consistency_mode || response.meta.consistency_mode,
          db_read_latency_ms:
            first.db_read_latency_ms ?? response.meta.db_read_latency_ms,
          served_by_node: first.served_by_node || response.meta.served_by_node,
          lamport_clock: response.meta.lamport_clock,
        },
      }
    },
    createGame: (payload) =>
      requestData(`${CATALOG}/games`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      }),
    updateStatus: (id, status) =>
      requestData(`${CATALOG}/games/${id}/status`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ status }),
      }),
  },
  rental: {
    health: () => requestData(`${RENTAL}/health`),
    discovery: () => requestData(`${RENTAL}/discovery`),
    listRentals: async ({ renterEmail, gameId, status } = {}) => {
      const response = await request(
        `${RENTAL}/rentals${query({
          renter_email: renterEmail,
          game_id: gameId,
          status,
        })}`
      )
      return {
        items: Array.isArray(response.body) ? response.body : [],
        meta: response.meta,
      }
    },
    createRental: async (payload) => {
      const response = await request(`${RENTAL}/rentals`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      })
      return { ...response.body, _meta: response.meta }
    },
    createRentalRaw: async (payload) => {
      const res = await fetch(
        `${RENTAL}/rentals`,
        withAuth({
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        })
      )
      const body = await parseBody(res)
      return {
        ok: res.ok,
        status: res.status,
        body,
        error: res.ok ? null : errorMessage(body, res.status),
        meta: readMeta(res),
      }
    },
    returnRental: (id) =>
      requestData(`${RENTAL}/rentals/${id}/return`, { method: 'POST' }),
  },
}
