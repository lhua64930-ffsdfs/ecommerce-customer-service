import type { SentimentType } from '../types/chat'

const SENTIMENT_META: Record<SentimentType, { emoji: string; label: string }> = {
  positive: { emoji: '😊', label: '心情不错' },
  neutral: { emoji: '😐', label: '情绪平和' },
  negative: { emoji: '😔', label: '需要关注' },
}

interface Props {
  sentiment: SentimentType
  score: number
}

export default function EmotionIndicator({ sentiment, score }: Props) {
  const meta = SENTIMENT_META[sentiment]
  const strength = Math.min(100, Math.round(Math.abs(score) * 100))

  return (
    <div className={`emotion-indicator ${sentiment}`}>
      <span className="emotion-kicker">SENTIMENT / 情绪监测</span>
      <span className="emoji" aria-hidden="true">
        {meta.emoji}
      </span>
      <span className="label">{meta.label}</span>
      <span className="score">{score.toFixed(2)}</span>
      <span className="emotion-meter" aria-hidden="true">
        <i style={{ width: `${strength}%` }} />
      </span>
    </div>
  )
}
