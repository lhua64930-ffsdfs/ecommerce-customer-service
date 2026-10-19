"""商品服务接口。"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.models.product import Product

router = APIRouter()


def _to_dict(product: Product) -> dict:
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
        "specifications": product.specifications,
        "images": product.images,
        "is_active": product.is_active,
    }


@router.get("/list", summary="商品列表")
async def list_products(
    keyword: str | None = None,
    category: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
) -> dict:
    statement = select(Product).where(Product.is_active.is_(True))
    count_statement = select(func.count()).select_from(Product).where(Product.is_active.is_(True))

    if keyword:
        pattern = f"%{keyword}%"
        condition = or_(
            Product.name.like(pattern),
            Product.brand.like(pattern),
            Product.category.like(pattern),
        )
        statement = statement.where(condition)
        count_statement = count_statement.where(condition)
    if category:
        statement = statement.where(Product.category == category)
        count_statement = count_statement.where(Product.category == category)

    total = await db.scalar(count_statement)
    rows = (
        (
            await db.execute(
                statement.order_by(Product.sales_count.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        )
        .scalars()
        .all()
    )
    return {
        "items": [_to_dict(product) for product in rows],
        "total": int(total or 0),
        "page": page,
        "page_size": page_size,
    }


@router.get("/{sku}", summary="商品详情")
async def get_product(sku: str, db: AsyncSession = Depends(get_db)) -> dict:
    result = await db.execute(select(Product).where(Product.sku == sku))
    product = result.scalar_one_or_none()
    if product is None:
        raise HTTPException(status_code=404, detail="商品不存在")
    return _to_dict(product)
