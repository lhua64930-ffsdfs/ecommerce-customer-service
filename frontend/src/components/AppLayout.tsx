import { Layout, Menu } from 'antd'
import {
  BookOutlined,
  DashboardOutlined,
  HistoryOutlined,
  MessageOutlined,
} from '@ant-design/icons'
import { Outlet, useLocation, useNavigate } from 'react-router-dom'
import './AppLayout.css'

const { Sider, Content } = Layout

const MENU_ITEMS = [
  { key: '/', icon: <MessageOutlined />, label: '在线客服' },
  { key: '/dashboard', icon: <DashboardOutlined />, label: '数据看板' },
  { key: '/knowledge', icon: <BookOutlined />, label: '知识库' },
  { key: '/sessions', icon: <HistoryOutlined />, label: '会话记录' },
]

export default function AppLayout() {
  const navigate = useNavigate()
  const location = useLocation()

  const selectedKey =
    MENU_ITEMS.find((item) => item.key !== '/' && location.pathname.startsWith(item.key))?.key ??
    '/'

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
          items={MENU_ITEMS}
          onClick={({ key }) => navigate(key)}
          style={{ borderInlineEnd: 'none' }}
        />
      </Sider>
      <Content className="app-content">
        <Outlet />
      </Content>
    </Layout>
  )
}
