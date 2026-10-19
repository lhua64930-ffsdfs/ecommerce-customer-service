import { useEffect, useState } from 'react'
import { App, Card, Col, Collapse, Empty, Row, Spin, Statistic, Table } from 'antd'
import ReactECharts from 'echarts-for-react'
import { analyticsApi } from '../api/analytics'
import type { AnalyticsSummary } from '../types/api'
import './DashboardPage.css'

const SENTIMENT_ORDER = ['negative', 'neutral', 'positive'] as const
const SENTIMENT_LABELS: Record<string, string> = {
  negative: '消极',
  neutral: '中性',
  positive: '积极',
}
const SENTIMENT_COLORS: Record<string, string> = {
  negative: '#d03b3b',
  neutral: '#898781',
  positive: '#2a78d6',
}

export default function DashboardPage() {
  const { message } = App.useApp()
  const [summary, setSummary] = useState<AnalyticsSummary | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    const load = async () => {
      try {
        setSummary(await analyticsApi.summary())
      } catch {
        message.error('数据加载失败,请稍后重试')
      } finally {
        setLoading(false)
      }
    }
    void load()
  }, [message])

  if (loading) {
    return <Spin size="large" className="dashboard-loading" />
  }

  if (!summary) {
    return (
      <div className="app-page">
        <Empty description="暂无数据" />
      </div>
    )
  }

  const kpis = [
    { title: '会话总量', value: summary.sessions_total },
    { title: '今日会话', value: summary.sessions_today },
    { title: '消息总量', value: summary.messages_total },
    { title: '用户总数', value: summary.users_total },
    {
      title: 'AI 解决率',
      value: (summary.ai_resolution_rate * 100).toFixed(1),
      suffix: '%',
    },
    {
      title: '转人工率',
      value: (summary.transfer_rate * 100).toFixed(1),
      suffix: '%',
    },
    {
      title: '平均满意度',
      value: summary.satisfaction_avg ?? '—',
      suffix: summary.satisfaction_avg ? '/5' : '',
    },
    { title: '待处理工单', value: summary.open_tickets },
  ]

  // 意图分布:横向条形图,单色(比较量级)
  const intentData = [...summary.intent_distribution].sort((a, b) => a.count - b.count)
  const intentOption = {
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
    grid: { left: 8, right: 48, top: 8, bottom: 8, containLabel: true },
    xAxis: {
      type: 'value',
      axisLabel: { color: '#898781' },
      splitLine: { lineStyle: { color: '#e1e0d9' } },
    },
    yAxis: {
      type: 'category',
      data: intentData.map((item) => item.name),
      axisTick: { show: false },
      axisLine: { lineStyle: { color: '#c3c2b7' } },
      axisLabel: { color: '#52514e' },
    },
    series: [
      {
        type: 'bar',
        data: intentData.map((item) => item.count),
        barWidth: 14,
        itemStyle: { color: '#2a78d6', borderRadius: [0, 4, 4, 0] },
        label: { show: true, position: 'right', color: '#52514e', fontSize: 12 },
      },
    ],
  }

  // 情感分布:发散堆叠条(消极红 ↔ 中性灰 ↔ 积极蓝)
  const sentimentCounts = Object.fromEntries(
    summary.sentiment_distribution.map((item) => [item.name, item.count]),
  )
  const sentimentTotal = SENTIMENT_ORDER.reduce(
    (sum, key) => sum + (sentimentCounts[key] ?? 0),
    0,
  )
  const sentimentPercent = Object.fromEntries(
    SENTIMENT_ORDER.map((key) => [
      key,
      sentimentTotal ? Number((((sentimentCounts[key] ?? 0) / sentimentTotal) * 100).toFixed(1)) : 0,
    ]),
  ) as Record<string, number>

  const sentimentOption = {
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'shadow' },
      valueFormatter: (value: number) => `${value}%`,
    },
    legend: {
      top: 0,
      data: SENTIMENT_ORDER.map((key) => SENTIMENT_LABELS[key]),
      textStyle: { color: '#52514e' },
    },
    grid: { left: 8, right: 28, top: 40, bottom: 8, containLabel: true },
    xAxis: {
      type: 'value',
      max: 100,
      axisLabel: { color: '#898781', formatter: '{value}%' },
      splitLine: { lineStyle: { color: '#e1e0d9' } },
    },
    yAxis: {
      type: 'category',
      data: ['占比'],
      axisTick: { show: false },
      axisLine: { lineStyle: { color: '#c3c2b7' } },
      axisLabel: { color: '#52514e' },
    },
    series: SENTIMENT_ORDER.map((key, index) => {
      const percent = sentimentPercent[key]
      return {
        name: SENTIMENT_LABELS[key],
        type: 'bar',
        stack: 'sentiment',
        barWidth: 32,
        data: [percent],
        itemStyle: {
          color: SENTIMENT_COLORS[key],
          borderColor: '#fff',
          borderWidth: 2,
          borderRadius:
            index === 0 ? [4, 0, 0, 4] : index === SENTIMENT_ORDER.length - 1 ? [0, 4, 4, 0] : 0,
        },
        label: {
          show: percent >= 8,
          position: 'inside',
          formatter: `${percent}%`,
          color: '#fff',
          fontSize: 12,
        },
      }
    }),
  }

  return (
    <div className="app-page">
      <div className="app-page-header">
        <h1>数据看板</h1>
        <p>实时统计客服会话、意图与情感分布</p>
      </div>

      <Row gutter={[16, 16]}>
        {kpis.map((kpi) => (
          <Col xs={12} sm={8} lg={6} key={kpi.title}>
            <Card className="kpi-card" size="small">
              <Statistic title={kpi.title} value={kpi.value} suffix={kpi.suffix} />
            </Card>
          </Col>
        ))}
      </Row>

      <Row gutter={[16, 16]} className="dashboard-charts">
        <Col xs={24} lg={14}>
          <Card title="意图分布" size="small">
            {intentData.length ? (
              <>
                <ReactECharts
                  option={intentOption}
                  style={{ height: Math.max(260, intentData.length * 34 + 40) }}
                  notMerge
                />
                <Collapse
                  ghost
                  size="small"
                  items={[
                    {
                      key: 'table',
                      label: '查看数据表',
                      children: (
                        <Table
                          size="small"
                          pagination={false}
                          rowKey="name"
                          dataSource={summary.intent_distribution}
                          columns={[
                            { title: '意图', dataIndex: 'name' },
                            { title: '数量', dataIndex: 'count', width: 100 },
                          ]}
                        />
                      ),
                    },
                  ]}
                />
              </>
            ) : (
              <Empty description="暂无意图数据" />
            )}
          </Card>
        </Col>

        <Col xs={24} lg={10}>
          <Card title="情感分布" size="small">
            {sentimentTotal ? (
              <>
                <ReactECharts option={sentimentOption} style={{ height: 160 }} notMerge />
                <Collapse
                  ghost
                  size="small"
                  items={[
                    {
                      key: 'table',
                      label: '查看数据表',
                      children: (
                        <Table
                          size="small"
                          pagination={false}
                          rowKey="name"
                          dataSource={SENTIMENT_ORDER.map((key) => ({
                            name: SENTIMENT_LABELS[key],
                            count: sentimentCounts[key] ?? 0,
                          }))}
                          columns={[
                            { title: '情感', dataIndex: 'name' },
                            { title: '数量', dataIndex: 'count', width: 100 },
                          ]}
                        />
                      ),
                    },
                  ]}
                />
              </>
            ) : (
              <Empty description="暂无情感数据" />
            )}
          </Card>
        </Col>
      </Row>
    </div>
  )
}
