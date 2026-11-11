import { Button, Card, Form, Input, Typography, Alert } from 'antd'
import { useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuthStore } from '../stores/authStore'

export default function LoginPage() {
  const navigate = useNavigate()
  const { config, user, error, login, init, clearError } = useAuthStore()

  useEffect(() => {
    void init()
  }, [init])

  useEffect(() => {
    if (user) navigate('/', { replace: true })
  }, [navigate, user])

  const onFinish = async (values: { username: string; password: string }) => {
    const ok = await login(values.username, values.password)
    if (ok) navigate('/', { replace: true })
  }

  return (
    <div
      style={{
        minHeight: '100vh',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        background: '#f4efe6',
        padding: 24,
      }}
    >
      <Card style={{ width: 380 }}>
        <Typography.Title level={3} style={{ marginBottom: 4 }}>
          售后智答
        </Typography.Title>
        <Typography.Paragraph type="secondary">
          登录后进入售后受理台
        </Typography.Paragraph>

        {error && (
          <Alert
            type="error"
            message={error}
            showIcon
            closable
            onClose={clearError}
            style={{ marginBottom: 16 }}
          />
        )}

        {config && !config.auth_enabled ? (
          <>
            <Alert
              type="info"
              showIcon
              message="当前为本地演示模式,未启用鉴权"
              style={{ marginBottom: 16 }}
            />
            <Button type="primary" block onClick={() => navigate('/')}>
              进入演示
            </Button>
          </>
        ) : (
          <Form layout="vertical" onFinish={onFinish}>
            <Form.Item
              label="账号"
              name="username"
              rules={[{ required: true, message: '请输入账号' }]}
            >
              <Input placeholder="demo_admin" autoComplete="username" />
            </Form.Item>
            <Form.Item
              label="密码"
              name="password"
              rules={[{ required: true, message: '请输入密码' }]}
            >
              <Input.Password
                placeholder="admin123"
                autoComplete="current-password"
              />
            </Form.Item>
            <Button type="primary" htmlType="submit" block>
              登录
            </Button>
            <Typography.Paragraph
              type="secondary"
              style={{ marginTop: 12, marginBottom: 0, fontSize: 12 }}
            >
              演示账号:demo_customer / demo123、demo_admin / admin123
            </Typography.Paragraph>
          </Form>
        )}
      </Card>
    </div>
  )
}
