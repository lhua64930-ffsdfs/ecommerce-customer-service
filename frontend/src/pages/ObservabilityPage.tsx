import { Card, Col, Row, Statistic, Table, Tag, Typography, Alert } from 'antd'
import { useEffect, useState } from 'react'
import {
  observabilityApi,
  type CostItem,
  type ObservabilityOverview,
  type RunItem,
} from '../api/observability'

export default function ObservabilityPage() {
  const [overview, setOverview] = useState<ObservabilityOverview | null>(null)
  const [runs, setRuns] = useState<RunItem[]>([])
  const [cost, setCost] = useState<CostItem[]>([])
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let active = true
    Promise.all([
      observabilityApi.overview(7),
      observabilityApi.runs(7, 20),
      observabilityApi.cost(30),
    ])
      .then(([summary, runData, costData]) => {
        if (!active) return
        setOverview(summary)
        setRuns(runData.items)
        setCost(costData.items)
      })
      .catch(() => {
        if (active) setError('观测数据加载失败,请确认后端已启动且当前账号为管理员')
      })
    return () => {
      active = false
    }
  }, [])

  const totalTokens = cost.reduce((sum, item) => sum + item.tokens, 0)

  return (
    <div style={{ padding: 24 }}>
      <Typography.Title level={3}>可观测</Typography.Title>
      <Typography.Paragraph type="secondary">
        运行状态、失败工具、Token 成本与轨迹回放入口。
      </Typography.Paragraph>

      {error && (
        <Alert type="error" showIcon message={error} style={{ marginBottom: 16 }} />
      )}

      <Row gutter={[16, 16]}>
        <Col xs={12} md={6}>
          <Card>
            <Statistic title="近 7 天运行" value={overview?.runs.total ?? 0} />
          </Card>
        </Col>
        <Col xs={12} md={6}>
          <Card>
            <Statistic title="失败步骤" value={overview?.steps.failed ?? 0} />
          </Card>
        </Col>
        <Col xs={12} md={6}>
          <Card>
            <Statistic title="低置信度待审" value={overview?.low_confidence.pending ?? 0} />
          </Card>
        </Col>
        <Col xs={12} md={6}>
          <Card>
            <Statistic title="近 30 天 Token" value={totalTokens} />
          </Card>
        </Col>
      </Row>

      <Card title="最近运行" style={{ marginTop: 16 }}>
        <Table<RunItem>
          rowKey="run_id"
          size="small"
          pagination={false}
          dataSource={runs}
          columns={[
            { title: 'run_id', dataIndex: 'run_id', ellipsis: true },
            {
              title: '状态',
              dataIndex: 'status',
              render: (value: string) => <Tag>{value}</Tag>,
            },
            { title: '模式', dataIndex: 'agent_mode' },
            { title: '步骤', dataIndex: 'total_steps' },
            { title: '耗时(ms)', dataIndex: 'total_latency_ms' },
            { title: 'Token', dataIndex: 'total_tokens' },
          ]}
        />
      </Card>

      <Card title="失败工具 Top" style={{ marginTop: 16 }}>
        <Table
          rowKey="name"
          size="small"
          pagination={false}
          dataSource={overview?.steps.top_failing_tools ?? []}
          columns={[
            { title: '工具', dataIndex: 'name' },
            { title: '失败次数', dataIndex: 'failed' },
          ]}
        />
      </Card>

      <Card title="按天 Token" style={{ marginTop: 16 }}>
        <Table
          rowKey="date"
          size="small"
          pagination={false}
          dataSource={cost}
          columns={[
            { title: '日期', dataIndex: 'date' },
            { title: '运行数', dataIndex: 'runs' },
            { title: 'Token', dataIndex: 'tokens' },
          ]}
        />
      </Card>

      {overview && (
        <Typography.Paragraph type="secondary" style={{ marginTop: 16 }}>
          Langfuse:{overview.langfuse_enabled ? '已启用' : '未配置'}
        </Typography.Paragraph>
      )}
    </div>
  )
}
