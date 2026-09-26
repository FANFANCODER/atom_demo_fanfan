// API client with automatic 401 -> /login?redirect= handling
const API_BASE = ''

function redirectToLogin() {
  const here = encodeURIComponent(location.pathname + location.search)
  location.href = `/login?redirect=${here}`
}

export async function api(path, options = {}) {
  const res = await fetch(`${API_BASE}${path}`, {
    credentials: 'include',
    headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
    ...options,
  })
  if (res.status === 401) {
    redirectToLogin()
    throw new Error('Unauthorized')
  }
  return res
}

export async function apiJson(path, options = {}) {
  const res = await api(path, options)
  const text = await res.text()
  if (!res.ok) {
    let msg = res.statusText
    try { msg = JSON.parse(text).detail || msg } catch {}
    const err = new Error(msg)
    err.status = res.status
    throw err
  }
  return text ? JSON.parse(text) : null
}
