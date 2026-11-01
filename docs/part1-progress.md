# 第一部分持续完善记录

范围：Wiki、MCP、Software、Auth Provider、平台能力与可靠性回归。项目代码只提交到本地 Git，不推送远程。

## 当前验收状态（2026-11-01）

- Python 全量测试：**322 passed, 2 skipped**；全仓覆盖率 **86.04%**。GitHub Actions 在全量测试命令中执行 85% 覆盖率门槛。
- 全仓 Ruff、全仓 Mypy（81 个源文件）、`compileall` 和 `git diff --check` 通过。
- 前端 Node 测试和 Vitest 各 3 项通过；TypeScript 检查与 Vite 生产构建通过。
- 两项真实 MySQL 集成测试因本机没有隔离 MySQL 服务而跳过；不得视为 MySQL 验收通过。
- 远程模型和 Provider 实际 OAuth 服务未接入测试；使用本地 SQLite 与模拟 HTTP 响应验证。

## 已实现并有自动化测试

### Wiki

- 项目与 Markdown 页面 CRUD、路径/修订冲突检查、标签搜索、wikilink 图谱。
- 来源录入、摄入状态和重试；附件上传/下载/删除；项目 JSON 备份与恢复。
- Wiki 问答复用代理安全、配额与日志链路；KB/Wiki 资源授权和管理员写权限。
- REST API 与 MCP 查询工具已接入。React 页面目前主要支持项目/页面的基础列表和创建，不能视作完整编辑器或移动端验收。

### MCP

- `POST /mcp` 使用 MCP 2025-06-18 JSON-RPC Streamable HTTP JSON 响应模式：initialize、ping、tools/list、tools/call。
- KB 工具覆盖知识库、文档、索引和来源操作；Wiki 提供列表、读取、标签、图谱、问答；已启用 Software 工具可聚合调用。
- 独立 MCP Token、可选 API Key 接入、工具级/资源级授权，以及不含工具参数和凭据的持久化调用审计。
- `/api/mcp/*` 兼容路由保留。

限制：当前传输无状态，不提供 SSE 会话、恢复、服务器主动通知或取消；工具权限仍依赖已配置的 ACL，必须按部署配置授权。

### Software

- 软件实例、工具、输入 schema 校验、启停、审批检查和调用记录。
- CLI、HTTP、MCP Server 连接器，以及通过安全 HTTP bridge 接入的 WeChat/CLIHUB 类型。
- MCP 工具列表可动态汇总已启用 Software 工具。
- OpenAPI 3.0/3.1 JSON 本地预览与选择性导入；支持本地 `$ref`、路径/查询参数与 `application/json` 请求体，调用前校验参数并检查目标 URL。
- OpenAPI 工具以单事务注册、默认每次调用需管理员显式批准；调用日志对常见凭据字段与 Bearer 值脱敏。
- React 管理页支持粘贴规范、预览操作、选择导入和展开输入 schema。

限制：自动扫描/安装未实现；暂不支持 header/cookie 参数、multipart 请求体、外部 `$ref`、复合 JSON Schema 关键字或认证密钥配置 UI；前端仍缺实例完整编辑、待审批队列和调用调试工作流。

### Auth Provider 与平台能力

- Provider 账户、PKCE state、加密 Token 保存、刷新、退出、配额和模型端点调用。
- 六个 Provider 标识通过可配置 HTTP OAuth adapter 实现；密钥使用独立配置密钥加密。
- Prompt 模板、语义缓存、客户端配置预览/写入与删除接口已有实现。

限制：适配器按可配置端点工作，尚未为每家 Provider 验证真实 OAuth 行为；Provider 账号还没有纳入网关的账号池/自动路由，也没有 React 端账号连接、刷新及配额交互界面。

## 本轮新增的可靠性和测试节点

| 提交 | 内容 |
|---|---|
| `47ab2b8` | ProxyService 请求、响应、配额和流生命周期测试 |
| `0af66bf` | 日志、安全规则、渠道与 API Key 仓储 SQLite 行为测试；修正日志 `trace_id` 查询字段 |
| `a19dfc0` | KB/配额仓储、认证分支、协议、Provider、Importer 和 Gateway 回归；增加覆盖率 CI |
| 本轮待提交 | OpenAPI 规范预览/选择导入、事务持久化、HTTP 参数映射、调用校验与日志脱敏；管理台导入交互 |

每个节点均先跑定向测试，再完成全量验证后提交；不推送远程。

## 尚未完成的计划项

1. 在隔离 MySQL 环境跑完整迁移、并发/锁语义、级联清理和仓储回归。
2. Provider 真实厂商 OAuth 互通、账号配额/模型映射落地，以及账号池网关路由。
3. Software 自动扫描/安装、实例凭据配置、待审批队列和调用调试 UI。
4. Wiki 完整编辑、附件引用、备份恢复、图谱与移动端浏览器验收。
5. MCP 的更多会话/流能力（若目标客户端要求）、工具调试台和权限配置界面。
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
