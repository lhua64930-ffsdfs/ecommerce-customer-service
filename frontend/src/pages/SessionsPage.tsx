import { useEffect, useState } from 'react'
import { App, Button, Card, Drawer, Empty, Spin, Table, Tag } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { analyticsApi } from '../api/analytics'
import { chatApi } from '../api/chat'
import MessageBubble from '../components/MessageBubble'
import type { SessionItem } from '../types/api'
import type { Message } from '../types/chat'
import { formatTime } from '../utils/formatTime'
import './ChatPage.css'

const STATUS_META: Record<string, { color: string; label: string }> = {
  active: { color: 'green', label: '进行中' },
  waiting: { color: 'blue', label: '等待中' },
  transferred: { color: 'orange', label: '已转人工' },
  closed: { color: 'default', label: '已关闭' },
}

export default function SessionsPage() {
  const { message } = App.useApp()

  const [items, setItems] = useState<SessionItem[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [loading, setLoading] = useState(false)

  const [drawerOpen, setDrawerOpen] = useState(false)
  const [activeSession, setActiveSession] = useState<SessionItem | null>(null)
  const [history, setHistory] = useState<Message[]>([])
  const [historyLoading, setHistoryLoading] = useState(false)

  const load = async (nextPage = page) => {
    setLoading(true)
    try {
      const result = await analyticsApi.sessions(nextPage, 10)
      setItems(result.items)
      setTotal(result.total)
      setPage(nextPage)
    } catch {
      message.error('会话列表加载失败')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void load(1)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const openSession = async (session: SessionItem) => {
    setActiveSession(session)
    setDrawerOpen(true)
    setHistoryLoading(true)
    setHistory([])
    try {
      const result = await chatApi.getHistory(session.session_id, 1, 100)
      setHistory(
        result.messages.map((item) => ({
          id: String(item.id),
          senderType: item.sender_type,
          content: item.content,
          createdAt: item.created_at,
          intent: item.intent ?? undefined,
          sentiment: item.sentiment ?? undefined,
          sentimentScore: item.sentiment_score ?? undefined,
        })),
      )
    } catch {
      message.error('会话历史加载失败')
    } finally {
      setHistoryLoading(false)
    }
  }

  const columns: ColumnsType<SessionItem> = [
    {
      title: '会话ID',
      dataIndex: 'session_id',
      width: 240,
      ellipsis: true,
      render: (value: string) => <span title={value}>{value}</span>,
    },
    {
      title: '用户ID',
      dataIndex: 'user_id',
      width: 90,
    },
    {
      title: '状态',
      dataIndex: 'status',
      width: 100,
      render: (value: string) => {
        const meta = STATUS_META[value] ?? { color: 'default', label: value }
        return <Tag color={meta.color}>{meta.label}</Tag>
      },
    },
    {
      title: '消息数',
      dataIndex: 'message_count',
      width: 90,
    },
    {
      title: '满意度',
      dataIndex: 'satisfaction_score',
      width: 90,
      render: (value: number | null) => (value ? `${value}/5` : '—'),
    },
    {
      title: '开始时间',
      dataIndex: 'started_at',
      width: 160,
      render: (value: string | null) => (value ? formatTime(value) : '—'),
    },
    {
      title: '操作',
      key: 'actions',
      width: 90,
      render: (_, item) => (
        <Button type="link" size="small" onClick={() => void openSession(item)}>
          查看
        </Button>
      ),
    },
  ]

  return (
    <div className="app-page">
      <div className="app-page-header">
        <h1>会话记录</h1>
        <p>查看历史会话与完整对话内容</p>
      </div>

      <Card size="small">
        <Table
          rowKey="session_id"
          size="small"
          loading={loading}
          columns={columns}
          dataSource={items}
          pagination={{
            current: page,
            pageSize: 10,
            total,
            showSizeChanger: false,
            onChange: (nextPage) => void load(nextPage),
          }}
        />
      </Card>

      <Drawer
        title={`会话详情 ${activeSession?.session_id ?? ''}`}
        width={620}
        open={drawerOpen}
        onClose={() => setDrawerOpen(false)}
      >
        {historyLoading ? (
          <Spin style={{ display: 'block', margin: '60px auto' }} />
        ) : history.length ? (
          <div className="session-history">
            {history.map((item) => (
              <MessageBubble key={item.id} message={item} />
            ))}
          </div>
        ) : (
          <Empty description="该会话没有消息" />
        )}
      </Drawer>
    </div>
  )
}
