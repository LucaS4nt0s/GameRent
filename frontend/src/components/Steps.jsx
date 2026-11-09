import Reveal from './Reveal.jsx'

export default function Steps() {
  return (
    <section className="wrap how" id="como">
      <Reveal className="sec-head">
        <div>
          <span className="kicker">Como funciona</span>
          <h2>Três passos até a primeira partida</h2>
        </div>
      </Reveal>
      <div className="steps2">
        <svg className="steps-line" viewBox="0 0 1000 40" preserveAspectRatio="none" aria-hidden="true">
          <path d="M60 20 C 300 -10, 400 50, 500 20 S 760 -10, 940 20" />
        </svg>

        <Reveal as="article" className="step2" style={{ '--tint': '#E3EDE5' }}>
          <div className="step-ill">
            <svg viewBox="0 0 220 150" aria-hidden="true">
              <g stroke="#B9CDBE" strokeWidth="7" strokeLinecap="round" fill="none">
                <path d="M-10 40h240M-10 108h240M54-10v170M150-10v170" />
                <path d="M-10 150 230 0" strokeWidth="5" />
              </g>
              <g fill="#CFDDD2">
                <rect x="70" y="56" width="22" height="18" rx="3" />
                <rect x="120" y="54" width="18" height="22" rx="3" />
                <rect x="164" y="60" width="28" height="16" rx="3" />
                <rect x="16" y="64" width="24" height="20" rx="3" />
              </g>
              <circle className="pulse" cx="110" cy="92" r="46" fill="#5F7F69" opacity=".18" />
              <circle cx="110" cy="92" r="46" fill="none" stroke="#5F7F69" strokeWidth="2" strokeDasharray="3 6" />
              <g className="pin-hop">
                <path d="M110 40a20 20 0 0 0-20 20c0 15 20 32 20 32s20-17 20-32a20 20 0 0 0-20-20Z" fill="#D2492A" />
                <circle cx="110" cy="60" r="7" fill="#FBF8F2" />
              </g>
              <ellipse cx="110" cy="94" rx="10" ry="3" fill="#1E1C18" opacity=".2" />
            </svg>
          </div>
          <span className="step-n">01</span>
          <h3>Escolha pela cidade</h3>
          <p>Use o GPS ou digite sua cidade e veja os jogos mais perto, com a distância de cada um. O endereço do dono nunca aparece.</p>
        </Reveal>

        <Reveal as="article" className="step2" delay={0.12} style={{ '--tint': '#F6E9CC' }}>
          <div className="step-ill">
            <svg viewBox="0 0 220 150" aria-hidden="true">
              <g opacity=".35">
                <rect x="26" y="70" width="52" height="40" rx="4" fill="#B79A63" />
                <rect x="142" y="70" width="52" height="40" rx="4" fill="#B79A63" />
                <path d="M40 84l24 14M64 84l-24 14M156 84l24 14M180 84l-24 14" stroke="#FBF8F2" strokeWidth="4" strokeLinecap="round" />
              </g>
              <ellipse cx="110" cy="122" rx="44" ry="6" fill="#1E1C18" opacity=".15" />
              <g className="box-pop">
                <rect x="74" y="62" width="72" height="58" rx="5" fill="#1F2A33" />
                <rect x="70" y="52" width="80" height="20" rx="4" fill="#2B3A67" />
                <circle cx="132" cy="62" r="5" fill="#FFE7A3" />
              </g>
              <g className="check-pop">
                <circle cx="150" cy="50" r="17" fill="#5F7F69" />
                <path d="M142 50l6 6 10-11" fill="none" stroke="#fff" strokeWidth="4" strokeLinecap="round" strokeLinejoin="round" />
              </g>
            </svg>
          </div>
          <span className="step-n">02</span>
          <h3>Reserve sem disputa</h3>
          <p>Confirmou, é seu. Se outra pessoa tentar a mesma caixa no mesmo segundo, só uma reserva passa.</p>
        </Reveal>

        <Reveal as="article" className="step2" delay={0.24} style={{ '--tint': '#F5DED6' }}>
          <div className="step-ill">
            <svg viewBox="0 0 220 150" aria-hidden="true">
              <rect x="0" y="118" width="220" height="32" fill="#E8C4B6" />
              <rect x="58" y="58" width="104" height="62" fill="#FBF8F2" stroke="#1E1C18" strokeWidth="2.5" />
              <path d="M48 62 110 20l62 42Z" fill="#D2492A" stroke="#1E1C18" strokeWidth="2.5" strokeLinejoin="round" />
              <rect x="98" y="80" width="24" height="40" fill="#1F2A33" />
              <rect x="70" y="72" width="16" height="16" fill="#E0A526" />
              <rect x="134" y="72" width="16" height="16" fill="#E0A526" />
              <g className="box-arrive">
                <rect x="128" y="102" width="26" height="18" rx="2" fill="#2B3A67" />
                <rect x="126" y="98" width="30" height="7" rx="2" fill="#3F5487" />
              </g>
              <g fill="#E0A526">
                <path className="spark" d="M60 30c1 6 2 7 8 8-6 1-7 2-8 8-1-6-2-7-8-8 6-1 7-2 8-8Z" />
                <path className="spark s2" d="M176 26c1 5 2 6 7 7-5 1-6 2-7 7-1-5-2-6-7-7 5-1 6-2 7-7Z" />
                <path className="spark s3" d="M188 70c1 4 1.5 5 6 6-4.5 1-5 1.5-6 6-1-4.5-1.5-5-6-6 4.5-1 5-2 6-6Z" />
              </g>
            </svg>
          </div>
          <span className="step-n">03</span>
          <h3>Jogue e devolva</h3>
          <p>O jogo chega na sua mesa. Acompanhe os dias em Minha conta e devolva com um clique quando a partida acabar.</p>
        </Reveal>
      </div>
    </section>
  )
}
