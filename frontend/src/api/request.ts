import axios from 'axios'
import { clearToken, getToken } from '../utils/token'

const request = axios.create({
  baseURL: '/api/v1',
  timeout: 90000,
})

request.interceptors.request.use((config) => {
  const token = getToken()
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

request.interceptors.response.use(
  (response) => response.data,
  (error) => {
    const status = error?.response?.status
    const url = String(error?.config?.url ?? '')
    if (status === 401 && !url.includes('/auth/')) {
      clearToken()
      if (window.location.pathname !== '/login') {
        window.location.href = '/login'
      }
    }
    return Promise.reject(error)
  },
)

export const http = {
  get: <T>(url: string, config?: object) => request.get<unknown, T>(url, config),
  post: <T>(url: string, data?: unknown, config?: object) =>
    request.post<unknown, T>(url, data, config),
  put: <T>(url: string, data?: unknown, config?: object) =>
    request.put<unknown, T>(url, data, config),
  delete: <T>(url: string, config?: object) => request.delete<unknown, T>(url, config),
}

export default request
