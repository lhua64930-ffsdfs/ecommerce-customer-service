import type { Message } from '../types/chat'
import { formatTime } from '../utils/formatTime'

const SENTIMENT_LABELS: Record<string, string> = {
  positive: '积极',
  neutral: '中性',
  negative: '需要关注',
}

interface Props {
  message: Message
}

export default function MessageBubble({ message }: Props) {
  const isUser = message.senderType === 'user'

  return (
    <article className={`message-bubble ${isUser ? 'is-user' : 'is-bot'}`}>
      {!isUser && (
        <div className="avatar avatar-bot" aria-hidden="true">
          e
        </div>
      )}

      <div className="bubble-wrapper">
        {!isUser && (message.intent || message.sentiment) && (
          <div className="message-meta">
            {message.intent && (
              <span className="intent-tag">
                <span className="meta-key">意图</span>
                {message.intent.intent_name}
                <span className="confidence">
                  {Math.round(message.intent.confidence * 100)}%
                </span>
              </span>
            )}
            {message.sentiment && (
              <span className={`emotion-tag ${message.sentiment}`}>
                <span className="meta-key">情绪</span>
                {SENTIMENT_LABELS[message.sentiment]}
              </span>
            )}
          </div>
        )}

        <div className={`bubble ${isUser ? 'bubble-user' : 'bubble-bot'}`}>
          {message.content}
        </div>

        <div className="message-time">{formatTime(message.createdAt)}</div>
      </div>

      {isUser && (
        <div className="avatar avatar-user" aria-hidden="true">
          您
        </div>
      )}
    </article>
  )
}
