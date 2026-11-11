import type { ReactNode } from 'react'
import ApprovalCard from './ApprovalCard'
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

const BOLD_CANDIDATE = /\*\*([^*\n]+?)\*\*/g
const CJK_PATTERN = /[一-龥]/
const BOUNDARY_PATTERN = /[\s：:，,。.;；、\-—()（）]/

const isBoundary = (char: string | undefined): boolean =>
  !char || BOUNDARY_PATTERN.test(char)

/**
 * 轻量渲染 LLM 常用的 **加粗** 语法。
 * 只接受两类:
 * 1. 标准 Markdown 边界(前后是空白/标点/行首行尾);
 * 2. 中文语境里紧贴汉字的强调(前后至少一侧是汉字,内容也含汉字)。
 * 这样既保留中文加粗,又不会把脱敏串 `张** 138****6789` 误判成加粗。
 */
function renderContent(content: string): ReactNode[] {
  const nodes: ReactNode[] = []
  let lastIndex = 0

  for (const match of content.matchAll(BOLD_CANDIDATE)) {
    const index = match.index ?? 0
    const text = match[1]
    const before = index > 0 ? content[index - 1] : undefined
    const afterIndex = index + match[0].length
    const after = afterIndex < content.length ? content[afterIndex] : undefined

    const standardMarkdown = isBoundary(before) && isBoundary(after)
    const cjkEmphasis =
      Boolean(before && CJK_PATTERN.test(before)) &&
      CJK_PATTERN.test(text) &&
      text.length >= 2

    if (!standardMarkdown && !cjkEmphasis) continue

    if (index > lastIndex) nodes.push(content.slice(lastIndex, index))
    nodes.push(<strong key={`bold-${index}`}>{text}</strong>)
    lastIndex = afterIndex
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

        {!isUser && message.pendingApproval && (
          <ApprovalCard message={message} />
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
