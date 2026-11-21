import { toNumber } from '../api.js'

// Gráfico SVG custo vs taxa de resolução, por política. Os valores são SIMULADOS (mock).
export default function CostQualityChart({ policies }) {
  const points = Object.entries(policies ?? {}).map(([name, summary]) => ({
    name,
    cost: toNumber(summary?.all?.total_cost_usd),
    resolved: toNumber(summary?.all?.resolved_rate),
  }))
  if (points.length === 0) return <p className="muted">Sem dados de benchmark.</p>

  const width = 480
  const height = 260
  const pad = 44
  const maxCost = Math.max(...points.map((p) => p.cost), 1e-9)
  const x = (cost) => pad + (cost / maxCost) * (width - pad * 2)
  const y = (rate) => height - pad - rate * (height - pad * 2)

  return (
    <figure>
      <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label="Custo versus taxa de resolução">
        <line x1={pad} y1={height - pad} x2={width - pad} y2={height - pad} className="axis" />
        <line x1={pad} y1={pad} x2={pad} y2={height - pad} className="axis" />
        <text x={width / 2} y={height - 8} className="label">custo total (USD, simulado)</text>
        <text x={12} y={pad - 12} className="label">resolvidas</text>
        {points.map((p) => (
          <g key={p.name}>
            <circle cx={x(p.cost)} cy={y(p.resolved)} r={6} className="point" />
            <text x={x(p.cost) + 10} y={y(p.resolved) - 8} className="label">{p.name}</text>
          </g>
        ))}
      </svg>
      <figcaption className="muted">Simulado: providers mock com preços fictícios.</figcaption>
    </figure>
  )
}
