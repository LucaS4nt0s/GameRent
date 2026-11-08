import { useEffect, useRef, useState } from 'react'
import { Icon, Logo } from './Brand.jsx'
import { firstName, initials } from '../utils/format.js'
import { navigate } from '../router.js'

export function goToSection(id) {
  if (window.location.hash.replace(/^#/, '').split('?')[0] !== '/') {
    navigate('/')
    setTimeout(() => document.getElementById(id)?.scrollIntoView({ behavior: 'smooth' }), 80)
  } else {
    document.getElementById(id)?.scrollIntoView({ behavior: 'smooth' })
  }
}

export default function Header({ user, cityLabel, onLogout, variant = 'light' }) {
  const [scrolled, setScrolled] = useState(false)
  const [menu, setMenu] = useState(false)
  const menuRef = useRef(null)

  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 10)
    onScroll()
    window.addEventListener('scroll', onScroll, { passive: true })
    return () => window.removeEventListener('scroll', onScroll)
  }, [])

  useEffect(() => {
    if (!menu) return undefined
    const close = (event) => {
      if (!menuRef.current?.contains(event.target)) setMenu(false)
    }
    document.addEventListener('mousedown', close)
    return () => document.removeEventListener('mousedown', close)
  }, [menu])

  const go = (path) => {
    setMenu(false)
    navigate(path)
  }

  return (
    <header className={`nav ${scrolled || variant === 'admin' ? 'scrolled' : ''}`}>
      <div className="wrap nav-in">
        <Logo />
        {variant === 'admin' ? (
          <span className="adm-tag">ADMIN</span>
        ) : (
          <nav className="nav-links" aria-label="Principal">
            <a href="#/" onClick={(e) => (e.preventDefault(), goToSection('catalogo'))}>
              Catálogo
            </a>
            <a href="#/" onClick={(e) => (e.preventDefault(), goToSection('como'))}>
              Como funciona
            </a>
            <a href="#/conta/jogos">Anunciar meu jogo</a>
          </nav>
        )}
        <div className="nav-right">
          {variant !== 'admin' && (
            <button className="city-pill" type="button" onClick={() => goToSection('buscar')} title="Alterar cidade">
              <Icon id="pin" />
              <span className="lbl">{cityLabel}</span>
            </button>
          )}
          {user ? (
            <div className="user-menu" ref={menuRef}>
              <button className="avatar-btn" type="button" onClick={() => setMenu((m) => !m)} aria-expanded={menu} aria-haspopup="menu">
                <span className={`avatar ${user.isAdmin ? 'admin' : ''}`}>{initials(user.name)}</span>
                <span className="who-name">{firstName(user.name)}</span>
              </button>
              {menu && (
                <div className="menu" role="menu">
                  <div className="menu-head">
                    <b>{user.name}</b>
                    <small>{user.email}</small>
                  </div>
                  <button role="menuitem" type="button" onClick={() => go('/conta')}>
                    Minhas locações
                  </button>
                  <button role="menuitem" type="button" onClick={() => go('/conta/jogos')}>
                    Meus jogos anunciados
                  </button>
                  <button role="menuitem" type="button" onClick={() => go('/conta/dados')}>
                    Minha conta
                  </button>
                  {user.isAdmin && (
                    <button role="menuitem" type="button" className="menu-admin" onClick={() => go('/admin')}>
                      Área do administrador
                    </button>
                  )}
                  <button role="menuitem" type="button" className="menu-out" onClick={() => (setMenu(false), onLogout())}>
                    Sair
                  </button>
                </div>
              )}
            </div>
          ) : (
            <a className="btn btn-ink" href={`#/entrar?next=${encodeURIComponent(window.location.hash.slice(1) || '/')}`}>
              Entrar
            </a>
          )}
        </div>
      </div>
    </header>
  )
}
