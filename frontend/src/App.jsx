import { useCallback, useEffect, useState } from 'react'
import { adminGet, getToken, setToken } from './api.js'
import ErrorBoundary from './components/ErrorBoundary.jsx'
import CostQualityChart from './components/CostQualityChart.jsx'
import { CostsPanel, RecentPanel, RoutingPanel, TeamsPanel } from './components/Panels.jsx'

export default function App() {
  const [token, setTokenState] = useState(getToken())
  const [data, setData] = useState(null)
  const [error, setError] = useState('')

  const load = useCallback(async (currentToken) => {
    if (!currentToken) return
    try {
      const [teams, usage, recent, benchmark] = await Promise.all([
        adminGet('/admin/teams', currentToken),
        adminGet('/admin/usage/summary', currentToken),
        adminGet('/admin/usage/recent?limit=50', currentToken),
        adminGet('/admin/benchmark', currentToken).catch(() => null),
      ])
      setData({ teams, usage, recent, benchmark })
      setError('')
    } catch (err) {
      setError(String(err.message ?? err))
    }
  }, [])

  useEffect(() => {
    load(token)
  }, [token, load])

  function submit(event) {
    event.preventDefault()
    const value = String(new FormData(event.currentTarget).get('token') ?? '').trim()
    setToken(value)
    setTokenState(value)
  }

  if (!token) {
    return (
      <main className="login">
        <h1>CostPilot</h1>
        <form onSubmit={submit}>
          <label>
            Token de administração
            <input name="token" type="password" autoComplete="off" required />
          </label>
          <button type="submit">Entrar</button>
        </form>
      </main>
    )
  }

  return (
    <main>
      <header>
        <h1>CostPilot — painel</h1>
        <button type="button" onClick={() => load(token)}>Actualizar</button>
      </header>
      {error && <p className="error" role="alert">{error}</p>}
      {data && (
        <div className="grid">
          <ErrorBoundary title="Equipas">
            <TeamsPanel teams={data.teams} token={token} onChanged={() => load(token)} />
          </ErrorBoundary>
          <ErrorBoundary title="Custos">
            <CostsPanel groups={data.usage.groups} />
          </ErrorBoundary>
          <ErrorBoundary title="Routing">
            <RoutingPanel routing={data.usage.routing} reasons={data.usage.reasons} />
          </ErrorBoundary>
          <ErrorBoundary title="Custo vs qualidade">
            <section className="panel">
              <h2>Custo vs qualidade (benchmark simulado)</h2>
              <CostQualityChart policies={data.benchmark?.policies} />
            </section>
          </ErrorBoundary>
          <ErrorBoundary title="Recentes">
            <RecentPanel rows={data.recent} />
          </ErrorBoundary>
        </div>
      )}
    </main>
  )
}
