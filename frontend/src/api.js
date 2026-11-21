// Cliente mínimo da API de administração. O token fica só na sessão do separador (sessionStorage).

const TOKEN_KEY = 'costpilot-admin-token'

export function getToken() {
  try {
    return sessionStorage.getItem(TOKEN_KEY) || ''
  } catch {
    return '' // armazenamento bloqueado: o painel continua, o token é pedido de novo
  }
}

export function setToken(token) {
  try {
    sessionStorage.setItem(TOKEN_KEY, token)
  } catch {
    // sem armazenamento disponível: o token fica só em memória
  }
}

async function errorMessage(response) {
  try {
    const body = await response.json()
    return `${response.status} ${String(body.code ?? '')}: ${String(body.message ?? '')}`.trim()
  } catch {
    return `HTTP ${response.status}`
  }
}

export async function adminRequest(method, path, token, body) {
  const headers = { 'x-admin-token': token }
  if (body !== undefined) headers['Content-Type'] = 'application/json'
  const response = await fetch(path, {
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  if (!response.ok) throw new Error(await errorMessage(response))
  return response.json()
}

export const adminGet = (path, token) => adminRequest('GET', path, token)
export const adminPut = (path, token, body) => adminRequest('PUT', path, token, body)

/** Converte um montante em string decimal (vindo da API) para número, sem lançar excepções. */
export function toNumber(value) {
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : 0
}
