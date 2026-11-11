import { http } from './request'
import type {
  KnowledgeDocumentItem,
  KnowledgeItem,
  KnowledgeListResponse,
  KnowledgeSearchResult,
  ReviewItem,
} from '../types/api'

export interface KnowledgePayload {
  category: string
  question: string
  answer: string
  keywords?: string
}

export const knowledgeApi = {
  list(params: { page?: number; page_size?: number; category?: string } = {}) {
    return http.get<KnowledgeListResponse>('/knowledge/list', { params })
  },

  add(data: KnowledgePayload) {
    return http.post<KnowledgeItem>('/knowledge/add', data)
  },

  update(id: number, data: Partial<KnowledgePayload> & { is_active?: boolean }) {
    return http.put<KnowledgeItem>(`/knowledge/${id}`, data)
  },

  remove(id: number) {
    return http.delete<{ success: boolean; id: number }>(`/knowledge/${id}`)
  },

  search(query: string, topK = 5, category?: string) {
    return http.post<{ query: string; results: KnowledgeSearchResult[] }>(
      '/knowledge/search',
      { query, top_k: topK, category },
    )
  },

  documents() {
    return http.get<{ items: KnowledgeDocumentItem[]; total: number }>(
      '/knowledge/documents',
    )
  },

  importDocument(data: {
    title: string
    content: string
    source?: string
    chunk_size?: number
    overlap?: number
  }) {
    return http.post<{
      document_id: number
      title: string
      chunks: number
      vectorized: boolean
    }>('/knowledge/documents/import', data)
  },

  deleteDocument(id: number) {
    return http.delete<{ success: boolean; id: number }>(
      `/knowledge/documents/${id}`,
    )
  },
}

export const reviewApi = {
  queue(status = 'extracted') {
    return http.get<{
      items: ReviewItem[]
      total: number
      pending_low_confidence: number
    }>('/review/queue', { params: { status } })
  },

  mine() {
    return http.post<{
      batch_no: string | null
      extracted: number
      kept: number
      reason: string
    }>('/review/mine')
  },

  approve(id: number) {
    return http.post<{ success: boolean; knowledge_id: number; question: string }>(
      `/review/${id}/approve`,
    )
  },

  discard(id: number) {
    return http.post<{ success: boolean; status: string }>(
      `/review/${id}/discard`,
    )
  },
}
