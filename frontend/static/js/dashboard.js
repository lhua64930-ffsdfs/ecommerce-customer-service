(() => {
  const A = window.App

  function renderSummary(summary) {
    const root = document.getElementById('page-root')
    const rate = (value) => `${(Number(value || 0) * 100).toFixed(1)}%`
    root.innerHTML = `
      <div class="page-head">
        <h1>数据看板</h1>
        <p>会话、消息、AI 解决率、转人工率与意图/情感分布</p>
      </div>
      <div class="grid grid-4">
        ${[
          ['会话总量', summary.sessions_total, '累计受理'],
          ['今日会话', summary.sessions_today, '自然日'],
          ['消息总量', summary.messages_total, '含用户与机器人'],
          ['用户总数', summary.users_total, '注册用户'],
          ['AI 解决率', rate(summary.ai_resolution_rate), '未转人工占比'],
          ['转人工率', rate(summary.transfer_rate), '机器人消息中触发转接'],
          ['满意度', summary.satisfaction_avg ?? '—', '1–5 分'],
          ['待处理工单', summary.open_tickets, 'pending / processing'],
        ].map(([label, value, note]) => `
          <div class="card stat">
            <div class="stat-label">${label}</div>
            <div class="stat-value">${A.escapeHtml(value)}</div>
            <div class="stat-note">${note}</div>
          </div>`).join('')}
      </div>
      <div class="grid grid-2" style="margin-top:16px">
        <div class="card">
          <h2>意图分布</h2>
          ${A.bars(summary.intent_distribution || [])}
        </div>
        <div class="card">
          <h2>情感分布</h2>
          ${A.bars((summary.sentiment_distribution || []).map((item) => ({
            name: { positive: '积极', neutral: '中性', negative: '负向' }[item.name] || item.name,
            count: item.count,
          })), 'red')}
        </div>
      </div>`
  }

  ;(async () => {
    const auth = await A.initPage('dashboard')
    if (!auth) return
    const root = document.getElementById('page-root')
    root.innerHTML = '<div class="empty">加载中…</div>'
    try {
      renderSummary(await A.api('/analytics/summary'))
    } catch (error) {
      root.innerHTML = `<div class="alert">${A.escapeHtml(error.message)}</div>`
    }
  })()
})()
