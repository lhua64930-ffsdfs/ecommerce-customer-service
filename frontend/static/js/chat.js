(() => {
  const A = window.App
  const state = {
    sessionId: null,
    messages: [],
    quickReplies: [],
    typing: false,
    sentiment: null,
    sentimentScore: 0,
  }
  let root
  let messagesEl
  let quickEl
  let sentimentEl

  const sessionCode = () => (state.sessionId ? state.sessionId.slice(0, 8).toUpperCase() : '待接入')

  function shellHtml() {
    return `
      <div class="chat-shell">
        <div class="chat-body">
          <header class="chat-head">
            <div class="chat-stamp">售后</div>
            <div class="chat-title">
              <div class="chat-kicker">AFTER-SALES DESK / 受理台</div>
              <strong>智能客服小e</strong>
              <span class="muted small"><span class="dot online"></span>在线受理中</span>
            </div>
            <div class="chat-meta">
              <span>受理编号 <span id="session-code">${sessionCode()}</span></span>
              <span>WEB · 7×24</span>
            </div>
          </header>
          <div id="sentiment" class="sentiment" style="display:none"></div>
          <div id="messages" class="messages"></div>
          <div id="quick-replies" class="quick-replies"></div>
          <form id="composer" class="composer">
            <textarea id="chat-input" rows="1" placeholder="请输入您的问题，例如：查订单 ORDER20260401001"></textarea>
            <button class="btn btn-primary" type="submit">发送</button>
          </form>
        </div>
      </div>`
  }

  async function ensureSession() {
    let id = A.getSessionId()
    if (id) {
      state.sessionId = id
      try {
        const history = await A.api(`/chat/history?session_id=${encodeURIComponent(id)}&page=1&page_size=100`)
        state.messages = (history.messages || []).map((item) => ({
          role: item.sender_type === 'user' ? 'user' : 'bot',
          content: item.content,
          citations: item.citations || [],
          pendingApproval: item.pending_approval || null,
          intent: item.intent,
          sentiment: item.sentiment,
          time: item.created_at,
        }))
      } catch {
        A.setSessionId(null)
        state.messages = []
      }
    }
    if (!state.messages.length) {
      const created = await A.api('/chat/session', { method: 'POST', body: '{}' })
      state.sessionId = created.session.session_id
      A.setSessionId(state.sessionId)
      state.messages = [{
        role: 'bot',
        content: created.welcome_message,
        citations: [],
        time: new Date().toISOString(),
      }]
      state.quickReplies = created.quick_replies || []
    }
  }

  function render() {
    if (!messagesEl) return
    const codeEl = document.getElementById('session-code')
    if (codeEl) codeEl.textContent = sessionCode()
    const welcome = state.messages.length <= 1
    messagesEl.innerHTML = welcome ? welcomeHtml() : state.messages.map(messageHtml).join('')
    quickEl.innerHTML = (state.quickReplies || [])
      .map((text) => `<button data-action="quick" data-text="${A.escapeHtml(text)}">${A.escapeHtml(text)}</button>`)
      .join('')
    messagesEl.scrollTop = messagesEl.scrollHeight
  }

  function welcomeHtml() {
    const services = [
      ['📦', '查订单', '订单 / 物流 / 收货信息', '我想查一下我的订单'],
      ['🛍️', '商品咨询', '价格 / 库存 / 活动', '有什么优惠活动吗'],
      ['💰', '退款退货', '取消 / 退款 / 退货', '如何申请退款'],
      ['👤', '转人工', '复杂问题 / 人工受理', '转人工客服'],
    ]
    return `
      <section class="welcome">
        <div class="welcome-kicker">SERVICE REQUEST / 受理单</div>
        <h2>今天需要处理什么?</h2>
        <p>我可以帮您查询订单、了解商品信息、解答售后问题等</p>
        <div class="quick-services">
          ${services.map(([icon, name, hint, text]) => `
            <button class="service-slip" data-action="quick" data-text="${A.escapeHtml(text)}">
              <span class="slip-icon">${icon}</span>
              <span class="slip-body"><span class="slip-name">${name}</span><span class="slip-hint">${hint}</span></span>
              <span class="slip-index">→</span>
            </button>`).join('')}
        </div>
        <p class="muted small">订单查询会校验归属；涉及资金的操作会先与您确认。</p>
      </section>`
  }

  function approvalHtml(msg, index) {
    const approval = msg.pendingApproval
    if (!approval) return ''
    const status = approval.status || 'pending'
    const pending = status === 'pending'
    return `
      <div class="approval">
        <h3>售后申请 · ${A.escapeHtml(approval.action)}</h3>
        <p style="margin:0 0 6px">${A.escapeHtml(approval.summary || '')}</p>
        <div class="row">
          ${A.badge(`风险 ${approval.risk_level}`, approval.risk_level === 'high' ? 'red' : 'gold')}
          ${A.badge(status, pending ? 'gold' : 'green')}
          ${approval.requires_human ? A.badge('需人工审核', 'red') : ''}
        </div>
        ${pending ? `
          ${approval.requires_verification && !msg.approvalVerified ? `
            <div class="row" style="margin-top:10px">
              <input class="input" style="flex:1" id="verify-order-${index}" placeholder="订单号" value="${A.escapeHtml(approval.order_no || '')}" />
              <input class="input" style="width:130px" id="verify-phone-${index}" placeholder="手机后四位" maxlength="4" />
              <button class="btn" data-action="verify" data-index="${index}">核验</button>
            </div>` : `<p class="muted small">${approval.requires_verification ? '✅ 订单已核验' : ''}</p>`}
          ${approval.requires_human ? `<input class="input" style="margin-top:8px" id="reviewer-${index}" placeholder="客服工号（高风险必填）" />` : ''}
          <div class="approval-actions">
            <button class="btn btn-primary" data-action="approve" data-index="${index}">确认执行</button>
            <button class="btn btn-danger" data-action="reject" data-index="${index}">拒绝</button>
          </div>` : ''}
      </div>`
  }

  function interruptHtml(msg, index) {
    const interrupt = msg.interrupt
    if (!interrupt) return ''
    if (interrupt.type === 'select_order') {
      return `
        <div class="card-inline">
          <h3>请选择要办理的订单</h3>
          ${(interrupt.orders || []).map((order) => `
            <button class="order-option" data-action="select-order" data-index="${index}" data-order="${A.escapeHtml(order.order_no)}">
              <strong>${A.escapeHtml(order.order_no)}</strong>
              <span>${A.escapeHtml(order.product_name || '订单')} · ${A.escapeHtml(order.status || '')}</span>
            </button>`).join('') || '<p class="muted small">没有可选订单</p>'}
        </div>`
    }
    if (interrupt.type === 'confirm_ticket') {
      const preview = interrupt.preview || {}
      return `
        <div class="card-inline">
          <h3>确认创建工单</h3>
          <p class="small">${A.escapeHtml(preview.content || preview.title || '请确认是否提交工单')}</p>
          <div class="row">
            <button class="btn btn-primary" data-action="confirm-ticket" data-index="${index}" data-confirm="1">确认提交</button>
            <button class="btn" data-action="confirm-ticket" data-index="${index}" data-confirm="0">取消</button>
          </div>
        </div>`
    }
    return ''
  }

  function messageHtml(msg, index) {
    const isUser = msg.role === 'user'
    const citations = (msg.citations || []).map((c) => (
      `<span class="citation">📖 ${A.escapeHtml(c.question || c.category || c.id)} (${Number(c.score || 0).toFixed(2)})</span>`
    )).join('')
    const feedback = !isUser && msg.content
      ? `<span class="feedback">
          <button data-action="feedback" data-index="${index}" data-rating="up" class="${msg.feedback === 'up' ? 'active' : ''}">👍</button>
          <button data-action="feedback" data-index="${index}" data-rating="down" class="${msg.feedback === 'down' ? 'active' : ''}">👎</button>
        </span>` : ''
    const meta = isUser ? '' : `
      <div class="msg-meta">
        ${msg.intent ? A.badge(`${msg.intent.intent_name || msg.intent.intent_code} ${Number(msg.intent.confidence || 0).toFixed(2)}`) : ''}
        ${msg.sentiment ? A.badge(msg.sentiment) : ''}
        ${feedback}
      </div>`
    return `
      <div class="msg ${isUser ? 'user' : 'bot'}">
        <div>
          <div class="bubble">${A.escapeHtml(msg.content || '')}</div>
          ${citations ? `<div>${citations}</div>` : ''}
          ${meta}
          ${interruptHtml(msg, index)}
          ${approvalHtml(msg, index)}
        </div>
      </div>`
  }

  function setSentiment(sentiment, score) {
    state.sentiment = sentiment
    state.sentimentScore = score
    if (!sentimentEl) return
    if (!sentiment) {
      sentimentEl.style.display = 'none'
      return
    }
    const label = { positive: '积极', neutral: '中性', negative: '负向' }[sentiment] || sentiment
    sentimentEl.className = `sentiment ${sentiment}`
    sentimentEl.style.display = 'block'
    sentimentEl.textContent = `情绪监测：${label} · ${Number(score || 0).toFixed(2)}`
  }

  function findLastUser(index) {
    for (let i = index; i >= 0; i -= 1) {
      if (state.messages[i]?.role === 'user') return state.messages[i].content
    }
    return ''
  }

  async function sendMessage(text) {
    const content = String(text || '').trim()
    if (!content || !state.sessionId || state.typing) return
    state.messages.push({ role: 'user', content, time: new Date().toISOString() })
    const bot = { role: 'bot', content: '', citations: [], time: new Date().toISOString() }
    state.messages.push(bot)
    state.typing = true
    state.quickReplies = []
    render()
    const botIndex = state.messages.length - 1

    try {
      const headers = { 'Content-Type': 'application/json' }
      const token = A.getToken()
      if (token) headers.Authorization = `Bearer ${token}`
      const response = await fetch('/api/v1/chat/send-stream', {
        method: 'POST',
        headers,
        body: JSON.stringify({ session_id: state.sessionId, content }),
      })
      if (!response.ok) throw new Error(`stream ${response.status}`)
      const reader = response.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''
      let receivedDelta = false
      let finished = false
      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })
        let boundary = buffer.indexOf('\n\n')
        while (boundary >= 0) {
          const raw = buffer.slice(0, boundary)
          buffer = buffer.slice(boundary + 2)
          const line = raw.split('\n').find((item) => item.startsWith('data: '))
          if (line) {
            const event = JSON.parse(line.slice(6))
            if (event.event === 'meta') {
              bot.intent = event.intent
              setSentiment(event.sentiment, event.sentiment_score)
            } else if (event.event === 'delta') {
              receivedDelta = true
              bot.content += String(event.text || '')
              render()
            } else if (event.event === 'citations') {
              bot.citations = event.items || []
              render()
            } else if (event.event === 'actions') {
              state.quickReplies = event.quick_replies || []
              bot.pendingApproval = event.pending_approval || null
              render()
            } else if (event.event === 'interrupt') {
              bot.interrupt = {
                type: event.kind || 'select_order',
                message: event.message || '',
                orders: event.orders || [],
                preview: event.preview || null,
              }
              bot.threadId = event.thread_id
              state.typing = false
              render()
            } else if (event.event === 'done') {
              finished = true
              const result = event.result || {}
              if (!receivedDelta && result.response && !bot.content) bot.content = result.response
              bot.intent = result.intent || bot.intent
              bot.citations = result.citations || bot.citations
              bot.pendingApproval = result.pending_approval || bot.pendingApproval
              bot.interrupt = result.interrupt || bot.interrupt
              bot.threadId = result.thread_id || bot.threadId
              state.quickReplies = result.quick_replies || state.quickReplies
              setSentiment(result.sentiment, result.sentiment_score)
              state.typing = false
              render()
            } else if (event.event === 'error') {
              throw new Error(event.message || '服务暂时不可用')
            }
          }
          boundary = buffer.indexOf('\n\n')
        }
      }
      if (!finished) {
        state.typing = false
        render()
      }
    } catch (error) {
      try {
        const result = await A.api('/chat/send', {
          method: 'POST',
          body: JSON.stringify({ session_id: state.sessionId, content }),
        })
        Object.assign(bot, {
          content: result.response,
          intent: result.intent,
          citations: result.citations || [],
          pendingApproval: result.pending_approval || null,
          interrupt: result.interrupt || null,
          threadId: result.thread_id || null,
        })
        state.quickReplies = result.quick_replies || []
        setSentiment(result.sentiment, result.sentiment_score)
      } catch (fallbackError) {
        bot.content = '抱歉，消息发送失败，请稍后重试。'
        A.toast(fallbackError.message || error.message, 'error')
      } finally {
        state.typing = false
        render()
      }
    }
  }

  async function resume(index, payload) {
    const msg = state.messages[index]
    if (!msg?.threadId || !state.sessionId) {
      A.toast('会话已失效，请重新发送消息', 'error')
      return
    }
    try {
      const result = await A.api('/chat/resume', {
        method: 'POST',
        body: JSON.stringify({
          session_id: state.sessionId,
          thread_id: msg.threadId,
          resume: payload,
        }),
      })
      msg.interrupt = result.interrupt || null
      msg.threadId = result.thread_id || msg.threadId
      state.messages.push({
        role: 'bot',
        content: result.response,
        citations: result.citations || [],
        pendingApproval: result.pending_approval || null,
        interrupt: result.interrupt || null,
        threadId: result.thread_id || null,
        time: new Date().toISOString(),
      })
      state.quickReplies = []
      render()
    } catch (error) {
      A.toast(error.message, 'error')
    }
  }

  async function verifyApproval(index) {
    const msg = state.messages[index]
    const approval = msg?.pendingApproval
    if (!approval) return
    const orderNo = document.getElementById(`verify-order-${index}`)?.value.trim()
    const phone = document.getElementById(`verify-phone-${index}`)?.value.trim()
    if (!orderNo || !phone) {
      A.toast('请填写订单号和手机后四位', 'error')
      return
    }
    try {
      const result = await A.api('/chat/verify-order', {
        method: 'POST',
        body: JSON.stringify({ session_id: state.sessionId, order_no: orderNo, phone_last4: phone }),
      })
      if (result.success) {
        msg.approvalVerified = true
        A.toast('订单核验通过', 'success')
        render()
      } else {
        A.toast(result.reason || '核验失败', 'error')
      }
    } catch (error) {
      A.toast(error.message, 'error')
    }
  }

  async function decideApproval(index, decision) {
    const msg = state.messages[index]
    const approval = msg?.pendingApproval
    if (!approval) return
    const reviewer = document.getElementById(`reviewer-${index}`)?.value.trim()
    if (approval.requires_human && decision === 'approve' && !reviewer) {
      A.toast('高风险申请需要填写客服工号', 'error')
      return
    }
    try {
      const path = `/chat/approvals/${encodeURIComponent(approval.approval_id)}/${decision === 'approve' ? 'approve' : 'reject'}`
      const body = decision === 'approve'
        ? { session_id: state.sessionId, reviewer: reviewer || undefined }
        : { session_id: state.sessionId, reason: '用户拒绝', reviewer: reviewer || undefined }
      const result = await A.api(path, { method: 'POST', body: JSON.stringify(body) })
      approval.status = result.status || (decision === 'approve' ? 'executed' : 'rejected')
      A.toast(decision === 'approve' ? '已提交审批处理' : '已拒绝该申请', 'success')
      render()
    } catch (error) {
      A.toast(error.message, 'error')
    }
  }

  async function sendFeedback(index, rating) {
    const msg = state.messages[index]
    if (!msg) return
    try {
      await A.api('/feedback', {
        method: 'POST',
        body: JSON.stringify({
          session_id: state.sessionId,
          question: findLastUser(index) || msg.content.slice(0, 200),
          rating,
        }),
      })
      msg.feedback = rating
      A.toast(rating === 'up' ? '感谢反馈' : '已记录，我们会继续改进', 'success')
      render()
    } catch (error) {
      A.toast(error.message, 'error')
    }
  }

  function bindEvents() {
    root.addEventListener('click', (event) => {
      const target = event.target.closest('[data-action]')
      if (!target) return
      const action = target.dataset.action
      if (action === 'quick') sendMessage(target.dataset.text)
      else if (action === 'feedback') sendFeedback(Number(target.dataset.index), target.dataset.rating)
      else if (action === 'verify') verifyApproval(Number(target.dataset.index))
      else if (action === 'approve') decideApproval(Number(target.dataset.index), 'approve')
      else if (action === 'reject') decideApproval(Number(target.dataset.index), 'reject')
      else if (action === 'select-order') {
        const index = Number(target.dataset.index)
        resume(index, { type: 'select_order', order_no: target.dataset.order })
      } else if (action === 'confirm-ticket') {
        const index = Number(target.dataset.index)
        resume(index, { type: 'confirm_ticket', confirmed: target.dataset.confirm === '1' })
      }
    })
    document.getElementById('composer').addEventListener('submit', (event) => {
      event.preventDefault()
      const input = document.getElementById('chat-input')
      const text = input.value
      input.value = ''
      sendMessage(text)
    })
    document.getElementById('chat-input').addEventListener('keydown', (event) => {
      if (event.key === 'Enter' && !event.shiftKey) {
        event.preventDefault()
        document.getElementById('composer').requestSubmit()
      }
    })
  }

  ;(async () => {
    const auth = await A.initPage('chat')
    if (!auth) return
    root = document.getElementById('page-root')
    root.classList.add('chat-page-root')
    root.style.padding = '0'
    root.style.maxWidth = 'none'
    root.innerHTML = shellHtml()
    messagesEl = document.getElementById('messages')
    quickEl = document.getElementById('quick-replies')
    sentimentEl = document.getElementById('sentiment')
    bindEvents()
    try {
      await ensureSession()
      render()
    } catch (error) {
      messagesEl.innerHTML = `<div class="alert">${A.escapeHtml(error.message)}</div>`
    }
  })()
})()
