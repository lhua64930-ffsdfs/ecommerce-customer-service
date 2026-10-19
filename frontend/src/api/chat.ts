import { http } from './request'
import type {
  CreateSessionResponse,
  MessageListResponse,
  SendMessageResponse,
} from '../types/chat'

export const chatApi = {
  createSession(data: { user_id?: number; channel?: string } = {}) {
    return http.post<CreateSessionResponse>('/chat/session', data)
  },

  sendMessage(data: { session_id: string; content: string }) {
    return http.post<SendMessageResponse>('/chat/send', data)
  },

  getHistory(sessionId: string, page = 1, pageSize = 20) {
    return http.get<MessageListResponse>('/chat/history', {
      params: { session_id: sessionId, page, page_size: pageSize },
    })
  },

  transferToHuman(sessionId: string, reason?: string) {
    return http.post('/chat/transfer', { session_id: sessionId, reason })
  },

  rateSession(sessionId: string, score: number, comment?: string) {
    return http.post('/chat/rate', { session_id: sessionId, score, comment })
  },
}
