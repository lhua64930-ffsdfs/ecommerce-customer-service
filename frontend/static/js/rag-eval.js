(() => {
  const A = window.App
  const state = { overview: null, jobs: [], log: '', logName: '' }

  const root = () => document.getElementById('page-root')

  function strategyRows(overview) {
    const strategies = overview?.rag?.strategies || {}
    const names = Object.keys(strategies)
    if (!names.length) return '<tr><td colspan="5" class="empty">暂无评测结果，请先运行评测作业</td></tr>'
    const fmt = (value) => (value == null ? '—' : Number(value).toFixed(4))
    return names.map((name) => {
      const report = strategies[name] || {}
      return `<tr>
        <td>${A.escapeHtml(name)}${overview.best_strategy?.name === name ? ' ' + A.badge('最佳', 'green') : ''}</td>
        <td class="mono">${fmt(report.recall_at_1)}</td>
        <td class="mono">${fmt(report.recall_at_3)}</td>
        <td class="mono">${fmt(report.recall_at_5)}</td>
        <td class="mono">${fmt(report.mrr_at_5)}</td>
      </tr>`
    }).join('')
  }

  function refusalText(overview) {
    const refusal = overview?.refusal
    if (!refusal) return '暂无拒答评测结果'
    const total = refusal.total ?? refusal.samples ?? '—'
    const correct = refusal.correct ?? refusal.refused ?? '—'
    const rate = refusal.refusal_rate ?? refusal.accuracy
    return `拒答 ${correct}/${total}${rate != null ? ` · ${(Number(rate) * 100).toFixed(2)}%` : ''}`
  }

  function jobButtons(job) {
    const running = job.status === 'running'
    return `<button class="btn btn-sm ${running ? 'btn-danger' : 'btn-primary'}" data-action="job-start" data-name="${job.name}" ${running ? 'disabled' : ''}>${running ? '运行中' : '运行'}</button>
      <button class="btn btn-sm" data-action="job-log" data-name="${job.name}">日志</button>`
  }

  function render() {
    const overview = state.overview
    root().innerHTML = `
      <div class="page-head">
        <h1>RAG 评测</h1>
        <p>四策略 Recall@1/3/5、MRR@5 与无答案拒答率</p>
      </div>
      <div class="grid grid-4">
        <div class="card stat">
          <div class="stat-label">评测状态</div>
          <div class="stat-value">${overview?.present ? '已生成' : '缺失'}</div>
          <div class="stat-note">${A.formatDate(overview?.rag_generated_at)}</div>
        </div>
        <div class="card stat">
          <div class="stat-label">最佳策略</div>
          <div class="stat-value" style="font-size:20px">${A.escapeHtml(overview?.best_strategy?.name || '—')}</div>
          <div class="stat-note">MRR@5 ${overview?.best_strategy?.mrr_at_5 ?? '—'}</div>
        </div>
        <div class="card stat">
          <div class="stat-label">拒答评测</div>
          <div class="stat-value" style="font-size:18px">${refusalText(overview)}</div>
          <div class="stat-note">${A.formatDate(overview?.refusal_generated_at)}</div>
        </div>
        <div class="card stat">
          <div class="stat-label">评测命令</div>
          <div class="stat-note mono" style="margin-top:8px">${A.escapeHtml(overview?.commands?.rag || '—')}</div>
        </div>
      </div>

      <div class="card" style="margin-top:16px">
        <h2>检索策略对照</h2>
        <div class="table-wrap">
          <table class="table">
            <thead><tr><th>策略</th><th>Recall@1</th><th>Recall@3</th><th>Recall@5</th><th>MRR@5</th></tr></thead>
            <tbody>${strategyRows(overview)}</tbody>
          </table>
        </div>
      </div>

      <div class="card">
        <h2>后台作业</h2>
        <div class="table-wrap">
          <table class="table">
            <thead><tr><th>作业</th><th>说明</th><th>状态</th><th>操作</th></tr></thead>
            <tbody>
              ${(state.jobs || []).map((job) => `
                <tr>
                  <td>${A.escapeHtml(job.title || job.name)}</td>
                  <td class="small muted">${A.escapeHtml(job.description || '')}</td>
                  <td>${A.badge(job.status, job.status === 'failed' ? 'red' : job.status === 'succeeded' ? 'green' : 'gold')}</td>
                  <td>${jobButtons(job)}</td>
                </tr>`).join('') || '<tr><td colspan="4" class="empty">暂无作业</td></tr>'}
            </tbody>
          </table>
        </div>
      </div>

      ${state.log ? `
        <div class="card">
          <h2>作业日志 · ${A.escapeHtml(state.logName)}</h2>
          <pre class="mono small" style="white-space:pre-wrap;max-height:360px;overflow:auto">${A.escapeHtml(state.log)}</pre>
        </div>` : ''}`
  }

  async function load() {
    const [overview, jobs] = await Promise.all([
      A.api('/rag-eval/overview'),
      A.api('/jobs'),
    ])
    state.overview = overview
    state.jobs = jobs.jobs || []
    render()
  }

  async function handle(action, target) {
    const name = target.dataset.name
    if (action === 'job-start') {
      await A.api(`/jobs/${encodeURIComponent(name)}`, { method: 'POST', body: '{}' })
      A.toast(`作业 ${name} 已启动`, 'success')
      await load()
    } else if (action === 'job-log') {
      const job = await A.api(`/jobs/${encodeURIComponent(name)}`)
      state.logName = name
      state.log = job.log || '暂无日志'
      render()
    }
  }

  ;(async () => {
    const auth = await A.initPage('rag-eval')
    if (!auth) return
    root().addEventListener('click', async (event) => {
      const target = event.target.closest('[data-action]')
      if (!target) return
      try { await handle(target.dataset.action, target) } catch (error) { A.toast(error.message, 'error') }
    })
    try { await load() } catch (error) { root().innerHTML = `<div class="alert">${A.escapeHtml(error.message)}</div>` }
  })()
})()
