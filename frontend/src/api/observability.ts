import { http } from './request'

export interface RunStatusBucket {
  count: number
  total_tokens: number
  avg_latency_ms: number
}

export interface ObservabilityOverview {
  days: number
  runs: { total: number; by_status: Record<string, RunStatusBucket> }
  steps: { failed: number; top_failing_tools: { name: string; failed: number }[] }
  low_confidence: { total: number; pending: number }
  approvals: Record<string, number>
  langfuse_enabled: boolean
}

export interface RunItem {
  run_id: string
  session_id: number
  agent_mode: string
  status: string
  total_steps: number
  total_latency_ms: number
  total_tokens: number
  started_at: string
  finished_at: string | null
}

export interface CostItem {
  date: string
  tokens: number
  runs: number
}

export const observabilityApi = {
  overview(days = 7) {
    return http.get<ObservabilityOverview>('/observability/overview', {
      params: { days },
    })
  },
  runs(days = 7, limit = 50) {
    return http.get<{ items: RunItem[]; total: number }>('/observability/runs', {
      params: { days, limit },
    })
  },
  cost(days = 30) {
    return http.get<{ total_tokens: number; items: CostItem[] }>(
      '/observability/cost',
      { params: { days } },
    )
  },
}
