import { Button, Layout, Menu, Space, Typography } from 'antd'
import {
  BookOutlined,
  DashboardOutlined,
  ExperimentOutlined,
  HistoryOutlined,
  LineChartOutlined,
  LogoutOutlined,
  MessageOutlined,
} from '@ant-design/icons'
import { Outlet, useLocation, useNavigate } from 'react-router-dom'
import { useAuthStore } from '../stores/authStore'
import './AppLayout.css'

const { Sider, Content } = Layout

const MENU_ITEMS = [
  { key: '/', icon: <MessageOutlined />, label: '在线客服', scope: 'public' },
  { key: '/dashboard', icon: <DashboardOutlined />, label: '数据看板', scope: 'admin' },
  { key: '/knowledge', icon: <BookOutlined />, label: '知识库', scope: 'admin' },
  { key: '/rag-eval', icon: <ExperimentOutlined />, label: 'RAG 评测', scope: 'admin' },
  {
    key: '/observability',
    icon: <LineChartOutlined />,
    label: '可观测',
    scope: 'admin',
  },
  { key: '/sessions', icon: <HistoryOutlined />, label: '会话记录', scope: 'staff' },
]

export default function AppLayout() {
  const navigate = useNavigate()
  const location = useLocation()
  const { user, config, logout } = useAuthStore()

  const enabled = Boolean(config?.auth_enabled)
  const roles = user?.roles ?? []
  const isAdmin = !enabled || roles.includes('admin')
  const isStaff = !enabled || roles.includes('admin') || roles.includes('agent')

  const items = MENU_ITEMS.filter((item) => {
    if (item.scope === 'admin') return isAdmin
    if (item.scope === 'staff') return isStaff
    return true
  })

  const selectedKey =
    items.find((item) => item.key !== '/' && location.pathname.startsWith(item.key))
      ?.key ?? '/'

  return (
    <Layout className="app-layout">
      <Sider className="app-sider" breakpoint="lg" collapsedWidth={0} width={200}>
        <div className="app-logo">
          <span className="app-logo-mark" aria-hidden="true">
            售
          </span>
          <span>售后智答</span>
        </div>
        <Menu
          mode="inline"
          selectedKeys={[selectedKey]}
          items={items.map(({ key, icon, label }) => ({ key, icon, label }))}
          onClick={({ key }) => navigate(key)}
          style={{ borderInlineEnd: 'none' }}
        />
        {enabled && user && (
          <div style={{ padding: '16px 20px' }}>
            <Space direction="vertical" size={4} style={{ width: '100%' }}>
              <Typography.Text style={{ color: 'rgba(255,255,255,0.85)' }}>
                {user.display_name || user.username}
              </Typography.Text>
              <Typography.Text
                style={{ color: 'rgba(255,255,255,0.55)', fontSize: 12 }}
              >
                {user.roles.join(' / ')}
              </Typography.Text>
              <Button
                size="small"
                icon={<LogoutOutlined />}
                onClick={() => {
                  logout()
                  navigate('/login')
                }}
              >
                退出
              </Button>
            </Space>
          </div>
        )}
      </Sider>
      <Content className="app-content">
        <Outlet />
      </Content>
    </Layout>
  )
}
