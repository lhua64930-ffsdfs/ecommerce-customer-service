import { http } from './request'
import type {
  KnowledgeItem,
  KnowledgeListResponse,
  KnowledgeSearchResult,
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
}
