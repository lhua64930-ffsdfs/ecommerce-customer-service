import { http } from './request'

export interface JobStatus {
  name: string
  title: string
  description: string
  status: 'idle' | 'running' | 'succeeded' | 'failed'
  returncode: number | null
  log?: string
}

export const jobApi = {
  list() {
    return http.get<{ jobs: JobStatus[] }>('/jobs')
  },

  start(name: string) {
    return http.post<JobStatus>(`/jobs/${name}`)
  },

  status(name: string) {
    return http.get<JobStatus>(`/jobs/${name}`)
  },

  stop(name: string) {
    return http.post<JobStatus>(`/jobs/${name}/stop`)
  },
}
