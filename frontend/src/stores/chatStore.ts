import { create } from 'zustand'
import { chatApi } from '../api/chat'
import type { Message, SentimentType } from '../types/chat'

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
      }))
      set({ sessionId, messages })
    } catch (error) {
      set({ error: errorMessage(error) })
    }
  },

  clearError() {
    set({ error: null })
  },
}))
