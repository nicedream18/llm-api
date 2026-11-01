# 完善计划第一部分检查报告

检查日期：2026-11-01。

本次按用户确认的范围，检查第一部分四个模块，修复并测试现有 MCP。Wiki、Software、Auth Provider 本轮不新增。结论基于本地当前工作区；没有重新核验 GitCode 参考仓库的提交和功能声明，也不以工具数量作为功能对齐验收依据。

## 四模块现状

| 模块 | 当前实现 | 本轮结论 |
| --- | --- | --- |
| Wiki 知识引擎 | 普通 KB 的创建、文档、检索和问答；未发现 Wiki 专属路由、模型、存储或页面 | 仍缺失，不能将普通 KB 当作 Wiki |
| MCP | 原有 3 个只读 KB 工具、自定义 REST 接口、独立 MCP Token 和可选 API Key 认证 | 本轮补充协议入口并修复参数校验、错误泄露与工具数据返回；整体仍属部分实现 |
| Software 软件工具中心 | 未发现软件实例、连接器、工具注册、风险审批、调用存储或对应前端 | 仍缺失，现有 Agent 不等同于 Software |
| Auth Provider 账号体系 | 管理员认证和渠道 API Key 已存在；未发现供应商账号、OAuth、刷新令牌、配额同步或账号路由 | 仍缺失，管理员登录不等同于上游供应商账号登录 |

检查范围包括 app/api/controllers、app/application/services、app/domain、app/infrastructure、app/types、app/static、docs/waliapi.sql、迁移和现有测试。

### Wiki 待建设范围

- Wiki 项目与 Markdown 页面 CRUD、目录层级、路径管理。
- 搜索、标签、wikilinks、图谱和 Wiki 问答。
- 源文件导入、删除、重新摄入及 pending/ingested/failed 状态。
- 项目备份、恢复、导入导出，页面附件和图片。
- Wiki 查询授权与 MCP 工具。

### Software 待建设范围

- CLI、HTTP、MCP Server、微信及 CLIHub 连接器。
- 软件实例、扫描安装、OpenAPI 导入与工具预览。
- 工具启停、风险分级、审批和持久化调用日志。
- 软件工具向 MCP 的聚合。

### Auth Provider 待建设范围

- Codex、Gemini、Grok、Kimi、Qoder、WorkBuddy 等供应商账号接入。
- OAuth、Token 刷新、退出、禁用、排序和账号状态。
- 配额查询、配额重置、模型同步与模型映射。
- 多账号路由、账号故障切换、与普通渠道混合路由。

这些功能需要单独的数据模型、迁移、接口、权限和测试，当前没有可验收的实现。

## MCP 已完成的修复

1. 新增 POST /mcp，使用 JSON-RPC 2.0，协商协议版本 2025-06-18；实现 initialize、ping、tools/list 和 tools/call。
2. 使用无状态 Streamable HTTP 的 JSON 响应模式，不签发会话 ID。GET /mcp、DELETE /mcp 返回 405，不声明支持 SSE 会话或恢复。
3. 新入口纳入独立 MCP Token 鉴权；默认拒绝普通下游 API Key，只有启用 MCP_API_KEY_ACCESS 才接受。支持 Bearer 和 X-MCP-Token；令牌比较使用常量时间函数。
4. 校验 Origin、Content-Type、Accept、协议版本、JSON-RPC 信封和请求 ID；请求体上限 1 MiB。
5. 通知返回空的 HTTP 202，且不会把无 ID 的工具调用当作实际执行请求。
6. 参数定义同时用于工具 schema 和运行时校验：拒绝非对象、缺失字段、非法检索模式、额外字段和非法 top_k；top_k 限定 1–100，并拒绝布尔值冒充整数。
7. 协议错误使用 -32700、-32600、-32601、-32602；工具内部失败使用正常工具结果中的 isError。客户端不再收到数据库连接或上游异常原文。
8. 列举知识库时将实际列表写入标准 content 文本，问答来源也写入 content，避免标准客户端只获得数量、丢失数据。
9. 记录工具名称、请求 ID、调用主体、错误类型、执行状态和耗时，不记录工具参数或异常原文。日志使用现有应用日志，不是独立持久化审计表。
10. 保留 /api/mcp/info、/tools/list、/tools/call；修正 info 中原先不实的 SSE 声明。

规范参考：

- [MCP 2025-06-18 Streamable HTTP](https://modelcontextprotocol.io/specification/2025-06-18/basic/transports)
- [MCP 生命周期与版本协商](https://modelcontextprotocol.io/specification/2025-06-18/basic/lifecycle)

这是一版明确限定版本和能力的实现，不代表对所有 MCP 版本或所有客户端兼容。

### MCP 仍未完成

- 当前仍为 3 个只读知识库工具；知识库写操作、文档读取/上传/删除、索引和来源管理的工具化尚未补齐。
- Wiki 和 Software 工具及其聚合依赖对应模块建设。
- 没有按 Token/主体配置的工具权限、按知识库授权或域级 RBAC。当前独立 Token 可读取全部 KB，启用 API Key 接入也不提供逐 KB 授权；本次鉴权加固不等同于补齐授权。
- 没有有状态 SSE、会话恢复、服务端通知和取消任务执行；这些能力本轮未声明支持。
- 没有 MCP 专属数据库审计、调用日志查询页或在线调试台。
- 未验证真实 MySQL、真实模型上游、真实文档检索和公网部署链路。

## 验证结果

在临时虚拟环境中安装项目 requirements，未修改项目依赖文件或现有虚拟环境。

- 改动前：现有 30 个测试通过。
- 改动后：全量 57 个测试通过，新增 27 个 MCP 测试用例（含参数化实例）。
- 官方 Python SDK mcp==1.12.4 互通通过：initialize、initialized 通知、tools/list、tools/call。使用 ASGI HTTP transport 和模拟 KB，无真实数据库或上游调用。
- 官方 SDK 测试保存在 tests/test_mcp.py；SDK 为可选测试依赖，未安装时仅跳过此互通测试，其余测试仍运行。
- 新路由、参数模型、鉴权中间件及 MCP 测试的 Ruff 检查通过；新增路由和参数模型的 Mypy 检查通过。
- 全仓 Ruff 仍有改动前相同的 61 条既有告警，不能报告为“全仓静态检查通过”。未顺带修改无关模块。
- compileall 和 diff 空白检查通过。
- 运行环境有一条 Starlette/AnyIO 弃用警告；不影响本轮断言。

可复现命令（在已安装 requirements 的 Python 环境中）：

~~~bash
python -m pytest -q
python -m compileall -q app tests
ruff check app/api/controllers/mcp_routes.py app/api/middleware/auth.py app/types/mcp.py tests/test_mcp.py
mypy --follow-imports=silent app/types/mcp.py app/api/controllers/mcp_routes.py
git diff --check
~~~

可选互通测试环境额外安装：

~~~bash
python -m pip install 'mcp==1.12.4' 'pydantic-settings==2.7.1'
python -m pytest tests/test_mcp.py -q
~~~

## DevBugKB 与失败尝试

- 已执行搜索：waliapi MCP Wiki Software Auth Provider、MCP JSON-RPC tools/call invalid arguments error response、No module named pytest 和冻结配置异常。
- 搜索命中 verified 案例 BUG-20261031-001（MySQL 用户认证失败），但与本次 MCP 问题无关，未套用其修复。具体 MCP 和 pytest 查询无匹配案例。
- 已查看 unresolved 的 BUG-20261031-006（Redis 超时草稿）以及 deprecated 目录说明；没有适用历史方案。
- 两个现有虚拟环境运行测试都失败于缺少 pytest。之后改用 /tmp/waliapi-phase1-check-venv 独立安装依赖，避免改动已有环境。
- 修复前复现：工具执行异常将内部连接信息原文返回；传入列表参数会返回内部 AttributeError 文本。
- 首轮新增测试夹具直接修改冻结 AppConfig，报 FrozenInstanceError；改为替换模块中的测试配置引用，随后通过。没有修改生产配置的冻结约束。
- 静态检查曾发现新增导入顺序和测试中嵌套 async with 问题，已修正，未扩大到无关既有告警。
- 本次未修改、提交或推送 DevBugKB 案例；也未提交或推送项目代码。

工作区原有大量未提交改动已保留。本次代码修改只涉及 MCP 实现、鉴权接入、应用路由注册及相关测试和本报告。
