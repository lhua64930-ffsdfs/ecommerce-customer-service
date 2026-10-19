"""工具描述(供 LLM 工具调用与提示词使用)。"""

TOOL_DESCRIPTIONS = """
## 可用工具

### 1. search_knowledge(知识库检索)
- 用途:从平台知识库检索商品信息、平台政策、常见问题解答
- 输入:搜索关键词
- 输出:相关的知识库条目

### 2. query_order(订单查询)
- 用途:查询用户订单的状态、物流、收货信息
- 输入:订单号(可选,不提供则返回订单列表)
- 输出:订单详细信息或订单列表

### 3. query_product(商品查询)
- 用途:搜索商品、了解价格库存、查看促销
- 输入:商品关键词
- 输出:商品列表及价格库存信息

### 4. refund(退款退货)
- 用途:处理取消订单、退款申请、退货流程
- 输入:操作类型(cancel/return/refund/query)、订单号、原因
- 输出:操作结果和处理流程

### 5. transfer_human(转人工)
- 用途:将用户转接给人工客服
- 输入:转接原因
- 输出:转接状态和等待时间

### 6. create_ticket(创建工单)
- 用途:记录用户问题,生成工单待处理
- 输入:工单类型、标题、内容
- 输出:工单编号
"""

TOOL_JSON_SCHEMA = [
    {
        "name": "search_knowledge",
        "description": "从知识库中检索商品信息、平台政策、常见问题等",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "搜索关键词"},
                "category": {"type": "string", "description": "知识库分类(可选)"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "query_order",
        "description": "查询用户订单状态、物流信息、收货地址等",
        "parameters": {
            "type": "object",
            "properties": {"order_no": {"type": "string", "description": "订单号(可选)"}},
            "required": [],
        },
    },
    {
        "name": "query_product",
        "description": "搜索商品信息、价格、库存",
        "parameters": {
            "type": "object",
            "properties": {
                "keywords": {"type": "string", "description": "商品关键词"},
                "category": {"type": "string", "description": "商品分类"},
            },
            "required": ["keywords"],
        },
    },
    {
        "name": "refund",
        "description": "处理退款退货申请、取消订单",
        "parameters": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["cancel", "return", "refund", "query"],
                    "description": "操作类型",
                },
                "order_no": {"type": "string", "description": "订单号"},
                "reason": {"type": "string", "description": "原因"},
            },
            "required": ["action"],
        },
    },
    {
        "name": "transfer_human",
        "description": "将用户转接给人工客服",
        "parameters": {
            "type": "object",
            "properties": {
                "reason": {
                    "type": "string",
                    "enum": ["用户主动请求", "投诉", "技术问题", "其他"],
                    "description": "转接原因",
                }
            },
            "required": ["reason"],
        },
    },
    {
        "name": "create_ticket",
        "description": "创建客服工单",
        "parameters": {
            "type": "object",
            "properties": {
                "type": {
                    "type": "string",
                    "enum": ["complaint", "refund", "consult", "suggestion"],
                    "description": "工单类型",
                },
                "title": {"type": "string", "description": "工单标题"},
                "content": {"type": "string", "description": "工单内容"},
            },
            "required": ["type", "content"],
        },
    },
]
