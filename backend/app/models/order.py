"""订单模型。"""
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    JSON,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Order(Base):
    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True, comment="订单ID")
    order_no: Mapped[str] = mapped_column(String(32), unique=True, nullable=False, comment="订单号")
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, comment="用户ID"
    )
    status: Mapped[str] = mapped_column(
        Enum(
            "pending", "paid", "shipped", "delivered", "completed", "cancelled", "refunded",
            name="order_status",
        ),
        nullable=False,
        server_default="pending",
        comment="订单状态",
    )
    total_amount: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False, comment="订单总金额")
    pay_amount: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True, comment="实付金额")
    shipping_address: Mapped[dict | None] = mapped_column(JSON, nullable=True, comment="收货地址")
    receiver_name: Mapped[str | None] = mapped_column(String(50), nullable=True, comment="收货人")
    receiver_phone: Mapped[str | None] = mapped_column(String(20), nullable=True, comment="联系电话")
    tracking_no: Mapped[str | None] = mapped_column(String(50), nullable=True, comment="物流单号")
    remark: Mapped[str | None] = mapped_column(Text, nullable=True, comment="订单备注")
    paid_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, comment="支付时间")
    shipped_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, comment="发货时间")
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, comment="收货时间")
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), comment="创建时间"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now(), comment="更新时间"
    )

    __table_args__ = (
        Index("idx_order_no", "order_no"),
        Index("idx_user_id", "user_id"),
        Index("idx_status", "status"),
        {"comment": "订单表"},
    )
