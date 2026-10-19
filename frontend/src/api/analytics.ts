import { http } from './request'
import type { AnalyticsSummary, SessionListResponse } from '../types/api'

export const analyticsApi = {
  summary() {
    return http.get<AnalyticsSummary>('/analytics/summary')
  },

  sessions(page = 1, pageSize = 20) {
    return http.get<SessionListResponse>('/analytics/sessions', {
      params: { page, page_size: pageSize },
    })
  },
}
