# 第一部分持续完善记录

范围：Wiki、MCP、Software、Auth Provider、平台能力与可靠性回归。项目代码只提交到本地 Git，不推送远程。

## 当前验收状态（2026-11-02）

- Python 全量测试：**361 passed, 5 skipped**；全仓覆盖率 **85.63%**，CI 同样执行 85% 门槛。
- 全仓 Ruff、Mypy、`compileall` 和 `git diff --check` 已纳入最终门禁。
- 前端 Vitest、Node Wiki 静态回归、TypeScript 检查和 Vite 生产构建通过。
- 本机没有隔离 MySQL 服务，真实 MySQL 测试保留跳过；GitHub Actions 已配置 MySQL 8.4 service。
- 本机没有真实 Provider OAuth 凭据和部署浏览器环境；Provider 使用脱敏 HTTP contract fixture，Wiki 浏览器 smoke test 明确跳过。

## 已实现并有自动化测试

### Wiki

- 项目与 Markdown 页面 CRUD、路径/修订冲突检查、标签搜索、wikilink 图谱。
- 来源录入、摄入状态和重试；附件上传/下载/删除；项目 JSON 备份与恢复。
- Wiki 问答复用代理安全、配额与日志链路；KB/Wiki 资源授权和管理员写权限。
- REST API、MCP 查询工具和 React 管理页已接入。管理页覆盖编辑、安全预览、标签、附件、来源、图谱、备份恢复和问答。
- 固定大型 Markdown 渲染性能回归已加入 Node 测试；真实移动端和长流程浏览器验收需要外部部署 URL 与 Playwright 浏览器。

### MCP

- `POST /mcp` 使用 MCP 2025-06-18 JSON-RPC Streamable HTTP JSON 响应模式：initialize、ping、tools/list、tools/call。
- KB、Wiki 和已启用 Software 工具可聚合调用；独立 MCP Token、可选 API Key、工具/资源授权和调用审计已实现。
- 会话和通知事件持久化，事件序号、TTL、主体绑定、Last-Event-ID 重放、保留窗口事件缺口错误和过期清理已实现。
- 内存队列只作为性能优化，数据库作为跨进程一致性来源；跨进程删除、主体不匹配、过期和缺口均有回归测试。
- `/api/mcp/*` 兼容路由保留。

### Software

- 软件实例、CLI/HTTP/MCP/OpenAPI/bridge connector、输入 schema 校验、启停、MCP 聚合和调用审计。
- 本机扫描覆盖固定可执行文件白名单，执行路径规范化、非文件/符号链接过滤、超时和路径去重。
- 实例与工具凭据只接受环境变量引用，API、日志和 MCP 返回值统一脱敏。
- 审批策略支持实例、工具、操作和风险级别覆盖；审批请求支持有效期、一次性决策、拒绝和审计查询，未批准/禁用/高风险工具在执行前拒绝。
- OpenAPI 3.0/3.1 JSON 预览与选择导入、dry-run 安装计划和管理台调试已实现。
- 仍不支持外部 `$ref`、header/cookie 参数、multipart 请求体或认证密钥配置 UI；真实安装仍需显式环境变量。

### Auth Provider 与平台能力

- Provider 账户、PKCE state、加密 Token 保存、刷新、退出、配额和模型端点调用。
- 六个 Provider 标识通过统一 HTTP OAuth adapter 契约实现；密钥只通过独立配置或环境变量解析。
- 账号失败计数、冷却、过期 Token 刷新和刷新后的重新读取已实现；配置了 `gateway_url`/`base_url` 的 active 账号可参与路由。
- Prompt 模板、语义缓存、客户端配置预览/写入与删除接口已有实现。

## 代码完成但环境待验收

1. **MySQL 8.4**：CI service 负责真实迁移重复执行、checksum 拒绝、并发锁、事务/行锁、级联删除和仓储回归；本机没有隔离实例。
2. **Provider**：需要真实 OAuth 服务和厂商凭据验证登录、刷新、退出、配额、模型同步、失败切换和专属协议；凭据不得进入测试数据、日志或 Git。
3. **Wiki 浏览器**：需要真实部署 URL 与 Playwright 浏览器验证移动端登录、权限、编辑、来源、附件、图谱、问答、备份恢复和长页面滚动。

## 本轮节点提交

| 提交 | 内容 |
|---|---|
| `cc040a4` | 关键运行时覆盖缺口与错误分支回归 |
| `c7aff8c` | MySQL migration/repository 集成测试与 CI service |
| `0a1ae7c` | Software 凭据、审批和调用安全基础 |
| `130a411` | MCP 会话与通知事件持久化基础 |
| `338591d` | Provider adapter 契约和 live fixture |
| `f4e9aa7` | MCP 跨进程事件重放和协议边界 |
| `13a7e60` | Software 扫描路径安全、审批策略和有效期 |
| `c97af3d` / `960f04c` | MCP 重放协议与仓储状态回归 |
| `d2359a6` | Wiki 长文档性能和可选浏览器 smoke test |
| `cbda537` | MySQL 方言迁移索引和仓储行锁检测修复 |

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

本轮最终门禁结果：361 passed / 5 skipped，覆盖率 85.63%；Ruff、Mypy、compileall、Node 4 项、Vitest 11 项、TypeScript 和 Vite build 全部通过。

没有把外部环境缺失伪报为通过；外部验收完成后应在此文档补充实际环境、命令和结果。

第二阶段的增量状态、节点提交和当前环境限制见 [`docs/part2-progress.md`](part2-progress.md)。
