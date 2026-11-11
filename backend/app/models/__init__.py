"""ORM 模型汇总,导入后 Base.metadata 才包含全部表。"""
from app.models.agent_run import AgentRun
from app.models.agent_step import AgentStep
from app.models.approval import Approval
from app.models.audit_log import AuditLog
from app.models.auth_extra import LoginCode, QrLoginSession
from app.models.intent import Intent
from app.models.knowledge import Knowledge
from app.models.knowledge_document import KnowledgeChunk, KnowledgeDocument
from app.models.low_confidence import LowConfidenceQuestion
from app.models.message import Message
from app.models.order import Order
from app.models.policy_decision import PolicyDecision
from app.models.policy_rule import PolicyRule
from app.models.product import Product
from app.models.qa_staging import QaExtractionStaging
from app.models.service_task import ServiceTask
from app.models.session import Session
from app.models.ticket import Ticket
from app.models.user import User
from app.models.verification import Verification

__all__ = [
    "User",
    "Session",
    "Message",
    "Intent",
    "Knowledge",
    "Order",
    "Product",
    "Ticket",
    "ServiceTask",
    "AgentRun",
    "AgentStep",
    "Approval",
    "PolicyRule",
    "PolicyDecision",
    "Verification",
    "AuditLog",
    "LowConfidenceQuestion",
    "QaExtractionStaging",
    "KnowledgeDocument",
    "KnowledgeChunk",
    "LoginCode",
    "QrLoginSession",
]
