(() => {
  const A = window.App
  const state = {
    tab: 'items',
    items: [],
    total: 0,
    documents: [],
    queue: [],
    pendingLowConf: 0,
    searchResults: null,
  }

  const root = () => document.getElementById('page-root')

  function tabs() {
    const defs = [
      ['items', '知识条目'],
      ['documents', '文档知识'],
      ['review', '飞轮待审'],
    ]
    return `<div class="row" style="margin-bottom:14px">${defs.map(([key, label]) => (
      `<button class="btn ${state.tab === key ? 'btn-primary' : ''}" data-action="tab" data-tab="${key}">${label}</button>`
    )).join('')}</div>`
  }

  function itemsView() {
    return `
      <div class="card">
        <h2>新增知识 <span class="muted small">(${state.total} 条)</span></h2>
        <div class="grid grid-2">
          <div class="field"><label>分类</label><input class="input" id="kb-category" placeholder="退换货政策" /></div>
          <div class="field"><label>关键词</label><input class="input" id="kb-keywords" placeholder="退货,退款" /></div>
        </div>
        <div class="field"><label>问题</label><input class="input" id="kb-question" placeholder="商品可以退换吗" /></div>
        <div class="field"><label>答案</label><textarea class="textarea" id="kb-answer" placeholder="回答内容"></textarea></div>
        <div class="row">
          <button class="btn btn-primary" data-action="add-item">新增</button>
          <input class="input" id="kb-search" style="max-width:260px" placeholder="语义检索问题" />
          <button class="btn" data-action="search">检索</button>
        </div>
        <div id="kb-search-results" style="margin-top:12px">${searchResultsHtml()}</div>
      </div>
      <div class="card">
        <h2>知识列表</h2>
        <div class="table-wrap">
          <table class="table">
            <thead><tr><th>ID</th><th>分类</th><th>问题</th><th>向量</th><th>命中</th><th>操作</th></tr></thead>
            <tbody>
              ${state.items.map((item) => `
                <tr>
                  <td class="mono">${item.id}</td>
                  <td>${A.escapeHtml(item.category)}</td>
                  <td>${A.escapeHtml(item.question)}</td>
                  <td>${item.vector_id ? A.badge('已索引', 'green') : A.badge('未索引', 'red')}</td>
                  <td>${item.hit_count || 0}</td>
                  <td>
                    <button class="btn btn-sm" data-action="edit-item" data-id="${item.id}">编辑</button>
                    <button class="btn btn-sm btn-danger" data-action="delete-item" data-id="${item.id}">删除</button>
                  </td>
                </tr>`).join('') || '<tr><td colspan="6" class="empty">暂无知识条目</td></tr>'}
            </tbody>
          </table>
        </div>
      </div>`
  }

  function searchResultsHtml() {
    if (!state.searchResults) return ''
    if (!state.searchResults.length) return '<p class="muted small">没有检索结果</p>'
    return `<div class="grid">${state.searchResults.map((item) => `
      <div class="card" style="padding:12px">
        <div class="row"><strong>${A.escapeHtml(item.question || '')}</strong><span class="right mono small">${Number(item.score || 0).toFixed(3)}</span></div>
        <p class="muted small" style="margin:6px 0 0">${A.escapeHtml(item.answer || '')}</p>
      </div>`).join('')}</div>`
  }

  function documentsView() {
    return `
      <div class="card">
        <h2>导入 Markdown 文档</h2>
        <div class="field"><label>标题</label><input class="input" id="doc-title" placeholder="售后处理手册" /></div>
        <div class="field"><label>Markdown 内容</label><textarea class="textarea" id="doc-content" style="min-height:140px" placeholder="# 章节\n正文…"></textarea></div>
        <button class="btn btn-primary" data-action="import-doc">导入并切块</button>
        <p class="muted small" style="margin-top:8px">自动按标题分层、中文递归切块并写入 Milvus；同名文档会替换旧版本。</p>
      </div>
      <div class="card">
        <h2>文档知识</h2>
        <div class="table-wrap">
          <table class="table">
            <thead><tr><th>ID</th><th>标题</th><th>来源</th><th>片段</th><th>状态</th><th>创建时间</th><th>操作</th></tr></thead>
            <tbody>
              ${state.documents.map((item) => `
                <tr>
                  <td class="mono">${item.id}</td>
                  <td>${A.escapeHtml(item.title)}</td>
                  <td>${A.escapeHtml(item.source || '—')}</td>
                  <td>${item.chunks}</td>
                  <td>${A.badge(item.status || 'active')}</td>
                  <td class="small">${A.formatDate(item.created_at)}</td>
                  <td><button class="btn btn-sm btn-danger" data-action="delete-doc" data-id="${item.id}">删除</button></td>
                </tr>`).join('') || '<tr><td colspan="7" class="empty">暂无文档</td></tr>'}
            </tbody>
          </table>
        </div>
      </div>`
  }

  function reviewView() {
    return `
      <div class="card">
        <h2>知识飞轮待审 <span class="muted small">(低置信度待处理 ${state.pendingLowConf} 条)</span></h2>
        <p class="muted small">低置信度问题 → LLM 抽取候选 → 人工复核 → 采纳补库。</p>
        <button class="btn btn-primary" data-action="mine">从低置信度问题抽取候选</button>
      </div>
      <div class="card">
        <div class="table-wrap">
          <table class="table">
            <thead><tr><th>ID</th><th>问题</th><th>答案</th><th>状态</th><th>操作</th></tr></thead>
            <tbody>
              ${state.queue.map((item) => `
                <tr>
                  <td class="mono">${item.id}</td>
                  <td>${A.escapeHtml(item.question)}</td>
                  <td>${A.escapeHtml(item.answer)}</td>
                  <td>${A.badge(item.status)}</td>
                  <td>
                    <button class="btn btn-sm btn-primary" data-action="approve-review" data-id="${item.id}">采纳</button>
                    <button class="btn btn-sm btn-danger" data-action="discard-review" data-id="${item.id}">弃用</button>
                  </td>
                </tr>`).join('') || '<tr><td colspan="5" class="empty">暂无待审候选</td></tr>'}
            </tbody>
          </table>
        </div>
      </div>`
  }

  function render() {
    root().innerHTML = `
      <div class="page-head">
        <h1>知识库</h1>
        <p>知识条目、文档切块与知识飞轮人工复核</p>
      </div>
      ${tabs()}
      ${state.tab === 'items' ? itemsView() : state.tab === 'documents' ? documentsView() : reviewView()}`
  }

  async function loadItems() {
    const data = await A.api('/knowledge/list?page=1&page_size=100')
    state.items = data.items || []
    state.total = data.total || state.items.length
  }

  async function loadDocuments() {
    const data = await A.api('/knowledge/documents')
    state.documents = data.items || []
  }

  async function loadQueue() {
    const data = await A.api('/review/queue?status=extracted&limit=100')
    state.queue = data.items || []
    state.pendingLowConf = data.pending_low_confidence || 0
  }

  async function refresh() {
    try {
      if (state.tab === 'items') await loadItems()
      else if (state.tab === 'documents') await loadDocuments()
      else await loadQueue()
      render()
    } catch (error) {
      root().innerHTML = `<div class="alert">${A.escapeHtml(error.message)}</div>`
    }
  }

  async function handleAction(action, target) {
    const id = Number(target.dataset.id)
    if (action === 'tab') {
      state.tab = target.dataset.tab
      await refresh()
    } else if (action === 'add-item') {
      const category = document.getElementById('kb-category').value.trim()
      const question = document.getElementById('kb-question').value.trim()
      const answer = document.getElementById('kb-answer').value.trim()
      const keywords = document.getElementById('kb-keywords').value.trim()
      if (!category || !question || !answer) return A.toast('分类、问题、答案必填', 'error')
      await A.api('/knowledge/add', { method: 'POST', body: JSON.stringify({ category, question, answer, keywords }) })
      A.toast('知识已新增并向量化', 'success')
      await refresh()
    } else if (action === 'edit-item') {
      const item = state.items.find((row) => row.id === id)
      if (!item) return
      const question = prompt('问题', item.question)
      if (question === null) return
      const answer = prompt('答案', item.answer)
      if (answer === null) return
      const category = prompt('分类', item.category)
      if (category === null) return
      await A.api(`/knowledge/${id}`, { method: 'PUT', body: JSON.stringify({ question, answer, category }) })
      A.toast('已更新', 'success')
      await refresh()
    } else if (action === 'delete-item') {
      if (!confirm('确认删除该知识条目？')) return
      await A.api(`/knowledge/${id}`, { method: 'DELETE' })
      A.toast('已删除', 'success')
      await refresh()
    } else if (action === 'search') {
      const query = document.getElementById('kb-search').value.trim()
      if (!query) return
      const result = await A.api('/knowledge/search', { method: 'POST', body: JSON.stringify({ query, top_k: 5 }) })
      state.searchResults = result.results || []
      render()
      A.toast(`命中 ${state.searchResults.length} 条`, 'success')
    } else if (action === 'import-doc') {
      const title = document.getElementById('doc-title').value.trim()
      const content = document.getElementById('doc-content').value.trim()
      if (!title || !content) return A.toast('标题和内容必填', 'error')
      const result = await A.api('/knowledge/documents/import', {
        method: 'POST',
        body: JSON.stringify({ title, content, chunk_size: 500, overlap: 80 }),
      })
      A.toast(`已导入 ${result.chunks || 0} 个片段`, 'success')
      await refresh()
    } else if (action === 'delete-doc') {
      if (!confirm('确认删除该文档及其片段？')) return
      await A.api(`/knowledge/documents/${id}`, { method: 'DELETE' })
      A.toast('已删除', 'success')
      await refresh()
    } else if (action === 'mine') {
      const result = await A.api('/review/mine', { method: 'POST', body: '{}' })
      A.toast(`抽取完成：${result.extracted ?? result.total ?? 0} 条候选`, 'success')
      await refresh()
    } else if (action === 'approve-review') {
      await A.api(`/review/${id}/approve`, { method: 'POST', body: '{}' })
      A.toast('已采纳并补库', 'success')
      await refresh()
    } else if (action === 'discard-review') {
      await A.api(`/review/${id}/discard`, { method: 'POST', body: '{}' })
      A.toast('已弃用', 'success')
      await refresh()
    }
  }

  ;(async () => {
    const auth = await A.initPage('knowledge')
    if (!auth) return
    root().addEventListener('click', async (event) => {
      const target = event.target.closest('[data-action]')
      if (!target) return
      try {
        await handleAction(target.dataset.action, target)
      } catch (error) {
        A.toast(error.message, 'error')
      }
    })
    await refresh()
  })()
})()
