export interface CountItem {
  name: string
  count: number
}

export interface AnalyticsSummary {
  sessions_total: number
  sessions_today: number
  messages_total: number
  users_total: number
  open_tickets: number
  ai_resolution_rate: number
  transfer_rate: number
  satisfaction_avg: number | null
  intent_distribution: CountItem[]
  sentiment_distribution: CountItem[]
}

export interface SessionItem {
  session_id: string
  user_id: number
  status: string
  channel: string
  message_count: number
  satisfaction_score: number | null
  started_at: string | null
  last_message_at: string | null
}

export interface SessionListResponse {
  items: SessionItem[]
  total: number
  page: number
  page_size: number
}

export interface KnowledgeItem {
  id: number
  category: string
  question: string
  answer: string
  keywords: string | null
  vector_id: string | null
  hit_count: number
  is_active: boolean
  created_at: string | null
  updated_at: string | null
}

export interface KnowledgeListResponse {
  items: KnowledgeItem[]
  total: number
  page: number
  page_size: number
}

export interface KnowledgeSearchResult {
  id: number
  score: number
  category: string
  question: string
  answer: string
}
