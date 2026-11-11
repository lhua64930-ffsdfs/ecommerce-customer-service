# MCP 工具服务化:独立 Server + 传输失败回退

**Status**: accepted

## Context

项目原有 6 个 Agent 工具与后端同进程,工具通过 `ToolContext` 直接拿 `AsyncSession`、用户与会话身份。这种方式简单,但工具无法被其他进程或语言复用,也不利于演示「工具协议」这一层能力。用户明确要求把工具 MCP 服务化,包括独立 MCP Server、额外依赖与 Docker 编排。

## Decision

用官方 `mcp` SDK 2.x 实现两个独立 MCP Server:知识/商品(8001)、订单/售后(8002),通过 **Streamable HTTP** 暴露 6 个工具;后端增加多 Server 清单发现与 `McpToolProxy`,在 `MCP_ENABLED=true` 时按工具归属转发到对应 Server。

关键边界:

- **Schema 优先来自 Server 动态清单**(`list_tools()` + 60 秒缓存),本地工具 Schema 兜底;
  模型看不到 `user_id` / `session_id`;
- 身份与原始消息由 `ToolContext` 注入代理,不通过模型参数传递;
- 只有幂等只读工具(`search_knowledge` / `query_order` / `query_product`)
  允许传输失败后回退本地;写/申请/转人工返回 `MCP_RESULT_UNKNOWN`;
- 执行引擎对副作用工具(`create_ticket` / `propose_after_sales_action` /
  `transfer_human`)不自动重试,避免超时后重复建单/排队;
- MCP Server 每次调用创建独立 `AsyncSessionLocal`,复用同一套工具类与 MySQL/Redis/Milvus;
- Docker Compose 增加 `cs-mcp-knowledge` 与 `cs-mcp-aftersales`,仅内部网络可达,不映射宿主机端口;
- 后端并发拉取两个 Server 的工具清单,单台失败只跳过该台。

## Considered Options

- **stdio transport**:适合本地单客户端,但无法作为 Docker 内多请求方共享服务,也与后端按请求调用模型不匹配。
- **SSE transport**:MCP 旧版方案,官方已主推 Streamable HTTP;新项目不再选。
- **自研 HTTP JSON-RPC**:可控,但重复实现协议、会话与工具 Schema,失去「标准 MCP」的复用价值。
- **完全远程、不做回退**:链路更纯,但 MCP 进程重启/网络抖动会直接阻断售后业务;回退只处理传输层,不影响服务化演示。
- **把 user_id/session_id 暴露给模型**:实现最简单,但模型可伪造身份,直接击穿订单归属校验。

## Consequences

- 新增 `mcp>=2.3` 依赖与两个 MCP 容器;冷启动与内存占用略增。
- MCP Server 与后端各自加载 BGE / Reranker,首次检索会重复初始化;通过共享 HF 缓存卷缓解。
- 每次工具调用建立独立 Streamable HTTP 会话,带来额外 RTT;工具调用次数少(≤5 步),换取无状态与易重启。
- 工具 Schema 通过 `list_tools()` 动态拉取并缓存 60 秒,Server 新增工具无需重启后端;
  清单不可达时退回本地 Schema,代价是缓存窗口内的工具变更不会立即生效。
- 副作用工具在传输失败后可能已经执行,因此不回退、不自动重试;前端/模型会收到
  `MCP_RESULT_UNKNOWN`,需要后续查询确认。这牺牲了一点可用性,换取幂等与安全。
- MCP Server 无公网鉴权,部署文档明确要求保持内部网络隔离。
