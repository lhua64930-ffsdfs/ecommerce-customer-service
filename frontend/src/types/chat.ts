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

export interface Citation {
  id: number
  category: string
  question: string
  score: number
}

export interface PendingApproval {
  approval_id: string
  action: 'cancel' | 'refund' | 'return' | string
  order_no: string | null
  summary: string
  risk_level: 'low' | 'medium' | 'high' | string
  status: 'pending' | 'executed' | 'rejected' | string
  requires_verification: boolean
  requires_human: boolean
}

export interface ApprovalActionResult {
  success: boolean
  status: string
  task_id?: number | null
  already_executed?: boolean
  result?: {
    success?: boolean
    ticket_no?: string
    message?: string
    already?: boolean
  } | null
}

export interface OrderOption {
  order_no: string
  status?: string
  product_name?: string | null
  total_amount?: number
  pay_amount?: number | null
  [key: string]: unknown
}

export interface InterruptPayload {
  type: string
  message?: string
  orders: OrderOption[]
  preview?: Record<string, unknown>
}

export interface Message {
  id: string
  senderType: SenderType
  content: string
  createdAt: string
  intent?: IntentInfo
  sentiment?: SentimentType
  sentimentScore?: number
  citations?: Citation[]
  pendingApproval?: PendingApproval
  interrupt?: InterruptPayload
  threadId?: string
  feedback?: 'up' | 'down'
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
  /** MCP 开启时标记实际执行路径 */
  transport?: 'mcp' | 'local_fallback'
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
  citations: Citation[]
  pending_approval: PendingApproval | null
  run_id: string | null
  agent_mode: 'multi_step' | 'single_step' | 'single_step_fallback'
  thread_id?: string | null
  interrupt?: InterruptPayload | null
}

export interface ResumeResponse {
  response: string
  thread_id: string | null
  interrupt: InterruptPayload | null
  pending_approval: PendingApproval | null
  tool_calls: ToolCall[]
  citations: Citation[]
  run_id: string | null
  message_id: number | null
  agent_mode: string
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
  citations: Citation[]
  pending_approval: PendingApproval | null
  created_at: string
}

export interface MessageListResponse {
  messages: HistoryMessage[]
  total: number
  page: number
  page_size: number
}
