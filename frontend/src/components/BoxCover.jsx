import { useState } from 'react'

/*
 * Imagem do jogo: usa a foto (image_url) quando existe e carrega; senão, desenha uma
 * caixa ilustrada com o título, para a vitrine nunca ficar com buraco.
 */
const COVERS = [
  ['#1F2A33', '#D99A1E', '#4F6E5B', '#F4F1EA', 'serif'],
  ['#B9472F', '#F0D9A8', '#5A2418', '#FFF6E6', 'serif'],
  ['#F2E6CF', '#1F2A33', '#C8402A', '#1F2A33', 'italic'],
  ['#2F4A3F', '#E9DCC0', '#D99A1E', '#F4F1EA', 'serif'],
  ['#E3D3B4', '#2B5F7A', '#C8402A', '#1E2B33', 'serif'],
  ['#6B2E3E', '#E7B75F', '#F2E6CF', '#FBEFDD', 'italic'],
  ['#264653', '#E9C46A', '#F4A261', '#F4F1EA', 'serif'],
  ['#EFE7DA', '#7A4E9C', '#2A9D8F', '#2A1F33', 'serif'],
  ['#D7C6F0', '#3B2A5C', '#E07A5F', '#2A1F44', 'italic'],
]

function hash(text) {
  let h = 0
  for (const ch of String(text)) h = (h * 31 + ch.charCodeAt(0)) >>> 0
  return h
}

function wrap(title, max) {
  const lines = ['']
  for (const word of String(title).split(/\s+/)) {
    const last = lines[lines.length - 1]
    if (`${last} ${word}`.trim().length > max && last) lines.push(word)
    else lines[lines.length - 1] = `${last} ${word}`.trim()
  }
  return lines.slice(0, 3)
}

function Motif({ kind, a, b, bg }) {
  switch (kind % 9) {
    case 0:
      return (
        <>
          <circle cx="120" cy="104" r="22" fill={a} />
          <path d="M0 160c40-24 70-6 100-20s50-22 70-10v66H0Z" fill={b} />
        </>
      )
    case 1:
      return Array.from({ length: 9 }, (_, k) => {
        const x = 22 + (k % 3) * 48 + (Math.floor(k / 3) % 2) * 24
        const y = 92 + Math.floor(k / 3) * 36
        return <path key={k} d={`M${x} ${y - 20}l20 11v22l-20 11-20-11v-22Z`} fill={k % 2 ? a : b} />
      })
    case 2:
      return (
        <>
          <path d="M-10 186C40 150 60 120 90 120s70 20 90-20" fill="none" stroke={a} strokeWidth="12" />
          <path d="M-10 186C40 150 60 120 90 120s70 20 90-20" fill="none" stroke={b} strokeWidth="12" strokeDasharray="4 10" />
        </>
      )
    case 3:
      return Array.from({ length: 16 }, (_, k) => (
        <rect key={k} x={26 + (k % 4) * 31} y={84 + Math.floor(k / 4) * 26} width="26" height="22" rx="3" fill={[a, b, '#F4F1EA', '#C8402A'][(k * 7) % 4]} />
      ))
    case 4:
      return [-18, -6, 6, 18].map((r, k) => (
        <rect key={k} x="66" y="96" width="40" height="58" rx="4" fill={k % 2 ? a : b} transform={`rotate(${r} 86 170)`} />
      ))
    case 5:
      return Array.from({ length: 12 }, (_, k) => (
        <rect key={k} x={20 + (k % 4) * 34} y={92 + Math.floor(k / 4) * 28} width="28" height="22" rx="2" fill={k === 5 ? b : a} />
      ))
    case 6:
      return (
        <>
          <path d="M30 196v-70h16v-14h12v14h14v-30h26v30h14v-14h12v14h16v70Z" fill={a} />
          <rect x="74" y="150" width="22" height="46" rx="11" fill={b} />
        </>
      )
    case 7:
      return [[50, 120], [100, 110], [76, 154], [124, 152]].map(([x, y], k) => (
        <path key={k} d={`M${x} ${y - 18}l16 18-16 22-16-22Z`} fill={k % 2 ? a : b} />
      ))
    default:
      return (
        <>
          <circle cx="112" cy="104" r="26" fill={b} />
          <circle cx="122" cy="98" r="22" fill={bg} />
          <rect x="58" y="128" width="40" height="68" rx="20" fill={a} />
        </>
      )
  }
}

export function IllustratedBox({ title, seed = title, crop = false }) {
  const h = hash(seed)
  const [bg, a, b, fg, style] = COVERS[h % COVERS.length]
  const lines = wrap(title, 11)
  const fs = lines.length > 2 ? 18 : 22
  const id = `sheen-${h}`
  return (
    <svg viewBox={crop ? '70 20 270 250' : '0 0 400 300'} preserveAspectRatio="xMidYMid meet" aria-hidden="true">
      <defs>
        <linearGradient id={id} x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#fff" stopOpacity=".12" />
          <stop offset=".5" stopColor="#fff" stopOpacity="0" />
          <stop offset="1" stopColor="#000" stopOpacity=".12" />
        </linearGradient>
      </defs>
      <g className="boxart">
        <ellipse cx="208" cy="262" rx="112" ry="10" fill="#161513" opacity=".16" />
        <path d="M112 52 130 40h170l-18 12Z" fill={bg} />
        <path d="M112 52 130 40h170l-18 12Z" fill="#fff" opacity=".35" />
        <path d="M282 52 300 40v196l-18 12Z" fill={bg} />
        <path d="M282 52 300 40v196l-18 12Z" fill="#000" opacity=".28" />
        <svg x="112" y="52" width="170" height="196" viewBox="0 0 170 196">
          <rect width="170" height="196" fill={bg} />
          <Motif kind={h >> 3} a={a} b={b} bg={bg} />
          {lines.map((line, k) => (
            <text
              key={k}
              x="14"
              y={30 + k * (fs + 2)}
              fontFamily="Fraunces, serif"
              fontWeight={style === 'italic' ? 500 : 800}
              fontStyle={style === 'italic' ? 'italic' : 'normal'}
              fontSize={fs}
              fill={fg}
            >
              {line}
            </text>
          ))}
          <rect width="170" height="196" fill={`url(#${id})`} />
        </svg>
      </g>
    </svg>
  )
}

export default function GameImage({ game, title, crop = false }) {
  const [failed, setFailed] = useState(false)
  if (game.image_url && !failed) {
    return (
      <img
        className="photo"
        src={game.image_url}
        alt={`Caixa do jogo ${title}`}
        loading="lazy"
        referrerPolicy="no-referrer"
        onError={() => setFailed(true)}
      />
    )
  }
  return <IllustratedBox title={title} seed={`${game.id}-${game.title}`} crop={crop} />
}
