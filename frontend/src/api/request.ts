import axios from 'axios'

const request = axios.create({
  baseURL: '/api/v1',
  timeout: 90000,
})

request.interceptors.response.use(
  (response) => response.data,
  (error) => Promise.reject(error),
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
