interface Props {
  replies: string[]
  onSelect: (text: string) => void
}

export default function QuickReply({ replies, onSelect }: Props) {
  if (!replies.length) return null

  return (
    <div className="quick-reply">
      <div className="quick-reply-head">
        <span className="quick-reply-title">常用处理</span>
        <span className="quick-reply-kicker">QUICK ACTIONS</span>
      </div>
      <div className="quick-reply-list">
        {replies.map((reply, index) => (
          <button
            key={`${reply}-${index}`}
            type="button"
            className="quick-reply-item"
            onClick={() => onSelect(reply)}
          >
            <span>{reply}</span>
            <span aria-hidden="true">→</span>
          </button>
        ))}
      </div>
    </div>
  )
}
