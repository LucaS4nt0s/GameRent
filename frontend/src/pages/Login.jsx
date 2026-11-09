import { useState } from 'react'
import { DEMO_USERS, useAuth } from '../auth.jsx'
import { navigate } from '../router.js'

export default function Login({ next = '/' }) {
  const auth = useAuth()
  const [name, setName] = useState('')
  const [email, setEmail] = useState('')

  function finish(session) {
    navigate(next.startsWith('/admin') && !session.isAdmin ? '/' : next)
  }

  return (
    <main className="wrap login">
      <div className="login-card">
        <h1>Entrar no Jogaí</h1>
        {auth.provider === 'cognito' ? (
          <>
            <p className="lead">Você vai para a página segura de login e volta para cá em seguida.</p>
            <button className="btn btn-brick wide" type="button" onClick={auth.loginCognito}>
              Entrar ou criar conta
            </button>
            {auth.error && <p className="form-error">{auth.error}</p>}
          </>
        ) : (
          <>
            <p className="lead">Use seu nome e e-mail para alugar e anunciar jogos.</p>
            <form
              className="login-form"
              onSubmit={(event) => {
                event.preventDefault()
                finish(auth.loginLocal({ name, email }))
              }}
            >
              <label>
                <span>Seu nome</span>
                <input value={name} onChange={(e) => setName(e.target.value)} required autoComplete="name" placeholder="Maria Eduarda" />
              </label>
              <label>
                <span>E-mail</span>
                <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} required autoComplete="email" placeholder="voce@exemplo.com" />
              </label>
              <button className="btn btn-brick wide" type="submit">
                Entrar
              </button>
            </form>
            <div className="demo">
              <span>Contas de demonstração</span>
              <div>
                {DEMO_USERS.map((demo) => (
                  <button key={demo.email} type="button" className="btn btn-line" onClick={() => finish(auth.loginLocal(demo))}>
                    {demo.label}
                  </button>
                ))}
              </div>
            </div>
            <p className="fine">
              Modo de desenvolvimento: o login fica só neste navegador. Em produção, o Jogaí usa o Amazon Cognito.
            </p>
          </>
        )}
      </div>
    </main>
  )
}
