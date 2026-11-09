import { useCallback, useEffect, useState } from 'react'
import { DEFAULT_CITY, nearestCity } from '../data/cities.js'

const KEY = 'jogai.location'

function load() {
  try {
    const saved = JSON.parse(localStorage.getItem(KEY) || 'null')
    if (saved && Number.isFinite(saved.lat) && Number.isFinite(saved.lon)) return saved
  } catch {
    // sem armazenamento: começa pela cidade padrão
  }
  return { lat: DEFAULT_CITY.lat, lon: DEFAULT_CITY.lon, label: DEFAULT_CITY.label, source: 'default' }
}

function store(value) {
  try {
    localStorage.setItem(KEY, JSON.stringify(value))
  } catch {
    // ignora
  }
}

export function getGpsPosition() {
  return new Promise((resolve, reject) => {
    if (!navigator.geolocation) {
      reject(new Error('Este navegador não oferece localização.'))
      return
    }
    navigator.geolocation.getCurrentPosition(
      (pos) => resolve({ lat: pos.coords.latitude, lon: pos.coords.longitude }),
      (err) =>
        reject(
          new Error(
            err.code === 1
              ? 'Você não liberou a localização. Digite sua cidade.'
              : 'Não foi possível obter sua localização agora. Digite sua cidade.'
          )
        ),
      { enableHighAccuracy: false, timeout: 10000, maximumAge: 300000 }
    )
  })
}

/*
 * Posição do cliente para a busca: GPS do aparelho por padrão; se a pessoa não liberar,
 * usa a cidade escolhida na tabela. Guardada no navegador para a próxima visita.
 */
export function useUserLocation() {
  const [location, setLocationState] = useState(load)
  const [locating, setLocating] = useState(false)
  const [gpsError, setGpsError] = useState('')

  const setLocation = useCallback((value) => {
    setLocationState(value)
    store(value)
  }, [])

  const useGps = useCallback(async () => {
    setLocating(true)
    setGpsError('')
    try {
      const { lat, lon } = await getGpsPosition()
      const city = nearestCity(lat, lon)
      setLocation({ lat, lon, label: city ? city.label : 'sua localização', source: 'gps' })
      return true
    } catch (err) {
      setGpsError(err.message)
      return false
    } finally {
      setLocating(false)
    }
  }, [setLocation])

  const useCity = useCallback(
    (city) => {
      setGpsError('')
      setLocation({ lat: city.lat, lon: city.lon, label: city.label, source: 'city' })
    },
    [setLocation]
  )

  // GPS por padrão: se a permissão já foi dada antes, atualiza sem perguntar de novo.
  useEffect(() => {
    if (location.source === 'city') return
    navigator.permissions
      ?.query({ name: 'geolocation' })
      .then((perm) => {
        if (perm.state === 'granted') useGps()
      })
      .catch(() => {})
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  return { location, locating, gpsError, useGps, useCity }
}
