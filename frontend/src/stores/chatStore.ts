import { create } from 'zustand'
import { chatApi } from '../api/chat'
import { getToken } from '../utils/token'
import type {
  InterruptPayload,
  Message,
  PendingApproval,
  SentimentType,
} from '../types/chat'

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
  resumeInterrupt: (
    messageId: string,
    resume: Record<string, unknown>,
  ) => Promise<void>
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
  sendFeedback: (messageId: string, rating: 'up' | 'down') => Promise<void>
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
    const botId = makeId()
    const placeholder: Message = {
      id: botId,
      senderType: 'bot',
      content: '',
      createdAt: new Date().toISOString(),
    }
    set((state) => ({
      messages: [...state.messages, userMessage, placeholder],
      isTyping: true,
      error: null,
    }))

    const patchBot = (patch: Partial<Message>) => {
      set((state) => ({
        messages: state.messages.map((item) =>
          item.id === botId ? { ...item, ...patch } : item,
        ),
      }))
    }
    let receivedDelta = false
    const appendDelta = (chunk: string) => {
      if (!chunk) return
      receivedDelta = true
      set((state) => ({
        isTyping: false,
        messages: state.messages.map((item) =>
          item.id === botId ? { ...item, content: item.content + chunk } : item,
        ),
      }))
    }

    try {
      const token = getToken()
      const response = await fetch('/api/v1/chat/send-stream', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify({ session_id: sessionId, content: text }),
      })
      if (!response.ok) {
        throw new Error(`stream request failed: ${response.status}`)
      }
      const reader = response.body?.getReader()
      if (!reader) throw new Error('stream unavailable')

      const decoder = new TextDecoder()
      let buffer = ''
      for (;;) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })

        let boundary = buffer.indexOf('\n\n')
        while (boundary >= 0) {
          const raw = buffer.slice(0, boundary)
          buffer = buffer.slice(boundary + 2)
          const line = raw.split('\n').find((item) => item.startsWith('data: '))
          if (line) {
            const event = JSON.parse(line.slice(6)) as Record<string, unknown>
            const type = event.event
            if (type === 'meta') {
              patchBot({
                intent: event.intent as Message['intent'],
                sentiment: event.sentiment as Message['sentiment'],
                sentimentScore: event.sentiment_score as number,
              })
              set({
                currentSentiment: event.sentiment as SentimentType,
                sentimentScore: event.sentiment_score as number,
              })
            } else if (type === 'delta') {
              appendDelta(String(event.text || ''))
            } else if (type === 'citations') {
              patchBot({ citations: (event.items as Message['citations']) ?? [] })
            } else if (type === 'actions') {
              set({ quickReplies: (event.quick_replies as string[]) ?? [] })
              patchBot({
                pendingApproval:
                  (event.pending_approval as Message['pendingApproval']) ?? undefined,
              })
            } else if (type === 'interrupt') {
              const kind = String(event.kind || 'select_order')
              patchBot({
                interrupt: {
                  type: kind,
                  message: String(event.message || ''),
                  orders: (event.orders as InterruptPayload['orders']) ?? [],
                  preview: event.preview as Record<string, unknown> | undefined,
                },
                threadId: event.thread_id ? String(event.thread_id) : undefined,
              })
              set({ isTyping: false })
            } else if (type === 'done') {
              const result = (event.result ?? {}) as Record<string, unknown>
              if (!receivedDelta && result.response) {
                appendDelta(String(result.response))
              }
              set((state) => ({
                isTyping: false,
                quickReplies:
                  (result.quick_replies as string[]) ?? state.quickReplies,
                messages: state.messages.map((item) =>
                  item.id === botId
                    ? {
                        ...item,
                        content:
                          item.content || String(result.response || ''),
                        intent:
                          (result.intent as Message['intent']) ?? item.intent,
                        sentiment:
                          (result.sentiment as Message['sentiment']) ??
                          item.sentiment,
                        sentimentScore:
                          (result.sentiment_score as number) ??
                          item.sentimentScore,
                        citations:
                          (result.citations as Message['citations']) ??
                          item.citations,
                        pendingApproval:
                          (result.pending_approval as Message['pendingApproval']) ??
                          item.pendingApproval,
                        interrupt:
                          (result.interrupt as Message['interrupt']) ??
                          item.interrupt,
                        threadId:
                          (result.thread_id as string | null) ?? item.threadId,
                      }
                    : item,
                ),
              }))
            } else if (type === 'error') {
              set({ error: String(event.message || '服务暂时不可用') })
            }
          }
          boundary = buffer.indexOf('\n\n')
        }
      }
    } catch (streamError) {
      // SSE 不可用时退回一次性接口,保证功能不中断
      try {
        const result = await chatApi.sendMessage({
          session_id: sessionId,
          content: text,
        })
        set((state) => ({
          isTyping: false,
          currentSentiment: result.sentiment,
          sentimentScore: result.sentiment_score,
          quickReplies: result.quick_replies ?? [],
          messages: state.messages.map((item) =>
            item.id === botId
              ? {
                  ...item,
                  content: result.response,
                  intent: result.intent,
                  sentiment: result.sentiment,
                  sentimentScore: result.sentiment_score,
                  citations: result.citations ?? [],
                  pendingApproval: result.pending_approval ?? undefined,
                  interrupt: result.interrupt ?? undefined,
                  threadId: result.thread_id ?? undefined,
                }
              : item,
          ),
        }))
      } catch (error) {
        set((state) => ({
          isTyping: false,
          error: errorMessage(error),
          messages: state.messages.map((item) =>
            item.id === botId
              ? { ...item, content: '抱歉,消息发送失败,请稍后重试。' }
              : item,
          ),
        }))
        void streamError
      }
    }
  },

  async resumeInterrupt(messageId, resume) {
    const sessionId = get().sessionId
    const source = get().messages.find((item) => item.id === messageId)
    const threadId = source?.threadId
    if (!sessionId || !threadId) {
      set({ error: '会话已失效,请重新发送消息' })
      return
    }

    const botId = makeId()
    set((state) => ({
      messages: [
        ...state.messages,
        {
          id: botId,
          senderType: 'bot',
          content: '',
          createdAt: new Date().toISOString(),
        },
      ],
      isTyping: true,
      error: null,
    }))

    try {
      const result = await chatApi.resume({
        session_id: sessionId,
        thread_id: threadId,
        resume,
      })
      set((state) => ({
        isTyping: false,
        messages: state.messages.map((item) => {
          if (item.id === messageId) {
            return {
              ...item,
              interrupt: result.interrupt ?? undefined,
              threadId: result.thread_id ?? undefined,
            }
          }
          if (item.id === botId) {
            return {
              ...item,
              content: result.response,
              pendingApproval: result.pending_approval ?? undefined,
              citations: result.citations ?? [],
              interrupt: result.interrupt ?? undefined,
              threadId: result.thread_id ?? undefined,
            }
          }
          return item
        }),
      }))
    } catch (error) {
      set((state) => ({
        isTyping: false,
        error: errorMessage(error),
        messages: state.messages.map((item) =>
          item.id === botId
            ? { ...item, content: '操作失败,请稍后重试。' }
            : item,
        ),
      }))
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

  async sendFeedback(messageId: string, rating: 'up' | 'down') {
    const sessionId = get().sessionId
    if (!sessionId) return
    const messages = get().messages
    const index = messages.findIndex((item) => item.id === messageId)
    if (index < 0) return
    const question =
      [...messages.slice(0, index)]
        .reverse()
        .find((item) => item.senderType === 'user')?.content || messages[index].content

    try {
      await chatApi.sendFeedback({
        session_id: sessionId,
        question,
        rating,
      })
      set((state) => ({
        messages: state.messages.map((item) =>
          item.id === messageId ? { ...item, feedback: rating } : item,
        ),
      }))
    } catch {
      set({ error: '反馈提交失败,请稍后重试' })
    }
  },

  clearError() {
    set({ error: null })
  },
}))
