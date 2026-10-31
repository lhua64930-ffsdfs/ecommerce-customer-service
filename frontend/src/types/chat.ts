export type SentimentType = 'positive' | 'neutral' | 'negative'
export type SenderType = 'user' | 'bot' | 'agent'

export interface Entity {
  type: string
  value: string
  start: number
  end: number
}

export interface IntentInfo {
  intent_code: string
  intent_name: string
  confidence: number
  entities: Entity[]
  handler_type: string
  priority: number
}

export interface Message {
  id: string
  senderType: SenderType
  content: string
  createdAt: string
  intent?: IntentInfo
  sentiment?: SentimentType
  sentimentScore?: number
}

export interface SessionInfo {
  session_id: string
  user_id: number | null
  status: string
  started_at: string
  message_count: number
  bot_name: string
}

export interface CreateSessionResponse {
  session: SessionInfo
  welcome_message: string
  quick_replies: string[]
}

export interface ToolCall {
  tool: string
  success: boolean
}

export interface SendMessageResponse {
  response: string
  intent: IntentInfo
  sentiment: SentimentType
  sentiment_score: number
  quick_replies: string[]
  need_transfer: boolean
  message_id: number | null
  tool_calls: ToolCall[]
  agent_mode: 'multi_step' | 'single_step' | 'single_step_fallback'
}

export interface HistoryMessage {
  id: number
  session_id: string
  sender_type: SenderType
  content: string
  content_type: string
  intent: IntentInfo | null
  sentiment: SentimentType | null
  sentiment_score: number | null
  created_at: string
}

export interface MessageListResponse {
  messages: HistoryMessage[]
  total: number
  page: number
  page_size: number
}
