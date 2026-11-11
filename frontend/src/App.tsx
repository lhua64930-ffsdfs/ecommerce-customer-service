import { useEffect } from 'react'
import type { ReactNode } from 'react'
import { Navigate, Route, Routes } from 'react-router-dom'
import { Spin } from 'antd'
import AppLayout from './components/AppLayout'
import ChatPage from './pages/ChatPage'
import DashboardPage from './pages/DashboardPage'
import KnowledgePage from './pages/KnowledgePage'
import LoginPage from './pages/LoginPage'
import ObservabilityPage from './pages/ObservabilityPage'
import RagEvalPage from './pages/RagEvalPage'
import SessionsPage from './pages/SessionsPage'
import { useAuthStore } from './stores/authStore'

function RequireAuth({ children }: { children: ReactNode }) {
  const { ready, config, token, init } = useAuthStore()

  useEffect(() => {
    void init()
  }, [init])

  if (!ready) {
    return (
      <div style={{ minHeight: '100vh', display: 'grid', placeItems: 'center' }}>
        <Spin />
      </div>
    )
  }
  if (config?.auth_enabled && !token) {
    return <Navigate to="/login" replace />
  }
  return <>{children}</>
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route
        element={
          <RequireAuth>
            <AppLayout />
          </RequireAuth>
        }
      >
        <Route path="/" element={<ChatPage />} />
        <Route path="/dashboard" element={<DashboardPage />} />
        <Route path="/knowledge" element={<KnowledgePage />} />
        <Route path="/rag-eval" element={<RagEvalPage />} />
        <Route path="/observability" element={<ObservabilityPage />} />
        <Route path="/sessions" element={<SessionsPage />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}
