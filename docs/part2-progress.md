# 第二阶段：生产可用性与账号运营

基线：`5bdad3f`，分支：`codex/part2-production-readiness`。仅提交本地 Git。

## 审计修复最新状态（2026-11-02）

后续以 `fcc1ae0` 为审计基线的 16 项问题已修复并补充回归：612 passed / 14 skipped，
覆盖率 89.04%，全部关键模块维持或提高基线；Node 4 项、Vitest 36 项及静态/构建门禁通过。
历史节点与结果保留。最新逐项验收、DevBugKB 案例、发布恢复边界和提交记录见
[`审计修复与验收记录`](code-review/REVIEW_FIX_VERIFICATION.md)。

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
| N1 | 账号检索、分组标签、批量启停、归档恢复和管理台 | 自动化完成；MySQL 待环境验收 |
| N2 | 持久化 OAuth、一次性 state、刷新租约及 Token 版本 | 自动化完成；真实 Provider/MySQL 待验收 |
| N3 | 配额/模型快照、同步任务、重试和恢复 | 自动化完成；MySQL/真实 Provider 待验收 |
| N4 | 路由组、配额均衡、预演和并发控制 | 自动化完成；MySQL 并发语义待验收 |
| N5 | 用量账本、真实超额结算、版本化价格和费用 | 自动化完成；MySQL 并发写入待验收 |
| N6 | 运营统计、时间窗口、下钻和站内告警 | 自动化完成；MySQL/浏览器待验收 |
| N7 | React 导航、渠道/API Key/日志操作流程 | 自动化完成；真实浏览器全流程在 N10 验收 |
| N8 | 可撤销会话、审计、轮换和运行诊断 | 自动化完成；MySQL/真实 OTLP 收集器待验收 |
| N9 | 本机客户端配置和受管服务 CLI | 自动化完成；真实客户端和容器验收待环境 |
| N10 | 浏览器全链路、压测、容器和升级验收 | 代码/可选测试完成；MySQL、浏览器、Docker 待环境 |
| N11 | 支持边界、部署恢复文档和最终验收记录 | 完成；外部环境项单列 |

## 已确认能力边界

- 六个 Provider 名称共用配置式 OAuth adapter，尚非六家独立厂商接入。
- OAuth state、配额/模型快照和同步任务已持久化；同步默认关闭，需管理员显式开启。
- 管理台旧的客户端配置接口仍只写项目 `data/client-config`；N9 本机 CLI 只有在用户显式指定临时或真实 home、完成预览和哈希确认后才写入目标客户端文件。
- 浏览器测试默认只跳过；配置部署 URL、管理员凭据和 Playwright 后会执行登录、Wiki 与渠道导航回归，仍不能替代完整真实 Provider 链路。
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

### N7

- React 使用 hash 导航、可复制页面地址、未知页返回、错误边界和会话过期登录；移动端保留完整导航文字与键盘焦点。
- 渠道支持编辑/草稿测试/复制/模型同步/单 Key 测试/多 Key 编辑/导入预览与确认/无密钥导出；编辑不回传遮罩或嵌套 Key。
- 访问密钥支持配额、过期、模型和渠道限制；普通编辑不修改实际配额用量。路由组编辑与无副作用预演、日志分页及重试/安全明细接入。
- 探测使用真实协议 adapter 与映射；Gemini/Ollama 模型同步使用各自格式；模型列表仅公开可用账号与公开映射名称，遵守渠道授权且不刷新 Token。
- JSON 布尔字段决定流式模式，防止其他 true 字段误触发；日志 DTO 保留执行和断流元数据。
- 后端 481 passed / 11 skipped，覆盖率 87.84%；Node 4、Vitest 32、Ruff/Mypy/compileall、类型检查与构建全部通过。
- 失败尝试：Gemini 探测未设置 upstream_model 被协议测试捕获；测试 mock 参数类型被 TypeScript 捕获，均修复后重跑完整门禁。
- DevBugKB 无可用案例源，未命中案例 ID；浏览器验收尚不能用组件测试替代。

### N8

- 026 迁移增加仅保存随机令牌哈希的会话和跨进程登录窗口；运行时拒绝旧 HMAC Cookie，升级后需重新登录。
- 登录在账号锁内校验并创建会话；会话绑定密码哈希，改密/停用立即拒绝旧会话；注销服务端撤销，提供主体限定的列表与撤销接口。
- 登录按来源每分钟最多五次（含成功），限流状态持久化；Cookie 写操作校验 Origin。反向代理不得信任客户端自行填写的转发 IP。
- 管理写操作在执行前记 start，完成/失败记 end；使用路由模板，不保存正文、查询串或动态路径参数。审计库不可用时不放行管理写操作；审计与各业务事务并非统一事务，崩溃可留下无 end 的 start。
- Provider 密钥支持当前写密钥及至多五个历史读密钥；重加密在账号锁内处理 Token 与 PKCE，坏密文导致整批回滚。轮换命令在 N9 接入。
- 设置页接入会话、改密、审计分页和诊断；指标仅公开有限类别且要求管理员认证。可选 OTLP SDK 已安装并用内存 exporter 验证脱敏，真实收集器未验收。
- 生命周期用 AsyncExitStack，在部分启动失败和单项停止异常时继续关闭资源；停止有时间上限，不能强制终止阻塞中的原生数据库线程。
- 新认证/会话仓储/轮换定向覆盖率 100%；后端 492 passed / 11 skipped、88.15%，Node 4、Vitest 33，全部静态检查与构建通过。
- 失败尝试：同秒会话测试依赖列表位置导致失败，改为独立 ID 判断；Mypy 发现认证实现分支类型推断问题，添加共同基类类型后重验。
- DevBugKB 无可用案例源，未命中案例 ID。

### N9

- `app.local_config` 支持 Codex TOML、Claude Code JSON、Gemini/Claude Desktop MCP 配置的检测、脱敏预览、统一差异、哈希乐观锁、原子写、备份和恢复。
- 拒绝路径穿越、符号链接/联接点、非普通文件、超过 2 MB 文件、带凭据或查询串的 URL；远程网关必须显式 HTTPS+allow-remote。凭据仅以环境变量引用出现。
- `app.local_service` 仅管理由自身写入随机 nonce、PID、启动时间、命令和工作目录均匹配的进程；固定 loopback、独立锁文件、日志权限、停止超时和异常回收。不会按 PID 猜测或终止其他进程。
- `scripts/waliapi_local.py` 提供显式 `config detect/preview/apply/restore`、`service start/status/stop`、MCP stdio bridge 和显式 `rotate-provider-keys --execute`；错误输出不包含输入正文或密钥。
- MCP bridge 限制 1 MiB 请求、2 MiB 响应，固定协议版本和 Token Header，支持 JSON/SSE、会话 ID和通知，错误统一脱敏。
- 本地配置、桥接、服务身份、竞争写入、备份篡改、CLI 参数和管理 API 定向测试 40 项，其中符号链接与浏览器/真实客户端环境按条件跳过；Ruff/Mypy 通过。
- 真实客户端未在用户目录写入，真实服务进程和 MCP Server 未启动验收；不得将临时 fixture 结果视为客户端已配置。

### N10

- Dockerfile 改为 Node 24 前端构建 + Python 3.12 运行时多阶段镜像；本机无 Docker，镜像构建待 CI/部署主机验收。
- Wiki 浏览器用例覆盖移动端 Wiki/渠道导航，提供带管理员凭据的登录、权限和页面回归入口；没有 URL、账号或 Playwright 浏览器时明确跳过。
- `scripts/platform_benchmark.py` 提供固定 5000 节点长文档 fixture、重复测量、P95 预算和 JSON 基线输出；本机 P95 约 0.65ms（仅解析基准，不代表上游问答延迟）。
- MySQL 8.4 集成、真实 Provider、浏览器全链路和容器构建仍依赖外部环境；CI service 配置是验收入口，未在本机虚报通过。
- 本节点定向测试 21 passed / 3 skipped；Docker 未安装，浏览器未配置，均保留环境限制记录。

### N11

- 文档统一区分“自动化完成”“代码完成、环境待验收”和“明确不支持”；没有把本机缺失的 MySQL、Docker、Provider 凭据或浏览器当作通过。
- 部署要求：Python 3.12、Node 24（仅镜像构建阶段）、MySQL 8.4；生产必须提供 `DB_PASSWORD`、`ADMIN_SESSION_SECRET`、`ADMIN_TOKEN`、`ADMIN_PASSWORD_HASH`/首次启动密码和 `PROVIDER_TOKEN_KEY`。
- 升级流程：先备份数据库与 `data/client-config`，执行 `python -m app.infrastructure.database.migrations validate` 和 `upgrade`，再启动服务；checksum 不一致必须停止升级，不能手工覆盖既有记录。
- 本机客户端操作必须先 `config preview`、人工检查脱敏 diff，再使用 `config apply --expected-sha256`；恢复必须使用备份 ID，文件发生外部修改时拒绝恢复。真实客户端配置、真实 Provider 账号和外部 MCP Server 不在本轮自动修改。
- 质量门禁最终结果：后端 **513 passed / 13 skipped，覆盖率 88.34%**；Ruff、Mypy、compileall、Node 4、前端 Vitest **33 项**、TypeScript、Vite 构建和 `git diff --check` 全部通过。
- 最终本地节点提交：`658e3f1`（N7）、`776ad18`（N8）、`5caf4e6`（N9）、`c51509d`（容器上下文）、`8f78f7f`（N10）；此前 N0–N6 提交保持独立可回溯。
- 外部待验收：MySQL 8.4 方言/并发/级联，真实 Provider OAuth 与专属协议，带凭据 Wiki 浏览器全流程，Docker 镜像构建和 OTLP 收集器端到端。
- 明确不支持：商业计费/SaaS 租户、原生桌面壳、自动安装第三方软件、自动修改用户真实客户端账号、向量语义匹配（当前缓存是请求哈希精确匹配）、未声明厂商专属 OAuth 保证。

### N1

- 新增独立 profile/event 表（020）；旧列表接口保持数组契约。
- 新增分页/字面量搜索、供应商/授权/启停/分组/标签过滤、稳定排序、批量部分失败返回。
- 归档与 Token 删除、状态和审计在同一事务内；恢复不恢复 Token，默认保持停用。
- 管理台接入筛选、批量、归档、记录、表单化连接参数；新增五项交互回归。
- 仓储新模块定向覆盖率 100%；新增隔离 MySQL 回归，本机因无服务跳过。
- 完整门禁：后端 367 passed / 6 skipped；覆盖率高于 85.63%；Node 4、Vitest 16，静态检查和构建通过。
- 失败尝试：门禁首次发现测试文件尾空行，修正后重跑；没有降低门槛或移除测试。
- DevBugKB 无可用案例源，未命中案例 ID。

### N2

- 021 迁移新增授权事务和 Token generation/refresh lease 表，state 哈希、PKCE 加密、十分钟过期。
- GET/POST 回调绑定主体和 Provider，单次消费；Token 更新、退出和归档使旧授权失效。
- 刷新在网络调用期间持有可过期租约，完成时校验 generation 和 owner；退出先清理本地 Token。
- 删除运行时授权码充当 Token 的回退；缺少端点、厂商不支持、授权失效分别报告明确错误。
- 六个标识的 `/capabilities` 明确为 configured_oauth、vendor_verified=false。
- 时间戳统一为 UTC；回调清除访问日志查询串；撤销失败日志不包含上游异常正文。
- 后端 393 passed / 7 skipped，覆盖率 86.37%；新增授权服务/仓储定向覆盖率至少 95%。
- Ruff、Mypy、compileall、Node 4、Vitest 16、TypeScript、Vite 构建和 diff 检查通过。
- MySQL 增加租约/版本竞争验收；本机缺少服务跳过。厂商 OAuth 仍需显式测试账号。

### N3

- 022 迁移新增快照、同步设置和有界任务队列；支持租约、重试、重启恢复和旧任务写入隔离。
- 配额按单位、货币、窗口分别保存；未知不表示无限，过期/旧授权的快照标为 stale。
- Token 和密钥字段在快照持久化前脱敏；失败保留上次成功值，错误模型响应拒绝覆盖。
- 管理台显示快照、任务和失败信息，支持手工排队、显式启用定时同步及间隔配置。
- 定向覆盖率：配额归一化与同步仓储 100%，worker 98%；前端增加四项真实交互回归。
- 全量门禁：后端 416 passed / 8 skipped，覆盖率 86.72%；Node 4、Vitest 20，静态检查和构建通过。
- 失败尝试：新增测试最初误用服务模型返回契约，修正断言；Ruff 要求类型错误使用 TypeError，已修正重验。
- 新增 MySQL 同步抢占、幂等、快照和级联清理验收；本机无服务，明确跳过。

### N4

- 023 迁移持久化路由策略、渠道/Key 冷却及容量租约；跨 worker 原子抢占，租约心跳失败取消请求。
- 支持显式路由组、Key/渠道/模型/上游 endpoint 过滤、重试预算和并发上限；默认保留优先级与权重策略。
- 配额策略使用每个窗口的比例，未知配额允许/拒绝可配置；过期、旧授权配额不作为有效余额。
- `/api/v1/routing/preview` 复用实际过滤逻辑；不占容量、不刷新 Token、不返回凭据。请求使用 `X-Route-Group`。
- 持久化熔断在冷却到期后只放行一次探测；旧并发请求成功不能覆盖新失败，客户端取消只释放容量。
- 修复多 Key HTTP 失败切换分支，Key 冷却跨 Gateway 实例生效；400 不惩罚账号，401/429/5xx/网络错误分别记录健康结果。
- 15 项新路由回归；策略模块 100%、仓储 SQLite 路径 98%。完整门禁 431 passed / 9 skipped，覆盖率 87.10%，其余门禁全部通过。
- MySQL 新增并发容量、upsert 和半开探测用例，因无服务保留跳过。DevBugKB 无可用案例源。

### N5

- 024 迁移新增只追加用量账本和价格版本；重复事件幂等，内容冲突明确拒绝，日志删除不影响账本。
- 每次上游尝试保存独立消耗，最终 outcome 不再重复汇总 Token；客户端 Trace ID 与内部执行 ID 分离。
- 价格使用 Decimal、货币和生效时间；旧记录不重新计价，无价格/无可拆分 usage 返回 unknown 而不是零。
- 费用是所配置的统一输入/输出 Token 单价估算，不承诺厂商缓存阶梯价、优惠或账单对账。
- 修复配额实际用量截断，允许真实债务超过上限并拒绝后续预占；取消/错误后已产生的消耗仍结算。
- 流式在 DONE、取消、网络错误时恰好记录一次尝试；原生 Anthropic usage 累积，日志缓冲有大小上限。
- 新账本、计量服务与解析定向覆盖率 100%；完整门禁 449 passed / 10 skipped，覆盖率 87.42%，全部静态/前端门禁通过。
- 失败尝试：异步测试 fixture 最初嵌套 asyncio.run，改为在线程中创建；闭包显式绑定并通过 Ruff/Mypy。
- MySQL 增加并发去重和 Decimal 价格回归，缺少服务跳过。DevBugKB 无可用案例源。

### N6

- 增加时间、时区、供应商、账号、模型、访问密钥、路由组、endpoint 统计和分页下钻。
- UTC 半开区间，支持 IANA 时区和夏令时重复小时；按所选日期/小时准确下钻。
- 请求数/失败率来自 outcome，用量/费用来自 attempt；Decimal 分币种汇总，保留未知和估算计数。
- 延迟 P50/P95/P99 和首 Token P95 使用真实观测；单查询最多 93 天、100000 事件和 2000 组，超预算明确拒绝。
- 025 迁移增加持久化站内告警、规则、确认/恢复审计和跨 worker 去重；规则显式创建，后台每 30 秒评估。
- 管理台支持筛选、明细分页、告警确认和规则启停；新增三项前端交互测试。
- 17 项后端定向回归，分析仓储 100%、告警仓储 98%、worker/service 96%；全量 466 passed / 11 skipped，覆盖率 87.71%。
- Ruff/Mypy/compileall、Node 4、Vitest 23、TypeScript 和构建通过；新增 MySQL 告警并发回归，缺环境跳过。
- 失败尝试：前端 fetch mock 参数类型与实际调用不符，被 TypeScript 拦截后修正。
- MySQL 幂等冲突读取改为锁定读取，避免 REPEATABLE READ 的旧快照误报冲突；真实语义仍由隔离环境验收。
