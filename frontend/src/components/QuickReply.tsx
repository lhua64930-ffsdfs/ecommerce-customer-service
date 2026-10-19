import { Button } from 'antd'

interface Props {
  replies: string[]
  onSelect: (text: string) => void
}

export default function QuickReply({ replies, onSelect }: Props) {
  if (!replies.length) return null

  return (
    <div className="quick-reply">
      <div className="quick-reply-title">💡 您可能想了解:</div>
      <div className="quick-reply-list">
        {replies.map((reply, index) => (
          <Button key={`${reply}-${index}`} size="small" onClick={() => onSelect(reply)}>
            {reply}
          </Button>
        ))}
      </div>
    </div>
  )
}
