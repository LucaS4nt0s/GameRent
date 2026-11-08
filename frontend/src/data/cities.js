// Tabela fixa de cidades usada quando a pessoa não libera o GPS ou quer buscar em outra cidade.
// Coordenadas aproximadas do centro de cada município (graus decimais).
export const CITIES = [
  ['São Paulo', 'SP', -23.5505, -46.6333],
  ['Campinas', 'SP', -22.9056, -47.0608],
  ['Santos', 'SP', -23.9608, -46.3336],
  ['Sorocaba', 'SP', -23.5015, -47.4526],
  ['Jundiaí', 'SP', -23.1857, -46.8978],
  ['Ribeirão Preto', 'SP', -21.1775, -47.8103],
  ['São José dos Campos', 'SP', -23.1896, -45.8841],
  ['Guarulhos', 'SP', -23.4543, -46.5337],
  ['Osasco', 'SP', -23.5329, -46.7916],
  ['Santo André', 'SP', -23.6639, -46.5383],
  ['São Bernardo do Campo', 'SP', -23.6914, -46.5646],
  ['Mogi das Cruzes', 'SP', -23.5229, -46.188],
  ['Piracicaba', 'SP', -22.7253, -47.6492],
  ['Limeira', 'SP', -22.564, -47.4017],
  ['Americana', 'SP', -22.7374, -47.3331],
  ['Indaiatuba', 'SP', -23.0882, -47.2234],
  ['Valinhos', 'SP', -22.9707, -46.9958],
  ['Sumaré', 'SP', -22.8219, -47.2669],
  ['Hortolândia', 'SP', -22.8529, -47.2143],
  ['Paulínia', 'SP', -22.7542, -47.1488],
  ['São Carlos', 'SP', -22.0174, -47.8909],
  ['Araraquara', 'SP', -21.7845, -48.178],
  ['Bauru', 'SP', -22.3246, -49.0871],
  ['Marília', 'SP', -22.2139, -49.9458],
  ['São José do Rio Preto', 'SP', -20.8113, -49.3758],
  ['Presidente Prudente', 'SP', -22.1207, -51.3925],
  ['Taubaté', 'SP', -23.0264, -45.5553],
  ['Rio de Janeiro', 'RJ', -22.9068, -43.1729],
  ['Niterói', 'RJ', -22.8832, -43.1034],
  ['Belo Horizonte', 'MG', -19.9167, -43.9345],
  ['Uberlândia', 'MG', -18.9128, -48.2755],
  ['Juiz de Fora', 'MG', -21.7642, -43.3496],
  ['Vitória', 'ES', -20.3155, -40.3128],
  ['Curitiba', 'PR', -25.4284, -49.2733],
  ['Londrina', 'PR', -23.3045, -51.1696],
  ['Maringá', 'PR', -23.4205, -51.9333],
  ['Florianópolis', 'SC', -27.5954, -48.548],
  ['Joinville', 'SC', -26.3045, -48.8487],
  ['Porto Alegre', 'RS', -30.0346, -51.2177],
  ['Caxias do Sul', 'RS', -29.1678, -51.1794],
  ['Brasília', 'DF', -15.7939, -47.8828],
  ['Goiânia', 'GO', -16.6869, -49.2648],
  ['Campo Grande', 'MS', -20.4697, -54.6201],
  ['Cuiabá', 'MT', -15.6014, -56.0979],
  ['Salvador', 'BA', -12.9777, -38.5016],
  ['Recife', 'PE', -8.0476, -34.877],
  ['Fortaleza', 'CE', -3.7319, -38.5267],
  ['Natal', 'RN', -5.7945, -35.211],
  ['João Pessoa', 'PB', -7.1195, -34.845],
  ['Maceió', 'AL', -9.6658, -35.735],
  ['Aracaju', 'SE', -10.9472, -37.0731],
  ['Teresina', 'PI', -5.0892, -42.8019],
  ['São Luís', 'MA', -2.5307, -44.3068],
  ['Belém', 'PA', -1.4558, -48.4902],
  ['Manaus', 'AM', -3.119, -60.0217],
  ['Palmas', 'TO', -10.2491, -48.3243],
  ['Porto Velho', 'RO', -8.7612, -63.9004],
  ['Rio Branco', 'AC', -9.9754, -67.8249],
  ['Macapá', 'AP', 0.0349, -51.0694],
  ['Boa Vista', 'RR', 2.8235, -60.6758],
].map(([name, uf, lat, lon]) => ({ name, uf, lat, lon, label: `${name}, ${uf}` }))

export const DEFAULT_CITY = CITIES[0]

const norm = (text) =>
  String(text)
    .normalize('NFD')
    .replace(/\p{M}/gu, '')
    .toLowerCase()
    .trim()

export function searchCities(query, limit = 6) {
  const q = norm(query).replace(/,.*$/, '')
  if (!q) return []
  return CITIES.filter((city) => {
    const n = norm(city.name)
    return n.startsWith(q) || n.includes(` ${q}`)
  }).slice(0, limit)
}

export function findCity(query) {
  const q = norm(query).replace(/,.*$/, '')
  return CITIES.find((city) => norm(city.name) === q) || searchCities(query, 1)[0] || null
}

function distanceKm(aLat, aLon, bLat, bLon) {
  const rad = Math.PI / 180
  const dLat = (bLat - aLat) * rad
  const dLon = (bLon - aLon) * rad
  const h = Math.sin(dLat / 2) ** 2 + Math.cos(aLat * rad) * Math.cos(bLat * rad) * Math.sin(dLon / 2) ** 2
  return 6371 * 2 * Math.asin(Math.sqrt(h))
}

// Cidade da tabela mais próxima de uma posição de GPS (só para exibir "perto de Campinas").
export function nearestCity(lat, lon) {
  let best = null
  for (const city of CITIES) {
    const d = distanceKm(lat, lon, city.lat, city.lon)
    if (!best || d < best.d) best = { city, d }
  }
  return best && best.d <= 60 ? best.city : null
}
