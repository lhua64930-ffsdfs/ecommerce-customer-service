import { http } from './request'

export interface StrategyReport {
  total: number
  top_k: number
  recall_at_1: number
  recall_at_3: number
  recall_at_5: number
  mrr_at_5: number
  retrieval_modes: Record<string, number>
}

export interface RagEvalOverview {
  present: boolean
  rag: {
    total: number
    top_k: number
    strategies: Record<string, StrategyReport>
  } | null
  rag_generated_at: string | null
  refusal: {
    total: number
    refused: number
    refusal_rate: number
    modes: Record<string, number>
    details: Array<Record<string, unknown>>
  } | null
  refusal_generated_at: string | null
  best_strategy: { name: string; mrr_at_5: number; recall_at_1: number } | null
  commands: Record<string, string>
}

export const ragEvalApi = {
  overview() {
    return http.get<RagEvalOverview>('/rag-eval/overview')
  },
}
