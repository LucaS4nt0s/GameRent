const CATALOG = import.meta.env.VITE_CATALOG_URL || '/api/catalog'
const RENTAL = import.meta.env.VITE_RENTAL_URL || '/api/rental'

async function request(url, options) {
  const res = await fetch(url, options)
  const text = await res.text()
  let body = null
  try {
    body = text ? JSON.parse(text) : null
  } catch {
    body = text
  }

  if (!res.ok) {
    const detail = body && body.detail ? body.detail : `Erro HTTP ${res.status}`
    throw new Error(detail)
  }
  return body
}

export const api = {
  catalog: {
    health: () => request(`${CATALOG}/health`),
    listGames: () => request(`${CATALOG}/games`),
    getGame: (id) => request(`${CATALOG}/games/${id}`),
    nearby: (lat, lon, maxKm) =>
      request(`${CATALOG}/games/nearby?lat=${lat}&lon=${lon}&max_km=${maxKm}`),
  },
  rental: {
    health: () => request(`${RENTAL}/health`),
    listRentals: () => request(`${RENTAL}/rentals`),
    createRental: (payload) =>
      request(`${RENTAL}/rentals`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      }),
    returnRental: (id) => request(`${RENTAL}/rentals/${id}/return`, { method: 'POST' }),
  },
}
