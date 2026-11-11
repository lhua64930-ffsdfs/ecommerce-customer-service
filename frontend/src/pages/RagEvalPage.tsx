import { useEffect, useState } from 'react'
import {
  Alert,
  Button,
  Card,
  Col,
  Empty,
  Row,
  Space,
  Spin,
  Statistic,
  Table,
  Tag,
  Typography,
} from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { jobApi, type JobStatus } from '../api/jobs'
import {
  ragEvalApi,
  type RagEvalOverview,
  type StrategyReport,
} from '../api/ragEval'

const STRATEGY_ORDER = ['vector', 'bm25', 'hybrid', 'hybrid_rerank']
const JOB_LABELS: Record<string, string> = {
  'evaluate-rag': '重跑检索评测',
  'evaluate-refusal': '重跑拒答评测',
  'mine-knowledge': '对话挖知识',
  'import-manual': '导入售后手册',
  'reset-demo-data': '重置演示数据',
}
const JOB_ORDER = [
  'evaluate-rag',
  'evaluate-refusal',
  'mine-knowledge',
  'import-manual',
]

interface StrategyRow {
  strategy: string
  report: StrategyReport
}

export default function RagEvalPage() {
  const [data, setData] = useState<RagEvalOverview | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [jobs, setJobs] = useState<Record<string, JobStatus>>({})
  const [activeJob, setActiveJob] = useState<JobStatus | null>(null)
  const [jobBusy, setJobBusy] = useState(false)

  const loadOverview = async () => {
    try {
      setData(await ragEvalApi.overview())
    } catch {
      setError('评测概览加载失败')
    } finally {
      setLoading(false)
    }
  }

  const loadJobs = async () => {
    try {
      const result = await jobApi.list()
      setJobs(
        Object.fromEntries(result.jobs.map((item) => [item.name, item])),
      )
    } catch {
      // 作业列表失败不阻塞评测看板
    }
  }

  useEffect(() => {
    void loadOverview()
    void loadJobs()
  }, [])

  const runJob = async (name: string) => {
    setJobBusy(true)
    try {
      let current = await jobApi.start(name)
      setActiveJob(current)
      while (current.status === 'running') {
        await new Promise((resolve) => setTimeout(resolve, 2000))
        current = await jobApi.status(name)
        setActiveJob(current)
      }
      await loadJobs()
      await loadOverview()
    } catch {
      setError('作业启动失败')
    } finally {
      setJobBusy(false)
    }
  }

  if (loading) {
    return <Spin style={{ display: 'block', margin: '80px auto' }} />
  }
  if (error) {
    return <Alert type="error" message={error} showIcon />
  }
  if (!data) {
    return <Empty description="暂无评测数据" />
  }

  const rows: StrategyRow[] = data.rag
    ? Object.entries(data.rag.strategies)
        .map(([strategy, report]) => ({ strategy, report }))
        .sort(
          (a, b) =>
            STRATEGY_ORDER.indexOf(a.strategy) - STRATEGY_ORDER.indexOf(b.strategy),
        )
    : []

  const columns: ColumnsType<StrategyRow> = [
    {
      title: '策略',
      dataIndex: 'strategy',
      render: (value: string) => (
        <Tag color={value === data.best_strategy?.name ? 'red' : 'default'}>
          {value}
        </Tag>
      ),
    },
    {
      title: 'Recall@1',
      dataIndex: ['report', 'recall_at_1'],
      render: (value: number) => value.toFixed(4),
    },
    {
      title: 'Recall@3',
      dataIndex: ['report', 'recall_at_3'],
      render: (value: number) => value.toFixed(4),
    },
    {
      title: 'Recall@5',
      dataIndex: ['report', 'recall_at_5'],
      render: (value: number) => value.toFixed(4),
    },
    {
      title: 'MRR@5',
      dataIndex: ['report', 'mrr_at_5'],
      render: (value: number) => value.toFixed(4),
    },
    {
      title: '检索模式',
      dataIndex: ['report', 'retrieval_modes'],
      render: (modes: Record<string, number>) =>
        Object.entries(modes)
          .map(([name, count]) => `${name}=${count}`)
          .join(', '),
    },
  ]

  return (
    <div className="app-page">
      <div className="app-page-header">
        <h1>RAG 评测</h1>
        <p>
          四策略检索对照 + 无答案拒答率。页面只读取评测产物,不在请求里重算。
        </p>
      </div>

      {!data.present ? (
        <Alert
          type="warning"
          showIcon
          style={{ marginBottom: 16 }}
          message="还没有 RAG 评测产物"
          description={
            <Typography.Text code>{data.commands.rag}</Typography.Text>
          }
        />
      ) : (
        <>
          <Row gutter={16} style={{ marginBottom: 16 }}>
            <Col xs={24} sm={12} lg={6}>
              <Card size="small">
                <Statistic
                  title="最佳策略"
                  value={data.best_strategy?.name ?? '—'}
                />
              </Card>
            </Col>
            <Col xs={24} sm={12} lg={6}>
              <Card size="small">
                <Statistic
                  title="最佳 MRR@5"
                  value={data.best_strategy?.mrr_at_5 ?? 0}
                  precision={4}
                />
              </Card>
            </Col>
            <Col xs={24} sm={12} lg={6}>
              <Card size="small">
                <Statistic
                  title="无答案拒答率"
                  value={data.refusal?.refusal_rate ?? 0}
                  precision={4}
                />
              </Card>
            </Col>
            <Col xs={24} sm={12} lg={6}>
              <Card size="small">
                <Statistic
                  title="拒答样本"
                  value={
                    data.refusal
                      ? `${data.refusal.refused}/${data.refusal.total}`
                      : '—'
                  }
                />
              </Card>
            </Col>
          </Row>

          <Card
            size="small"
            title={`检索策略对照(${data.rag?.total ?? 0} 条查询)`}
            style={{ marginBottom: 16 }}
            extra={
              <Typography.Text type="secondary">
                生成于 {data.rag_generated_at ?? '—'}
              </Typography.Text>
            }
          >
            <Table
              rowKey="strategy"
              size="small"
              columns={columns}
              dataSource={rows}
              pagination={false}
            />
          </Card>

          <Card
            size="small"
            title="无答案拒答评测"
            extra={
              <Typography.Text type="secondary">
                生成于 {data.refusal_generated_at ?? '—'}
              </Typography.Text>
            }
          >
            {data.refusal ? (
              <Typography.Paragraph style={{ margin: 0 }}>
                共 {data.refusal.total} 条知识库外问题,正确拒答{' '}
                {data.refusal.refused} 条,拒答率{' '}
                {(data.refusal.refusal_rate * 100).toFixed(1)}%。
                命令:<Typography.Text code>{data.commands.refusal}</Typography.Text>
              </Typography.Paragraph>
            ) : (
              <Typography.Paragraph style={{ margin: 0 }}>
                还没有拒答评测产物。运行{' '}
                <Typography.Text code>{data.commands.refusal}</Typography.Text>{' '}
                后刷新。
              </Typography.Paragraph>
            )}
          </Card>
        </>
      )}

      <Card size="small" title="后台作业" style={{ marginTop: 16 }}>
        <Space wrap>
          {JOB_ORDER.map((name) => (
            <Button
              key={name}
              loading={jobBusy && activeJob?.name === name}
              disabled={jobBusy}
              title={jobs[name]?.description}
              onClick={() => void runJob(name)}
            >
              {JOB_LABELS[name] ?? name}
              {jobs[name]?.status === 'running' ? ' · 运行中' : ''}
            </Button>
          ))}
        </Space>
        {activeJob && (
          <div style={{ marginTop: 12 }}>
            <Space>
              <Tag
                color={
                  activeJob.status === 'succeeded'
                    ? 'green'
                    : activeJob.status === 'failed'
                      ? 'red'
                      : activeJob.status === 'running'
                        ? 'blue'
                        : 'default'
                }
              >
                {activeJob.status}
              </Tag>
              <span>{activeJob.title}</span>
              {activeJob.returncode !== null && (
                <Typography.Text type="secondary">
                  exit={activeJob.returncode}
                </Typography.Text>
              )}
            </Space>
            {activeJob.log && (
              <pre className="job-log">{activeJob.log}</pre>
            )}
          </div>
        )}
      </Card>
    </div>
  )
}
