"""种子数据:演示用户、意图字典、商品、订单、知识库与向量索引。

设计原则:
- 幂等:已存在的数据不重复插入;
- 向量化只处理 vector_id 为空的知识,避免每次启动重复计算;
- 向量化失败不阻塞启动(可稍后重建)。
"""
from __future__ import annotations

import json
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.intent import Intent
from app.models.knowledge import Knowledge
from app.models.order import Order
from app.models.product import Product
from app.models.user import User
from app.services.intent_service import IntentService
from app.services.rag_service import RAGService
from app.utils.logger import logger

KNOWLEDGE_FILE = Path(__file__).resolve().parents[3] / "knowledge_base" / "faqs.json"


def _hash_password(password: str) -> str:
    try:
        import bcrypt

        return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
    except Exception as exc:  # noqa: BLE001 - 演示密码,失败不阻塞
        logger.warning("密码哈希失败,使用占位值: {}", exc)
        return "!"


async def seed_all(db: AsyncSession) -> None:
    """执行全部种子数据写入。"""
    user = await _seed_demo_user(db)
    await _seed_intents(db)
    await _seed_products(db)
    await _seed_orders(db, user.id)
    await db.commit()

    knowledge_items = await _seed_knowledge(db)
    await db.commit()

    await _seed_vectors(db, knowledge_items)


async def _seed_demo_user(db: AsyncSession) -> User:
    result = await db.execute(select(User).where(User.username == "demo_customer"))
    user = result.scalar_one_or_none()
    if user is not None:
        return user

    user = User(
        username="demo_customer",
        email="demo@example.com",
        phone="13800000000",
        password_hash=_hash_password("demo123"),
        user_type="customer",
        is_active=True,
    )
    db.add(user)
    await db.flush()
    logger.info("已创建演示用户 demo_customer (id={})", user.id)
    return user


async def _seed_intents(db: AsyncSession) -> None:
    existing = {
        code
        for code in (
            await db.execute(select(Intent.intent_code))
        ).scalars().all()
    }

    created = 0
    for code, config in IntentService.INTENT_CONFIGS.items():
        if code in existing:
            continue
        db.add(
            Intent(
                intent_name=config["name"],
                intent_code=code,
                description=f"{config['name']}意图",
                handler_type=config["handler"],
                sample_utterances=" ".join(config["keywords"]),
                priority=config["priority"],
                is_active=True,
            )
        )
        created += 1

    if created:
        logger.info("已写入 {} 个意图定义", created)


async def _seed_products(db: AsyncSession) -> None:
    total = await db.scalar(select(func.count()).select_from(Product))
    if total:
        return

    products = [
        Product(
            sku="SKU-IPHONE15PM-256",
            name="Apple iPhone 15 Pro Max 256GB 钛金属色",
            category="手机",
            brand="Apple",
            price=Decimal("9999.00"),
            original_price=Decimal("10999.00"),
            stock=50,
            sales_count=12580,
            description="A17 Pro 芯片,钛金属设计,4800万像素主摄。",
            specifications={"屏幕": "6.7英寸", "存储": "256GB", "颜色": "钛金属色"},
            images=["https://img.example.com/iphone15pm.jpg"],
        ),
        Product(
            sku="SKU-DYSON-HD15",
            name="戴森(Dyson)HD15 新一代吹风机",
            category="家电",
            brand="戴森",
            price=Decimal("2999.00"),
            original_price=Decimal("3299.00"),
            stock=120,
            sales_count=8950,
            description="高速数码马达,智能温控,呵护发质。",
            specifications={"功率": "1600W", "档位": "3档"},
            images=["https://img.example.com/dyson-hd15.jpg"],
        ),
        Product(
            sku="SKU-NIKE-AJ1-001",
            name="Nike Air Jordan 1 Retro High OG 男款篮球鞋",
            category="运动鞋",
            brand="Nike",
            price=Decimal("1499.00"),
            original_price=Decimal("1499.00"),
            stock=35,
            sales_count=5680,
            description="经典 AJ1 高帮复刻,百搭配色。",
            specifications={"鞋帮": "高帮", "材质": "皮革"},
            images=["https://img.example.com/nike-aj1.jpg"],
        ),
        Product(
            sku="SKU-MACBOOK-M3-014",
            name="Apple MacBook Pro 14英寸 M3 Pro芯片 18+512GB",
            category="电脑",
            brand="Apple",
            price=Decimal("16999.00"),
            original_price=Decimal("18999.00"),
            stock=25,
            sales_count=3200,
            description="M3 Pro 芯片,14 英寸 Liquid 视网膜 XDR 显示屏。",
            specifications={"芯片": "M3 Pro", "内存": "18GB", "存储": "512GB"},
            images=["https://img.example.com/macbook-pro14.jpg"],
        ),
        Product(
            sku="SKU-HW-P60PRO-256",
            name="华为 P60 Pro 超聚光XMAGE影像 玄武镀膜",
            category="手机",
            brand="华为",
            price=Decimal("5988.00"),
            original_price=Decimal("6988.00"),
            stock=80,
            sales_count=9800,
            description="XMAGE 影像,双向北斗卫星消息。",
            specifications={"屏幕": "6.67英寸", "存储": "256GB"},
            images=["https://img.example.com/huawei-p60pro.jpg"],
        ),
    ]
    db.add_all(products)
    await db.flush()
    logger.info("已写入 {} 个演示商品", len(products))


async def _seed_orders(db: AsyncSession, user_id: int) -> None:
    total = await db.scalar(
        select(func.count()).select_from(Order).where(Order.user_id == user_id)
    )
    if total:
        return

    orders = [
        Order(
            order_no="ORDER20260315001",
            user_id=user_id,
            status="shipped",
            total_amount=Decimal("9999.00"),
            pay_amount=Decimal("9599.00"),
            shipping_address={"province": "北京市", "city": "北京市", "detail": "朝阳区建国路88号"},
            receiver_name="张先生",
            receiver_phone="13800006789",
            tracking_no="SF1234567890",
            remark="Apple iPhone 15 Pro Max 256GB × 1",
            created_at=datetime(2026, 3, 15, 10, 30),
            paid_at=datetime(2026, 3, 15, 10, 35),
            shipped_at=datetime(2026, 3, 16, 14, 20),
        ),
        Order(
            order_no="ORDER20260401001",
            user_id=user_id,
            status="paid",
            total_amount=Decimal("2999.00"),
            pay_amount=Decimal("2699.00"),
            shipping_address={"province": "上海市", "city": "上海市", "detail": "浦东新区世纪大道1000号"},
            receiver_name="李女士",
            receiver_phone="13900001234",
            remark="戴森吹风机 HD15 × 1",
            created_at=datetime(2026, 4, 1, 16, 0),
            paid_at=datetime(2026, 4, 1, 16, 10),
        ),
        Order(
            order_no="ORDER20260310005",
            user_id=user_id,
            status="delivered",
            total_amount=Decimal("1499.00"),
            pay_amount=Decimal("1499.00"),
            shipping_address={"province": "广东省", "city": "深圳市", "detail": "南山区科技园"},
            receiver_name="王先生",
            receiver_phone="13700005678",
            tracking_no="YT9876543210",
            remark="Nike Air Jordan 1 球鞋 × 1",
            created_at=datetime(2026, 3, 10, 9, 0),
            paid_at=datetime(2026, 3, 10, 9, 5),
            shipped_at=datetime(2026, 3, 11, 10, 0),
            delivered_at=datetime(2026, 3, 13, 15, 30),
        ),
    ]
    db.add_all(orders)
    await db.flush()
    logger.info("已写入 {} 个演示订单", len(orders))


async def _seed_knowledge(db: AsyncSession) -> list[Knowledge]:
    total = await db.scalar(select(func.count()).select_from(Knowledge))
    if total:
        return list(
            (
                await db.execute(select(Knowledge).where(Knowledge.vector_id.is_(None)))
            )
            .scalars()
            .all()
        )

    try:
        with KNOWLEDGE_FILE.open("r", encoding="utf-8") as file:
            entries = json.load(file)
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        logger.error("知识库文件读取失败: {}", exc)
        return []

    items = [
        Knowledge(
            category=entry.get("category", "其他"),
            question=entry.get("question", ""),
            answer=entry.get("answer", ""),
            keywords=entry.get("keywords", ""),
            embedding_model="bge-small-zh-v1.5",
        )
        for entry in entries
    ]
    db.add_all(items)
    await db.flush()
    logger.info("已写入 {} 条知识库", len(items))
    return items


async def _seed_vectors(db: AsyncSession, items: list[Knowledge]) -> None:
    if not items:
        return

    documents = [
        {
            "id": item.id,
            "category": item.category,
            "question": item.question,
            "answer": item.answer,
        }
        for item in items
        if item.vector_id is None
    ]
    if not documents:
        return

    try:
        await RAGService().add_documents(documents)
        for item in items:
            if item.vector_id is None:
                item.vector_id = str(item.id)
                item.embedding_model = "bge-small-zh-v1.5"
        await db.commit()
        logger.info("知识向量初始化完成,共 {} 条", len(documents))
    except Exception as exc:  # noqa: BLE001 - 向量库不可用时允许降级运行
        logger.warning("知识向量初始化失败,将使用关键词降级检索: {}", exc)
