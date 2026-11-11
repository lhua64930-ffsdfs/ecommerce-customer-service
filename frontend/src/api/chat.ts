import { http } from './request'
import type {
  ApprovalActionResult,
  CreateSessionResponse,
  MessageListResponse,
  PendingApproval,
  ResumeResponse,
  SendMessageResponse,
} from '../types/chat'

export const chatApi = {
  createSession(data: { user_id?: number; channel?: string } = {}) {
    return http.post<CreateSessionResponse>('/chat/session', data)
  },

  sendMessage(data: { session_id: string; content: string }) {
    return http.post<SendMessageResponse>('/chat/send', data)
  },

  resume(data: {
    session_id: string
    thread_id: string
    resume: Record<string, unknown>
  }) {
    return http.post<ResumeResponse>('/chat/resume', data)
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

  verifyOrder(data: { session_id: string; order_no: string; phone_last4: string }) {
    return http.post<{ success: boolean; reason?: string; order?: Record<string, unknown> }>(
      '/chat/verify-order',
      data,
    )
  },

  listApprovals(sessionId: string) {
    return http.get<{ items: PendingApproval[]; total: number }>('/chat/approvals', {
      params: { session_id: sessionId },
    })
  },

  approveApproval(
    approvalId: string,
    data: { session_id: string; reviewer?: string },
  ) {
    return http.post<ApprovalActionResult>(
      `/chat/approvals/${approvalId}/approve`,
      data,
    )
  },

  rejectApproval(
    approvalId: string,
    data: { session_id: string; reason?: string; reviewer?: string },
  ) {
    return http.post<ApprovalActionResult>(
      `/chat/approvals/${approvalId}/reject`,
      data,
    )
  },

  sendFeedback(data: {
    session_id: string
    question: string
    rating: 'up' | 'down'
    comment?: string
  }) {
    return http.post<{ success: boolean; pooled: boolean; id?: number }>(
      '/feedback',
      data,
    )
  },
}
