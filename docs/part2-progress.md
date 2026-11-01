# 第二阶段：生产可用性与账号运营

基线：`5bdad3f`，分支：`codex/part2-production-readiness`。仅提交本地 Git。

## 基线复测（2026-11-02）

Windows / Python 3.12.10 / Node 24.21.0 / npm 11.19.0。
Python 361 passed、5 skipped，覆盖率 85.63%；Ruff、Mypy、compileall、Node 4 项、
Vitest 11 项、TypeScript 和 Vite 构建通过。完整覆盖数据在本机
`data/part2-baseline-coverage.json`，不提交运行产物。

无隔离 MySQL、真实 Provider 测试账号及浏览器部署验收环境；现有跳过保留。
未发现可用 DevBugKB 工具或本地案例库，当前无命中案例 ID；缺陷通过定向回归验证。

## 节点

| 节点 | 交付内容 | 状态 |
|---|---|---|
| N0 | 可复现基线、固定前端版本、质量门禁 | 完成 |
| N1 | 账号检索、分组标签、批量启停、归档恢复和管理台 | 待实施 |
| N2 | 持久化 OAuth、一次性 state、刷新租约及 Token 版本 | 待实施 |
| N3 | 配额/模型快照、同步任务、重试和恢复 | 待实施 |
| N4 | 路由组、配额均衡、预演和并发控制 | 待实施 |
| N5 | 用量账本、真实超额结算、版本化价格和费用 | 待实施 |
| N6 | 运营统计、时间窗口、下钻和站内告警 | 待实施 |
| N7 | React 导航、渠道/API Key/日志操作流程 | 待实施 |
| N8 | 可撤销会话、审计、轮换和运行诊断 | 待实施 |
| N9 | 本机客户端配置和受管服务 CLI | 待实施 |
| N10 | 浏览器全链路、压测、容器和升级验收 | 待实施 |
| N11 | 支持边界、部署恢复文档和最终验收记录 | 待实施 |

## 已确认能力边界

- 六个 Provider 名称共用配置式 OAuth adapter，尚非六家独立厂商接入。
- OAuth state 位于内存；配额/模型缺少持久化快照和后台同步。
- 客户端配置目前只写项目 `data/client-config` 目录。
- 浏览器测试只打开 Wiki 页，不能替代登录与业务全流程。
- 所谓语义缓存目前是请求哈希精确缓存；本轮不承诺向量语义匹配。

## 每节点固定门禁

使用项目虚拟环境执行 `python scripts/quality_gate.py`。
脚本顺序检查完整后端测试、覆盖率、Ruff、Mypy、compileall、Node 回归、
前端测试/类型检查/构建和 Git diff。任何失败会阻止后续提交。
全局覆盖率至少 85.63%，已记录的关键模块不得下降。

每节点补正常/错误/权限/并发回归，更新本文件，再提交。真实环境验收单列。
MySQL DDL 不承诺事务回滚；迁移必须可恢复，既有 checksum 不可修改。

## 提交记录

通过 `git log --oneline codex/part1-platform-completion..HEAD` 查询逐节点提交。
具体测试结果和环境限制在节点实施时追加。
