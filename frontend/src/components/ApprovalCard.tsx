import { useState } from 'react'
import { Button, Input } from 'antd'
import { useChatStore } from '../stores/chatStore'
import type { Message } from '../types/chat'

const ACTION_LABELS: Record<string, string> = {
  cancel: '取消订单',
  refund: '退款',
  return: '退货',
}

const RISK_LABELS: Record<string, string> = {
  low: '低风险',
  medium: '中风险',
  high: '高风险',
}

const STATUS_LABELS: Record<string, string> = {
  executed: '已执行',
  rejected: '已拒绝',
  approved: '已批准',
}

interface Props {
  message: Message
}

/** 售后确认卡片:用户确认/拒绝,高风险需客服工号,敏感操作需手机后四位核验。 */
export default function ApprovalCard({ message }: Props) {
  const approval = message.pendingApproval
  const { verifyApprovalOrder, decideApproval } = useChatStore()

  const [phone, setPhone] = useState('')
  const [reviewer, setReviewer] = useState('')
  const [rejectReason, setRejectReason] = useState('')
  const [showReject, setShowReject] = useState(false)
  const [verified, setVerified] = useState(!approval?.requires_verification)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  if (!approval) return null

  const pending = approval.status === 'pending'
  const needsHuman = approval.requires_human
  const actionLabel = ACTION_LABELS[approval.action] || approval.action
  const riskLabel = RISK_LABELS[approval.risk_level] || approval.risk_level
  const statusLabel = pending
    ? needsHuman
      ? '待人工审核'
      : '待确认'
    : STATUS_LABELS[approval.status] || approval.status

  const handleVerify = async () => {
    if (!approval.order_no) return
    if (!/^\d{4}$/.test(phone.trim())) {
      setError('请输入手机号后四位')
      return
    }
    setBusy(true)
    setError('')
    const result = await verifyApprovalOrder(approval.order_no, phone.trim())
    setBusy(false)
    if (result.success) {
      setVerified(true)
    } else {
      setError(result.reason || '核验失败')
    }
  }

  const handleApprove = async () => {
    if (!verified) {
      setError('请先核验订单')
      return
    }
    if (needsHuman && !reviewer.trim()) {
      setError('高风险操作需填写客服工号')
      return
    }
    setBusy(true)
    setError('')
    const result = await decideApproval(
      message.id,
      approval.approval_id,
      'approve',
      needsHuman ? { reviewer: reviewer.trim() } : undefined,
    )
    setBusy(false)
    if (!result.success) {
      if (result.code === 'require_verification') setVerified(false)
      setError(result.message)
    }
  }

  const handleReject = async () => {
    setBusy(true)
    setError('')
    const result = await decideApproval(
      message.id,
      approval.approval_id,
      'reject',
      { reason: rejectReason.trim() || undefined },
    )
    setBusy(false)
    if (!result.success) setError(result.message)
  }

  return (
    <section className={`approval-card ${pending ? 'is-pending' : 'is-closed'}`} aria-label="售后确认卡片">
      <div className="approval-head">
        <div>
          <div className="approval-kicker">AFTER-SALES REQUEST / 售后申请</div>
          <div className="approval-title">
            {actionLabel}
            {approval.order_no ? ` · ${approval.order_no}` : ''}
          </div>
        </div>
        <span className={`approval-status ${approval.status}`}>{statusLabel}</span>
      </div>

      <p className="approval-summary">{approval.summary}</p>

      <div className="approval-meta">
        <span className={`approval-risk ${approval.risk_level}`}>{riskLabel}</span>
        {needsHuman && <span className="approval-flag">需人工审核</span>}
        {approval.requires_verification && !verified && (
          <span className="approval-flag">需订单核验</span>
        )}
      </div>

      {pending && (
        <>
          {!verified && (
            <div className="approval-field">
              <span className="approval-label">手机号后四位</span>
              <Input
                maxLength={4}
                value={phone}
                onChange={(event) => setPhone(event.target.value.replace(/\D/g, ''))}
                placeholder="例如 1234"
                aria-label="手机号后四位"
              />
              <Button size="small" onClick={() => void handleVerify()} disabled={busy}>
                核验订单
              </Button>
            </div>
          )}

          {needsHuman && (
            <div className="approval-field">
              <span className="approval-label">客服工号</span>
              <Input
                value={reviewer}
                onChange={(event) => setReviewer(event.target.value)}
                placeholder="例如 A001"
                aria-label="客服工号"
              />
            </div>
          )}

          {showReject && (
            <div className="approval-field">
              <span className="approval-label">拒绝原因</span>
              <Input
                value={rejectReason}
                onChange={(event) => setRejectReason(event.target.value)}
                placeholder="可选"
                aria-label="拒绝原因"
              />
            </div>
          )}

          {error && <div className="approval-error">{error}</div>}

          <div className="approval-actions">
            <Button
              type="primary"
              size="small"
              loading={busy}
              onClick={() => void handleApprove()}
              disabled={!verified || (needsHuman && !reviewer.trim())}
            >
              {needsHuman ? '审核通过' : '确认执行'}
            </Button>
            {!showReject ? (
              <Button size="small" onClick={() => setShowReject(true)} disabled={busy}>
                拒绝
              </Button>
            ) : (
              <Button size="small" danger loading={busy} onClick={() => void handleReject()}>
                确认拒绝
              </Button>
            )}
          </div>
        </>
      )}

      {!pending && (
        <div className="approval-result">
          {approval.status === 'executed'
            ? '该售后申请已执行,结果已写入订单、工单与审计记录。'
            : '该售后申请已拒绝,订单保持不变。'}
        </div>
      )}
    </section>
  )
}
