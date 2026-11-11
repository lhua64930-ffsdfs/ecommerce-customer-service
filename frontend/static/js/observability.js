(() => {
  const A = window.App
  const state = { overview: null, runs: [], cost: [] }
  const root = () => document.getElementById('page-root')

  function render() {
    const overview = state.overview
    const byStatus = overview?.runs?.by_status || {}
    const runTotal = overview?.runs?.total || 0
    const failedSteps = overview?.steps?.failed || 0
    const pending = overview?.low_confidence?.pending || 0
    const totalTokens = state.cost.reduce((sum, item) => sum + Number(item.tokens || 0), 0)
    root().innerHTML = `
      <div class="page-head">
        <h1>可观测</h1>
        <p>运行状态、失败工具、Token 成本与轨迹回放</p>
      </div>
      <div class="grid grid-4">
        <div class="card stat"><div class="stat-label">近 7 天运行</div><div class="stat-value">${runTotal}</div><div class="stat-note">Agent Run</div></div>
        <div class="card stat"><div class="stat-label">失败步骤</div><div class="stat-value">${failedSteps}</div><div class="stat-note">tool / model 步骤</div></div>
        <div class="card stat"><div class="stat-label">低置信度待审</div><div class="stat-value">${pending}</div><div class="stat-note">知识飞轮入口</div></div>
        <div class="card stat"><div class="stat-label">近 30 天 Token</div><div class="stat-value">${totalTokens}</div><div class="stat-note">本地近似值</div></div>
      </div>

      <div class="grid grid-2" style="margin-top:16px">
        <div class="card">
          <h2>运行状态</h2>
          ${Object.keys(byStatus).length ? Object.entries(byStatus).map(([status, item]) => `
            <div class="row" style="justify-content:space-between;padding:6px 0;border-bottom:1px solid var(--rule)">
              <span>${A.badge(status)}</span>
              <span class="mono small">${item.count} 次 · ${item.total_tokens} tokens · ${item.avg_latency_ms} ms</span>
            </div>`).join('') : '<p class="muted">暂无运行数据</p>'}
        </div>
        <div class="card">
          <h2>失败工具 Top</h2>
          ${A.bars((overview?.steps?.top_failing_tools || []).map((item) => ({
            name: item.name, count: item.failed,
          })), 'red')}
        </div>
      </div>

      <div class="card" style="margin-top:16px">
        <h2>最近运行</h2>
        <div class="table-wrap">
          <table class="table">
            <thead><tr><th>run_id</th><th>状态</th><th>模式</th><th>步骤</th><th>耗时</th><th>Token</th><th>开始时间</th></tr></thead>
            <tbody>
              ${state.runs.map((run) => `
                <tr>
                  <td class="mono small">${A.escapeHtml(run.run_id)}</td>
                  <td>${A.badge(run.status, run.status === 'failed' ? 'red' : 'green')}</td>
                  <td>${A.escapeHtml(run.agent_mode)}</td>
                  <td>${run.total_steps}</td>
                  <td>${run.total_latency_ms} ms</td>
                  <td>${run.total_tokens}</td>
                  <td class="small">${A.formatDate(run.started_at)}</td>
                </tr>`).join('') || '<tr><td colspan="7" class="empty">暂无运行记录</td></tr>'}
            </tbody>
          </table>
        </div>
      </div>

      <div class="card">
        <h2>按天 Token</h2>
        <div class="table-wrap">
          <table class="table">
            <thead><tr><th>日期</th><th>运行数</th><th>Token</th></tr></thead>
            <tbody>
              ${state.cost.map((item) => `
                <tr><td class="mono">${A.escapeHtml(item.date)}</td><td>${item.runs}</td><td>${item.tokens}</td></tr>
              `).join('') || '<tr><td colspan="3" class="empty">暂无数据</td></tr>'}
            </tbody>
          </table>
        </div>
        <p class="muted small" style="margin-top:8px">Langfuse：${overview?.langfuse_enabled ? '已启用' : '未配置'}。权威成本以 Langfuse 为准。</p>
      </div>`
  }

  ;(async () => {
    const auth = await A.initPage('observability')
    if (!auth) return
    root().innerHTML = '<div class="empty">加载中…</div>'
    try {
      const [overview, runs, cost] = await Promise.all([
        A.api('/observability/overview?days=7'),
        A.api('/observability/runs?days=7&limit=50'),
        A.api('/observability/cost?days=30'),
      ])
      state.overview = overview
      state.runs = runs.items || []
      state.cost = cost.items || []
      render()
    } catch (error) {
      root().innerHTML = `<div class="alert">${A.escapeHtml(error.message)}</div>`
    }
  })()
})()
