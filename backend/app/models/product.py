"""商品模型。"""
from datetime import datetime
from decimal import Decimal

from sqlalchemy import BigInteger, Boolean, DateTime, Index, Integer, JSON, Numeric, String, Text, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Product(Base):
    __tablename__ = "products"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True, comment="商品ID")
    sku: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, comment="商品SKU")
    name: Mapped[str] = mapped_column(String(200), nullable=False, comment="商品名称")
    category: Mapped[str] = mapped_column(String(50), nullable=False, comment="商品分类")
    brand: Mapped[str | None] = mapped_column(String(50), nullable=True, comment="品牌")
    price: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False, comment="售价")
    original_price: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True, comment="原价")
    stock: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0", comment="库存")
    sales_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0", comment="销量")
    description: Mapped[str | None] = mapped_column(Text, nullable=True, comment="商品描述")
    specifications: Mapped[dict | None] = mapped_column(JSON, nullable=True, comment="规格参数")
    images: Mapped[list | None] = mapped_column(JSON, nullable=True, comment="图片列表")
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("1"), comment="是否上架"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), comment="创建时间"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now(), comment="更新时间"
    )

    __table_args__ = (
        Index("idx_sku", "sku"),
        Index("idx_category", "category"),
        Index("idx_name", "name"),
        {"comment": "商品表"},
    )
