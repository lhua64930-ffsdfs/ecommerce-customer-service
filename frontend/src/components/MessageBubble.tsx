import type { ReactNode } from 'react'
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

// 只识别前后为行首/行尾/空白/常见标点的 **加粗**;
// 避免把脱敏串里的 ** 张** 138****6789 误判为 Markdown。
const BOLD_PATTERN =
  /(?<=^|[\s：:，,。.;；、\-—()（）])\*\*([^*\n]+?)\*\*(?=$|[\s：:，,。.;；、\-—()（）])/gm

/** 轻量渲染 LLM 常用的 **加粗** 语法,其余内容保持纯文本(React 自动转义)。 */
function renderContent(content: string): ReactNode[] {
  const nodes: ReactNode[] = []
  let lastIndex = 0

  for (const match of content.matchAll(BOLD_PATTERN)) {
    const index = match.index ?? 0
    if (index > lastIndex) nodes.push(content.slice(lastIndex, index))
    nodes.push(<strong key={`bold-${index}`}>{match[1]}</strong>)
    lastIndex = index + match[0].length
  }
  if (lastIndex < content.length) nodes.push(content.slice(lastIndex))
  return nodes
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
          {renderContent(message.content)}
        </div>

        {!isUser && message.citations && message.citations.length > 0 && (
          <div className="citation-block" aria-label="知识库引用">
            <span className="citation-kicker">引用</span>
            {message.citations.map((citation) => (
              <span
                className="citation-chip"
                key={`${citation.id}-${citation.question}`}
                title={citation.category}
              >
                <span className="citation-index">[{citation.id}]</span>
                <span className="citation-question">{citation.question}</span>
                <span className="citation-score">{citation.score.toFixed(2)}</span>
              </span>
            ))}
          </div>
        )}

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
