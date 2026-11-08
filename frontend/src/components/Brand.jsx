export function Icons() {
  return (
    <svg width="0" height="0" style={{ position: 'absolute' }} aria-hidden="true">
      <symbol id="pin" viewBox="0 0 24 24">
        <path fill="currentColor" d="M12 2a7 7 0 0 0-7 7c0 5 7 13 7 13s7-8 7-13a7 7 0 0 0-7-7Zm0 9.5A2.5 2.5 0 1 1 12 6.5a2.5 2.5 0 0 1 0 5Z" />
      </symbol>
      <symbol id="target" viewBox="0 0 24 24">
        <g fill="none" stroke="currentColor" strokeWidth="2">
          <circle cx="12" cy="12" r="7" />
          <path d="M12 1v4M12 19v4M1 12h4M19 12h4" />
        </g>
      </symbol>
      <symbol id="meeple" viewBox="0 0 40 40">
        <path fill="currentColor" d="M20 3a6 6 0 0 0-6 6c0 2 .9 3.6 2.3 4.6C11 15 4 17 4 21c0 2.3 4 2.6 8 2.2L8 35c-.4 1.4.6 2 2 2h6l4-7 4 7h6c1.4 0 2.4-.6 2-2l-4-11.8c4 .4 8 0 8-2.2 0-4-7-6-12.3-7.4A6 6 0 0 0 20 3Z" />
      </symbol>
      <symbol id="close" viewBox="0 0 24 24">
        <path d="M6 6l12 12M18 6 6 18" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
      </symbol>
    </svg>
  )
}

export function Logo({ onClick }) {
  return (
    <a className="logo" href="#/" onClick={onClick} aria-label="Jogaí, página inicial">
      <span className="jg">
        jog
        <span className="ai">
          a
          <span className="i">
            ı
            <svg className="acc" aria-hidden="true">
              <use href="#meeple" />
            </svg>
          </span>
        </span>
      </span>
    </a>
  )
}

export function Icon({ id, className }) {
  return (
    <svg className={className} aria-hidden="true">
      <use href={`#${id}`} />
    </svg>
  )
}
