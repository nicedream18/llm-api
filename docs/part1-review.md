# 第一部分实现检查报告

检查日期：2026-11-01。该报告更正先前“Wiki、Software、Auth Provider 尚未建设”的过时结论。检查基于当前本地代码、自动化测试和前端源码，不代表对参考仓库最新提交或线上服务的复核。

## 功能状态

| 模块 | 当前已实现 | 尚未达到完整平台能力的部分 |
|---|---|---|
| Wiki | 项目/页面编辑、来源/附件、搜索标签、图谱、问答、备份恢复、资源授权、REST/MCP；管理台支持 Markdown 编辑、安全预览和问答来源 | 真实浏览器移动布局与长文档交互验收待做 |
| MCP | MCP 2025-06-18 JSON-RPC HTTP、TTL 会话和主体绑定、KB/Wiki/Software 工具、权限校验、审计；管理台工具调试、审计和权限配置；会话 SSE 通知与取消 | 不支持断线事件重放或跨进程会话队列 |
| Software | CLI/HTTP/MCP connector、OpenAPI 3.0/3.1 JSON 预览与选择导入、参数映射、schema 校验、启停、服务端审批队列、调用调试、本机工具白名单扫描、dry-run 安装计划、脱敏调用记录、MCP 聚合 | 扫描范围固定；真实安装需显式环境变量；不支持外部 `$ref`、header/cookie 参数、表单请求体或认证密钥配置 UI |
| Auth Provider | 账户、PKCE OAuth 流程、Token 加密/刷新/退出、配额和模型端点、HTTP adapter；管理台生命周期操作；显式配置 `gateway_url`/`base_url` 的 active 账号可进入网关候选池 | 厂商专属端点未做真实联调；未实现厂商专属协议、自动 Token 轮换和账号级故障统计 |
| 平台 | Prompt、语义缓存、客户端配置预览/写入/删除 | 客户端支持范围和真实安装探测仍有限，界面缺少配置差异预览和更多目标 |
| 网关与安全 | API Key/管理员认证、权限、配额预占结算、重试、响应协议转换、安全扫描与日志 | MySQL 并发语义和真实上游链路仍须隔离环境验收；流中断后不能安全地从上游继续重试 |

旧报告的 3 个 MCP 工具、未实现 Wiki/Software/Provider 及未落库审计说法已不适用于当前代码。

## 工程与验证

- 最新完整 Python 测试：330 passed，2 skipped，覆盖率 85.81%；GitHub Actions 全量测试命令执行 85% 门槛。
- 跳过项为隔离 MySQL 集成测试，因为本机未提供测试 MySQL 服务；SQLite 测试不能替代 MySQL 的锁、事务和迁移验证。
- React 前端 10 项 Vitest 通过，TypeScript 检查和 Vite 生产构建通过；Node 静态 Wiki 渲染测试 3 项通过。
- 全仓 Ruff、Mypy（81 个源文件）、compileall、diff 检查、Node/Vitest 测试和前端生产构建均已通过。
- 仓储行为测试在临时 SQLite 文件/数据库上执行，不使用应用配置的数据库。
- 全局仍有 Starlette/AnyIO 弃用警告；不是本次断言失败。

## 需要后续按风险推进

1. 使用隔离 MySQL 实例验证全量 migration upgrade 重复执行、checksum 拒绝、事务/锁和级联删除。
2. 为 Auth Provider 接入厂商真实 API，并先明确 token 轮换、失败降级与账号生命周期，再加账号路由。
3. 扩展 Software 扫描器覆盖范围、实例凭据配置和更细粒度的审批策略。
4. 对 Wiki 管理台执行真实浏览器移动端工作流验收，并继续补长文档编辑性能测试。
5. 继续补 middleware、migration runner、Gateway、streaming、Importer 和 repository 低覆盖分支；覆盖率全局 85% 并不意味着关键模块覆盖充分。

## 最近发现并修复

- 日志追踪 ID 搜索误查 request log 主键，改为按 `trace_id` 筛选并加入 SQLite 回归。
- 安全规则仓储原本依赖 `UTC_TIMESTAMP()`，改用统一时间参数，便于在 SQLite 验证仓储行为。
- 知识库统计查询没有用知识库表过滤，导致不存在的 ID 也返回全零统计；现按实际 KB 行过滤并回归验证。
- KB 任务失败重试和配额结算/释放仓储锁只在 MySQL 方言追加 `FOR UPDATE`，保持 MySQL 行锁，同时允许 SQLite 运行相同行为测试。
