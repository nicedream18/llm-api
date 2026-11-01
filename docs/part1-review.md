# 第一部分实现检查报告

检查日期：2026-11-02。报告基于当前本地分支代码、自动化测试和前端源码，不代表对线上 Provider、MySQL 或真实浏览器环境的验收。

## 功能状态

| 模块 | 代码完成范围 | 环境限制 |
|---|---|---|
| Wiki | 项目/页面编辑、来源/附件、搜索标签、图谱、问答、备份恢复、资源授权、REST/MCP；React 和原生管理台均支持 Markdown 编辑与安全预览；长文档性能回归已加入 | 移动端真实浏览器和长流程端到端验收待部署环境 |
| MCP | MCP 2025-06-18 JSON-RPC HTTP、TTL/主体绑定、KB/Wiki/Software 工具、权限和审计；数据库事件持久化、Last-Event-ID 重放、保留窗口缺口错误、跨进程读取/删除 | MySQL 多进程锁语义待 CI service 验收 |
| Software | CLI/HTTP/MCP/OpenAPI/bridge connector、schema 校验、扫描路径规范化/超时/去重、环境变量凭据、统一脱敏、实例/工具/操作/风险审批策略、有效期与审计 | 扫描是固定白名单；真实安装需显式开关；不支持外部 `$ref`、header/cookie、multipart 或认证密钥配置 UI |
| Auth Provider | 账户、PKCE、加密 Token、刷新/退出、过期刷新、配额/模型端点、统一 HTTP adapter、失败计数/冷却和网关重新读取 | 真实 OAuth 与厂商专属协议待凭据环境验收 |
| 平台 | Prompt 模板、语义缓存、客户端配置预览/写入/删除、管理台生命周期页面 | 真实 CLI 安装探测范围仍有限 |
| 网关与安全 | API Key/管理员认证、权限、配额预占结算、重试、响应协议转换、安全扫描、日志和流式回归 | 真实上游链路和 MySQL 并发语义待外部环境 |

## 工程与验证

- Python 全量测试：**361 passed, 5 skipped**，覆盖率 **85.63%**；新增节点都有定向测试、错误分支测试和回归测试。
- Ruff、Mypy、`compileall`、`git diff --check`、Node Wiki 测试、Vitest、TypeScript 检查和 Vite 构建均纳入门禁。
- MySQL 集成测试在没有本机隔离服务时跳过，由 GitHub Actions MySQL 8.4 service 执行真实验收。
- Provider live 测试只在 `WALIAPI_PROVIDER_LIVE_URL` 与 `WALIAPI_PROVIDER_LIVE_TOKEN` 同时提供时执行，测试数据和日志不记录凭据。
- 浏览器 smoke test 只在设置 `WALIAPI_BROWSER_URL` 且安装 Playwright 浏览器时执行，否则明确跳过。

## 外部验收清单

1. MySQL：首次/重复迁移、checksum mismatch、并发 GET_LOCK、事务回滚、行锁、Wiki/KB/Software/Provider/MCP 级联清理和配额并发扣减。
2. Provider：真实 OAuth 登录、Token 刷新/轮换、退出、配额、模型同步、失败冷却与恢复、厂商协议转换。
3. Browser：移动端登录和权限、页面编辑、来源摄入、附件、图谱、问答引用、Markdown 安全预览、长页面滚动、备份恢复一致性。

这些项目是环境验收项，代码没有将它们标记为已通过。

## 第二阶段交叉更新（2026-11-02）

后续生产就绪节点已在 `docs/part2-progress.md` 维护。当前增量包括 React 管理流程、持久化管理员会话与审计、Provider 密钥轮换、本机配置 CLI、受管 loopback 服务、MCP stdio bridge、Docker 多阶段构建和可选浏览器/长文档基准。最新自动化门禁为 513 passed / 13 skipped、88.34% 覆盖率；MySQL、真实 Provider、浏览器、Docker 和 OTLP 收集器仍按环境矩阵单列。
