import GameImage from './BoxCover.jsx'
import Reveal from './Reveal.jsx'
import { Icon } from './Brand.jsx'
import { brl, displayTitle, km, ownerShort } from '../utils/format.js'

export default function GameCard({ game, featured = false, delay = 0, onRent, myRental, onReturn, returning = '' }) {
  const title = displayTitle(game.title)
  const available = game.status === 'AVAILABLE'
  const withMe = Boolean(myRental)
  return (
    <Reveal as="article" className={`game ${featured ? 'feature' : ''} ${available || withMe ? '' : 'out'} ${withMe ? 'mine' : ''}`} delay={delay}>
      <div className="art">
        <GameImage game={game} title={title} />
        {game.distance_km !== undefined && (
          <span className="dist">
            <Icon id="pin" />a {km(game.distance_km)}
          </span>
        )}
        {withMe ? (
          <span className="state mine">Com você</span>
        ) : (
          !available && <span className="state">{game.status === 'RENTED' ? 'Alugado' : 'Em pausa'}</span>
        )}
      </div>
      <div className="game-b">
        <h3>{title}</h3>
        <span className="meta">
          {game.category} · de {ownerShort(game.owner_name)}
        </span>
        {featured && <p className="desc">{game.description}</p>}
        <div className="row">
          <span className="price">
            {brl(game.price_per_day)} <small>/dia</small>
          </span>
          {withMe ? (
            <button
              className="rent give-back"
              type="button"
              disabled={returning === myRental.rental_id}
              onClick={() => onReturn(myRental)}
            >
              {returning === myRental.rental_id ? 'Devolvendo…' : 'Devolver'}
            </button>
          ) : (
            <button className="rent" type="button" disabled={!available} onClick={() => onRent(game)}>
              {available ? 'Alugar' : 'Indisponível'}
            </button>
          )}
        </div>
      </div>
    </Reveal>
  )
}
