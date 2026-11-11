import { create } from 'zustand'
import { chatApi } from '../api/chat'
import type { Message, PendingApproval, SentimentType } from '../types/chat'

const makeId = (): string =>
  typeof crypto !== 'undefined' && 'randomUUID' in crypto
    ? crypto.randomUUID()
    : `${Date.now()}-${Math.random().toString(16).slice(2)}`

const errorMessage = (error: unknown): string => {
  const detail = (error as { response?: { data?: { detail?: unknown } } })?.response?.data
    ?.detail
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) return '请求参数有误,请检查后重试'
  return '服务暂时不可用,请稍后重试'
}

interface ChatState {
  sessionId: string | null
  userId: number | null
  messages: Message[]
  currentSentiment: SentimentType | null
  sentimentScore: number
  quickReplies: string[]
  isTyping: boolean
  error: string | null
  initSession: () => Promise<void>
  sendMessage: (content: string) => Promise<void>
  loadHistory: (sessionId: string) => Promise<void>
  verifyApprovalOrder: (
    orderNo: string,
    phoneLast4: string,
  ) => Promise<{ success: boolean; reason?: string }>
  decideApproval: (
    messageId: string,
    approvalId: string,
    decision: 'approve' | 'reject',
    options?: { reviewer?: string; reason?: string },
  ) => Promise<{ success: boolean; code?: string; message: string }>
  clearError: () => void
}

export const useChatStore = create<ChatState>((set, get) => ({
  sessionId: null,
  userId: null,
  messages: [],
  currentSentiment: null,
  sentimentScore: 0,
  quickReplies: [],
  isTyping: false,
  error: null,

  async initSession() {
    if (get().sessionId) return
    try {
      const result = await chatApi.createSession()
      set({
        sessionId: result.session.session_id,
        userId: result.session.user_id,
        quickReplies: result.quick_replies,
        messages: [
          {
            id: 'welcome',
            senderType: 'bot',
            content: result.welcome_message,
            createdAt: new Date().toISOString(),
          },
        ],
        error: null,
      })
    } catch (error) {
      set({ error: errorMessage(error) })
    }
  },

  async sendMessage(content: string) {
    const text = content.trim()
    const sessionId = get().sessionId
    if (!text || !sessionId) return

    const userMessage: Message = {
      id: makeId(),
      senderType: 'user',
      content: text,
      createdAt: new Date().toISOString(),
    }
    set((state) => ({
      messages: [...state.messages, userMessage],
      isTyping: true,
      error: null,
    }))

    try {
      const result = await chatApi.sendMessage({ session_id: sessionId, content: text })
      const botMessage: Message = {
        id: result.message_id ? String(result.message_id) : makeId(),
        senderType: 'bot',
        content: result.response,
        createdAt: new Date().toISOString(),
        intent: result.intent,
        sentiment: result.sentiment,
        sentimentScore: result.sentiment_score,
        citations: result.citations ?? [],
        pendingApproval: result.pending_approval ?? undefined,
      }
      set((state) => ({
        messages: [...state.messages, botMessage],
        currentSentiment: result.sentiment,
        sentimentScore: result.sentiment_score,
        quickReplies: result.quick_replies ?? [],
        isTyping: false,
      }))
    } catch (error) {
      set({
        isTyping: false,
        error: errorMessage(error),
        messages: [
          ...get().messages,
          {
            id: makeId(),
            senderType: 'bot',
            content: '抱歉,消息发送失败,请稍后重试。',
            createdAt: new Date().toISOString(),
          },
        ],
      })
    }
  },

  async loadHistory(sessionId: string) {
    try {
      const history = await chatApi.getHistory(sessionId)
      const messages: Message[] = history.messages.map((item) => ({
        id: String(item.id),
        senderType: item.sender_type,
        content: item.content,
        createdAt: item.created_at,
        intent: item.intent ?? undefined,
        sentiment: item.sentiment ?? undefined,
        sentimentScore: item.sentiment_score ?? undefined,
        citations: item.citations ?? [],
        pendingApproval: item.pending_approval ?? undefined,
      }))
      set({ sessionId, messages })
    } catch (error) {
      set({ error: errorMessage(error) })
    }
  },

  async verifyApprovalOrder(orderNo: string, phoneLast4: string) {
    const sessionId = get().sessionId
    if (!sessionId) return { success: false, reason: '会话未就绪' }
    try {
      const result = await chatApi.verifyOrder({
        session_id: sessionId,
        order_no: orderNo,
        phone_last4: phoneLast4,
      })
      return { success: result.success, reason: result.reason }
    } catch (error) {
      return { success: false, reason: errorMessage(error) }
    }
  },

  async decideApproval(
    messageId: string,
    approvalId: string,
    decision: 'approve' | 'reject',
    options?: { reviewer?: string; reason?: string },
  ) {
    const sessionId = get().sessionId
    if (!sessionId) return { success: false, message: '会话未就绪' }

    try {
      const result =
        decision === 'approve'
          ? await chatApi.approveApproval(approvalId, {
              session_id: sessionId,
              reviewer: options?.reviewer,
            })
          : await chatApi.rejectApproval(approvalId, {
              session_id: sessionId,
              reason: options?.reason,
              reviewer: options?.reviewer,
            })

      const status = result.status || (decision === 'approve' ? 'executed' : 'rejected')
      const resultMessage =
        result.result?.message ||
        (decision === 'approve'
          ? '售后申请已处理,请查看订单状态。'
          : '已拒绝本次售后申请。')

      set((state) => ({
        messages: [
          ...state.messages.map((message) =>
            message.id === messageId && message.pendingApproval
              ? {
                  ...message,
                  pendingApproval: {
                    ...message.pendingApproval,
                    status,
                  } as PendingApproval,
                }
              : message,
          ),
          {
            id: makeId(),
            senderType: 'bot',
            content: resultMessage,
            createdAt: new Date().toISOString(),
          },
        ],
      }))
      return { success: true, message: resultMessage }
    } catch (error) {
      const detail = (error as { response?: { data?: { detail?: unknown } } })?.response
        ?.data?.detail
      if (detail && typeof detail === 'object') {
        const parsed = detail as { code?: string; message?: string }
        return {
          success: false,
          code: parsed.code,
          message: parsed.message || '处理失败,请稍后重试',
        }
      }
      return { success: false, message: errorMessage(error) }
    }
  },

  clearError() {
    set({ error: null })
  },
}))
