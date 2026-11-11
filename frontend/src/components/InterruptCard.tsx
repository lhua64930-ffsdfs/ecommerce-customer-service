import { Button, Card, Space, Tag, Typography } from 'antd'
import type { InterruptPayload } from '../types/chat'

interface Props {
  interrupt: InterruptPayload
  disabled?: boolean
  onResume: (resume: Record<string, unknown>) => void
}

export default function InterruptCard({
  interrupt,
  disabled,
  onResume,
}: Props) {
  if (interrupt.type === 'select_order') {
    return (
      <Card
        size="small"
        title="请选择要办理的订单"
        style={{ margin: '8px 0 16px 56px', maxWidth: 560 }}
      >
        <Space direction="vertical" style={{ width: '100%' }} size={8}>
          {interrupt.orders.map((order) => (
            <Button
              key={order.order_no}
              block
              disabled={disabled}
              onClick={() =>
                onResume({
                  type: 'select_order',
                  order_no: order.order_no,
                })
              }
              style={{ textAlign: 'left', height: 'auto', padding: '10px 12px' }}
            >
              <Space direction="vertical" size={0} style={{ width: '100%' }}>
                <Space>
                  <strong>{order.order_no}</strong>
                  {order.status ? <Tag>{order.status}</Tag> : null}
                </Space>
                <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                  {order.product_name || '订单'}
                  {order.pay_amount != null
                    ? ` · ¥${Number(order.pay_amount).toFixed(2)}`
                    : ''}
                </Typography.Text>
              </Space>
            </Button>
          ))}
          {interrupt.orders.length === 0 && (
            <Typography.Text type="secondary">没有可选订单</Typography.Text>
          )}
        </Space>
      </Card>
    )
  }

  if (interrupt.type === 'confirm_ticket') {
    const preview = interrupt.preview || {}
    return (
      <Card
        size="small"
        title="确认创建工单"
        style={{ margin: '8px 0 16px 56px', maxWidth: 560 }}
      >
        <Typography.Paragraph style={{ marginBottom: 8 }}>
          {String(preview.content || preview.title || '请确认是否提交工单')}
        </Typography.Paragraph>
        <Space>
          <Button
            type="primary"
            disabled={disabled}
            onClick={() =>
              onResume({ type: 'confirm_ticket', confirmed: true })
            }
          >
            确认提交
          </Button>
          <Button
            disabled={disabled}
            onClick={() =>
              onResume({ type: 'confirm_ticket', confirmed: false })
            }
          >
            取消
          </Button>
        </Space>
      </Card>
    )
  }

  return null
}
