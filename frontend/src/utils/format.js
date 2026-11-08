export const STATUS_LABEL = {
  AVAILABLE: 'Disponível',
  RENTED: 'Alugado',
  MAINTENANCE: 'Em pausa',
}

export function brl(value) {
  return Number(value || 0).toLocaleString('pt-BR', { style: 'currency', currency: 'BRL' })
}

export function km(value) {
  const n = Number(value || 0)
  if (n < 1) return `${Math.max(100, Math.round((n * 1000) / 100) * 100)} m`
  return `${n.toLocaleString('pt-BR', { maximumFractionDigits: 1 })} km`
}

export function shortDate(iso) {
  if (!iso) return ''
  return new Date(iso).toLocaleDateString('pt-BR', { day: '2-digit', month: 'short' })
}

export function dueDate(rental) {
  const start = new Date(rental.created_at)
  start.setDate(start.getDate() + Number(rental.rental_days || 0))
  return start
}

export function daysLeft(rental) {
  const ms = dueDate(rental).getTime() - Date.now()
  return Math.ceil(ms / 86400000)
}

export function firstName(name = '') {
  return String(name).trim().split(/\s+/)[0] || ''
}

export function initials(name = '') {
  return (
    String(name)
      .replace(/[^\p{L}\p{N} ]/gu, '')
      .split(/\s+/)
      .filter(Boolean)
      .slice(0, 2)
      .map((word) => word[0].toUpperCase())
      .join('') || 'J'
  )
}

// Nome curto do dono para o cliente ("Ana Paula Souza" -> "Ana P.")
export function ownerShort(name = '') {
  const parts = String(name).trim().split(/\s+/)
  if (parts.length < 2) return parts[0] || ''
  return `${parts[0]} ${parts[1][0]}.`
}

// Título mais limpo para a vitrine: "Catan (Os Colonizadores de Catan)" -> "Catan"
export function displayTitle(title = '') {
  return String(title).replace(/\s*\(.*\)\s*$/, '').trim() || title
}
