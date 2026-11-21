import { adminPut, toNumber } from '../api.js'

export function TeamsPanel({ teams, token, onChanged }) {
  async function toggle(team, enabled) {
    await adminPut(`/admin/teams/${encodeURIComponent(team.team)}/autopilot`, token, {
      enabled: !enabled,
    })
    onChanged()
  }
  return (
    <section className="panel">
      <h2>Equipas e autopilot</h2>
      <table>
        <thead>
          <tr>
            <th>Equipa</th>
            <th>Orçamento</th>
            <th>Gasto</th>
            <th>Reservado</th>
            <th>Modelo fixo</th>
            <th>Autopilot</th>
          </tr>
        </thead>
        <tbody>
          {teams.map((t) => (
            <tr key={t.team}>
              <td>{t.team}</td>
              <td>{t.budget_usd}</td>
              <td>{t.spent_usd}</td>
              <td>{t.reserved_usd}</td>
              <td>{t.fixed_model}</td>
              <td>
                <button type="button" onClick={() => toggle(t, t.autopilot_enabled)}>
                  {t.autopilot_enabled ? 'ligado' : 'desligado'}
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  )
}

export function CostsPanel({ groups }) {
  const totals = new Map()
  for (const g of groups) {
    const key = `${String(g.team)} · ${String(g.provider)} · ${String(g.task_type)}`
    totals.set(key, (totals.get(key) ?? 0) + toNumber(g.cost_usd))
  }
  const rows = [...totals.entries()].sort((a, b) => b[1] - a[1])
  return (
    <section className="panel">
      <h2>Custo por equipa, provider e tarefa</h2>
      {rows.length === 0 ? (
        <p className="muted">Ainda sem tentativas registadas.</p>
      ) : (
        <table>
          <thead>
            <tr>
              <th>Equipa · provider · tarefa</th>
              <th>Custo (USD)</th>
            </tr>
          </thead>
          <tbody>
            {rows.map(([key, cost]) => (
              <tr key={key}>
                <td>{key}</td>
                <td>{cost.toFixed(6)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  )
}

export function RoutingPanel({ routing, reasons }) {
  const max = Math.max(1, ...routing.map((r) => toNumber(r.attempts)))
  return (
    <section className="panel">
      <h2>Distribuição de routing e motivos</h2>
      <ul className="bars">
        {routing.map((r) => (
          <li key={r.model}>
            <span>{r.model}</span>
            <span className="bar" style={{ width: `${(toNumber(r.attempts) / max) * 100}%` }} />
            <span>{r.attempts}</span>
          </li>
        ))}
      </ul>
      <h3>Motivos</h3>
      <ul>
        {reasons.map((r) => (
          <li key={r.reason}>
            {r.reason}: {r.attempts}
          </li>
        ))}
      </ul>
    </section>
  )
}

export function RecentPanel({ rows }) {
  return (
    <section className="panel">
      <h2>Últimas tentativas</h2>
      <table>
        <thead>
          <tr>
            <th>Tarefa</th>
            <th>#</th>
            <th>Modelo</th>
            <th>Estado</th>
            <th>Motivo</th>
            <th>Custo (USD)</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={`${r.task_id}-${r.attempt}-${i}`}>
              <td>{r.task_id}</td>
              <td>{r.attempt}</td>
              <td>{r.model}</td>
              <td>{r.status}</td>
              <td>{r.reason}</td>
              <td>{r.cost_usd}{r.cost_estimated ? ' (est.)' : ''}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  )
}
