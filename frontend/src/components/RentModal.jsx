import { useEffect, useState } from 'react'
import GameImage from './BoxCover.jsx'
import { Icon } from './Brand.jsx'
import { brl, displayTitle, km, ownerShort } from '../utils/format.js'

export default function RentModal({ game, user, busy, onClose, onConfirm }) {
  const [days, setDays] = useState(2)
  const title = displayTitle(game.title)

  useEffect(() => {
    const onKey = (event) => event.key === 'Escape' && onClose()
    window.addEventListener('keydown', onKey)
    document.body.style.overflow = 'hidden'
    return () => {
      window.removeEventListener('keydown', onKey)
      document.body.style.overflow = ''
    }
  }, [onClose])

  return (
    <div className="overlay" onClick={onClose}>
      <div className="sheet" role="dialog" aria-modal="true" aria-labelledby="rent-title" onClick={(event) => event.stopPropagation()}>
        <button className="sheet-close" type="button" onClick={onClose} aria-label="Fechar">
          <Icon id="close" />
        </button>
        <div className="sheet-art">
          <GameImage game={game} title={title} />
        </div>
        <div className="sheet-body">
          <span className="meta">
            {game.category} · de {ownerShort(game.owner_name)}
            {game.distance_km !== undefined && ` · a ${km(game.distance_km)}`}
          </span>
          <h3 id="rent-title">{title}</h3>
          <p className="desc">{game.description}</p>

          <div className="days">
            <span>Quantos dias?</span>
            <div className="stepper">
              <button type="button" onClick={() => setDays((d) => Math.max(1, d - 1))} aria-label="Menos um dia">
                −
              </button>
              <strong>{days}</strong>
              <button type="button" onClick={() => setDays((d) => Math.min(30, d + 1))} aria-label="Mais um dia">
                +
              </button>
            </div>
          </div>

          <div className="sheet-total">
            <span>
              {brl(game.price_per_day)} × {days} {days === 1 ? 'dia' : 'dias'}
            </span>
            <strong>{brl(game.price_per_day * days)}</strong>
          </div>

          <button className="btn btn-brick wide" type="button" disabled={busy} onClick={() => onConfirm(days)}>
            {busy ? 'Reservando…' : user ? 'Confirmar aluguel' : 'Entrar para alugar'}
          </button>
          {user && <p className="fine">A reserva fica no nome de {user.name} ({user.email}).</p>}
        </div>
      </div>
    </div>
  )
}
