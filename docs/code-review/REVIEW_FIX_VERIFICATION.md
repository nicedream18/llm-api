# 审计修复与验收记录

日期：2026-11-02。分支：`codex/part2-production-readiness`。
审计基线：`fcc1ae07543ba21c996cb587ce14e565e46c0bd2`。

本次落实原审计的 16 项代码修复，补充权限、协议、事务失败注入、线程调度和 React 事件回归。
原始 `REVIEW_REPORT.md`、`REVIEW_SUMMARY.md`、`REVIEW_FIX_PLAN.md` 保留审计时的内容；其中“未修改业务代码”描述的是审计轮次，并非本次修复状态。
三份原报告入库时仅清理了 Git 检查指出的行尾/文件末尾空白，并验证正文词序没有变化。

## DevBugKB 对照

修复前已检索 `nicedream18/DevBugKB`。`BUG-20261102-001` 至 `BUG-20261102-016`
与 `REVIEW-001` 至 `REVIEW-016` 一一对应，原记录状态为 unresolved，并非可直接复用的 verified 方案。
这些案例已在该仓库的 `33ae5a60cf5cf490e720e64b4f69426c9cbb8d29` 中登记，无需重复新建。
本次逐项结合当前代码实施并验证，验证结果记录在本文件；未修改 DevBugKB 的远端状态。

## 逐项交付

| 审计 / 案例尾号 | 修复内容 | 自动化证据与验收边界 |
|---|---|---|
| 001 | 通用与命名 MCP 软件工具同时检查 `mcp_tool execute` 和具体 `software execute`；动态工具列表按资源权限过滤 | `test_review_policy.py::test_both_mcp_names_enforce_resource_acl`，覆盖拒绝与授权后的调用；Software 既有审批、禁用和审计回归随全量门禁通过 |
| 002 | HTTP/MCP 将 AuthContext 传入 KB；RAG、Embedding、研究后续轮次统一进入 Proxy 的模型、渠道、配额与用量入口；调用上下文通过 ContextVar 隔离 | `test_embedding_denial_propagates_without_keyword_fallback`、`test_kb_chat_uses_gateway_policy_and_quota`、`test_research_followup_budget_and_context_reset`、`test_embedding_scoped_call_preserves_endpoint_and_counts_usage`；策略拒绝不会被关键词降级吞掉 |
| 003 | 非流式响应的脱敏结果应用到返回值、原始响应字节与日志；策略 block 不被 fail-open 绕过；流式响应扫描组合显式拒绝 | `test_response_redaction_reaches_client_and_log`、`test_response_block_cannot_be_bypassed_by_fail_open`、`test_response_policy_rejects_stream_before_dispatch`；HTTP 在上游调用前返回 422，未实现跨片段流式响应扫描 |
| 004 | OpenAI 流到 Responses/Anthropic 保留文本、多个并行工具的索引、ID、名称、参数片段及完成事件；修复 Gemini SSE 分隔与文本重复累积 | `test_review_protocols.py::test_interleaved_text_and_parallel_fragmented_tools`、`test_gemini_text_is_emitted_and_assembled_once`；真实 Provider/客户端兼容性仍待外部验收 |
| 005 | Anthropic 非流式 tool_use 与 Chat tool_calls 双向保留；请求侧支持工具定义、选择、调用结果与停止序列 | `test_anthropic_tool_use_normalizes_and_round_trips_without_losing_blocks`、`test_anthropic_request_preserves_tools_results_and_choice`；采用无网络契约数据，不代表厂商联调通过 |
| 006 | EOF 不再补造成功；异常/错误帧终止为失败；网关 attempt、Proxy 日志与用量结果一致；客户端断开记为 499 | `test_eof_requires_protocol_terminal_evidence`、`test_error_event_cannot_be_followed_by_success`、`test_truncated_gateway_attempt_and_proxy_log_are_failures`、`test_client_disconnect_agrees_in_log_and_usage_and_retains_consumption`，以及既有 SSE/超时回归 |
| 007 | Embedding 在事务外完成；同一事务替换文档分块、更新文档、KB 统计与任务终态，失败保留上一版本 | `test_review_recovery.py::test_publish_rollback_and_retry_are_atomic`，在分块插入、文档更新、KB 更新、任务更新及 COMMIT 五个边界注入失败后重试；SQLite 实事务已通过，MySQL 待验收 |
| 008 | owner + attempt_count 代次 + 有效租约校验完成、失败、进度及续租；线程协作取消；修正 ORM Session 的 MySQL 方言识别以启用 FOR UPDATE | `test_lease_transfer_fences_every_late_write`、`test_cancelled_or_mismatched_execution_cannot_replace_prior_version`、`test_worker_cancellation_stops_late_thread_publication`、`test_row_locks_resolve_the_real_orm_session_dialect`；新增 MySQL publication 回归，本机明确跳过 |
| 009 | 结算/释放前持久化 intent；重启重放、终态幂等确认、冲突保留；unknown 消耗保留预占并告警；恢复 worker 纳入应用生命周期 | `test_settlement_failure_survives_restart_and_replay_is_idempotent`、`test_unknown_consumption_is_retained_and_conflicts_are_visible`、原子写失败/容量/坏记录测试，以及真实 SQLite QuotaRepository 的故障后重启恢复；MySQL 并发仍待验收 |
| 010 | MCP router 仅校验并传递原始 arguments，服务只规范化一次 | `test_http_dynamic_arguments_are_normalized_once`，断言连接器接收原始嵌套业务参数 |
| 011 | 活动请求以主体类型、主体 ID、session 和 RPC ID 隔离；拒绝重复 ID；取消后保留执行登记直到同步连接器结束，移除未知请求取消墓碑 | `test_cancel_is_bound_to_principal_and_active_request`、`test_cancellation_retains_inflight_id_until_connector_finishes`、`test_tool_execution_capacity_is_bounded`；取消响应明确说明底层执行可能仍在进行 |
| 012 | API Key 数据库鉴权、流式渠道预检、扫描、配额结算和日志写入放入受限线程池 | `test_slow_authentication_does_not_block_event_loop`、`test_stream_database_work_leaves_event_loop_responsive`、`test_authentication_thread_pool_waiting_is_bounded`；本机验证事件循环仍可调度，未宣称 Linux 生产混合负载验收 |
| 013 | 索引文件原子保存节点到 chunk UUID 的映射与内容/数据集摘要；行重排不串文档；数据增删改、损坏映射和旧索引安全拒绝 | `test_stable_index_mapping_rejects_stale_content_and_legacy_indexes`、`test_malformed_index_identity_is_rejected`；旧索引需要显式重建 |
| 014 | 同代次已知模型集合过期后仍限制路由，保持空集合拒绝和显式映射语义 | `test_provider_sync.py` 的模型快照回归，覆盖 0 / 16 / 360 / 720 分钟、空集合和显式映射；新鲜度由同步状态单独报告 |
| 015 | 协议转换前校验 JSON 顶层对象及 model 类型；流式在发送 SSE 响应头前校验 model | `test_non_object_json_and_model_types_return_400`、`test_invalid_stream_model_is_rejected_before_sse_headers`；非法请求无配额预占或上游调用 |
| 016 | React 在同步事件阶段保存 input、file、目标 KB；成功后清空输入并刷新，刷新失败单独反馈 | `frontend/src/KnowledgeUpload.test.tsx` 的 3 项组件测试：真实 change 事件、异步成功、同文件重选与切换 KB、上传失败与刷新失败；部署浏览器待验收 |

## 最终质量门禁

执行环境：Windows、Python 3.12.10，项目 `.venv`。

```powershell
.venv\Scripts\python.exe scripts\quality_gate.py
```

| 检查 | 结果 |
|---|---|
| pytest 全量 + coverage | 612 passed，14 skipped；89.04% |
| 覆盖率基线 | 全局高于 85.6299%；全部关键模块未下降 |
| Ruff（app/tests/scripts） | 通过 |
| Mypy | 115 个源文件通过；既有无注解函数体不完全检查的提示仍存在 |
| compileall（app/tests/scripts） | 通过 |
| Node Wiki 回归 | 4 passed |
| Vitest | 9 个文件，36 passed |
| TypeScript / Vite build | 通过；同步提交 React 构建产物 |
| git diff --check | 通过 |

关键模块覆盖率：auth 95.42%、provider_service 86.13%、dispatcher 94.74%、
gateway 87.21%、provider_adapters 81.88%、streaming 94.59%、quota_repo 100%。
测试保留一条依赖 Starlette/AnyIO 的弃用警告，没有将警告隐藏或计为业务缺陷。

14 项跳过包括：MySQL 隔离实例 10 项、真实 Provider 凭据 1 项、部署浏览器 2 项、
Windows 创建符号链接权限 1 项。OTel 内存导出和官方 MCP SDK 互操作回归已执行，未计入跳过。

## 发布、恢复与数据核对

1. 升级前停止所有旧 KB Worker，再启动新版本，避免旧执行仍使用无 fencing 的写入路径。本次没有操作用户生产任务或清洗历史分块。
2. 本次复用已有任务 attempt_count 作为执行代次，没有新增数据库迁移。MySQL 8.4 的真实锁、并发及事务语义需运行 opt-in 集成套件；CI 已配置隔离 MySQL service，本次未触发或声称远端 CI 通过。
3. 设置 `QUOTA_RECOVERY_DIR` 到持久化、限制访问的存储；默认 `data/quota-recovery`。多进程/容器部署应保留并共享该目录，恢复依赖同一数据库的终态和行锁。临时文件 flush/fsync 后原子替换，目录/磁盘持久性仍取决于部署文件系统。
4. 已知 settle/release intent 可自动重放；`unknown`、冲突和损坏记录只告警保留。崩溃发生在用量未知阶段，或磁盘与数据库同时不可写时，需要结合 quota ledger、usage ledger 和上游证据人工对账，不得批量退还未知消耗。
5. 未包含新身份映射的 HNSW 索引不参与返回结果，需要重建；本次不自动删除旧索引或用户数据。回退应用前应停止 Worker，并使用备份核对索引与任务、配额终态，不能靠回退代码反向抹除已提交用量。
6. 启用 `scan_response` 时暂不接受流式请求；普通请求完成扫描后输出脱敏结果。需要流式响应扫描的场景仍属于明确未支持能力，不应以关闭安全策略作为此次修复验收方式。
7. MCP 的活动执行去重和取消登记为进程内状态；会话/事件持久化已有独立实现。本次修复跨主体取消隔离，没有承诺跨进程强制中止同步工具或外部副作用。
8. MySQL、真实 Provider、部署浏览器、Docker 冷启动/停机/升级、Linux 同步/流式混合负载与真实 OTLP 收集器，均未在本机验收；契约测试和组件测试不能代替这些环境结果。

## 修复过程中的失败与修正

- 参数规范化测试最初暴露测试替身/仓储参数形状不一致；按真实接口调整测试，不恢复生产权限旁路。
- Gemini 新 SSE 回归最初失败，进一步定位到空行未触发 decoder flush；修复后 SSE/NDJSON 两种格式均通过，文本只累积一次。
- 真实 quota spool 回归最初复用了已超额的测试 Key，预占被正确拒绝；改为独立 Key 后验证数据库故障恢复与最终仅结算一次。
- 全量测试、静态检查与构建首次通过后，Git 差异检查发现两处行尾空格；仅清理对应位置，再执行最终检查。没有降低覆盖率基线或删去失败场景。
- 暂存原审计报告时额外发现 Markdown 硬换行空格和末尾空行；清理这些空白并验证正文一致后重新检查，未改写原审计结论或证据。

本记录的状态是“16 项代码修复及本地自动化验收完成；所列环境验收待执行”，不等同于整个平台已经完成生产验收。

## 本地 Git 提交

| 提交 | 内容 |
|---|---|
| `4f90b07` | `fix: enforce audit security protocol and recovery contracts`；后端 15 项审计修复及定向/错误分支回归 |
| `c5e0d8a` | `fix: preserve knowledge upload targets across async events`；REVIEW-016、3 项组件回归及构建产物 |

最终质量门禁进程退出码为 0；提交前再次通过已暂存差异的 `git diff --cached --check`。
本文件及原始审计报告随独立验收文档提交保存；本次没有执行远端 push。
