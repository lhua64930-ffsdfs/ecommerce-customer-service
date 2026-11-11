"""售后审批服务:模型只提申请,确认/审批通过后由系统执行写操作。

设计要点:
- 申请与执行分离:``propose`` 只生成审批单,``approve`` 才真正写库;
- 执行前再次走策略引擎与订单状态重验,避免申请后状态变化;
- 审批单状态机保证幂等,重复 approve 返回 already_executed;
- 高风险操作要求人工审核(客服工号),敏感操作要求订单号 + 手机后四位核验。
"""
from __future__ import annotations

import time
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.approval import Approval
from app.models.audit_log import AuditLog
from app.models.order import Order
from app.models.service_task import ServiceTask
from app.models.session import Session
from app.models.ticket import Ticket
from app.models.verification import Verification
from app.policies.engine import PolicyEngine, PolicyResult
from app.runtime.tasks import ServiceTaskService
from app.utils.logger import logger
from app.utils.pii import mask_address, mask_name, mask_phone

VALID_ACTIONS = ("cancel", "refund", "return")


def _now() -> datetime:
    return datetime.now()


def _approval_no() -> str:
    return f"APV{int(time.time())}{uuid.uuid4().hex[:4].upper()}"


def _ticket_no() -> str:
    return f"TKT{int(time.time())}{uuid.uuid4().hex[:4].upper()}"


class ApprovalError(Exception):
    """审批流程中的可预期错误。"""

    def __init__(self, code: str, message: str, status_code: int = 422) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


class ApprovalService:
    """售后申请、核验、审批与执行。"""

    def __init__(self, db: AsyncSession, policy: PolicyEngine | None = None) -> None:
        self.db = db
        self.policy = policy or PolicyEngine()
        self.tasks = ServiceTaskService(db)

    # ---------------- 申请 ----------------
    async def propose(
        self,
        session_uuid: str,
        user_id: int,
        action: str,
        order_no: str | None,
        reason: str | None = None,
        intent_code: str | None = None,
    ) -> dict[str, Any]:
        if action not in VALID_ACTIONS:
            raise ApprovalError("invalid_action", "不支持的售后动作")
        if not order_no:
            raise ApprovalError("order_no_required", "请提供需要办理的订单号")

        session = await self._resolve_session(session_uuid)
        order = await self._get_order(order_no, session.user_id)
        if order is None:
            raise ApprovalError("order_not_found", "未找到该订单,或该订单不属于当前账号", 404)

        summary = self._summary(action, order)

        # 同一会话、订单、动作已有待处理申请时直接复用,避免重复建单
        existing = (
            await self.db.execute(
                select(Approval)
                .where(
                    Approval.session_id == session.id,
                    Approval.order_no == order.order_no,
                    Approval.action == action,
                    Approval.status == "pending",
                )
                .order_by(Approval.id.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if existing is not None:
            return {
                "decision": "needs_human" if existing.requires_human else "needs_confirm",
                "response": f"您有一笔待处理的售后申请:{summary}。请按提示完成确认或核验。",
                "pending": self._pending_payload(existing),
                "task_id": existing.task_id,
                "approval_no": existing.approval_no,
                "executed": False,
            }

        context = self._context(session, order, action)
        policy = await self.policy.evaluate(self.db, action, context)
        if policy.decision == "deny":
            task = await self.tasks.create(
                session_id=session.id,
                user_id=session.user_id,
                task_type=action,
                target_order_no=order.order_no,
                intent_code=intent_code,
                summary=summary,
                status="rejected",
            )
            self._audit(
                session,
                "approval.denied",
                "order",
                order.order_no,
                {"action": action, "reason": policy.reason, "rule_id": policy.rule_id},
            )
            await self.db.commit()
            return {
                "decision": policy.decision,
                "response": f"暂无法为您办理:{policy.reason}",
                "pending": None,
                "task_id": task.id,
                "approval_no": None,
                "executed": False,
            }

        verified = await self._is_verified(session.id, order.order_no)
        requires_human = policy.decision == "needs_human"
        task = await self.tasks.get_or_create(
            session_id=session.id,
            user_id=session.user_id,
            task_type=action,
            target_order_no=order.order_no,
            intent_code=intent_code,
            summary=summary,
        )
        await self.tasks.set_status(task, "pending_approval")

        approval = Approval(
            approval_no=_approval_no(),
            task_id=task.id,
            session_id=session.id,
            user_id=session.user_id,
            action=action,
            order_no=order.order_no,
            payload={
                "summary": summary,
                "reason": reason,
                "order_status": order.status,
                "pay_amount": self._amount(order),
            },
            policy_decision_id=policy.policy_decision_id,
            risk_level=policy.risk_level,
            status="pending",
            requires_verification=not verified,
            requires_human=requires_human,
        )
        self.db.add(approval)
        await self.db.flush()
        self._audit(
            session,
            "approval.created",
            "approval",
            approval.approval_no,
            {
                "action": action,
                "decision": policy.decision,
                "rule_id": policy.rule_id,
                "risk_level": policy.risk_level,
            },
        )

        # 低风险 + 已核验:系统按策略自动执行,仍然保留审批记录
        if policy.decision == "allow_auto" and verified:
            result = await self._execute(approval, order, session)
            success = bool(result.get("success"))
            approval.status = "executed" if success else "rejected"
            approval.decided_by = "system:policy"
            approval.decided_at = _now()
            approval.executed_at = _now() if success else None
            approval.result_json = result
            await self.tasks.set_status(task, "completed" if success else "rejected")
            self._audit(
                session,
                "approval.auto_executed" if success else "approval.auto_failed",
                "approval",
                approval.approval_no,
                {"action": action, "result": result},
            )
            await self.db.commit()
            return {
                "decision": policy.decision,
                "response": f"已按售后策略自动处理:{summary}。{result.get('message', '')}",
                "pending": None,
                "task_id": task.id,
                "approval_no": approval.approval_no,
                "executed": success,
                "result": result,
            }

        await self.db.commit()
        if policy.decision == "needs_human":
            response = f"已提交人工审核:{summary}。客服会尽快处理。"
        elif policy.decision == "allow_auto":
            response = (
                f"该订单符合自动处理条件,请先核验订单(手机号后四位),"
                f"核验通过后将自动处理:{summary}。"
            )
        else:
            response = f"已为您生成售后申请:{summary}。请确认后由系统执行。"
        return {
            "decision": policy.decision,
            "response": response,
            "pending": self._pending_payload(approval),
            "task_id": task.id,
            "approval_no": approval.approval_no,
            "executed": False,
        }

    # ---------------- 审批 ----------------
    async def approve(
        self,
        approval_no: str,
        session_uuid: str,
        reviewer: str | None = None,
    ) -> dict[str, Any]:
        session = await self._resolve_session(session_uuid)
        approval = await self._get_approval(approval_no, session.id)

        if approval.status == "executed":
            return {
                "success": True,
                "status": "executed",
                "already_executed": True,
                "result": approval.result_json,
            }
        if approval.status != "pending":
            raise ApprovalError(
                "invalid_status", f"审批单当前状态为 {approval.status},不能继续处理"
            )
        if approval.requires_human and not reviewer:
            raise ApprovalError(
                "require_human_review", "高风险售后操作需要人工审核(请提供客服工号)"
            )
        if not await self._is_verified(session.id, approval.order_no or ""):
            raise ApprovalError(
                "require_verification", "请先核验订单号与手机号后四位"
            )

        order = await self._get_order(approval.order_no or "", session.user_id)
        if order is None:
            raise ApprovalError("order_not_found", "订单不存在或不属于当前账号", 404)

        context = self._context(session, order, approval.action)
        policy = await self.policy.evaluate(self.db, approval.action, context)
        approval.policy_decision_id = policy.policy_decision_id

        # 申请后状态/金额可能变化:重新决策,不允许盲执行
        if policy.decision == "deny":
            return await self._reject_after_policy(
                approval, session, policy, reviewer
            )
        if policy.decision == "needs_human" and not reviewer:
            raise ApprovalError(
                "require_human_review", "当前状态需要人工审核(请提供客服工号)"
            )

        result = await self._execute(approval, order, session)
        success = bool(result.get("success"))
        approval.status = "executed" if success else "rejected"
        approval.decided_by = reviewer or "user"
        approval.decided_at = _now()
        approval.executed_at = _now() if success else None
        approval.result_json = result

        task = await self._task(approval)
        if task is not None:
            await self.tasks.set_status(task, "completed" if success else "rejected")
        self._audit(
            session,
            "approval.executed" if success else "approval.failed",
            "approval",
            approval.approval_no,
            {
                "action": approval.action,
                "reviewer": reviewer,
                "decision": policy.decision,
                "result": result,
            },
        )
        await self.db.commit()
        return {
            "success": success,
            "status": approval.status,
            "task_id": approval.task_id,
            "result": result,
        }

    async def reject(
        self,
        approval_no: str,
        session_uuid: str,
        reason: str | None = None,
        reviewer: str | None = None,
    ) -> dict[str, Any]:
        session = await self._resolve_session(session_uuid)
        approval = await self._get_approval(approval_no, session.id)
        if approval.status == "executed":
            raise ApprovalError("already_executed", "审批单已执行,不能拒绝")
        if approval.status != "pending":
            raise ApprovalError(
                "invalid_status", f"审批单当前状态为 {approval.status},不能继续处理"
            )

        approval.status = "rejected"
        approval.decided_by = reviewer or "user"
        approval.decided_at = _now()
        approval.result_json = {
            "success": False,
            "message": reason or "用户拒绝了本次售后申请",
        }
        task = await self._task(approval)
        if task is not None:
            await self.tasks.set_status(task, "rejected")
        self._audit(
            session,
            "approval.rejected",
            "approval",
            approval.approval_no,
            {"reason": reason or "", "reviewer": reviewer},
        )
        await self.db.commit()
        return {
            "success": True,
            "status": "rejected",
            "task_id": approval.task_id,
            "result": approval.result_json,
        }

    # ---------------- 订单核验 ----------------
    async def verify(
        self, session_uuid: str, order_no: str, phone_last4: str
    ) -> dict[str, Any]:
        session = await self._resolve_session(session_uuid)
        order = await self._get_order(order_no, session.user_id)
        if order is None:
            return {"success": False, "reason": "订单号或手机号后四位不正确"}

        expected = str(order.receiver_phone or "").strip()[-4:]
        if not expected or expected != str(phone_last4 or "").strip():
            self._audit(
                session,
                "verification.failed",
                "order",
                order.order_no,
                {"reason": "phone_mismatch"},
            )
            await self.db.commit()
            return {"success": False, "reason": "订单号或手机号后四位不正确"}

        record = (
            await self.db.execute(
                select(Verification).where(
                    Verification.session_id == session.id,
                    Verification.order_no == order.order_no,
                )
            )
        ).scalar_one_or_none()
        if record is None:
            self.db.add(
                Verification(
                    session_id=session.id,
                    user_id=session.user_id,
                    order_no=order.order_no,
                    phone_last4=expected,
                )
            )
        else:
            record.phone_last4 = expected
            record.verified_at = _now()

        # 已核验的会话不必在每张待审批卡片上重复要求核验
        pending_approvals = (
            (
                await self.db.execute(
                    select(Approval).where(
                        Approval.session_id == session.id,
                        Approval.order_no == order.order_no,
                        Approval.status == "pending",
                    )
                )
            )
            .scalars()
            .all()
        )
        for item in pending_approvals:
            item.requires_verification = False

        self._audit(
            session, "verification.succeeded", "order", order.order_no, {}
        )
        await self.db.commit()
        return {"success": True, "order": self._order_view(order)}

    async def list_approvals(self, session_uuid: str) -> list[dict[str, Any]]:
        session = await self._resolve_session(session_uuid)
        rows = (
            (
                await self.db.execute(
                    select(Approval)
                    .where(Approval.session_id == session.id)
                    .order_by(Approval.id.desc())
                    .limit(50)
                )
            )
            .scalars()
            .all()
        )
        return [self._approval_dict(item) for item in rows]

    # ---------------- 执行 ----------------
    async def _execute(
        self, approval: Approval, order: Order, session: Session
    ) -> dict[str, Any]:
        if approval.action == "cancel":
            if order.status == "cancelled":
                return {
                    "success": True,
                    "already": True,
                    "message": "订单已经是取消状态,无需重复取消",
                }
            if order.status not in ("pending", "paid"):
                return {
                    "success": False,
                    "message": f"订单当前状态为 {order.status},已无法直接取消",
                }
            order.status = "cancelled"
            return {
                "success": True,
                "message": f"已取消订单 {order.order_no},退款将在 1-3 个工作日内原路退回",
                "order_status": "cancelled",
            }

        action_name = "退货" if approval.action == "return" else "退款"
        title = f"{action_name}申请 {order.order_no}"
        existing = (
            await self.db.execute(
                select(Ticket)
                .where(
                    Ticket.user_id == order.user_id,
                    Ticket.type == "refund",
                    Ticket.title == title,
                )
                .order_by(Ticket.id.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if existing is not None:
            return {
                "success": True,
                "already": True,
                "ticket_no": existing.ticket_no,
                "message": f"{action_name}申请已存在,工单号 {existing.ticket_no}",
            }

        ticket = Ticket(
            ticket_no=_ticket_no(),
            session_id=session.id,
            user_id=order.user_id,
            type="refund",
            title=title,
            content=(
                f"用户申请{action_name}:订单 {order.order_no},"
                f"金额 ¥{self._amount(order):.2f}。"
                f"策略风险等级: {approval.risk_level}。"
            ),
            status="pending",
            priority="high" if approval.risk_level == "high" else "normal",
        )
        self.db.add(ticket)
        await self.db.flush()
        return {
            "success": True,
            "ticket_no": ticket.ticket_no,
            "message": f"已提交{action_name}申请,工单号 {ticket.ticket_no},客服将跟进处理",
        }

    async def _reject_after_policy(
        self,
        approval: Approval,
        session: Session,
        policy: PolicyResult,
        reviewer: str | None,
    ) -> dict[str, Any]:
        approval.status = "rejected"
        approval.decided_by = reviewer or "system:policy"
        approval.decided_at = _now()
        approval.result_json = {
            "success": False,
            "message": f"当前状态无法执行:{policy.reason}",
        }
        task = await self._task(approval)
        if task is not None:
            await self.tasks.set_status(task, "rejected")
        self._audit(
            session,
            "approval.policy_rejected",
            "approval",
            approval.approval_no,
            {"decision": policy.decision, "rule_id": policy.rule_id},
        )
        await self.db.commit()
        return {
            "success": False,
            "status": "rejected",
            "task_id": approval.task_id,
            "result": approval.result_json,
        }

    # ---------------- 内部工具 ----------------
    async def _resolve_session(self, session_uuid: str) -> Session:
        if not session_uuid:
            raise ApprovalError("session_required", "缺少会话ID")
        result = await self.db.execute(
            select(Session).where(Session.session_id == session_uuid)
        )
        session = result.scalar_one_or_none()
        if session is None:
            raise ApprovalError("session_not_found", "会话不存在,请先创建会话", 404)
        return session

    async def _get_order(self, order_no: str, user_id: int) -> Order | None:
        result = await self.db.execute(
            select(Order).where(Order.order_no == order_no.upper())
        )
        order = result.scalar_one_or_none()
        if order is None or order.user_id != user_id:
            return None
        return order

    async def _get_approval(self, approval_no: str, session_id: int) -> Approval:
        result = await self.db.execute(
            select(Approval).where(Approval.approval_no == approval_no)
        )
        approval = result.scalar_one_or_none()
        if approval is None or approval.session_id != session_id:
            raise ApprovalError("approval_not_found", "审批单不存在", 404)
        return approval

    async def _is_verified(self, session_id: int, order_no: str) -> bool:
        if not order_no:
            return False
        result = await self.db.execute(
            select(Verification.id).where(
                Verification.session_id == session_id,
                Verification.order_no == order_no.upper(),
            )
        )
        return result.scalar_one_or_none() is not None

    async def _task(self, approval: Approval) -> ServiceTask | None:
        if approval.task_id is None:
            return None
        return await self.db.get(ServiceTask, approval.task_id)

    @staticmethod
    def _amount(order: Order) -> float:
        value = order.pay_amount if order.pay_amount is not None else order.total_amount
        return float(value or 0)

    def _context(self, session: Session, order: Order, action: str) -> dict[str, Any]:
        return {
            "action": action,
            "order": {
                "order_no": order.order_no,
                "status": order.status,
                "pay_amount": self._amount(order),
                "user_id": order.user_id,
            },
            "session": {
                "session_id": session.session_id,
                "user_id": session.user_id,
            },
        }

    def _summary(self, action: str, order: Order) -> str:
        amount = self._amount(order)
        if action == "cancel":
            return f"取消订单 {order.order_no},退款 ¥{amount:.2f} 原路退回"
        if action == "return":
            return f"退货订单 {order.order_no},金额 ¥{amount:.2f}"
        return f"退款订单 {order.order_no},金额 ¥{amount:.2f}"

    def _pending_payload(self, approval: Approval) -> dict[str, Any]:
        payload = approval.payload or {}
        return {
            "approval_id": approval.approval_no,
            "action": approval.action,
            "order_no": approval.order_no,
            "summary": payload.get("summary", ""),
            "risk_level": approval.risk_level,
            "status": approval.status,
            "requires_verification": approval.requires_verification,
            "requires_human": approval.requires_human,
        }

    def _approval_dict(self, approval: Approval) -> dict[str, Any]:
        item = self._pending_payload(approval)
        item["status"] = approval.status
        item["result"] = approval.result_json
        item["created_at"] = approval.created_at.isoformat()
        return item

    @staticmethod
    def _order_view(order: Order) -> dict[str, Any]:
        return {
            "order_no": order.order_no,
            "status": order.status,
            "pay_amount": float(order.pay_amount or order.total_amount or 0),
            "receiver_name": mask_name(order.receiver_name),
            "receiver_phone": mask_phone(order.receiver_phone),
            "shipping_address": mask_address(order.shipping_address),
        }

    def _audit(
        self,
        session: Session,
        action: str,
        target_type: str,
        target_id: str | None,
        detail: dict[str, Any],
    ) -> None:
        self.db.add(
            AuditLog(
                user_id=session.user_id,
                session_id=session.id,
                action=action,
                target_type=target_type,
                target_id=target_id,
                detail_json=detail,
            )
        )
        logger.info("审计: {} {} {}", action, target_type, target_id)
