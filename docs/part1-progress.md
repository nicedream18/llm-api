# 第一部分持续完善记录

范围：Wiki、MCP、Software、Auth Provider、平台能力与可靠性回归。项目代码只提交到本地 Git，不推送远程。

## 当前验收状态（2026-11-01）

- Python 全量测试：**332 passed, 2 skipped**；全仓覆盖率 **85.74%**。GitHub Actions 在全量测试命令中执行 85% 覆盖率门槛。
- 全仓 Ruff、全仓 Mypy（81 个源文件）、`compileall` 和 `git diff --check` 通过。
- 前端 Node 静态 Wiki 测试 3 项通过，Vitest 10 项通过；TypeScript 检查与 Vite 生产构建通过。
- 本机没有隔离 MySQL 服务，因此本地两项真实 MySQL 集成测试跳过；GitHub Actions 已配置 MySQL 8.4 service，会在 CI 中执行这两项测试。
- 远程模型和 Provider 实际 OAuth 服务未接入测试；使用本地 SQLite 与模拟 HTTP 响应验证。

## 已实现并有自动化测试

### Wiki

- 项目与 Markdown 页面 CRUD、路径/修订冲突检查、标签搜索、wikilink 图谱。
- 来源录入、摄入状态和重试；附件上传/下载/删除；项目 JSON 备份与恢复。
- Wiki 问答复用代理安全、配额与日志链路；KB/Wiki 资源授权和管理员写权限。
- REST API 与 MCP 查询工具已接入。React 管理页支持项目设置、页面 Markdown 编辑/安全预览、标签搜索、附件管理、来源摄入、图谱查看、备份恢复和 Wiki 问答；移动端布局仍需真实浏览器验收。

### MCP

- `POST /mcp` 使用 MCP 2025-06-18 JSON-RPC Streamable HTTP JSON 响应模式：initialize、ping、tools/list、tools/call。
- KB 工具覆盖知识库、文档、索引和来源操作；Wiki 提供列表、读取、标签、图谱、问答；已启用 Software 工具可聚合调用。
- 独立 MCP Token、可选 API Key 接入、工具级/资源级授权，以及不含工具参数和凭据的持久化调用审计。
- MCP initialize 会签发带 TTL 的会话 ID；后续请求按主体绑定校验，支持 DELETE 终止会话；管理台提供工具列表、参数调用和审计查看。
- `/api/mcp/*` 兼容路由保留。

限制：SSE 通知和请求取消已支持，但不提供断线事件重放，也不跨进程共享会话队列；工具权限必须按部署配置 ACL 授权。

### Software

- 软件实例、工具、输入 schema 校验、启停、审批检查和调用记录。
- CLI、HTTP、MCP Server 连接器，以及通过安全 HTTP bridge 接入的 WeChat/CLIHUB 类型。
- MCP 工具列表可动态汇总已启用 Software 工具。
- OpenAPI 3.0/3.1 JSON 本地预览与选择性导入；支持本地 `$ref`、路径/查询参数与 `application/json` 请求体，调用前校验参数并检查目标 URL。
- OpenAPI 工具以单事务注册、默认每次调用需管理员显式批准；调用日志对常见凭据字段与 Bearer 值脱敏。
- React 管理页支持粘贴规范、预览操作、选择导入和展开输入 schema；支持实例编辑、工具调用调试、调用记录和服务端持久化审批队列。
- Software 管理页支持固定白名单本机扫描和默认 dry-run 安装计划；实际安装必须显式开启 `SOFTWARE_ALLOW_INSTALL=true`。

限制：扫描仅覆盖固定可执行文件白名单，安装不负责未知软件的自动发现；暂不支持 header/cookie 参数、multipart 请求体、外部 `$ref`、复合 JSON Schema 关键字或认证密钥配置 UI。审批队列只执行已注册工具。

### Auth Provider 与平台能力

- Provider 账户、PKCE state、加密 Token 保存、刷新、退出、配额和模型端点调用。
- 六个 Provider 标识通过可配置 HTTP OAuth adapter 实现；密钥使用独立配置密钥加密。
- 管理台支持 Provider 账号创建/编辑、OAuth 授权、手动 Token、安全退出、刷新、额度查询和模型同步。
- 配置了 `gateway_url`/`base_url` 且账号处于 active 的 Provider 会进入网关候选池，按优先级和模型映射参与路由；未配置网关地址或 Token 的账号不会被路由。
- Prompt 模板、语义缓存、客户端配置预览/写入与删除接口已有实现。

限制：适配器按可配置端点工作，尚未为每家 Provider 验证真实 OAuth 行为；账号池仅支持显式配置通用网关地址，尚未实现厂商专属请求协议、自动 Token 轮换后的重新路由和故障熔断统计。

## 本轮新增的可靠性和测试节点

| 提交 | 内容 |
|---|---|
| `47ab2b8` | ProxyService 请求、响应、配额和流生命周期测试 |
| `0af66bf` | 日志、安全规则、渠道与 API Key 仓储 SQLite 行为测试；修正日志 `trace_id` 查询字段 |
| `a19dfc0` | KB/配额仓储、认证分支、协议、Provider、Importer 和 Gateway 回归；增加覆盖率 CI |
| `f012263` | OpenAPI 规范预览/选择导入、事务持久化、HTTP 参数映射、调用校验与日志脱敏；管理台导入交互 |
| `b037d10` | Wiki 管理台编辑器、Markdown 安全预览、附件/来源/图谱/备份工作流；附件列表接口 |
| `f5a13fa` | Provider 管理台生命周期操作；显式配置 Provider 账号进入网关候选池；Provider 路由回归测试 |
| `342c7a9` | MCP 会话 TTL/主体绑定/终止、管理员调试台和审计查看 |
| `064fe8f` | Wiki 管理台问答工作流、来源引用和 API 请求回归 |
| `23dc7cf` | Software 实例编辑、工具调用调试和调用记录管理台 |
| `9702135` | 管理台访问授权配置 |
| `9a5d292` | Software 服务端审批请求、决策、执行和调用审计 |
| `9be4b47` | MCP SSE 通知队列、SSE 会话流和取消通知 |
| `352b4a0` | Software 本机工具扫描、受控安装计划和管理台入口 |
| `80ee591` | Provider Token 过期刷新、账号失败冷却和网关健康回写 |

每个节点均先跑定向测试，再完成全量验证后提交；不推送远程。

## 尚未完成的计划项

1. 在 CI 的 MySQL 8.4 service 中持续验证完整迁移、并发/锁语义、级联清理和仓储回归；本机仍需连接隔离实例才能执行。
2. Provider 真实厂商 OAuth 互通和厂商专属协议适配；账号池失败计数、冷却和过期 Token 刷新已实现。
3. Software 扩展扫描器覆盖范围、实例凭据配置和更细粒度的审批策略。
4. Wiki 移动端真实浏览器验收；页面编辑和备份恢复已在管理台接入，仍需端到端浏览器回归。
5. MCP 断线事件重放和跨进程会话存储；当前已支持 SSE 通知、取消和权限配置界面。
6. 逐模块提高低覆盖路径，重点是 migration runner、middleware、importer、gateway、streaming 和数据库仓储；总覆盖率门槛 85% 不代表这些模块都达到该比例。

## 最近一次复现命令

```bash
python -m pytest --cov=app --cov-fail-under=85 -q
ruff check app tests
mypy --follow-imports=silent app
python -m compileall -q app tests
node --test tests/frontend/*.test.cjs
cd frontend && npm test && npm run build
git diff --check
```
