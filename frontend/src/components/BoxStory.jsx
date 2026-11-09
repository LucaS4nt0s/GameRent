import { useEffect, useRef, useState } from 'react'

/*
 * Abertura do site guiada pela rolagem: as peças caem na caixa, a tampa fecha,
 * a etiqueta é colada e a caixa segue pela rota até a casa do cliente.
 * Só usa transform/opacity (GPU) e só calcula quando a seção está na tela.
 */

// s = solto no ar, e = dentro da caixa, t = janela de tempo [início, fim] no progresso 0..1
const PIECES = {
  board: { s: [165, 10, -8], e: [165, 250, 0], t: [0.1, 0.34] },
  card1: { s: [40, 70, -18], e: [110, 262, -4], t: [0.14, 0.36] },
  card2: { s: [420, 40, 14], e: [330, 262, 5], t: [0.17, 0.39] },
  card3: { s: [455, 170, 22], e: [250, 266, -2], t: [0.2, 0.41] },
  m1: { s: [60, 215, -20], e: [150, 272, 0], t: [0.22, 0.42] },
  m2: { s: [110, 150, 15], e: [190, 276, 0], t: [0.24, 0.43] },
  m3: { s: [380, 205, -12], e: [380, 272, 0], t: [0.26, 0.44] },
  die1: { s: [360, 120, 30], e: [300, 280, 8], t: [0.28, 0.45] },
  die2: { s: [22, 140, -25], e: [90, 282, -6], t: [0.29, 0.46] },
  tok: { s: [300, 0, 0], e: [230, 284, 0], t: [0.3, 0.47] },
}
const BOUNDS = [0, 0.12, 0.48, 0.72, 1]
const ROUTE = 'M260 452 C 420 452, 300 222, 380 220'

const clamp = (v, a = 0, b = 1) => Math.min(b, Math.max(a, v))
const seg = (p, a, b) => clamp((p - a) / (b - a))
const eio = (t) => (t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2)
const eob = (t) => {
  const c = 1.5
  return 1 + (c + 1) * Math.pow(t - 1, 3) + c * Math.pow(t - 1, 2)
}
const lerp = (a, b, t) => a + (b - a) * t

export default function BoxStory({ cityLabel, onFindGames }) {
  const storyRef = useRef(null)
  const stageRef = useRef(null)
  const refs = useRef({})
  const [phase, setPhase] = useState(0)
  const set = (key) => (el) => {
    refs.current[key] = el
  }

  useEffect(() => {
    const story = storyRef.current
    const stage = stageRef.current
    const r = refs.current
    const routeLen = r.routeMask.getTotalLength()
    r.routeMask.style.strokeDasharray = routeLen
    const reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches
    let visible = true
    let raf = 0
    let lastPhase = -1

    function fit() {
      const box = stage.parentElement
      stage.style.setProperty('--fit', Math.min(1, (box.clientWidth - 16) / 560, (box.clientHeight - 10) / 560))
    }

    function frame() {
      raf = 0
      const rect = story.getBoundingClientRect()
      const total = story.offsetHeight - window.innerHeight
      let p = clamp(-rect.top / total)
      if (reduce) p = p > 0.02 ? 1 : 0

      for (const [key, d] of Object.entries(PIECES)) {
        const el = r[key]
        const t = eio(seg(p, d.t[0], d.t[1]))
        el.style.transform = `translate(${lerp(d.s[0], d.e[0], t)}px,${lerp(d.s[1], d.e[1], t)}px) rotate(${lerp(d.s[2], d.e[2], t)}deg) scale(${lerp(1, 0.82, t)})`
        el.firstElementChild.style.animationPlayState = t > 0 ? 'paused' : 'running'
      }
      const lt = eob(seg(p, 0.48, 0.6))
      r.lid.style.transform = `translateY(${lerp(-330, 0, lt)}px) rotate(${lerp(-6, 0, lt)}deg)`
      r.lid.style.opacity = seg(p, 0.46, 0.5)
      r.strap.style.transform = `scaleY(${eio(seg(p, 0.61, 0.66))})`
      const lb = seg(p, 0.65, 0.71)
      r.label.style.opacity = lb > 0 ? 1 : 0
      r.label.style.transform = `rotate(${lerp(-18, -6, eob(lb))}deg) scale(${lerp(1.6, 1, eob(lb))})`
      const tr = eio(seg(p, 0.74, 0.95))
      const sc = lerp(1, 0.3, tr)
      const pt = r.routeMask.getPointAtLength(routeLen * tr)
      r.boxg.style.transform = `translate(${pt.x - 260}px,${pt.y - (380 + 66 * sc)}px) scale(${sc})`
      r.routeMask.style.strokeDashoffset = -routeLen * tr
      const hs = eio(seg(p, 0.7, 0.78))
      r.house.style.opacity = hs
      r.house.style.transform = `translateY(${lerp(10, 0, hs)}px) scale(${lerp(0.9, 1, hs)})`

      const ph = p < BOUNDS[1] ? 0 : p < BOUNDS[2] ? 1 : p < BOUNDS[3] ? 2 : 3
      if (ph !== lastPhase) {
        lastPhase = ph
        setPhase(ph)
      }
    }

    const schedule = () => {
      if (visible && !raf) raf = requestAnimationFrame(frame)
    }
    const io = new IntersectionObserver(([entry]) => {
      visible = entry.isIntersecting
      schedule()
    })
    io.observe(story)
    const onResize = () => {
      fit()
      schedule()
    }
    window.addEventListener('scroll', schedule, { passive: true })
    window.addEventListener('resize', onResize)
    fit()
    frame()
    return () => {
      io.disconnect()
      window.removeEventListener('scroll', schedule)
      window.removeEventListener('resize', onResize)
      cancelAnimationFrame(raf)
    }
  }, [])

  return (
    <section className="story" ref={storyRef} aria-label="Como o jogo chega até você">
      <div className="story-stick">
        <div className="story-copy">
          <div className={`phase ${phase === 0 ? 'on' : ''}`}>
            <span className="kicker">Aluguel de jogos de tabuleiro</span>
            <h1>
              A noite de jogos <em>começa</em> antes da primeira jogada.
            </h1>
            <p>Escolha entre os jogos de pessoas da sua cidade. A gente confere cada peça.</p>
            <div className="scroll-hint">
              <i /> role para ver
            </div>
          </div>
          <div className={`phase ${phase === 1 ? 'on' : ''}`}>
            <span className="kicker">Conferido peça por peça</span>
            <h2>
              Cartas, dados, meeples. <em>Nada fica de fora.</em>
            </h2>
            <p>Todo jogo volta para a caixa completo e revisado antes de sair de novo.</p>
          </div>
          <div className={`phase ${phase === 2 ? 'on' : ''}`}>
            <span className="kicker">Lacrado e etiquetado</span>
            <h2>
              Fechou a caixa, <em>já é seu.</em>
            </h2>
            <p>Reserva confirmada em segundos, sem dois clientes no mesmo jogo.</p>
          </div>
          <div className={`phase ${phase === 3 ? 'on' : ''}`}>
            <span className="kicker">Entrega na sua cidade</span>
            <h2>
              Da estante de alguém <em>para a sua mesa.</em>
            </h2>
            <p>Alugue por dia, jogue quanto quiser e devolva quando acabar a partida.</p>
            <button className="btn btn-brick" type="button" onClick={onFindGames}>
              Encontrar jogos perto de mim
            </button>
          </div>
        </div>

        <div className="stage-wrap" aria-hidden="true">
          <div className="stage" ref={stageRef}>
            <svg className="route" viewBox="0 0 560 560">
              <path d={ROUTE} />
              <path className="mask-path" ref={set('routeMask')} d={ROUTE} />
            </svg>
            <svg className="house" ref={set('house')} viewBox="0 0 110 100">
              <rect x="14" y="44" width="82" height="52" rx="3" fill="#FBF8F2" stroke="#1E1C18" strokeWidth="2.5" />
              <path d="M6 48 55 8l49 40Z" fill="#D2492A" stroke="#1E1C18" strokeWidth="2.5" strokeLinejoin="round" />
              <rect x="44" y="62" width="22" height="34" rx="2" fill="#1F2A33" />
              <rect x="22" y="56" width="14" height="14" rx="2" fill="#E0A526" />
              <rect x="74" y="56" width="14" height="14" rx="2" fill="#E0A526" />
            </svg>

            <div className="boxg" ref={set('boxg')}>
              <div className="box-shadow" />
              <div className="box-back" />

              <div className="piece" ref={set('board')}>
                <div className="bob" style={{ '--d': '.2s' }}>
                  <svg width="190" height="190" viewBox="0 0 190 190">
                    <rect width="190" height="190" rx="8" fill="#E9DCC0" stroke="#1E1C18" strokeWidth="2" />
                    <g fill="none" stroke="#1E1C18" strokeOpacity=".35">
                      <path d="M20 20h150v150H20z" />
                      <path d="M20 57h150M20 95h150M20 132h150M57 20v150M95 20v150M132 20v150" />
                    </g>
                    <circle cx="95" cy="95" r="30" fill="#5F7F69" />
                    <path d="M38 38h19v19H38zM132 132h19v19h-19z" fill="#D2492A" />
                    <path d="M132 38h19v19h-19zM38 132h19v19H38z" fill="#E0A526" />
                  </svg>
                </div>
              </div>
              <div className="piece" ref={set('card1')}>
                <div className="bob" style={{ '--d': '.6s' }}>
                  <svg width="78" height="112" viewBox="0 0 78 112">
                    <rect width="78" height="112" rx="7" fill="#FBF8F2" stroke="#1E1C18" strokeWidth="2" />
                    <rect x="7" y="7" width="64" height="70" rx="4" fill="#1F2A33" />
                    <circle cx="52" cy="28" r="9" fill="#E0A526" />
                    <path d="M7 64c14-14 26-6 34-14s18-6 30 2v25H7Z" fill="#5F7F69" />
                    <rect x="14" y="88" width="50" height="5" rx="2" fill="#1E1C18" opacity=".25" />
                  </svg>
                </div>
              </div>
              <div className="piece" ref={set('card2')}>
                <div className="bob" style={{ '--d': '1.1s' }}>
                  <svg width="78" height="112" viewBox="0 0 78 112">
                    <rect width="78" height="112" rx="7" fill="#FBF8F2" stroke="#1E1C18" strokeWidth="2" />
                    <rect x="7" y="7" width="64" height="70" rx="4" fill="#D2492A" />
                    <path d="M39 18c10 12 14 22 0 46-14-24-10-34 0-46Z" fill="#F3EDE2" />
                    <circle cx="39" cy="44" r="6" fill="#E0A526" />
                    <rect x="14" y="88" width="50" height="5" rx="2" fill="#1E1C18" opacity=".25" />
                  </svg>
                </div>
              </div>
              <div className="piece" ref={set('card3')}>
                <div className="bob" style={{ '--d': '1.5s' }}>
                  <svg width="78" height="112" viewBox="0 0 78 112">
                    <rect width="78" height="112" rx="7" fill="#FBF8F2" stroke="#1E1C18" strokeWidth="2" />
                    <rect x="7" y="7" width="64" height="70" rx="4" fill="#E0A526" />
                    <path d="M14 70 30 40l10 16 8-10 16 24Z" fill="#1F2A33" />
                    <circle cx="26" cy="22" r="6" fill="#FBF8F2" />
                  </svg>
                </div>
              </div>
              {[
                ['m1', '#D2492A', '.3s'],
                ['m2', '#5F7F69', '.9s'],
                ['m3', '#E0A526', '1.3s'],
              ].map(([key, color, delay]) => (
                <div className="piece" ref={set(key)} key={key}>
                  <div className="bob" style={{ '--d': delay }}>
                    <svg width="46" height="46" style={{ color }}>
                      <use href="#meeple" />
                    </svg>
                  </div>
                </div>
              ))}
              <div className="piece" ref={set('die1')}>
                <div className="bob" style={{ '--d': '.5s' }}>
                  <svg width="46" height="46" viewBox="0 0 46 46">
                    <rect x="2" y="2" width="42" height="42" rx="9" fill="#FBF8F2" stroke="#1E1C18" strokeWidth="2" />
                    <g fill="#1E1C18">
                      <circle cx="13" cy="13" r="3.6" />
                      <circle cx="23" cy="23" r="3.6" />
                      <circle cx="33" cy="33" r="3.6" />
                    </g>
                  </svg>
                </div>
              </div>
              <div className="piece" ref={set('die2')}>
                <div className="bob" style={{ '--d': '1.7s' }}>
                  <svg width="40" height="40" viewBox="0 0 46 46">
                    <rect x="2" y="2" width="42" height="42" rx="9" fill="#1F2A33" />
                    <g fill="#F3EDE2">
                      <circle cx="13" cy="13" r="3.6" />
                      <circle cx="33" cy="13" r="3.6" />
                      <circle cx="13" cy="33" r="3.6" />
                      <circle cx="33" cy="33" r="3.6" />
                    </g>
                  </svg>
                </div>
              </div>
              <div className="piece" ref={set('tok')}>
                <div className="bob" style={{ '--d': '.8s' }}>
                  <svg width="38" height="38" viewBox="0 0 38 38">
                    <circle cx="19" cy="19" r="17" fill="#E0A526" stroke="#1E1C18" strokeWidth="2" />
                    <circle cx="19" cy="19" r="9" fill="none" stroke="#1E1C18" strokeWidth="2" strokeDasharray="3 3" />
                  </svg>
                </div>
              </div>

              <div className="box-front">
                <span className="tag">Jogaí · conferido</span>
              </div>

              <svg className="lid" ref={set('lid')} viewBox="0 0 412 210">
                <defs>
                  <clipPath id="lidc">
                    <rect width="412" height="210" rx="8" />
                  </clipPath>
                </defs>
                <g clipPath="url(#lidc)">
                  <rect width="412" height="210" fill="#1F2A33" />
                  <circle cx="318" cy="60" r="34" fill="#E0A526" />
                  <circle cx="318" cy="60" r="52" fill="none" stroke="#E0A526" strokeOpacity=".25" strokeWidth="10" />
                  <path d="M0 150c60-30 110-10 160-30s110-50 170-20 82 20 82 20v90H0Z" fill="#2E4A44" />
                  <path d="M0 175c70-20 140 0 210-15s140-25 202 5v45H0Z" fill="#5F7F69" />
                  <g fill="#D2492A">
                    <path d="M60 128h8l2 18h-12Z" />
                    <path d="M110 112h8l2 20h-12Z" />
                    <path d="M164 120h8l2 18h-12Z" />
                  </g>
                  <g fill="#E0A526">
                    <circle cx="64" cy="122" r="5" />
                    <circle cx="114" cy="106" r="5" />
                    <circle cx="168" cy="114" r="5" />
                  </g>
                  <text x="28" y="52" fontFamily="Fraunces, serif" fontWeight="600" fontSize="34" fill="#F3EDE2">
                    Exploding
                  </text>
                  <text x="28" y="88" fontFamily="Fraunces, serif" fontStyle="italic" fontSize="38" fill="#F3EDE2">
                    Kittens
                  </text>
                  <text x="30" y="198" fontFamily="Instrument Sans" fontWeight="600" fontSize="10" fill="#F3EDE2" letterSpacing="3" opacity=".7">
                    2–5 JOGADORES · 15 MIN
                  </text>
                </g>
              </svg>
              <div className="strap" ref={set('strap')} />
              <svg className="label" ref={set('label')} viewBox="0 0 150 96">
                <rect x="1" y="1" width="148" height="94" rx="6" fill="#FBF8F2" stroke="#1E1C18" strokeWidth="2" />
                <rect x="1" y="1" width="148" height="24" rx="6" fill="#D2492A" />
                <text x="12" y="18" fontFamily="Instrument Sans" fontWeight="700" fontSize="11" fill="#fff" letterSpacing="1.5">
                  JOGAÍ · ENTREGA
                </text>
                <text x="12" y="46" fontFamily="Instrument Sans" fontSize="9" fill="#8A8274">
                  PARA
                </text>
                <text x="12" y="62" fontFamily="Fraunces, serif" fontWeight="600" fontSize="14" fill="#1E1C18">
                  {cityLabel}
                </text>
                <g fill="#1E1C18">
                  {[12, 16, 22, 26, 31, 35, 41, 46, 52, 56].map((x, i) => (
                    <rect key={x} x={x} y="72" width={[2, 4, 1.5, 3, 1.5, 4, 2, 3, 1.5, 4][i]} height="14" />
                  ))}
                </g>
                <circle cx="120" cy="66" r="18" fill="none" stroke="#5F7F69" strokeWidth="2" />
                <text x="120" y="70" textAnchor="middle" fontFamily="Instrument Sans" fontWeight="700" fontSize="9" fill="#5F7F69">
                  OK ✓
                </text>
              </svg>
            </div>
          </div>
        </div>
      </div>
    </section>
  )
}
