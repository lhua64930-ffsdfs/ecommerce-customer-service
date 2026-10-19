import { useEffect, useRef } from 'react'
import { Alert, Button } from 'antd'
import EmotionIndicator from '../components/EmotionIndicator'
import InputBox from '../components/InputBox'
import MessageBubble from '../components/MessageBubble'
import QuickReply from '../components/QuickReply'
import { useChatStore } from '../stores/chatStore'
import './ChatPage.css'

const QUICK_SERVICES = [
  { code: 'order', icon: '📦', name: '查订单', text: '我想查一下我的订单' },
  { code: 'product', icon: '🛍️', name: '商品咨询', text: '有什么优惠活动吗' },
  { code: 'refund', icon: '💰', name: '退款退货', text: '如何申请退款' },
  { code: 'human', icon: '👤', name: '转人工', text: '转人工客服' },
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
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, isTyping])

  const showWelcome = messages.length <= 1

  return (
    <div className="chat-page">
      <header className="chat-header">
        <div className="bot-avatar">🤖</div>
        <div className="header-info">
          <span className="bot-name">智能客服小e</span>
          <span className={`status ${sessionId ? 'online' : 'offline'}`}>
            {sessionId ? '在线' : '连接中...'}
          </span>
        </div>
        <div className="header-tip">7×24 小时在线</div>
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
          <div className="welcome">
            <div className="welcome-icon">🤖</div>
            <h2>您好,我是智能客服小e</h2>
            <p>我可以帮您查询订单、了解商品信息、解答售后问题等</p>
            <div className="quick-services">
              {QUICK_SERVICES.map((service) => (
                <Button
                  key={service.code}
                  disabled={!sessionId}
                  onClick={() => void sendMessage(service.text)}
                >
                  {service.icon} {service.name}
                </Button>
              ))}
            </div>
          </div>
        )}

        {messages.map((message) => (
          <MessageBubble key={message.id} message={message} />
        ))}

        {isTyping && (
          <div className="typing">
            <span />
            <span />
            <span />
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
