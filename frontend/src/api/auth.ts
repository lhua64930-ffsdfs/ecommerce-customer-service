import { http } from './request'

export interface AuthConfig {
  auth_enabled: boolean
  registration_enabled: boolean
}

export interface AuthUser {
  user_id: number | null
  username: string
  display_name?: string | null
  roles: string[]
  tenant_id?: string
}

export interface LoginResponse {
  token: string
  user_id: number
  username: string
  user_type: string
}

export const authApi = {
  config() {
    return http.get<AuthConfig>('/auth/config')
  },
  login(username: string, password: string) {
    return http.post<LoginResponse>('/auth/login', { username, password })
  },
  me() {
    return http.get<AuthUser>('/auth/me')
  },
}
