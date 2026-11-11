"""会话级订单核验:订单号 + 手机后四位通过后,才允许敏感操作。"""
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Verification(Base):
    __tablename__ = "verifications"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True, comment="核验ID")
    session_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False, comment="会话ID"
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, comment="用户ID"
    )
    order_no: Mapped[str] = mapped_column(String(32), nullable=False, comment="订单号")
    phone_last4: Mapped[str] = mapped_column(String(4), nullable=False, comment="手机号后四位")
    verified_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), comment="核验时间"
    )

    __table_args__ = (
        UniqueConstraint("session_id", "order_no", name="uq_verification_session_order"),
        Index("idx_verification_session", "session_id"),
        {"comment": "订单核验记录表"},
    )
