"""商品查询工具:按关键词检索数据库商品。"""
from __future__ import annotations

import re
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.product import Product
from app.utils.logger import logger

CATEGORY_WORDS = [
    "手机", "电脑", "平板", "耳机", "音箱", "相机",
    "衣服", "鞋子", "包包", "化妆品", "护肤品",
    "家电", "家具", "玩具", "图书", "食品",
    "iPhone", "Nike", "Adidas", "Apple", "戴森",
    "小米", "华为", "三星", "索尼", "飞利浦",
]


class QueryProductTool:
    """搜索商品、查询库存和价格。"""

    def __init__(self) -> None:
        self.name = "query_product"
        self.description = "搜索商品信息,查询商品库存、价格、详情和促销活动"
        self.requires_auth = False

    async def execute(self, params: dict[str, Any]) -> dict[str, Any]:
        db: AsyncSession | None = params.get("db")
        message: str = params.get("user_message", "")
        keywords = params.get("keywords") or self._extract_keywords(message)

        if db is None:
            return {"success": False, "response": "商品查询服务暂时不可用"}

        if not keywords:
            return {
                "success": True,
                "response": '请告诉我您想查询什么商品?比如"iPhone手机"或"运动鞋"',
                "products": [],
            }

        try:
            products = await self._search_products(db, keywords)
        except Exception as exc:  # noqa: BLE001
            logger.error("商品查询失败: {}", exc)
            return {"success": False, "response": "商品查询服务暂时不可用"}

        return {
            "success": True,
            "response": self._format_product_list(products, keywords),
            "products": [self._product_to_dict(item) for item in products],
        }

    @staticmethod
    def _extract_keywords(text: str) -> list[str]:
        found = [word for word in CATEGORY_WORDS if word.lower() in text.lower()]
        if found:
            return found[:3]
        # 没有品类词时,提取中文词组或英文单词
        return re.findall(r"[一-龥]{2,}|[A-Za-z]{3,}", text)[:2]

    @staticmethod
    async def _search_products(db: AsyncSession, keywords: list[str]) -> list[Product]:
        conditions = []
        for keyword in keywords:
            pattern = f"%{keyword}%"
            conditions.extend(
                [
                    Product.name.like(pattern),
                    Product.brand.like(pattern),
                    Product.category.like(pattern),
                ]
            )
        statement = (
            select(Product)
            .where(Product.is_active.is_(True), or_(*conditions))
            .order_by(Product.sales_count.desc())
            .limit(5)
        )
        result = await db.execute(statement)
        return list(result.scalars().all())

    @staticmethod
    def _format_product_list(products: list[Product], keywords: list[str]) -> str:
        if not products:
            return f'抱歉,暂未找到与"{" ".join(keywords)}"相关的商品'

        lines = [f"🔍 为您找到 {len(products)} 件相关商品:\n\n"]
        for index, product in enumerate(products, 1):
            price = float(product.price)
            original = float(product.original_price) if product.original_price else price
            if original > price:
                discount = int((1 - price / original) * 100)
                price_text = f"¥{price:.2f} ~~¥{original:.2f}~~ ({discount}% OFF)"
            else:
                price_text = f"¥{price:.2f}"

            if product.stock > 10:
                stock_text = "✅有货"
            elif product.stock > 0:
                stock_text = "⚠️库存紧张"
            else:
                stock_text = "❌缺货"

            lines.append(
                f"{index}. **{product.name}**\n"
                f"   💰 {price_text} | 🛒 已售{product.sales_count}\n"
                f"   {stock_text} | {product.brand or ''} | {product.category}\n\n"
            )
        lines.append('回复"商品 [编号]"可查看详情')
        return "".join(lines)

    @staticmethod
    def _product_to_dict(product: Product) -> dict[str, Any]:
        return {
            "id": product.id,
            "sku": product.sku,
            "name": product.name,
            "category": product.category,
            "brand": product.brand,
            "price": float(product.price),
            "original_price": float(product.original_price) if product.original_price else None,
            "stock": product.stock,
            "sales_count": product.sales_count,
            "description": product.description,
        }

    def get_schema(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": {
                    "keywords": {"type": "string", "description": "商品关键词"},
                    "category": {"type": "string", "description": "商品分类"},
                },
                "required": ["keywords"],
            },
        }
