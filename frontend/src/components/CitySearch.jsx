import { useState } from 'react'
import { findCity, searchCities } from '../data/cities.js'
import { Icon } from './Brand.jsx'

export const RADII = [5, 10, 25, 50]

export default function CitySearch({ location, locating, gpsError, onGps, onCity, radius, onRadius, onSearch, dark = true }) {
  const [text, setText] = useState(location.source === 'gps' ? '' : location.label)
  const [open, setOpen] = useState(false)
  const [active, setActive] = useState(0)
  const [error, setError] = useState('')
  const hits = searchCities(text)

  function pick(city) {
    setText(city.label)
    setOpen(false)
    setError('')
    onCity(city)
  }

  function submit(event) {
    event.preventDefault()
    if (text.trim()) {
      const city = hits[active] || findCity(text)
      if (!city) {
        setError('Não encontramos essa cidade. Escolha uma das sugestões.')
        return
      }
      pick(city)
    }
    onSearch?.()
  }

  return (
    <form className={`search-form ${dark ? '' : 'light'}`} onSubmit={submit} role="search">
      <div className="city-input">
        <Icon id="pin" />
        <input
          value={text}
          onChange={(event) => {
            setText(event.target.value)
            setActive(0)
            setOpen(true)
            setError('')
          }}
          onFocus={(event) => {
            event.target.select()
            setOpen(true)
          }}
          onBlur={() => setTimeout(() => setOpen(false), 150)}
          onKeyDown={(event) => {
            if (!open || !hits.length) return
            if (event.key === 'ArrowDown') {
              event.preventDefault()
              setActive((i) => Math.min(hits.length - 1, i + 1))
            } else if (event.key === 'ArrowUp') {
              event.preventDefault()
              setActive((i) => Math.max(0, i - 1))
            }
          }}
          placeholder={location.source === 'gps' ? `Perto de ${location.label}` : 'Digite sua cidade'}
          aria-label="Cidade"
          autoComplete="off"
          role="combobox"
          aria-expanded={open && hits.length > 0}
          aria-controls="city-suggest"
        />
        {open && hits.length > 0 && (
          <ul className="suggest open" id="city-suggest" role="listbox">
            {hits.map((city, i) => (
              <li
                key={city.label}
                role="option"
                aria-selected={i === active}
                className={i === active ? 'act' : ''}
                onMouseDown={(event) => {
                  event.preventDefault()
                  pick(city)
                }}
              >
                <span>{city.name}</span>
                <small>{city.uf}</small>
              </li>
            ))}
          </ul>
        )}
      </div>
      <div className="search-row">
        <div className="radius" role="group" aria-label="Distância máxima">
          <span>Até</span>
          {RADII.map((value) => (
            <button key={value} type="button" className={`chip ${radius === value ? 'on' : ''}`} onClick={() => onRadius(value)}>
              {value} km
            </button>
          ))}
        </div>
        <button className="btn btn-brick" type="submit">
          Buscar jogos
        </button>
      </div>
      <button
        className="geo"
        type="button"
        disabled={locating}
        onClick={async () => {
          const ok = await onGps()
          if (ok) {
            setText('')
            onSearch?.()
          }
        }}
      >
        <Icon id="target" />
        {locating ? 'Localizando…' : location.source === 'gps' ? `Usando sua localização (${location.label})` : 'Usar minha localização'}
      </button>
      {(error || gpsError) && <p className="form-error">{error || gpsError}</p>}
    </form>
  )
}
