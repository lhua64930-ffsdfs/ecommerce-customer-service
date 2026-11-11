import { create } from 'zustand'
import { authApi, type AuthConfig, type AuthUser } from '../api/auth'
import { clearToken, getToken, setToken } from '../utils/token'

interface AuthState {
  token: string | null
  user: AuthUser | null
  config: AuthConfig | null
  ready: boolean
  error: string | null
  init: () => Promise<void>
  login: (username: string, password: string) => Promise<boolean>
  logout: () => void
  clearError: () => void
}

const errorText = (error: unknown): string => {
  const detail = (error as { response?: { data?: { detail?: unknown } } })?.response
    ?.data?.detail
  if (typeof detail === 'string') return detail
  return '登录失败,请稍后重试'
}

export const useAuthStore = create<AuthState>((set, get) => ({
  token: getToken(),
  user: null,
  config: null,
  ready: false,
  error: null,

  async init() {
    if (get().ready) return
    try {
      const config = await authApi.config()
      set({ config })
      const token = getToken()
      if (config.auth_enabled && token) {
        try {
          const user = await authApi.me()
          set({ token, user })
        } catch {
          clearToken()
          set({ token: null, user: null })
        }
      }
    } catch {
      // 配置接口失败时按未启用鉴权处理,避免本地演示被锁死
      set({ config: { auth_enabled: false, registration_enabled: false } })
    } finally {
      set({ ready: true })
    }
  },

  async login(username, password) {
    try {
      const result = await authApi.login(username, password)
      setToken(result.token)
      const user: AuthUser = {
        user_id: result.user_id,
        username: result.username,
        roles: [result.user_type],
      }
      set({ token: result.token, user, error: null })
      return true
    } catch (error) {
      set({ error: errorText(error) })
      return false
    }
  },

  logout() {
    clearToken()
    set({ token: null, user: null })
  },

  clearError() {
    set({ error: null })
  },
}))
