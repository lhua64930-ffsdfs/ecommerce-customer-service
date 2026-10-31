import { useEffect, useRef } from 'react'
import { Alert } from 'antd'
import EmotionIndicator from '../components/EmotionIndicator'
import InputBox from '../components/InputBox'
import MessageBubble from '../components/MessageBubble'
import QuickReply from '../components/QuickReply'
import { useChatStore } from '../stores/chatStore'
import './ChatPage.css'

const QUICK_SERVICES = [
  {
    code: 'order',
    index: '01',
    icon: '📦',
    name: '查订单',
    text: '我想查一下我的订单',
    hint: '订单 / 物流 / 收货信息',
  },
  {
    code: 'product',
    index: '02',
    icon: '🛍️',
    name: '商品咨询',
    text: '有什么优惠活动吗',
    hint: '价格 / 库存 / 活动',
  },
  {
    code: 'refund',
    index: '03',
    icon: '💰',
    name: '退款退货',
    text: '如何申请退款',
    hint: '取消 / 退款 / 退货',
  },
  {
    code: 'human',
    index: '04',
    icon: '👤',
    name: '转人工',
    text: '转人工客服',
    hint: '复杂问题 / 人工受理',
  },
]

export default function ChatPage() {
  const {
    messages,
    sessionId,
    currentSentiment,
    sentimentScore,
    quickReplies,
    isTyping,
    error,
    initSession,
    sendMessage,
    clearError,
  } = useChatStore()

  const initialized = useRef(false)
  const bottomRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (initialized.current) return
    initialized.current = true
    void initSession()
  }, [initSession])

  useEffect(() => {
    // 首次进入时保留欢迎单的顶部,不自动滚到底部
    if (messages.length <= 1) return
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, isTyping])

  const showWelcome = messages.length <= 1
  const sessionCode = sessionId ? sessionId.slice(0, 8).toUpperCase() : '待接入'

  return (
    <div className="chat-page">
      <header className="chat-header">
        <div className="header-stamp" aria-hidden="true">
          售后
        </div>

        <div className="header-info">
          <div className="header-kicker">AFTER-SALES DESK / 受理台</div>
          <div className="header-title-row">
            <span className="bot-name">智能客服小e</span>
            <span className={`status ${sessionId ? 'online' : 'offline'}`}>
              {sessionId ? '在线受理中' : '接入中'}
            </span>
          </div>
        </div>

        <div className="header-docket">
          <div className="docket-field">
            <span className="docket-label">受理编号</span>
            <span className="docket-value">{sessionCode}</span>
          </div>
          <div className="docket-field docket-meta">
            <span className="docket-label">渠道 / 时段</span>
            <span className="docket-value">WEB · 7×24</span>
          </div>
        </div>
      </header>

      {currentSentiment && (
        <EmotionIndicator sentiment={currentSentiment} score={sentimentScore} />
      )}

      {error && (
        <Alert
          className="chat-alert"
          type="error"
          message={error}
          showIcon
          closable
          onClose={clearError}
        />
      )}

      <div className="chat-messages">
        {showWelcome && (
          <section className="welcome">
            <div className="welcome-kicker">SERVICE REQUEST / 受理单</div>
            <h2>今天需要处理什么?</h2>
            <p>我可以帮您查询订单、了解商品信息、解答售后问题等</p>

            <div className="quick-services">
              {QUICK_SERVICES.map((service) => (
                <button
                  key={service.code}
                  type="button"
                  className="service-slip"
                  disabled={!sessionId}
                  onClick={() => void sendMessage(service.text)}
                >
                  <span className="slip-index">{service.index}</span>
                  <span className="slip-icon" aria-hidden="true">
                    {service.icon}
                  </span>
                  <span className="slip-body">
                    <span className="slip-name">{service.name}</span>
                    <span className="slip-hint">{service.hint}</span>
                  </span>
                  <span className="slip-arrow" aria-hidden="true">
                    →
                  </span>
                </button>
              ))}
            </div>

            <p className="welcome-note">
              订单查询会校验归属;涉及资金的操作会先与您确认。
            </p>
          </section>
        )}

        {!showWelcome && (
          <div className="transcript-label">
            <span>会话记录 / TRANSCRIPT</span>
            <span>{messages.length} 条</span>
          </div>
        )}

        {messages.map((message) => (
          <MessageBubble key={message.id} message={message} />
        ))}

        {isTyping && (
          <div className="typing" aria-label="正在输入">
            <span />
            <span />
            <span />
            <em>正在检索</em>
          </div>
        )}

        <div ref={bottomRef} />
      </div>

      {quickReplies.length > 0 && (
        <QuickReply replies={quickReplies} onSelect={(text) => void sendMessage(text)} />
      )}

      <InputBox
        disabled={!sessionId || isTyping}
        onSend={(text) => void sendMessage(text)}
      />
    </div>
  )
}
