/** @file api.js @description Same-origin JSON requests and local display preferences. */
const API_BASE = import.meta.env.VITE_STATUS_API || '';

export async function request(path, options = {}) {
  const response = await fetch(`${API_BASE}${path}`, {
    credentials: 'same-origin', cache: 'no-store', ...options,
    headers: { 'Content-Type': 'application/json', ...options.headers },
  });
  const body = await response.json();
  if (!response.ok) {
    const error = new Error(body.error || `HTTP ${response.status}`);
    error.status = response.status;
    error.retryAfter = Number(response.headers.get('Retry-After') || 0);
    throw error;
  }
  return body;
}

export function post(path, body) {
  return request(path, { keepalive: body.action === 'release', method: 'POST', body: JSON.stringify(body) });
}

export function readPreference(key, fallback) {
  try { return JSON.parse(localStorage.getItem(`status-${key}`)) ?? fallback; }
  catch { return fallback; }
}
