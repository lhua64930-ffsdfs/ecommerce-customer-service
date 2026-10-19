import type { Message } from '../types/chat'
import { formatTime } from '../utils/formatTime'

const SENTIMENT_LABELS: Record<string, string> = {
  positive: '😊 积极',
  neutral: '😐 中性',
  negative: '😔 消极',
}

interface Props {
  message: Message
}

export default function MessageBubble({ message }: Props) {
  const isUser = message.senderType === 'user'

  return (
    <div className={`message-bubble ${isUser ? 'is-user' : 'is-bot'}`}>
      {!isUser && <div className="avatar">🤖</div>}

      <div className="bubble-wrapper">
        {!isUser && message.intent && (
          <div className="intent-tag">
            🏷️ {message.intent.intent_name}
            <span className="confidence">
              ({(message.intent.confidence * 100).toFixed(0)}%)
            </span>
          </div>
        )}

        {!isUser && message.sentiment && (
          <div className={`emotion-tag ${message.sentiment}`}>
            {SENTIMENT_LABELS[message.sentiment]}
          </div>
        )}

        <div className={`bubble ${isUser ? 'bubble-user' : 'bubble-bot'}`}>
          {message.content}
        </div>

        <div className="message-time">{formatTime(message.createdAt)}</div>
      </div>

      {isUser && <div className="avatar">👤</div>}
    </div>
  )
}
