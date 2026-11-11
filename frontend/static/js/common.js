const API_BASE = '/api/v1'
const TOKEN_KEY = 'after_sales_token'
const USER_KEY = 'after_sales_user'
const SESSION_KEY = 'after_sales_session_id'

const getToken = () => {
  try { return localStorage.getItem(TOKEN_KEY) } catch { return null }
}
const setToken = (token) => {
  try { localStorage.setItem(TOKEN_KEY, token) } catch { /* ignore */ }
}
const clearToken = () => {
  try { localStorage.removeItem(TOKEN_KEY) } catch { /* ignore */ }
}
const getStoredUser = () => {
  try { return JSON.parse(localStorage.getItem(USER_KEY) || 'null') } catch { return null }
}
const setStoredUser = (user) => {
  try {
    if (user) localStorage.setItem(USER_KEY, JSON.stringify(user))
    else localStorage.removeItem(USER_KEY)
  } catch { /* ignore */ }
}

function escapeHtml(value) {
  return String(value ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;')
}

function formatDate(value) {
  if (!value) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return String(value)
  return date.toLocaleString('zh-CN', { hour12: false })
}

function toast(message, type = 'info') {
  let box = document.getElementById('toast-box')
  if (!box) {
    box = document.createElement('div')
    box.id = 'toast-box'
    box.className = 'toast-box'
    document.body.appendChild(box)
  }
  const item = document.createElement('div')
  item.className = `toast toast-${type}`
  item.textContent = message
  box.appendChild(item)
  setTimeout(() => item.remove(), 3600)
}

async function api(path, options = {}) {
  const headers = { 'Content-Type': 'application/json', ...(options.headers || {}) }
  const token = getToken()
  if (token) headers.Authorization = `Bearer ${token}`
  const response = await fetch(`${API_BASE}${path}`, { ...options, headers })
  const text = await response.text()
  let data = {}
  try { data = text ? JSON.parse(text) : {} } catch { data = { detail: text } }
  if (response.status === 401 && !path.startsWith('/auth/')) {
    clearToken()
    setStoredUser(null)
    if (location.pathname !== '/login') location.href = '/login'
    throw new Error('登录已失效')
  }
  if (!response.ok) {
    const detail = data?.detail
    const message = typeof detail === 'string'
      ? detail
      : (detail?.message || detail?.code || `请求失败 (${response.status})`)
    throw new Error(message)
  }
  return data
}

async function ensureAuth() {
  let config
  try {
    config = await api('/auth/config')
  } catch {
    config = { auth_enabled: false, registration_enabled: false }
  }
  if (!config.auth_enabled) return { enabled: false, user: null, config }
  if (!getToken()) {
    location.href = `/login?next=${encodeURIComponent(location.pathname)}`
    return null
  }
  try {
    const user = await api('/auth/me')
    setStoredUser(user)
    return { enabled: true, user, config }
  } catch {
    clearToken()
    setStoredUser(null)
    location.href = `/login?next=${encodeURIComponent(location.pathname)}`
    return null
  }
}

const NAV_ITEMS = [
  { href: '/', label: '在线客服', scope: 'public' },
  { href: '/dashboard', label: '数据看板', scope: 'admin' },
  { href: '/knowledge', label: '知识库', scope: 'admin' },
  { href: '/rag-eval', label: 'RAG 评测', scope: 'admin' },
  { href: '/observability', label: '可观测', scope: 'admin' },
  { href: '/sessions', label: '会话记录', scope: 'staff' },
]

function renderShell(user, active) {
  const enabled = Boolean(user)
  const roles = user?.roles || []
  const isAdmin = !enabled || roles.includes('admin')
  const isStaff = !enabled || roles.includes('admin') || roles.includes('agent')
  const currentPath = active === 'chat' ? '/' : `/${active}`
  const nav = NAV_ITEMS.filter((item) => {
    if (item.scope === 'admin') return isAdmin
    if (item.scope === 'staff') return isStaff
    return true
  }).map((item) => (
    `<a class="nav-link ${item.href === currentPath ? 'active' : ''}" href="${item.href}">${item.label}</a>`
  )).join('')
  const userText = enabled
    ? `${escapeHtml(user.display_name || user.username)} · ${escapeHtml(roles.join('/'))}`
    : '本地演示'
  const logout = enabled ? '<button class="btn btn-ghost" id="logout-btn">退出</button>' : ''
  const shell = document.getElementById('app-shell')
  if (!shell) return
  shell.innerHTML = `
    <header class="topbar">
      <div class="brand">
        <span class="brand-mark">售</span>
        <span>售后智答</span>
      </div>
      <nav class="nav">${nav}</nav>
      <div class="topbar-user"><span>${userText}</span>${logout}</div>
    </header>
    <main class="page" id="page-root"></main>
  `
  const btn = document.getElementById('logout-btn')
  if (btn) {
    btn.addEventListener('click', () => {
      clearToken()
      setStoredUser(null)
      location.href = '/login'
    })
  }
}

async function initPage(active) {
  const auth = await ensureAuth()
  if (!auth) return null
  renderShell(auth.user, active)
  return auth
}

function getSessionId() {
  try { return localStorage.getItem(SESSION_KEY) } catch { return null }
}
function setSessionId(value) {
  try {
    if (value) localStorage.setItem(SESSION_KEY, value)
    else localStorage.removeItem(SESSION_KEY)
  } catch { /* ignore */ }
}

function badge(text, tone = '') {
  return `<span class="tag ${tone ? `tag-${tone}` : ''}">${escapeHtml(text)}</span>`
}

function bars(items, tone = '') {
  const max = Math.max(1, ...items.map((item) => Number(item.count) || 0))
  return items.length
    ? items.map((item) => `
        <div class="bar-row">
          <span class="bar-label">${escapeHtml(item.name)}</span>
          <span class="bar-track"><span class="bar-fill ${tone}" style="width:${Math.max(2, (Number(item.count) / max) * 100)}%"></span></span>
          <span class="bar-value">${item.count}</span>
        </div>`).join('')
    : '<p class="muted">暂无数据</p>'
}

window.App = {
  API_BASE, getToken, setToken, clearToken, getStoredUser, setStoredUser,
  api, ensureAuth, initPage, escapeHtml, formatDate, toast, badge, bars,
  getSessionId, setSessionId,
}
