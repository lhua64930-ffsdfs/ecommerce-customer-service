(() => {
  const A = window.App
  const state = { sessions: [], total: 0, history: null, historySession: '' }
  const root = () => document.getElementById('page-root')

  function render() {
    root().innerHTML = `
      <div class="page-head">
        <h1>会话记录</h1>
        <p>历史会话与完整对话回放</p>
      </div>
      <div class="card">
        <div class="table-wrap">
          <table class="table">
            <thead><tr><th>会话</th><th>用户</th><th>状态</th><th>消息数</th><th>满意度</th><th>开始时间</th><th>操作</th></tr></thead>
            <tbody>
              ${state.sessions.map((item) => `
                <tr>
                  <td class="mono small">${A.escapeHtml(item.session_id)}</td>
                  <td>${item.user_id ?? '—'}</td>
                  <td>${A.badge(item.status, item.status === 'transferred' ? 'red' : 'green')}</td>
                  <td>${item.message_count}</td>
                  <td>${item.satisfaction_score ?? '—'}</td>
                  <td class="small">${A.formatDate(item.started_at)}</td>
                  <td>
                    <button class="btn btn-sm" data-action="history" data-id="${A.escapeHtml(item.session_id)}">回放</button>
                    <button class="btn btn-sm" data-action="continue" data-id="${A.escapeHtml(item.session_id)}">继续</button>
                  </td>
                </tr>`).join('') || '<tr><td colspan="7" class="empty">暂无会话</td></tr>'}
            </tbody>
          </table>
        </div>
      </div>
      ${state.history ? `
        <div class="card">
          <h2>对话回放 · <span class="mono small">${A.escapeHtml(state.historySession)}</span></h2>
          <div style="max-height:460px;overflow:auto">
            ${(state.history.messages || []).map((item) => `
              <div class="msg ${item.sender_type === 'user' ? 'user' : 'bot'}">
                <div>
                  <div class="bubble">${A.escapeHtml(item.content)}</div>
                  ${(item.citations || []).map((citation) => (
                    `<span class="citation">📖 ${A.escapeHtml(citation.question || citation.category || citation.id)} (${Number(citation.score || 0).toFixed(2)})</span>`
                  )).join('')}
                  <div class="msg-meta">
                    ${A.badge(item.sender_type === 'user' ? '用户' : '客服')}
                    ${item.intent ? A.badge(item.intent.intent_name || item.intent.intent_code) : ''}
                    ${item.pending_approval ? A.badge(`申请 ${item.pending_approval.status || 'pending'}`, 'gold') : ''}
                    <span>${A.formatDate(item.created_at)}</span>
                  </div>
                </div>
              </div>`).join('') || '<p class="empty">没有消息</p>'}
          </div>
        </div>` : ''}`
  }

  async function load() {
    const data = await A.api('/analytics/sessions?page=1&page_size=50')
    state.sessions = data.items || []
    state.total = data.total || state.sessions.length
    render()
  }

  async function handle(action, target) {
    const sessionId = target.dataset.id
    if (action === 'history') {
      const history = await A.api(`/chat/history?session_id=${encodeURIComponent(sessionId)}&page=1&page_size=100`)
      state.history = history
      state.historySession = sessionId
      render()
      const panel = root().querySelector('.card:last-child')
      if (panel) panel.scrollIntoView({ behavior: 'smooth' })
    } else if (action === 'continue') {
      A.setSessionId(sessionId)
      location.href = '/'
    }
  }

  ;(async () => {
    const auth = await A.initPage('sessions')
    if (!auth) return
    root().addEventListener('click', async (event) => {
      const target = event.target.closest('[data-action]')
      if (!target) return
      try { await handle(target.dataset.action, target) } catch (error) { A.toast(error.message, 'error') }
    })
    try { await load() } catch (error) { root().innerHTML = `<div class="alert">${A.escapeHtml(error.message)}</div>` }
  })()
})()
