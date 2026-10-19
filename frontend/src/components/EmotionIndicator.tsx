import type { SentimentType } from '../types/chat'

const SENTIMENT_META: Record<SentimentType, { emoji: string; label: string }> = {
  positive: { emoji: '😊', label: '心情不错' },
  neutral: { emoji: '🤖', label: '情绪平和' },
  negative: { emoji: '😔', label: '需要关注' },
}

interface Props {
  sentiment: SentimentType
  score: number
}

export default function EmotionIndicator({ sentiment, score }: Props) {
  const meta = SENTIMENT_META[sentiment]

  return (
    <div className={`emotion-indicator ${sentiment}`}>
      <span className="emoji">{meta.emoji}</span>
      <span className="label">{meta.label}</span>
      <span className="score">({score.toFixed(2)})</span>
    </div>
  )
}
