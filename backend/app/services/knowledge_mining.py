"""知识飞轮:从低置信度问题/对话中抽取候选问答,去重后进入人工审核队列。

抽取结果只写入 staging,不直接进 knowledge 表——模型从聊天里归纳的答案
可能带具体订单/地址,必须人工确认后才能作为知识库依据。
"""
from __future__ import annotations

import json
import re
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.knowledge import Knowledge
from app.models.low_confidence import LowConfidenceQuestion
from app.models.message import Message
from app.models.qa_staging import QaExtractionStaging
from app.services.dedupe import dedupe_candidates
from app.services.llm_service import LLMError, LLMService
from app.utils.logger import logger

MINING_PROMPT = """你是电商售后知识运营助手。请从下面的对话/问题中抽取可复用的问答对。

要求:
- 只抽取通用、可复用的售后知识,不要包含具体用户姓名、手机号、地址、订单号;
- 答案必须来自对话中客服给出的信息,不要编造;
- 没有可复用内容时返回空数组;
- 只返回 JSON:{{"pairs": [{{"question": "...", "answer": "..."}}]}}

素材:
{text}
"""


def _parse(raw: str) -> list[dict[str, str]]:
    cleaned = raw.strip()
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", cleaned, flags=re.MULTILINE).strip()
    match = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if match:
        cleaned = match.group(0)
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        return []
    if not isinstance(data, dict) or not isinstance(data.get("pairs"), list):
        return []
    result = []
    for item in data["pairs"]:
        if not isinstance(item, dict):
            continue
        question = str(item.get("question") or "").strip()
        answer = str(item.get("answer") or "").strip()
        if question and answer:
            result.append({"question": question, "answer": answer})
    return result


async def extract_pairs(text: str, llm: LLMService | None = None) -> list[dict[str, str]]:
    llm = llm or LLMService()
    if llm.is_mock or not text.strip():
        return []
    try:
        raw = await llm.generate(
            MINING_PROMPT.format(text=text[:12000]),
            temperature=0.2,
            json_mode=True,
        )
    except LLMError as exc:
        logger.warning("知识抽取失败: {}", exc)
        return []
    return _parse(raw)


async def mine_knowledge(db: AsyncSession, batch_size: int = 20) -> dict:
    """从低置信度问题 + 最近对话中抽取候选问答,去重后写入 staging。"""
    llm = LLMService()
    low_conf = (
        (
            await db.execute(
                select(LowConfidenceQuestion)
                .where(LowConfidenceQuestion.status == "pending")
                .order_by(LowConfidenceQuestion.id.desc())
                .limit(50)
            )
        )
        .scalars()
        .all()
    )
    if not low_conf:
        return {"batch_no": None, "extracted": 0, "kept": 0, "reason": "没有待处理低置信度问题"}

    session_ids = {item.session_id for item in low_conf if item.session_id}
    messages = (
        (
            await db.execute(
                select(Message)
                .where(Message.session_id.in_(session_ids))
                .order_by(Message.id.desc())
                .limit(200)
            )
        )
        .scalars()
        .all()
    )
    messages = list(reversed(messages))
    text = "\n".join(
        f"{'用户' if item.sender_type == 'user' else '客服'}:{item.content}"
        for item in messages
    )
    if not text.strip():
        text = "\n".join(f"问题:{item.query}" for item in low_conf)

    pairs: list[dict[str, str]] = []
    for start in range(0, len(text), 6000):
        pairs.extend(await extract_pairs(text[start : start + 6000], llm))
    if not pairs:
        return {"batch_no": None, "extracted": 0, "kept": 0, "reason": "未抽取到候选问答"}

    existing = list(
        (await db.execute(select(Knowledge.question))).scalars().all()
    )
    candidates = [
        {"question": pair["question"][:500], "answer": pair["answer"]}
        for pair in pairs
    ]
    kept_items, _ = dedupe_candidates(candidates, existing)

    batch_no = datetime.now().strftime("mine-%Y%m%d%H%M%S")
    for item in kept_items:
        db.add(
            QaExtractionStaging(
                batch_no=batch_no,
                source_ref="low_confidence",
                question=item["question"],
                answer=item["answer"],
                status="extracted",
            )
        )
    await db.commit()
    logger.info(
        "知识抽取完成: batch={} extracted={} kept={}",
        batch_no,
        len(pairs),
        len(kept_items),
    )
    return {
        "batch_no": batch_no,
        "extracted": len(pairs),
        "kept": len(kept_items),
        "reason": "",
    }
