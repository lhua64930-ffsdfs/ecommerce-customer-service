# 售后智答

售后智答是一个电商售后智能客服系统。本上下文定义项目中反复出现的领域术语,供人与 Agent 在设计、实现和评审时使用同一套语言。

## 会话与售后

**会话 (Session)**:
一次用户与客服之间的连续对话,包含多条消息和最终状态。
_Avoid_: 聊天、对话记录、ticket

**转人工 (Human handoff)**:
将当前会话交给人工客服继续处理。
_Avoid_: 升级、转接客服、人工

**工单 (Ticket)**:
脱离会话独立跟踪的售后事项记录,用于后续人工处理。
_Avoid_: 任务、issue、工单号(作为概念)

**售后事项 (Service task)**:
一次售后诉求的持久化进度记录,包含目标、订单、状态与摘要;
同会话同订单同类型的未完成事项复用。
_Avoid_: 订单、条、记录(泛称)

**审批单 (Approval)**:
模型提交的售后申请记录,经过用户确认或人工审核后由系统执行;
包含动作、订单号、风险等级、策略决策与执行结果。
_Avoid_: 申请、工单(混淆)

**策略引擎 (Policy engine)**:
用可配置规则判断售后资格(金额/状态/风险)并给出决策的组件;
决策分为自动执行、用户确认、人工审核、拒绝四档。
_Avoid_: 规则判断、if-else

**订单核验 (Order verification)**:
通过订单号 + 手机号后四位确认操作人身份的过程,核验结果绑定会话。
_Avoid_: 登录、鉴权(更广义)

## Agent

**单步 Agent (Single-step Agent)**:
对一条用户消息只做一次意图判断,并调用一个处理器或工具就结束的 Agent。
_Avoid_: 路由、意图路由、ReAct

**多步 Agent (Multi-step Agent)**:
在一次用户请求内可以多次调用工具、观察结果并决定下一步,直到完成任务或达到步数上限的 Agent。
_Avoid_: 工作流、链、ReAct

**复合任务 (Compound task)**:
一次用户请求内先查询订单或商品状态,再执行取消、退货等后续动作的任务;
例如「查订单 ORDER20260401001 然后帮我取消」。
_Avoid_: 批量任务、工作流

**强停兜底 (Strong-stop fallback)**:
当多步图失败、超过步数或没有可用结果时,不调用单步 Agent,
直接返回固定兜底话术并结束本次请求。
_Avoid_: Agent Fallback、回退单步 Agent

**Agent 模式 (Agent mode)**:
本次请求实际使用的 Agent 路径,对应响应字段 `agent_mode`:
多步 Agent(`multi_step`)、单步 Agent(`single_step`;无模型时走单步离线模式)。
_Avoid_: 路由模式、处理类型、降级模式

## 工具与观测

**MCP Server**:
以 MCP 协议独立部署、向可信调用方暴露工具的服务;
本项目通过 Streamable HTTP 暴露 6 个 Agent 工具。
_Avoid_: 工具 API、插件服务

**MCP 工具代理 (MCP tool proxy)**:
后端把工具调用转发到 MCP Server 的适配层;
对模型仍暴露本地 Schema,身份参数由后端注入,传输失败可回退。
_Avoid_: 远程工具、RPC 客户端

**工具回退 (Tool fallback)**:
MCP 连接/协议/超时失败时,改用进程内工具实现执行同一次调用;
只对幂等只读工具生效,远程已返回业务失败时不触发。
_Avoid_: Agent Fallback(不同层)

**副作用工具 (Side-effect tool)**:
会改变业务状态的工具,如建工单、提交售后申请、转人工排队;
不自动重试,结果未知时也不回退本地,避免重复执行。
_Avoid_: 写工具(转人工不是写库但仍有副作用)

**动态工具发现 (Dynamic tool discovery)**:
从 MCP Server 拉取工具清单并按 TTL 缓存,Server 新增工具无需重启后端。
_Avoid_: 工具注册、插件扫描(内置工具场景)

**Trace**:
Langfuse 中一次请求的观测记录,可带 session_id、user_id、tags 与名称。
_Avoid_: 日志、调用链(泛称)

**Generation**:
Langfuse 中一次 LLM 调用的观测单元,记录模型、token、延迟与输入输出。
_Avoid_: 请求、调用

## 运行时与安全

**Checkpoint Thread**:
LangGraph 按 `会话ID` 保留的执行状态,跨轮续接;
每轮重置步骤/工具记录,消息由 `add_messages` 累积,用于 interrupt 后恢复。
_Avoid_: 会话、上下文(泛称)

**中断 / 恢复 (Interrupt / Resume)**:
图在缺订单号等 slot-filling 场景暂停,前端选择后用 `Command(resume=...)` 继续;
只做交互补全,不执行写操作。
_Avoid_: 审批、确认(不同层)

**技能包 (Skill pack)**:
`skills/*.md` 中的运营指令,按意图追加到系统提示词。
_Avoid_: 提示词模板、知识条目

**语义历史 (Semantic history)**:
用 embedding 从被滑窗丢弃的历史消息中补捞相关轮次。
_Avoid_: 记忆、摘要(不同层)

**熔断器 (Circuit breaker)**:
上游连续失败后短路,冷却后半开放一个探针;避免打爆故障服务。
_Avoid_: 限流、降级(不同机制)

**保留期 (Retention)**:
按 `created_at` 分批删除过期会话/消息/低置信度/审计数据;0 表示永久保留。
_Avoid_: 清理缓存、归档

**租户 (Tenant)**:
用户与会话的隔离维度,写入 JWT 与数据库;跨租户访问按不存在处理。
_Avoid_: 分组、团队(泛称)

**登录码 (Login code)**:
短信登录的一次性验证码,只存 HMAC,限时、限尝试次数。
_Avoid_: 密码、token

## 检索与评估

**知识条目 (Knowledge item)**:
知识库中的一条“问题—答案”记录,带分类和关键词。
_Avoid_: 文档、FAQ、语料

**RAG 引用 (Citation)**:
附着在生成回答上的来源标识,指向生成时使用的知识条目;
对外包含知识 id、分类、问题与相似度,并随消息持久化。
_Avoid_: 来源、参考、链接

**评测集 (Evaluation set)**:
一组固定的“问题 → 期望知识条目”样本,用于衡量检索质量。
_Avoid_: 测试集(单元测试)、数据集

**Recall@3**:
评测集中,期望知识条目出现在检索结果前 3 名的题目比例。
_Avoid_: 命中率、准确率

**检索降级 (Retrieval fallback)**:
向量检索不可用时,改用关键词检索知识条目的策略。
_Avoid_: 降级、Agent Fallback

**混合检索 (Hybrid retrieval)**:
向量检索与 BM25 并行召回,用 RRF 融合后再用 CrossEncoder 重排的检索方式。
_Avoid_: 多路检索、双路召回

**证据置信度 (Evidence confidence)**:
用 Top1 分、有效证据数、Top1-Top2 分差、关键条款命中四个信号,
判断检索结果是否足以支撑回答的分数。
_Avoid_: 检索分数、相似度

**知识飞轮 (Knowledge flywheel)**:
低置信度问题 → LLM 抽取候选问答 → 人工复核 → 采纳补库的闭环。
_Avoid_: 自动学习、知识自动更新

**SSE 事件流 (Server-Sent Events)**:
聊天响应按 `meta / delta / tool / citations / actions / done` 事件逐步推送。
_Avoid_: WebSocket、长轮询

**文档片段 (Document chunk)**:
Markdown 文档按标题和中文标点切出的片段,带章节路径,引用可定位到该片段。
_Avoid_: 知识条目(FAQ)、文件

**回答校验 (Answer guard)**:
检查回答中的订单号、金额、日期是否逐字来自证据的机械校验。
_Avoid_: 事实核查、LLM 裁判
