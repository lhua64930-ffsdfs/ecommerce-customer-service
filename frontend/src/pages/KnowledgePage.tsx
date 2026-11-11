import { useEffect, useState } from 'react'
import {
  App,
  Button,
  Card,
  Empty,
  Form,
  Input,
  List,
  Modal,
  Popconfirm,
  Space,
  Spin,
  Table,
  Tag,
  Typography,
} from 'antd'
import { PlusOutlined, ReloadOutlined } from '@ant-design/icons'
import type { ColumnsType } from 'antd/es/table'
import { knowledgeApi, reviewApi, type KnowledgePayload } from '../api/knowledge'
import type {
  KnowledgeDocumentItem,
  KnowledgeItem,
  KnowledgeSearchResult,
  ReviewItem,
} from '../types/api'

export default function KnowledgePage() {
  const { message } = App.useApp()
  const [form] = Form.useForm<KnowledgePayload>()
  const [docForm] = Form.useForm<{
    title: string
    source?: string
    content: string
  }>()

  const [items, setItems] = useState<KnowledgeItem[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [loading, setLoading] = useState(false)

  const [modalOpen, setModalOpen] = useState(false)
  const [editing, setEditing] = useState<KnowledgeItem | null>(null)
  const [submitting, setSubmitting] = useState(false)

  const [searchKeyword, setSearchKeyword] = useState('')
  const [searchResults, setSearchResults] = useState<KnowledgeSearchResult[]>([])
  const [searching, setSearching] = useState(false)

  const [reviewItems, setReviewItems] = useState<ReviewItem[]>([])
  const [reviewLoading, setReviewLoading] = useState(false)
  const [lowConfCount, setLowConfCount] = useState(0)
  const [mining, setMining] = useState(false)

  const [documents, setDocuments] = useState<KnowledgeDocumentItem[]>([])
  const [documentsLoading, setDocumentsLoading] = useState(false)
  const [docModalOpen, setDocModalOpen] = useState(false)
  const [docSubmitting, setDocSubmitting] = useState(false)

  const load = async (nextPage = page) => {
    setLoading(true)
    try {
      const result = await knowledgeApi.list({ page: nextPage, page_size: 10 })
      setItems(result.items)
      setTotal(result.total)
      setPage(nextPage)
    } catch {
      message.error('知识库加载失败')
    } finally {
      setLoading(false)
    }
  }

  const loadReview = async () => {
    setReviewLoading(true)
    try {
      const result = await reviewApi.queue()
      setReviewItems(result.items)
      setLowConfCount(result.pending_low_confidence)
    } catch {
      message.error('待审队列加载失败')
    } finally {
      setReviewLoading(false)
    }
  }

  const loadDocuments = async () => {
    setDocumentsLoading(true)
    try {
      const result = await knowledgeApi.documents()
      setDocuments(result.items)
    } catch {
      message.error('文档知识加载失败')
    } finally {
      setDocumentsLoading(false)
    }
  }

  useEffect(() => {
    void load(1)
    void loadReview()
    void loadDocuments()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const openCreate = () => {
    setEditing(null)
    form.resetFields()
    setModalOpen(true)
  }

  const openEdit = (item: KnowledgeItem) => {
    setEditing(item)
    form.setFieldsValue({
      category: item.category,
      question: item.question,
      answer: item.answer,
      keywords: item.keywords ?? '',
    })
    setModalOpen(true)
  }

  const submit = async () => {
    try {
      const values = await form.validateFields()
      setSubmitting(true)
      if (editing) {
        await knowledgeApi.update(editing.id, values)
        message.success('更新成功,向量已重建')
      } else {
        await knowledgeApi.add(values)
        message.success('新增成功,向量已写入')
      }
      setModalOpen(false)
      setEditing(null)
      form.resetFields()
      await load(editing ? page : 1)
    } catch (error) {
      if ((error as { errorFields?: unknown }).errorFields) return
      message.error('保存失败,请稍后重试')
    } finally {
      setSubmitting(false)
    }
  }

  const mineKnowledge = async () => {
    setMining(true)
    try {
      const result = await reviewApi.mine()
      if (result.kept > 0) {
        message.success(`抽取完成:新增 ${result.kept} 条候选知识`)
      } else {
        message.info(result.reason || '暂无可抽取的候选知识')
      }
      await loadReview()
    } catch {
      message.error('知识抽取失败')
    } finally {
      setMining(false)
    }
  }

  const approveReview = async (item: ReviewItem) => {
    try {
      await reviewApi.approve(item.id)
      message.success('已采纳并写入知识库')
      await loadReview()
      await load(1)
    } catch {
      message.error('采纳失败')
    }
  }

  const discardReview = async (item: ReviewItem) => {
    try {
      await reviewApi.discard(item.id)
      message.success('已弃用')
      await loadReview()
    } catch {
      message.error('操作失败')
    }
  }

  const submitDocument = async () => {
    try {
      const values = await docForm.validateFields()
      setDocSubmitting(true)
      const result = await knowledgeApi.importDocument(values)
      message.success(
        `导入成功:${result.chunks} 个片段${result.vectorized ? ',已向量化' : ',向量化失败'}`,
      )
      setDocModalOpen(false)
      docForm.resetFields()
      await loadDocuments()
    } catch (error) {
      if ((error as { errorFields?: unknown }).errorFields) return
      message.error('文档导入失败')
    } finally {
      setDocSubmitting(false)
    }
  }

  const removeDocument = async (id: number) => {
    try {
      await knowledgeApi.deleteDocument(id)
      message.success('文档已删除')
      await loadDocuments()
    } catch {
      message.error('删除失败')
    }
  }

  const remove = async (id: number) => {
    try {
      await knowledgeApi.remove(id)
      message.success('已删除')
      await load(page)
    } catch {
      message.error('删除失败')
    }
  }

  const search = async (value: string) => {
    const keyword = value.trim()
    setSearchKeyword(keyword)
    if (!keyword) {
      setSearchResults([])
      return
    }
    setSearching(true)
    try {
      const result = await knowledgeApi.search(keyword, 5)
      setSearchResults(result.results)
    } catch {
      message.error('语义检索失败')
    } finally {
      setSearching(false)
    }
  }

  const columns: ColumnsType<KnowledgeItem> = [
    {
      title: '分类',
      dataIndex: 'category',
      width: 120,
      render: (value: string) => <Tag color="blue">{value}</Tag>,
    },
    {
      title: '问题',
      dataIndex: 'question',
      ellipsis: true,
    },
    {
      title: '关键词',
      dataIndex: 'keywords',
      width: 180,
      ellipsis: true,
    },
    {
      title: '向量',
      dataIndex: 'vector_id',
      width: 90,
      render: (value: string | null) =>
        value ? <Tag color="green">已索引</Tag> : <Tag color="orange">未索引</Tag>,
    },
    {
      title: '操作',
      key: 'actions',
      width: 130,
      render: (_, item) => (
        <Space size="small">
          <Button type="link" size="small" onClick={() => openEdit(item)}>
            编辑
          </Button>
          <Popconfirm
            title="确认删除这条知识?"
            description="删除后会同时移除对应向量"
            onConfirm={() => void remove(item.id)}
          >
            <Button type="link" size="small" danger>
              删除
            </Button>
          </Popconfirm>
        </Space>
      ),
    },
  ]

  const documentColumns: ColumnsType<KnowledgeDocumentItem> = [
    { title: '标题', dataIndex: 'title', ellipsis: true },
    {
      title: '来源',
      dataIndex: 'source',
      width: 180,
      ellipsis: true,
      render: (value: string | null) => value || '—',
    },
    { title: '片段', dataIndex: 'chunks', width: 80 },
    {
      title: '状态',
      dataIndex: 'status',
      width: 90,
      render: (value: string) => <Tag color="green">{value}</Tag>,
    },
    {
      title: '操作',
      key: 'actions',
      width: 90,
      render: (_, item) => (
        <Popconfirm
          title="确认删除这份文档?"
          description="删除后会同时移除全部片段向量"
          onConfirm={() => void removeDocument(item.id)}
        >
          <Button type="link" size="small" danger>
            删除
          </Button>
        </Popconfirm>
      ),
    },
  ]

  return (
    <div className="app-page">
      <div className="app-page-header">
        <h1>知识库管理</h1>
        <p>维护客服知识条目,保存后自动写入 Milvus 向量索引</p>
      </div>

      <Card size="small" title="语义检索" style={{ marginBottom: 16 }}>
        <Input.Search
          placeholder="输入问题,按语义检索知识库,例如:退款多久到账"
          enterButton="检索"
          allowClear
          loading={searching}
          onSearch={(value) => void search(value)}
        />
        {searching ? (
          <Spin style={{ display: 'block', margin: '24px auto' }} />
        ) : searchResults.length > 0 ? (
          <List
            style={{ marginTop: 16 }}
            dataSource={searchResults}
            renderItem={(item) => (
              <List.Item>
                <List.Item.Meta
                  title={
                    <Space>
                      <span>{item.question}</span>
                      <Tag color="green">相似度 {(item.score * 100).toFixed(0)}%</Tag>
                      <Tag>{item.category}</Tag>
                    </Space>
                  }
                  description={item.answer}
                />
              </List.Item>
            )}
          />
        ) : searchKeyword ? (
          <Empty
            style={{ marginTop: 24 }}
            description={`未检索到与「${searchKeyword}」相关的内容`}
          />
        ) : null}
      </Card>

      <Card
        size="small"
        title={`文档知识(${documents.length})`}
        style={{ marginBottom: 16 }}
        extra={
          <Space>
            <Button icon={<ReloadOutlined />} onClick={() => void loadDocuments()}>
              刷新
            </Button>
            <Button
              type="primary"
              icon={<PlusOutlined />}
              onClick={() => {
                docForm.resetFields()
                setDocModalOpen(true)
              }}
            >
              导入 Markdown
            </Button>
          </Space>
        }
      >
        <Table
          rowKey="id"
          size="small"
          loading={documentsLoading}
          columns={documentColumns}
          dataSource={documents}
          pagination={false}
          locale={{ emptyText: '暂无文档知识,可导入 Markdown 长文档' }}
        />
      </Card>

      <Card
        size="small"
        title={`知识飞轮 · 待审队列(${reviewItems.length})`}
        style={{ marginBottom: 16 }}
        extra={
          <Space>
            <Tag color={lowConfCount > 0 ? 'orange' : 'default'}>
              低置信度待处理 {lowConfCount}
            </Tag>
            <Button icon={<ReloadOutlined />} onClick={() => void loadReview()}>
              刷新
            </Button>
            <Button loading={mining} onClick={() => void mineKnowledge()}>
              抽取候选
            </Button>
          </Space>
        }
      >
        {reviewLoading ? (
          <Spin style={{ display: 'block', margin: '24px auto' }} />
        ) : reviewItems.length > 0 ? (
          <List
            dataSource={reviewItems}
            renderItem={(item) => (
              <List.Item
                actions={[
                  <Button
                    key="approve"
                    type="link"
                    size="small"
                    onClick={() => void approveReview(item)}
                  >
                    采纳
                  </Button>,
                  <Popconfirm
                    key="discard"
                    title="确认弃用这条候选知识?"
                    onConfirm={() => void discardReview(item)}
                  >
                    <Button type="link" size="small" danger>
                      弃用
                    </Button>
                  </Popconfirm>,
                ]}
              >
                <List.Item.Meta
                  title={
                    <Space>
                      <Tag color="purple">对话沉淀</Tag>
                      <span>{item.question}</span>
                    </Space>
                  }
                  description={item.answer}
                />
              </List.Item>
            )}
          />
        ) : (
          <Empty description="暂无待审候选知识" />
        )}
      </Card>

      <Card
        size="small"
        title={`知识库条目(${total})`}
        extra={
          <Space>
            <Button icon={<ReloadOutlined />} onClick={() => void load(page)}>
              刷新
            </Button>
            <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>
              新增知识
            </Button>
          </Space>
        }
      >
        <Table
          rowKey="id"
          size="small"
          loading={loading}
          columns={columns}
          dataSource={items}
          expandable={{
            expandedRowRender: (item) => (
              <Typography.Paragraph style={{ margin: 0 }}>{item.answer}</Typography.Paragraph>
            ),
          }}
          pagination={{
            current: page,
            pageSize: 10,
            total,
            showSizeChanger: false,
            onChange: (nextPage) => void load(nextPage),
          }}
        />
      </Card>

      <Modal
        title={editing ? '编辑知识' : '新增知识'}
        open={modalOpen}
        confirmLoading={submitting}
        onOk={() => void submit()}
        onCancel={() => {
          setModalOpen(false)
          setEditing(null)
        }}
        destroyOnHidden
        width={640}
      >
        <Form form={form} layout="vertical" style={{ marginTop: 12 }}>
          <Form.Item
            name="category"
            label="分类"
            rules={[{ required: true, message: '请输入分类' }]}
          >
            <Input placeholder="例如:退换货政策 / 配送服务" maxLength={50} />
          </Form.Item>
          <Form.Item
            name="question"
            label="问题"
            rules={[{ required: true, message: '请输入问题' }]}
          >
            <Input.TextArea rows={2} placeholder="用户可能提出的问题" />
          </Form.Item>
          <Form.Item
            name="answer"
            label="答案"
            rules={[{ required: true, message: '请输入答案' }]}
          >
            <Input.TextArea rows={4} placeholder="标准回答内容" />
          </Form.Item>
          <Form.Item name="keywords" label="关键词(空格分隔,可选)">
            <Input placeholder="例如:退款 到账 多久" maxLength={500} />
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        title="导入 Markdown 文档"
        open={docModalOpen}
        confirmLoading={docSubmitting}
        onOk={() => void submitDocument()}
        onCancel={() => setDocModalOpen(false)}
        destroyOnHidden
        width={760}
      >
        <Form form={docForm} layout="vertical" style={{ marginTop: 12 }}>
          <Form.Item
            name="title"
            label="文档标题"
            rules={[{ required: true, message: '请输入文档标题' }]}
          >
            <Input placeholder="例如:售后处理手册" maxLength={200} />
          </Form.Item>
          <Form.Item name="source" label="来源(可选)">
            <Input placeholder="例如:after_sales_manual.md" maxLength={300} />
          </Form.Item>
          <Form.Item
            name="content"
            label="Markdown 内容"
            rules={[{ required: true, message: '请输入 Markdown 内容' }]}
          >
            <Input.TextArea
              rows={12}
              placeholder={'# 售后处理手册\n\n## 退货与退款\n\n### 七天无理由\n...'}
            />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  )
}
