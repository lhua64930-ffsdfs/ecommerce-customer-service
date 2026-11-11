# RAG 检索评测报告

> 评测对象:`RetrievalService.search()` 的检索排序质量。
> 评测集:`knowledge_base/eval_set.json`;脚本:`backend/scripts/evaluate_rag.py`。
> 本报告只评估检索排序,不评估 LLM 生成答案。

## 1. 评测集

- 12 个种子知识条目,每个条目 3 条自然语言查询,共 **36 条**样本;
- 每条样本标注 `expected_id`(对应 `knowledge_base/faqs.json` 的条目 id)、
  `category` 与标准问题文本;
- 查询覆盖退换货、配送、支付、会员、促销、保修、优惠券、发票、
  订单修改、正品、退款到账、人工客服 12 个售后主题。

## 2. 检索策略

| 策略 | 实现 |
| --- | --- |
| `vector` | BGE 向量 + Milvus COSINE |
| `bm25` | Milvus 原生 BM25(中文 analyzer) |
| `hybrid` | 向量 + BM25 并行召回,RRF 融合 |
| `hybrid_rerank` | hybrid 召回后用本地 `BAAI/bge-reranker-base` 精排 |

## 3. 指标定义

| 指标 | 定义 |
| --- | --- |
| Recall@1 | 期望知识条目排在检索结果第 1 位的样本比例 |
| Recall@3 | 期望知识条目出现在前 3 名的样本比例 |
| Recall@5 | 期望知识条目出现在前 5 名的样本比例 |
| MRR@5 | 期望条目排名倒数的平均值(未进入前 5 记 0) |

命中判定优先比较知识 id;若数据库自增 id 与 `faqs.json` 的参考 id 不一致,
则用标准问题文本兜底匹配,保证评测可跨环境复现。

## 4. 运行方式

```bash
cd backend
./venv/Scripts/python.exe scripts/evaluate_rag.py --strategy all
```

单策略运行:`--strategy vector|bm25|hybrid|hybrid_rerank`。
默认只评 FAQ,自动排除文档片段;要对照文档切块影响时加 `--include-chunks`。
`--json` 输出 JSON,`--output <path>` 写入文件。

## 5. 实测结果(12 条种子 FAQ)

运行环境:本地开发环境,Milvus 2.5.4 + BGE small zh v1.5 + bge-reranker-base,
12 条种子知识,`top_k=5`,评测时间 2026-11-11。

| 策略 | Recall@1 | Recall@3 | Recall@5 | MRR@5 |
| --- | --- | --- | --- | --- |
| vector | 0.9722 | 1.0000 | 1.0000 | 0.9861 |
| bm25 | 0.8056 | 0.8889 | 0.8889 | 0.8380 |
| hybrid | 0.8611 | 0.9444 | 1.0000 | 0.9060 |
| **hybrid_rerank** | **1.0000** | **1.0000** | **1.0000** | **1.0000** |

`hybrid_rerank` 分类别 Recall@3:12 个分类全部为 1.0000(每个分类 3 条样本)。

说明:

- BM25 单独使用召回偏弱,直接与向量做 RRF 融合时(hybrid)会被弱召回拖累;
  本地 CrossEncoder 重排后,`hybrid_rerank` 把 36 条查询全部排到第 1 位。
- 这组对照说明:**重排是必要的**,不能只做“向量 + 关键词”的简单融合。
- 原始 JSON 结果见 [rag_eval_result.json](rag_eval_result.json)。

## 6. 加入文档切块后的对照(可选)

导入 `knowledge_base/after_sales_manual.md`(10 个文档片段)后,
用 `evaluate_rag.py --strategy all --include-chunks` 再跑同一套评测:

| 策略 | Recall@1 | Recall@3 | Recall@5 | MRR@5 |
| --- | --- | --- | --- | --- |
| vector | 0.9167 | 1.0000 | 1.0000 | 0.9537 |
| bm25 | 0.6944 | 0.8611 | 0.8889 | 0.7708 |
| hybrid | 0.7778 | 0.8889 | 0.8889 | 0.8287 |
| **hybrid_rerank** | **0.8611** | **0.9722** | **1.0000** | **0.9236** |

指标变化的原因不是答案变差,而是**评测口径**:评测集期望命中 FAQ 的 `knowledge.id`;
文档片段是另一个知识源,部分问题由更细的章节片段排到第 1,按 FAQ id 判定就是“未命中”。
这组数据说明文档切块会改变检索排序,评测集需要按知识源分别设计。

原始 JSON:[rag_eval_with_docs_result.json](rag_eval_with_docs_result.json)。

## 7. 无答案拒答评测

评测集:`knowledge_base/unanswerable_questions.json`,20 条知识库外问题;
同时开启证据置信度闸与 LLM 自检。

```bash
cd backend
./venv/Scripts/python.exe scripts/evaluate_refusal.py --self-check
```

本机实测:

| 样本数 | 正确拒答 | 拒答率 | 检索模式 |
| --- | --- | --- | --- |
| 20 | 20 | 1.0000 | hybrid_rerank |

原始 JSON:[refusal_eval_result.json](refusal_eval_result.json)。

> 拒答率会随模型、提示词与阈值变化;该结果是当前配置下的实测,不是通用基准。
