# 本地 Git 代码审查报告

## 1. 审查结论

**整体质量：64 / 100；已确认问题16项：P0=0、P1=10、P2=6、P3=0。**

项目具备分层结构、持久化授权/会话、配额与用量账本、Provider 同步和较完整的自动化门禁；现有测试和静态检查通过。但调用入口之间的授权与计费策略不一致，工具调用协议存在静默数据丢失，知识库任务的租约和提交边界缺少可靠约束。涉及多调用者、计费、工具执行的生产部署应先解决本报告的 P1 项。

未发现达到本次 P0 定义且证据充分的问题。这不构成对未覆盖部署环境或所有安全漏洞的保证。问题按独立根因计数，没有把个人风格偏好、依赖版本年代或尚未复现的疑点记为 Bug。

### 1.1 评分依据

| 维度 | 得分 | 依据 |
| --- | ---: | --- |
| 正确性与协议契约 | 20/30 | 常规请求覆盖较好；工具流、工具响应、EOF、动态 MCP 参数等实际失败路径缺测 |
| 安全与权限 | 13/25 | 有统一鉴权、资源 grants、会话撤销与密钥加密；不同入口仍可绕过资源/模型/配额策略，响应脱敏失效 |
| 数据一致性与可靠性 | 12/20 | 有任务租约和持久账本；缺少执行 fencing、幂等发布和失败结算恢复 |
| 架构与可维护性 | 11/15 | API/服务/领域/仓储有分层；横切策略分散，协议转换重复，异步/同步边界不统一 |
| 测试与工程交付 | 8/10 | 513个后端测试、33个前端测试通过，行覆盖率88.34%；真实 MySQL/Provider/浏览器/容器验收仍有缺口 |
| **合计** | **64/100** | 人工风险评价，不是由覆盖率直接换算的质量认证 |

## 2. 版本、分支和基准

| 项目 | 本次审查值 |
| --- | --- |
| 审查日期 | 2026-11-02，Asia/Shanghai |
| 仓库根目录 | C:/Users/nicedream/Desktop/dong/llm-api |
| 项目声明版本 | FastAPI: WaLiAPI-Python 1.0.0；frontend package: 0.1.0 |
| 当前分支 | codex/part2-production-readiness |
| 当前 HEAD | fcc1ae07543ba21c996cb587ce14e565e46c0bd2 |
| HEAD 提交时间 | 2026-11-02T03:23:44+08:00 |
| **主要审查基准** | 本地 codex/part1-platform-completion，5bdad3ffd5b5ca334faac001e3f8579271646cf4 |
| 本地阶段分支差异 | 14 commits；128 files changed，+6375/-614 |
| 本地保存的默认远程 HEAD 指针 | refs/remotes/origin/codex/part1-platform-completion |
| 该指针/与 HEAD 的 merge-base | e2581cad42ae49586fe5ad6f652130e12141f0e9 |
| 该历史指针至 HEAD | 70 commits；203 files changed，+14993/-903 |
| 跟踪文件规模 | 298个跟踪文件，其中193个 Python 文件；app 中112个 Python 文件接受 Mypy/覆盖率检查 |

用户明确要求只审查本地 Git。没有 fetch、pull、访问托管平台或使用远程服务进行审查。默认分支指针只是本地旧的 Git 元数据，不能代表远程最新状态。docs/part2-progress.md 同样将5bdad3f记为第二阶段基线，因此以本地阶段分支为主要 diff；同时检查当前版本核心代码，补审早期历史遗留问题。

**缺陷归属：** REVIEW-014 为本阶段模型同步新增路径；REVIEW-016 为本阶段新增 React App 页面路径。其余14项在基线中已有相关有缺陷实现，属于修改上下游或未修改核心模块的补充发现；尤其 REVIEW-009 的结算异常吞掉问题并非本阶段首次引入。不能将16项全部解释为这14个提交新引入的回归。

本次只新增 docs/code-review/ 下的三份报告，不修改业务、测试、依赖或 Git 分支；不提交、推送或合并。测试及复现使用新建临时目录、内存 SQLite 和模拟传输，未清理用户原有文件。报告写入前 git status --porcelain=v1 --untracked-files=all 输出为空。

## 3. 技术栈、模块和业务链路

### 3.1 技术栈

- 后端：Python 3.12.10、FastAPI 0.115.6、Uvicorn 0.34.0、Pydantic 2.10.4。
- 数据：SQLAlchemy 2.0.36 同步 engine + 原生参数化 SQL、PyMySQL 1.1.1、MySQL；迁移001–026。测试大量使用 SQLite。
- 外部通信：httpx 0.28.1；模型代理同时支持同步入口与异步 SSE。
- 安全：Argon2 密码、数据库持久会话、资源 grants、Fernet/MultiFernet Token 加密、OAuth state/刷新租约。
- 前端：React 19.3.1、TypeScript 7.0.2、Vite 8.3.5、Vitest 5.0.5、jsdom 30.1.3。
- 工程：pytest、pytest-cov、Ruff、Mypy、Node 原生测试；GitHub Actions 的 MySQL 服务；Docker 多阶段构建。
- Agent/知识库：MCP JSON-RPC、工具/软件连接器、持久任务 Worker、导入与 embedding、向量/HNSW/关键词检索、RAG 与 Wiki。

### 3.2 模块职责与依赖

| 目录/模块 | 职责与主要依赖 |
| --- | --- |
| app/main.py、config.py、container.py | 生命周期、环境配置、迁移与 Worker 启停，手工组装单例依赖 |
| app/api/controllers、middleware/auth.py、resource_dependencies.py | HTTP/MCP 协议、身份与入口级资源校验 |
| application/services/misc_services.py | 代理授权、扫描、配额、日志、MCP 分发；多个职责集中于一个文件 |
| domain/gateway.py、dispatcher.py、routing.py | 渠道候选、回退、容量/配额策略与实际 HTTP 调用 |
| domain/streaming.py、*converter.py、infrastructure/adapters | 上下游协议归一化与 SSE 转换 |
| provider_*、token_keyring.py | 账号、OAuth/刷新、快照同步、令牌生命周期 |
| usage_service.py、domain/usage.py、*_repo.py | 用量和配额账本、定价、统计、告警 |
| kb_service.py、kb_worker.py、knowledge.py、index_service.py | 文档导入、任务恢复、embedding、检索与 RAG |
| wiki_service.py、software_service.py、MCP | Wiki 检索/问答、受控连接器执行和审批 |
| local_config.py、local_service.py、local_bridge.py | 本机客户端配置预览/备份/恢复、受管进程与桥接 API |
| frontend/src | 管理员 React 工作流；app/static/admin 为构建产物 |

主要调用链：

1. 模型请求 → AuthMiddleware → ProxyService（模型授权/扫描/配额）→ Gateway → Dispatcher/路由 → ChannelAdapter → httpx → 协议转换 → 用量/日志。
2. KB 问答 → KB 资源 read 检查 → KbService → RagService/Embedder → Gateway。这里绕过链路1的关键策略，见 REVIEW-002。
3. MCP → 会话/JSON-RPC → validate_arguments → McpService.call_tool → 资源授权 → KB/Wiki/Software。重复规范化和不同名称入口的授权差异见 REVIEW-001、010。
4. KB 上传 → 持久任务 → Worker claim/renew → 导入/embedding → 分块/文档/KB/任务状态分别写入，见 REVIEW-007、008。
5. Provider 操作 → 加密凭据/OAuth → 同步任务 → 配额/模型快照 → 路由候选；有效期和同步周期不一致见 REVIEW-014。

## 4. 实际审查范围与限制

### 4.1 顺序与覆盖方法

先读取 README、AGENTS.md、依赖/配置/部署/门禁、Git 状态和阶段历史，再按“鉴权与计费 → 网关与协议 → Provider/路由 → KB 任务与索引 → MCP/软件/Wiki → 管理台与本机工具”追踪。查看128文件差异清单及高风险文件的 diff、当前实现和关联仓储/测试；没有声称逐行审查128个差异文件的全部内容。

| 深度 | 已审查文件/范围 |
| --- | --- |
| 入口与配置 | README、AGENTS.md、requirements.txt/observability、frontend/package.json/lock相关配置、pytest.ini、config.py、main.py、container.py、Dockerfile、.dockerignore、quality.yml、quality_gate.py、quality-baseline.json、part2-progress 的基线/边界 |
| 鉴权与资源 | auth middleware、resource_dependencies；auth/access/admin 服务及 DurableAdminAuth；admin_repo、admin_session_repo、access_repo；auth/access/administration API、授权与会话测试 |
| 网关主链深审 | misc_services 中 ProxyService/McpService；gateway、dispatcher、routing、streaming、provider_quota、usage；channel_adapters 的 OpenAI/Anthropic 与模型 URL 路径；相关 proxy/routing/quota/stream/MCP 测试 |
| Provider/运营 | provider_service、provider_authorization、provider_sync_worker、provider_adapters；provider/auth/operations/sync/routing/quota/usage/analytics 仓储；provider/platform/operations/usage API 与服务；token_keyring、telemetry |
| KB 高风险深审 | kb_service 导入/问答/索引流程、kb_worker、kb_repo 任务与分块读写；knowledge 的拆分、embedding、检索、RAG；index_service 的构建和查询映射；importer 的 URL/路径保护和导入关键段 |
| Wiki/软件/本机 | wiki_service 的 ask、备份恢复相关段、wiki API 的入口；software_service 的 invoke/审批/参数/CLI/HTTP/OpenAPI路径；platform_service、local_config、local_service、local_bridge；相应测试 |
| 前端 | App、api、adminHooks、ProviderManager/SyncPanel、RoutingManager、AdministrationPanel、ApiKeyManager；ChannelManager 关键请求/状态路径、OperationsPage；相关测试与构建配置 |
| 全量自动检查 | 跟踪的193个 Python 文件 AST 解析；app/tests/scripts Ruff；app 中112文件 Mypy；全后端 pytest 与覆盖率；8个前端测试文件、TypeScript、Vite临时构建、4项 Node 测试 |

### 4.2 未逐行审查/未实测部分

- Agent 会话与 agent_repo、全部 OpenAPI/Multipart 解析分支、所有 converter 的每个功能分支、完整 HNSW 算法实现，没有做穷举或形式证明。
- e2581ca到5bdad3f之间的56个早期提交没有逐个重新审查；仅结合当前核心实现与关联历史追查，未把70个提交都标为逐项覆盖。
- Wiki/MCP/旧版静态页面的全部 UI、日志/软件/Wiki仓储每条 SQL、所有迁移升级组合、local_cli 全部参数组合未逐行深审；仅追踪关联风险路径。
- 打包后的 app/static/admin/assets、node_modules、venv、用户 data 目录未逐文件审查；没有把依赖源码当项目业务代码审查。
- 没有连接 MySQL；未执行真实 InnoDB 锁、隔离级别、迁移中断恢复、多进程租约/刷新并发或真实数据量查询计划验收。SQLite 复现不替代 MySQL 行为证明。
- 没有真实 Provider/OAuth/配额/模型 HTTP 服务、OTLP 收集器、实际本机客户端安装目录或桌面进程的验收。Provider 名称共用配置式 adapter 的边界在项目文档中已有说明，本报告不将其误称为独立厂商协议已验证。
- 没有运行部署浏览器全流程、Docker build/run、Linux 环境或生产负载压力测试。jsdom 复现仅验证 React 事件生命周期。
- 没有进行联网 CVE/漏洞库审计、npm audit 或 pip-audit，不能宣称第三方依赖无漏洞；已做本地 pip check。
- 报告完成时未修改代码，因此没有任何“修复后测试通过”的结论。

## 5. 检查命令与实际结果

### 5.1 版本和静态检查

| 命令/检查 | 结果 |
| --- | --- |
| git status --porcelain=v1 --untracked-files=all；rev-parse / symbolic-ref / merge-base / log / diff | 本地版本与差异见第2节；没有访问远程 |
| .venv\Scripts\python.exe -B -m ruff check --no-cache app tests scripts | 退出0 |
| .venv\Scripts\python.exe -B -m mypy --cache-dir <新临时目录>/mypy --follow-imports=silent app | 112文件无错误；提示部分未注解函数体默认不检查 |
| 使用 ast.parse 读取 git ls-files "*.py" | 193文件解析成功；不生成 pyc |
| .venv\Scripts\python.exe -B -m pip check | No broken requirements found |
| git diff --check | 退出0；报告写入后再次核对 |

没有直接运行 scripts/quality_gate.py：它会生成 data 下的报告、compileall 的 pyc 和清空/重写 app/static/admin 构建目录。本次分别运行其关键检查，并将覆盖率、缓存和构建产物放到新临时目录；这不等于宣称原脚本整体执行成功。

### 5.2 后端隔离测试

使用已存在 venv，不安装或升级依赖。将应用数据库指向127.0.0.1:1并禁止真实服务 opt-in，防止读取用户配置后误连数据库；不启动 main 的生产生命周期。以下是执行命令的可重跑形式：

~~~powershell
$reviewTemp = Join-Path $env:TEMP ('llm-api-code-review-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $reviewTemp | Out-Null
$env:PYTHONDONTWRITEBYTECODE = '1'
$env:COVERAGE_FILE = Join-Path $reviewTemp '.coverage'
$env:APP_ENV = 'test'
$env:DB_HOST = '127.0.0.1'
$env:DB_PORT = '1'
$env:DB_NAME = 'review_no_external_db'
$env:DB_PASSWORD = 'review-local-only'
$env:DB_UNIX_SOCKET = ''
Get-ChildItem Env: | Where-Object {
    $_.Name -like 'WALIAPI_TEST_MYSQL*' -or
    $_.Name -like 'WALIAPI_PROVIDER_LIVE*' -or
    $_.Name -like 'WALIAPI_BROWSER*'
} | ForEach-Object { Remove-Item -LiteralPath ('Env:' + $_.Name) }
.venv\Scripts\python.exe -B -m pytest -p no:cacheprovider --basetemp (Join-Path $reviewTemp 'pytest') --cov=app --cov-report="json:$reviewTemp/coverage.json" -q -o faulthandler_timeout=30
~~~

仅移除测试子进程的 opt-in 环境变量，未修改 .env 或用户持久环境。

**结果：513 passed、13 skipped、1 warning，37.65秒。** Warning 为 Starlette TestClient 使用的 AnyIO BlockingPortal 别名弃用提示。跳过项涉及隔离 MySQL、真实 Provider、部署浏览器及可选运行依赖等，不能计作已通过的集成验收。

**行覆盖率：9807 / 11102 = 88.3354%（显示88.34%），1295行未覆盖、2行排除。没有采集分支覆盖率。** 全局高于85%门槛及85.6299%仓库基线；7个关键模块也全部达到基线：

| 关键模块 | 本次% | 基线% |
| --- | ---: | ---: |
| auth_service.py | 95.42 | 95.42 |
| provider_service.py | 85.90 | 78.46 |
| dispatcher.py | 94.74 | 94.74 |
| gateway.py | 86.57 | 82.41 |
| provider_adapters.py | 81.88 | 71.31 |
| streaming.py | 85.67 | 85.00 |
| quota_repo.py | 100.00 | 100.00 |

本次覆盖率文件：C:/Users/NICEDR~1/AppData/Local/Temp/llm-api-code-review-5a4400ef74f04e268ea2f2247cf4b48c/coverage.json。临时目录可能随系统清理消失，核心结果和复现源码因此也保留在本报告。

### 5.3 前端与构建

从 frontend 目录使用已安装本地入口，避免 npm 包管理操作；命令如下：

~~~powershell
node .\node_modules\typescript\bin\tsc --noEmit
node .\node_modules\vitest\vitest.mjs run --no-cache
node .\node_modules\vite\bin\vite.js build --outDir <新建临时目录>/build
~~~

- TypeScript：无错误。
- Vitest：**8文件、33测试全部通过**，约2.86秒。
- Vite：35模块，构建成功，约215ms；主 JS 312.77KB，gzip90.82KB。只写新临时目录，未运行会清空跟踪构建目录的默认 build。
- 仓库根运行 node --test tests/frontend/wiki.test.cjs tests/frontend/wiki.performance.test.cjs：**4/4通过**，约157ms。此单机文本渲染测试不等于服务负载测试。
- 本次构建目录：C:/Users/NICEDR~1/AppData/Local/Temp/llm-api-review-frontend-2e16515b36cb4c2c97d3700b9b8ba0da/build。

### 5.4 检查过程中的环境限制

初次在受限 Windows 沙箱运行 ASGI 测试时，asyncio Proactor 创建 socketpair 阻塞在 socket.accept；faulthandler 已定位。中止本次检查进程后，在允许本机回环套接字的执行环境重跑得到上述完整测试结果；没有将这一沙箱现象报告为应用死锁。npm 在沙箱中的挂起也未被当作项目缺陷；后续直接运行本地 Node 入口完成检查。

最初前端复现尝试调用 TypeScript 7 不再提供的 transpileModule 失败，随后改用项目实际 Vite transformWithOxc 成功复现；这属于审查脚本适配过程，不计入项目问题。

## 6. 优先处理的前10项

| 顺序 | 问题 | 选择依据 |
| ---: | --- | --- |
| 1 | REVIEW-001 通用软件 MCP 越权 | 资源执行边界失效 |
| 2 | REVIEW-002 KB 绕过模型/渠道/配额 | 多调用者成本与隔离边界失效 |
| 3 | REVIEW-003 响应脱敏/扫描失效 | 配置生效假象、秘密外泄 |
| 4 | REVIEW-008 Worker 缺少 fencing | 先约束执行权，阻止迟到写覆盖 |
| 5 | REVIEW-007 导入重试重复数据 | 在 fencing 基础上实现幂等原子发布 |
| 6 | REVIEW-009 配额结算无恢复 | 持久化失败核对，避免额度永久失真 |
| 7 | REVIEW-010 动态 MCP 参数重复规范化 | 标准 HTTP 工具功能不能正确执行 |
| 8 | REVIEW-004 流式工具信息丢失 | Agent/Responses/Anthropic 工具契约 |
| 9 | REVIEW-005 Anthropic tool_use 丢失 | 上游工具结果的另一条独立转换路径 |
| 10 | REVIEW-006 EOF 被当成功 | 保证协议完成、日志和用量一致 |

## 7. 问题明细

下述行号均对应审查 HEAD；后续修改后可能移动。“已复现”明确说明替身边界，不等于已连接生产环境验证。

### REVIEW-001 — 通用 MCP 软件工具入口绕过软件资源授权

- **优先级：** P1
- **文件位置：** app/application/services/misc_services.py:648；app/application/services/misc_services.py:681；app/application/services/software_service.py:282
- **问题类型：** 安全
- **变更归属：** 历史缺陷；MCP / 软件服务在本阶段的上下游补充审查中发现。
- **问题描述：** call_tool 只在名称以 software. 开头时检查 software 资源的 execute 权限；invoke_software_tool 接受任意 tool_id，却只检查 mcp_tool 权限。SoftwareService.invoke 负责可用性、参数与审批，未补做资源 ACL。list_tools 还会追加所有启用软件工具的名称和 schema。
- **触发条件：** 非管理员 API Key 已获 invoke_software_tool 的 MCP execute 授权，但未获目标 software execute 授权；目标工具启用，且无需逐次审批。
- **影响范围：** 调用者可以执行未获授权的软件连接器操作并取得结果；工具列表可能暴露其未授权的工具元数据。该路径仍受审批规则约束，不能据此声称绕过管理员审批。
- **证据：** 真实 AccessRepository/AccessService（内存 SQLite）+ McpService/SoftwareService，仅替换最终连接器。software_grant=false，命名入口被拒绝，通用入口返回 {private: returned}，connector_calls=1；未授权工具仍出现在 advertised 中。
- **验证状态：** 已复现：服务调用链、真实授权仓储；未执行真实外部连接器。
- **修复建议：** 在统一的规范化工具描述中提取目标 tool_id；命名与通用入口都验证 mcp_tool 和 software execute；枚举工具时使用同一资源策略。保持现有审批检查。
- **修复优先级：** 立即处理；在向非管理员开放软件 MCP 权限前完成。
- **复核入口：** 附录 A / mcp_resource_acl。

### REVIEW-002 — 知识库问答与深度研究绕过调用者模型、渠道和配额策略

- **优先级：** P1
- **文件位置：** app/api/controllers/routes.py:558；app/application/services/kb_service.py:211；app/domain/knowledge.py:561
- **问题类型：** 安全 / Bug
- **变更归属：** 历史缺陷；知识库核心模块补充审查。
- **问题描述：** HTTP 层只验证 KB read 资源授权；ask/deep_research 的服务签名不接收 AuthContext。RagService 直接构建缺少 principal_id、allowed_channels 的 ProxyRequestEntity，再调用 GatewayService.forward_sync，绕开 ProxyService 的 allowed_models 与配额预留/结算；Embedding 也直接调用网关。
- **触发条件：** 合法 API Key 拥有 KB read，但仅允许 cheap 模型和指定渠道、配额已耗尽；请求知识库 ask，指定 expensive 模型。
- **影响范围：** 已耗尽配额的 Key 仍能发起模型调用，并可能使用其未获授权的渠道；深度研究多轮放大成本，且统一用量归属和审计不完整。
- **证据：** 真实鉴权中间件、KB HTTP router、AccessService 与 RagService；只捕获最终网关调用。HTTP=200，requested_model=expensive，forwarded_channels=[]，forwarded_principal=null；Key quota_limit=quota_used=1。
- **验证状态：** 已复现：HTTP 至 RAG 的策略绕过；外部 LLM 由无网络替身捕获。
- **修复建议：** 贯穿 HTTP/MCP → KB → RAG/Embedding 传递 AuthContext；所有计费调用进入统一授权、配额与用量服务。对 deep_research 每轮独立结算并设置总预算。
- **修复优先级：** 立即处理；多租户或计费部署的发布阻断项。
- **复核入口：** 附录 A / kb_policy_bypass。

### REVIEW-003 — 响应脱敏结果被丢弃，流式响应完全跳过响应扫描

- **优先级：** P1
- **文件位置：** app/application/services/misc_services.py:296；app/application/services/misc_services.py:315；app/application/services/misc_services.py:371
- **问题类型：** 安全
- **变更归属：** 历史缺陷；本阶段改动了同一代理服务的账本、流式处理和日志路径。
- **问题描述：** 非流式响应调用 _scan，却只使用 blocked/findings，不把 sanitized_body 写回 proxy_response.body，随后原文发送客户端并进入响应日志。forward_stream_async 仅执行 request 扫描，未根据 scan_response 执行 response 扫描。
- **触发条件：** 启用扫描且 mode=redact、scan_response=true，规则命中上游响应中的秘密；或使用需要响应阻断/脱敏的流式接口。
- **影响范围：** 策略明确要求脱敏的秘密仍返回调用者，且可能存入日志；流式接口使响应侧策略整体失效。
- **证据：** 真实 SecurityScanner 自定义规则 sk-[A-Za-z0-9]{20,}；扫描结果 sanitized=true 且不含合成秘密，但 ProxyService 返回 HTTP200 且 downstream_contains_secret=true。流式路径缺失 response 扫描由完整方法静态证实。
- **验证状态：** 已复现：非流式脱敏丢失；静态证实：流式响应扫描缺失。使用合成秘密，无真实凭据。
- **修复建议：** 序列化与日志记录前应用响应 sanitized_body；流式扫描设计必须覆盖跨 chunk 匹配，可采用有界缓冲或明确拒绝无法执行的响应策略组合，避免只逐片正则扫描而留下跨片绕过。
- **修复优先级：** 立即处理；在宣称响应 DLP/脱敏有效之前修复。
- **复核入口：** 附录 A / response_redaction。

### REVIEW-004 — OpenAI 流转换为 Responses / Anthropic 时丢失工具调用

- **优先级：** P1
- **文件位置：** app/domain/streaming.py:314；app/domain/streaming.py:334
- **问题类型：** Bug
- **变更归属：** 历史缺陷；本阶段修改该文件的用量处理，但这两个转换函数的缺陷已存在于基线。
- **问题描述：** 两个转换函数仅处理 delta.content 和 finish_reason，忽略 delta.tool_calls。源流合法的函数名、call_id 和 JSON 参数没有对应目标事件；Anthropic 可能仅得到 tool_use 停止原因，Responses 则出现空输出的完成事件。
- **触发条件：** 通过 /v1/messages 或 /v1/responses 使用 OpenAI 上游，stream=true，模型决定调用工具。
- **影响范围：** Agent/Codex 等客户端不能执行模型要求的工具，工作流中断或误以为已完成；普通文本流测试无法覆盖。
- **证据：** 真实 StreamCodec 输入 call_1 / lookup / {} 的 tool_calls delta、finish_reason=tool_calls 和 [DONE]。两种目标协议的输出都不包含 lookup 或 call_1。
- **验证状态：** 已复现：完整转换器事件序列；未声称已用真实客户端或厂商服务验收。
- **修复建议：** 按 tool index 保存工具状态，保留 ID/函数名与增量参数，生成目标协议的工具项开始、参数增量及结束事件；覆盖多工具、碎片 JSON、文本混合的回归矩阵。
- **修复优先级：** 尽快处理；工具调用兼容性发布阻断项。
- **复核入口：** 附录 A / stream_tool_calls_responses、stream_tool_calls_anthropic。

### REVIEW-005 — Anthropic 上游非流式响应归一化丢弃 tool_use

- **优先级：** P1
- **文件位置：** app/infrastructure/adapters/channel_adapters.py:151；app/domain/gateway.py:305
- **问题类型：** Bug
- **变更归属：** 历史缺陷；该文件本阶段仅补充 Ollama models URL，工具转换缺陷属于补充核心审查。
- **问题描述：** AnthropicAdapter.normalize_response 仅拼接 content 中的 text，生成 OpenAI message 时未转换 tool_use 为 tool_calls。GatewayService 确实对上游响应调用该适配器，丢失发生在统一代理输出前。
- **触发条件：** 选择 claude/Anthropic 渠道，使用非流式工具调用，上游返回包含 tool_use 的成功响应。
- **影响范围：** 函数 ID、名称、参数被静默丢弃；调用方收到空文本，工具流程失败。prepare_body 对工具定义和工具结果也没有完整双向映射，需一起做契约验收。
- **证据：** 真实 AnthropicAdapter 输入 content=[{type:tool_use,id:t,name:lookup,input:{}}]，输出 choices[0].message.content 为空，且没有 tool_calls；实际 Gateway normalize_response 调用点位于第305行。
- **验证状态：** 已复现：响应转换器；静态追踪：生产网关接入点。请求侧与真实厂商交互未现场验证，不作为额外已确认问题计数。
- **修复建议：** 复用/统一已有协议转换实现，保留 tool_use → tool_calls、工具结果、stop_reason 与 usage；为实际 ChannelAdapter 路径建立双向契约测试。
- **修复优先级：** 尽快处理；与 REVIEW-004 一并验收，两个实现路径分别修复。
- **复核入口：** 附录 A / anthropic_nonstream_tool。

### REVIEW-006 — SSE 无成功终止标记时被补成成功完成

- **优先级：** P1
- **文件位置：** app/domain/streaming.py:180；app/domain/streaming.py:372；app/domain/gateway.py:439；app/application/services/misc_services.py:387
- **问题类型：** Bug / 工程质量
- **变更归属：** 历史缺陷；本阶段流式账本/日志改动继承了这一完成状态。
- **问题描述：** StreamCodec.finish 在收到 EOF 且 done=false 时调用 _finish_protocol，生成成功终止事件。ProxyService 默认 status=completed，并可补 [DONE]，没有保留“仅连接结束”与“上游业务完成”的差异。
- **触发条件：** 上游 HTTP200，已输出 partial 文本后正常关闭连接，但未提供 finish_reason / [DONE] 或目标协议的成功终止事件。
- **影响范围：** 客户端接受被截断的结果且不会按错误处理；成功日志、尝试记录与计费状态可能矛盾，影响自动恢复和运营统计。
- **证据：** 实际 GatewayService + ProxyService + httpx.MockTransport，上游仅发送一条 partial delta 后 EOF。downstream_done=true，logged_status=completed；代理提前关闭生成器时该上游 attempt.succeeded=false，显示状态分歧。
- **验证状态：** 已复现：网关到流式代理的本地故障注入，无真实上游网络。
- **修复建议：** 解析器收尾仅排出剩余事件；单独跟踪各协议已观察到的成功终止证据。异常 EOF 返回 truncated/error，不伪造 completed；输出开始后不自动重放整个请求。
- **修复优先级：** 尽快处理；与流式协议修复同时完成。
- **复核入口：** 附录 A / premature_stream_eof。

### REVIEW-007 — 知识库导入在分块提交后失败，自动重试生成重复数据

- **优先级：** P1
- **文件位置：** app/application/services/kb_service.py:177；app/application/services/kb_service.py:184；app/infrastructure/repositories/kb_repo.py:216；app/application/services/kb_worker.py:90
- **问题类型：** Bug / 数据一致性
- **变更归属：** 历史缺陷；未修改的知识库导入核心模块补充审查。
- **问题描述：** 分块写入、文档元数据、KB 统计、任务完成分别提交。分块 ID 每次拆分重新生成 UUID；后续步骤抛错时 Worker 会重新运行全流程，没有替换已有文档分块或去重。
- **触发条件：** save_chunk_batch 已成功提交，随后 update_doc / update_kb / 完成任务失败；任务恢复或自动重试。
- **影响范围：** 相同文档出现重复 chunks/embedding，检索结果重复、统计和索引污染、成本增加；连续故障会累积。
- **证据：** 真实 KbService/TextSplitter、带已提交状态的内存仓储替身：第一次 update_doc 注入异常，第二次导入同一 doc。chunks_after_retry=2，distinct_chunk_ids=2，内容均为 reference text。实际 KbRepository.save_chunk_batch 为 INSERT，各仓储方法独立事务。
- **验证状态：** 已复现：服务故障注入；静态证实：真实仓储事务边界和无幂等 INSERT。未运行 MySQL 故障恢复。
- **修复建议：** 向量计算在事务外完成；在有效任务租约内，以文档版本原子替换分块并提交元数据/任务完成。使用稳定身份或唯一约束抵御重复提交，结合 REVIEW-008 的执行代次校验。
- **修复优先级：** 立即安排；先补 fencing，再完成幂等提交。
- **复核入口：** 附录 A / kb_import_retry。

### REVIEW-008 — 知识库 Worker 失去租约后仍可覆盖新 Worker 的任务状态

- **优先级：** P1
- **文件位置：** app/application/services/kb_worker.py:61；app/application/services/kb_worker.py:68；app/infrastructure/repositories/kb_repo.py:333；app/infrastructure/repositories/kb_repo.py:359
- **问题类型：** Bug / 并发安全
- **变更归属：** 历史缺陷；知识库任务恢复/并发核心补充审查。
- **问题描述：** 续租失败返回 false 被忽略；to_thread 中旧执行仍继续。fail_or_retry_task 与进度/完成等状态写入只按 task_id，不要求 worker_id 或执行代次。取消 asyncio 包装任务也无法停止已运行的线程。
- **触发条件：** Worker A 暂停/网络故障使租约过期，任务被 Worker B 领取；A 恢复后发生错误、提交结果或更新状态。
- **影响范围：** 旧 Worker 可以把 B 正在运行的任务重置为 pending/failed 或提前完成，并允许多个执行同时写分块；带来重复处理、错误可见状态和数据污染。
- **证据：** 真实 KbRepository.fail_or_retry_task 在内存 SQLite 中执行：已有 task.running、worker_id=worker-B、attempt_count=2；模拟 A 的迟到失败后，状态变 pending，worker_id/lease_until 均变 null。调用不携带任何 owner，SQL 无 owner 条件。
- **验证状态：** 已复现：真实仓储的迟到写入；静态证实：续租失败忽略及线程取消边界。未做真实多进程 MySQL 压测。
- **修复建议：** 领取任务生成单调执行代次/fencing token；所有分块发布、状态、失败与完成提交都校验 owner+generation+有效租约。续租失败停止后续发布，执行线程使用协作式停止信号。
- **修复优先级：** 立即安排；作为 REVIEW-007 的前置修复。
- **复核入口：** 附录 A / kb_stale_worker。

### REVIEW-009 — 配额结算失败仅写日志，预留永久悬挂且没有恢复机制

- **优先级：** P1
- **文件位置：** app/application/services/misc_services.py:274；app/application/services/misc_services.py:282；app/application/services/misc_services.py:477；app/infrastructure/repositories/quota_repo.py:17
- **问题类型：** Bug / 工程质量
- **变更归属：** 历史缺陷；本阶段改造了实际消耗结算与独立用量账本，但异常后缺少恢复的问题仍在。
- **问题描述：** reserve 先增加 api_keys.quota_used 并写入 reserved 账目；settle/release 失败被捕获后仍返回业务成功。仓库未找到针对这些 reserved 的持久化待结算队列、超时核对或启动恢复；独立 usage ledger 不会自动修复 quota ledger。
- **触发条件：** 上游已经成功消耗 token，在最终结算/释放预留时数据库暂时不可用或出现事务错误，之后请求结束或进程退出。
- **影响范围：** 实际消耗与额度长期不一致：小实际用量会被多扣，大实际用量可能少扣；配额较小的 Key 可因此持续被限流。账本存在并不等于能够恢复。
- **证据：** 真实 QuotaRepository + 内存 SQLite，settle 注入 RuntimeError，代理上游成功并返回5 token。HTTP200；quota_used=1024、ledger_status=reserved、actual_tokens=5，后续无恢复路径。
- **验证状态：** 已复现：真实预留仓储与结算失败注入；未声称已经发生真实生产数据库故障。
- **修复建议：** 持久化 execution_id、已知实际用量和 pending settlement；结算幂等，失败进入可重放队列，重启后核对。未知消耗单列并告警，不能简单全部释放导致漏计费。
- **修复优先级：** 立即安排；用于计费/硬配额之前完成。
- **复核入口：** 附录 B / lost_quota_settlement。

### REVIEW-010 — MCP 动态命名软件工具被重复包装参数，标准 HTTP 调用失败

- **优先级：** P1
- **文件位置：** app/api/controllers/mcp_routes.py:308；app/api/controllers/mcp_routes.py:319；app/application/services/misc_services.py:627；app/application/services/misc_services.py:644
- **问题类型：** Bug / 接口契约
- **变更归属：** 历史缺陷；MCP 软件工具的上下游补充审查。
- **问题描述：** HTTP router 先调用 validate_arguments，把 software.<id>.<name> 的原始参数包装为 {tool_id, arguments, approved}，再把结果传给 call_tool。call_tool 又执行同一个非幂等规范化，导致实际连接器参数多套一层。
- **触发条件：** 通过 POST /mcp 调用已发布的 software.tool-1.echo，工具要求 message 字段；传入合法 {message:hello}。
- **影响范围：** 工具参数校验报缺少 message；宽松 schema 则把错误参数传给连接器。tools/list 看似成功、直接服务单测成功，HTTP 实际执行失败。
- **证据：** 真实 FastAPI MCP router + McpService + SoftwareService，连接器仅替换为无副作用回显。直接 call_tool 返回 {message:hello}；相同参数 HTTP200 的 JSON-RPC result.isError=true、Tool execution failed；connector_calls 总计1，HTTP 路径未抵达连接器。
- **验证状态：** 已复现：完整 HTTP 动态工具调用路径；鉴权上下文为测试管理员，不绕过待验证的参数处理。
- **修复建议：** 明确“原始参数校验”与“内部规范化参数”的边界，只执行一次规范化；由 call_tool 统一拥有校验，或引入不同的内部执行方法/类型。添加命名与通用入口的 HTTP 契约回归。
- **修复优先级：** 尽快处理；软件 MCP 功能发布阻断项。
- **复核入口：** 附录 C / dynamic_software_arguments。

### REVIEW-011 — 无 session 的 MCP 请求按公共 request ID 注册，调用者可取消他人请求

- **优先级：** P2
- **文件位置：** app/api/controllers/mcp_routes.py:56；app/api/controllers/mcp_routes.py:275；app/api/controllers/mcp_routes.py:322
- **问题类型：** 安全 / 并发安全
- **变更归属：** 历史缺陷；MCP 并发与取消补充审查。
- **问题描述：** 缺少 mcp-session-id 仍允许请求。运行任务和取消标记的键是 (session_id,rpc_id)，不包含身份；所有无会话客户端共享 (None,id)。取消通知也未核对发起者，重复 ID 会覆盖注册。
- **触发条件：** 部署允许 API Key 访问 MCP；两个已鉴权调用者均不建立 session，使用常见 rpc_id=1/42；其中一方发送 notifications/cancelled。
- **影响范围：** 跨调用者中断响应或发生串扰。已运行的 to_thread 连接器未必随响应取消而停止，调用方可能重试已生效操作。攻击需获得 MCP 接入身份，不是匿名取消。
- **证据：** 真实 MCP router、ASGITransport，分别注入 victim/attacker 两个 AuthContext；victim 的工具保持运行，attacker 用相同 ID 取消。attacker_status=202，victim 返回 code=-32800 / Request cancelled。
- **验证状态：** 已复现：路由层跨身份取消；外部鉴权由两个测试上下文替代，工具替身无外部副作用。
- **修复建议：** 所有任务/取消标记按 (principal_type,principal_id,session_id,rpc_id) 命名；拒绝同一命名空间中的活动重复 ID；为取消标记设置上限和过期机制，明确线程任务取消语义。
- **修复优先级：** 下一修复批次；多调用者 MCP 上线前完成。
- **复核入口：** 附录 B / mcp_cross_principal_cancel。

### REVIEW-012 — 同步数据库鉴权和部分流式结算阻塞 ASGI 事件循环

- **优先级：** P2
- **文件位置：** app/api/middleware/auth.py:165；app/application/services/misc_services.py:371；app/application/services/misc_services.py:384；app/application/services/misc_services.py:481；app/application/services/misc_services.py:490
- **问题类型：** 性能 / 资源管理
- **变更归属：** 历史问题；本阶段新增用量记录使用了部分 to_thread，但仍存在同步路径。
- **问题描述：** async dispatch 直接调用同步 api_authorizer.authenticate，后者同步查询 SQLAlchemy/PyMySQL 仓储；流式路径中的扫描读库、quota reserve/settle 和最终日志也存在直接同步调用。一个 DB 慢查询可阻塞同进程的其他流和请求。
- **触发条件：** 数据库延迟、连接池等待或数据库短暂拥塞；并发流式请求运行在同一事件循环。
- **影响范围：** 请求间头阻塞，已有 SSE 输出停顿、取消/健康检查响应延迟；并发放大数据库故障影响。
- **证据：** 真实 ApiKeyAuthMiddleware.dispatch，仓储调用注入200ms 同步延迟；同循环预期20ms 的 heartbeat 实测约201ms 才执行。数值仅为故障模型，不是生产吞吐压测。
- **验证状态：** 已复现：鉴权阻塞机制；静态证实：流式同步调用点。
- **修复建议：** 将整段同步数据库工作移到受限线程池，或使用一致的异步驱动；统一异步服务边界并限制并发。验证慢 DB 时 SSE 心跳与取消响应，避免只零散包裹个别 SQL。
- **修复优先级：** 后续可靠性批次，进入高并发部署前处理。
- **复核入口：** 附录 B / auth_blocks_event_loop。

### REVIEW-013 — HNSW 将查询行序号当分块身份，顺序变化后返回错误文档

- **优先级：** P2
- **文件位置：** app/domain/index_service.py:256；app/domain/index_service.py:333；app/infrastructure/repositories/kb_repo.py:236
- **问题类型：** Bug / 数据一致性
- **变更归属：** 历史缺陷；未修改的核心检索模块补充审查。
- **问题描述：** 建索引用 enumerate(chunks) 的 i 作为向量 ID，查询时再次查询 chunks 并按当前行序号关联内容。数据库只 ORDER BY chunk_index，各文档都从0计数，同值顺序未定义，且增删后序号会变化。
- **触发条件：** 至少两篇文档有相同 chunk_index；建索引和查询间数据库返回行顺序改变，或数据变更后查询旧索引。
- **影响范围：** 向量分数属于 A，返回内容与来源却是 B；RAG 引用和回答依据错误，难以从高相似度分数发现。
- **证据：** 真实 IndexService/HnswIndex，新临时目录保存索引。仓储合法返回顺序由 [a,b] 变 [b,a]；查询 a 的 [1,0] 向量，得到 chunk_id=b、score=1.0。未依赖随机 MySQL 行顺序复现。
- **验证状态：** 已复现：真实索引与可允许的行顺序变化；真实 MySQL 执行计划未测。
- **修复建议：** 同一索引版本持久化 node_id→chunk UUID 映射，并校验索引与数据 generation；重建后原子切换。补稳定 ORDER BY 只能降低概率，不能替代持久身份和版本校验。
- **修复优先级：** 后续可靠性批次；依赖检索证据准确性的场景优先。
- **复核入口：** 附录 A / hnsw_unstable_identity。

### REVIEW-014 — Provider 模型快照15分钟过期，默认同步6小时，使路由退化为通配

- **优先级：** P2
- **文件位置：** app/application/services/provider_service.py:224；app/application/services/provider_service.py:252；app/types/provider_sync.py:32
- **问题类型：** Bug / 配置一致性
- **变更归属：** 本阶段新增模型快照/同步路径的缺陷。
- **问题描述：** _discovered_models 固定15分钟后返回 None；默认 models_interval=21600秒。没有显式 model_mappings 时，过期模型集合变成 []，筛选条件 (models or discovered is not None) 为假，渠道不再拒绝未知模型，/v1/models 也不再展示已发现模型。
- **触发条件：** Provider 已同步模型，未显式配置映射，采用默认6小时周期；距成功抓取超过15分钟。同步需管理员开启；未开启时也可能出现已有快照变陈旧。
- **影响范围：** 大部分同步间隔内，已知不支持的模型被送到该 Provider；发现列表消失，造成错误路由/额外失败与回退延迟。
- **证据：** 真实 ProviderService/ProviderRepository + 对应 SQLite 迁移。fresh 时拒绝 unsupported；将 fetched_at 设为16分钟前后，接受 unsupported 且 models=[]；默认间隔21600秒。
- **验证状态：** 已复现：真实快照与路由服务；未调用真实 Provider。
- **修复建议：** 按同步周期统一新鲜度策略；区分未配置的通配渠道与已知集合的过期。可保留陈旧已知模型并触发刷新，或显式关闭陈旧渠道，避免 None 隐式放开限制。
- **修复优先级：** 下一修复批次，启用 Provider 模型同步前完成。
- **复核入口：** 附录 B / provider_stale_models。

### REVIEW-015 — 合法 JSON 数组/null 未校验顶层类型，网关返回500

- **优先级：** P2
- **文件位置：** app/application/services/misc_services.py:211；app/application/services/misc_services.py:222
- **问题类型：** Bug / API 参数校验
- **变更归属：** 历史缺陷；本阶段修改同一代理核心服务。
- **问题描述：** json.loads 成功后直接访问 body_json.get，未要求顶层 object。语法正确的 []、null、数值等会抛 AttributeError；全局异常处理将其作为服务器错误。其他协议转换同样需要在转换前约束结构。
- **触发条件：** 已鉴权请求向聊天代理发送 [] 或 null，而非对象。
- **影响范围：** 非法客户端输入被计为500，日志噪声、错误监控和客户端重试行为失真；不是已验证的整个服务宕机或拒绝服务漏洞。
- **证据：** 真实 ProxyService.forward('[]', {}) 抛 AttributeError: 'list' object has no attribute 'get'；追踪 main.py 的全局 Exception handler 返回500。未发真实上游请求。
- **验证状态：** 已复现：服务异常；静态证实：HTTP 全局异常映射。
- **修复建议：** 解析后立即验证 isinstance(body_json,dict)，再校验 model 类型和最小消息结构；对非对象返回统一400/422，流式尽量在发送响应头前完成验证。
- **修复优先级：** 常规修复批次，可与统一调用入口一起完成。
- **复核入口：** 附录 B / json_array_input。

### REVIEW-016 — 知识库上传成功后异步读取 React event.currentTarget 导致假失败

- **优先级：** P2
- **文件位置：** frontend/src/App.tsx:75
- **问题类型：** Bug / 前端生命周期
- **变更归属：** 本阶段新增 React 管理页面路径。
- **问题描述：** 上传完成的 Promise 回调访问 event.currentTarget.value；React 事件处理结束后 currentTarget 已清空。回调抛错，被上传失败 catch 捕获，后续 load() 不执行。
- **触发条件：** 管理台知识库页面选择文件，上传 API 成功返回；Promise 在事件分发结束后完成。
- **影响范围：** 后端已接收文件，前端却显示 Cannot set properties of null，列表不刷新、文件输入未清空；用户重试可能导致重复导入。
- **证据：** 实际 App.tsx 经已安装 Vite 编译，在真实 React + jsdom 渲染；API 和无关页面替换为无网络替身，触发真实 change 事件。uploads=1、knowledge_list_reads=1（仅初始加载），页面出现 Cannot set properties of null (setting 'value')。
- **验证状态：** 已复现：真实 React 事件与实际组件源码；未进行真实浏览器部署验收。
- **修复建议：** 同步保存 const input=event.currentTarget 和 kb_id，再在回调使用保存的 DOM 引用；分离服务端成功与刷新失败的提示，补真实事件派发的上传成功回归。
- **修复优先级：** 常规修复批次，管理台交付前完成。
- **复核入口：** 附录 D / knowledge_upload_currentTarget。


## 8. 当前最重要的架构风险

1. **横切策略没有统一执行边界。** ProxyService、RagService、McpService、SoftwareService 分别实施部分授权/计费，入口组合决定实际权限。建议把规范化后的“模型调用”和“资源工具执行”作为唯一策略入口，显式传递不可变 AuthContext 与 execution_id。
2. **持久任务的“领取”不等于“有权提交”。** 有 lease 而无 fencing、幂等发布和统一事务，使失效执行仍能写入。先定义可验证状态机和提交所有权，再考虑 Worker 并行扩容。
3. **协议映射依赖局部手写转换。** 非流式 adapter、独立 converter、SSE codec 的能力不一致。建议以统一事件/消息模型建立矩阵，分别覆盖文本、工具、错误、取消、usage 和结束语义，减少多套逻辑漂移。
4. **用量、配额、调用日志没有统一可恢复的完成协议。** 多张表各自持久化，却缺少失败恢复与对账状态机。不能用日志打印代替 durable reconciliation。
5. **同步数据库与异步网络边界不稳定。** ASGI 线程、to_thread、asyncio.run 与共享 httpx client 混用；即使当前测试通过，也需要统一事件循环和阻塞任务的归属。跨循环疑点的边界见下一节。

这些是从已发现问题归纳的设计改进方向，不额外算作5个 Bug，也不要求无边界重构。

## 9. 未确认为缺陷的疑点与后续验证

| 疑点 | 本次证据与结论 | 后续所需验证 |
| --- | --- | --- |
| 共享 AsyncClient 被多次 asyncio.run 使用 | 真实 Gateway/Dispatcher + 本机 HTTP/1.1 keepalive 服务，在 Windows 默认 Proactor 和 Selector 两种策略下连续3次均200且每次1 attempt；**未复现，不计入问题数** | Linux生产循环、同步与流式混合并发、连接池关闭的特定执行顺序；不能仅凭结构认定已经出错 |
| MySQL 迁移中断/DDL 非事务恢复 | 阅读迁移转换与脚本，未执行隔离 MySQL 中断恢复；**待验证** | 独立实例反复升级、途中退出和重启；不得拿 SQLite 事务语义替代 |
| URL 检查与实际连接间的 DNS/重定向边界 | 阅读 ImportGuard 和软件 HTTP 校验；没有完成可控 DNS 重绑定端到端验证；**待验证，不认定已存在可利用 SSRF** | 受控解析与私网地址/重定向/IPv6矩阵、实际连接IP约束 |
| 多进程 Agent 状态、所有工具副作用取消 | 没有多进程/真实连接器压测；to_thread 无强制终止能力已在相关发现中限定说明 | 外部执行幂等键、取消后状态查询、进程隔离与有界队列 |

本次没有确认 SQL 注入、匿名管理员访问、硬编码真实生产密钥或可利用的任意文件删除漏洞；这不是对全部路径的穷举排除。

## 9.1 交付核对

报告写入后核对：16个问题编号唯一、P1/P2统计为10/6，50处文件行号均存在；附录A/B/C的Python源码可解析。Git状态仅出现三份docs/code-review报告，未出现其他跟踪或未跟踪业务变更；git diff --check退出0。

## 10. 测试与工程可靠性的主要不足

- 测试更多验证单函数和单服务的预期输出，缺少真实入口到策略执行层的组合测试。REVIEW-010 说明服务直接调用成功仍可掩盖 HTTP 入口错误；REVIEW-001/002 说明“已鉴权”不等于资源和成本边界正确。
- quota_repo 行覆盖率100%仍未覆盖“上游成功→结算失败→进程退出→恢复”的跨组件行为。KB 缺少提交后失败、租约转移、迟到执行和故障重放测试。
- 缺少跨协议工具调用矩阵，尤其分片工具参数、多工具、纯工具响应、异常 EOF、usage 末帧和取消。
- 前端异步生命周期测试不足；以真实 DOM 事件分发可揭示 Promise 回调中的 currentTarget 清空问题。
- 本次13个跳过项不能算完整集成覆盖；MySQL8锁和迁移、真实 Provider、部署浏览器、Docker/健康探针与 OTLP 应有独立验收结果。现有 CI 确实声明 MySQL 服务，不能说“项目没有 MySQL CI”；本次未执行该服务。
- Mypy 默认不检查部分无注解函数体，AST/Ruff/行覆盖率不能证明关键状态机和权限组合正确。建议把本次复现转为有断言的行为回归，在另一次授权修复任务中提交。

## 11. 复现附录说明

以下保留本次成功复现使用的代码，便于本地复核；**没有把它们写入业务或测试目录**。附录 A/B 在内存 SQLite 中建表，HTTP 使用 ASGI/MockTransport；连接器替身无外部副作用。A 的 HNSW 演示只写新 tempfile 目录，输出其路径，不删除目录。C 为实际 MCP HTTP 路径；D 在内存编译实际 React 页面，不写 review-memory.cjs 文件。

在仓库根目录，用 PowerShell 进程隔离数据库与真实服务配置；然后把相应 Python 代码块作为 $poc 的 here-string，通过标准输入执行：

~~~powershell
$env:PYTHONDONTWRITEBYTECODE='1'
$env:APP_ENV='test'
$env:DB_HOST='127.0.0.1'
$env:DB_PORT='1'
$env:DB_NAME='review_no_external_db'
$env:DB_PASSWORD='review-local-only'
$env:DB_UNIX_SOCKET=''
# $poc = @'
# 复制下方相应 Python 代码块
# '@
$poc | .venv\Scripts\python.exe -B -
~~~

D 使用 $js 的 here-string 并执行 $js | node -（仓库根目录，frontend/node_modules 已安装）。代码中的 synthetic、sk-AAAA...、example.invalid 均为合成测试数据。运行前应保持 APP_ENV=test，不应将复现脚本改为真实生产连接。附录输出是故障证明，不是修复或完整回归套件。

### 复现输出索引

| 脚本/case | 关键观测 |
| --- | --- |
| A / mcp_resource_acl | software_grant=false；generic_result返回；connector_calls=1 |
| A / kb_policy_bypass | HTTP200；expensive；channels=[]；principal=null；配额已耗尽 |
| A / response_redaction | scanner_sanitized=true；downstream_contains_secret=true |
| A / stream_tool_calls_* | 两种目标均未保留tool名称和ID |
| A / anthropic_nonstream_tool | 无tool_calls，content为空 |
| A / premature_stream_eof | done=true；日志completed；attempt.succeeded=false |
| A / kb_import_retry | 同文档同内容2 chunks，2个不同UUID |
| A / kb_stale_worker | B的running任务被A改成pending，owner/lease清空 |
| A / hnsw_unstable_identity | expected=a；returned=b；score=1.0 |
| B / provider_stale_models | 间隔21600；fresh拒绝，16分钟后接受未知模型 |
| B / auth_blocks_event_loop | 20ms heartbeat被200ms同步仓储调用延至约201ms |
| B / lost_quota_settlement | HTTP200；quota_used=1024；reserved；实际5 |
| B / json_array_input | AttributeError: list has no attribute get |
| B / mcp_cross_principal_cancel | attacker202；victim -32800 |
| C / dynamic_software_arguments | direct成功；HTTP result.isError=true；连接器只执行直接调用 |
| D / knowledge_upload_currentTarget | 上传1次；列表仅初次加载；currentTarget null 错误 |

## 附录 A：授权、响应扫描、协议、KB 和索引复现

~~~python

import asyncio, json, tempfile, threading, time
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import Mock, patch
from dataclasses import replace
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import httpx
from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.application.services.misc_services import ProxyService, McpService
from app.application.services.software_service import SoftwareService
from app.application.services.access_service import AccessService
from app.application.services.kb_service import KbService
from app.application.services.auth_service import AdminAuthService
from app.domain.knowledge import RagService, RagContextBuilder, TextSplitter, serialize_embedding
from app.domain.entities import *
from app.domain.gateway import GatewayService
from app.domain.streaming import StreamCodec
from app.domain.security import SecurityScanner
from app.config import SecuritySettings
from app.types.auth import AuthContext
from app.types.models import UploadDocDTO
from app.types.access import AccessGrantInput
from app.infrastructure.repositories.access_repo import AccessRepository
from app.infrastructure.database.migrations import execute_migration

def emit(name, **values):
    print(json.dumps({"case": name, **values}, ensure_ascii=True), flush=True)
def memory():
    return create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread":False})
engine = memory()
with engine.begin() as db:
    execute_migration(db, Path("docs/migrations/010_access_grants.sql"))
access_repo = AccessRepository(engine)
access = AccessService(access_repo)
ctx = AuthContext("api_key", "key", allowed_models=frozenset({"cheap"}), allowed_channels=frozenset({"allowed"}), quota_limit=1, quota_used=1)
def grant(kind, rid, action):
    access_repo.create(AccessGrantInput(principal_type="api_key",principal_id="key",resource_type=kind,resource_id=rid,action=action).model_dump())

# Real MCP service and Software service, connector replaced to prevent side effects.
grant("mcp_tool", "invoke_software_tool", "execute")
software_repo = Mock()
software_repo.get_tool.return_value = {"id":"private-tool","instance_id":"i","name":"lookup","enabled":1,"risk_level":"low","approval_mode":"none","config":{},"input_schema":{"type":"object"}}
software_repo.get_instance.return_value = {"id":"i","connector_type":"http","enabled":1,"config":{}}
software_repo.list_tools.return_value = [software_repo.get_tool.return_value]
software = SoftwareService(software_repo)
software._invoke_connector = Mock(return_value={"private":"returned"})
mcp = McpService(Mock(), access, software_service=software)
named = mcp.call_tool("software.private-tool.lookup", {}, ctx)
generic = mcp.call_tool("invoke_software_tool", {"tool_id":"private-tool","arguments":{}}, ctx)
emit("mcp_resource_acl", software_grant=access.can(ctx,"software","private-tool","execute"), named_denied=named.get("isError",False), generic_result=generic.get("result"), connector_calls=software._invoke_connector.call_count, advertised=[x["name"] for x in mcp.list_tools(ctx)["tools"]])

# HTTP KB authorization is real; the final transport is captured.
grant("kb","kb","read")
kb_repo = Mock()
kb_repo.find_kb_by_id.return_value = KbKnowledgeBaseEntity(id="kb",name="kb")
retriever = Mock()
retriever.keyword_search.return_value = [SearchResultEntity(chunk_id="chunk",doc_id="doc",content="reference",score=1,metadata={})]
captured = []
def gateway_sync(request):
    captured.append(request)
    return ProxyResponseEntity(body=json.dumps({"choices":[{"message":{"content":"answer"}}]}))
rag = RagService(retriever, Mock(), NS(forward_sync=gateway_sync), RagContextBuilder())
kb = KbService(kb_repo,rag,TextSplitter(),Mock())
channel_repo = Mock()
channel_repo.get_api_key_by_key.return_value = ApiKeyEntity(id="key",key="synthetic",allowed_models=["cheap"],allowed_channels=["allowed"],quota_limit=1,quota_used=1)
container=NS(kb_service=kb,access_service=access,channel_repo=channel_repo,admin_service=NS(auth=AdminAuthService()))
from app.api.controllers.routes import kb_router
from app.api.middleware.auth import ApiKeyAuthMiddleware
application=FastAPI(); application.include_router(kb_router); application.add_middleware(ApiKeyAuthMiddleware)
with patch("app.api.controllers.routes.get_container",return_value=container), patch("app.api.resource_dependencies.get_container",return_value=container), patch("app.api.middleware.auth.get_container",return_value=container):
    with TestClient(application) as client:
        response=client.post("/api/v1/kb/kb/ask",headers={"Authorization":"Bearer synthetic"},json={"question":"q","model":"expensive","search_mode":"keyword"})
emit("kb_policy_bypass", http_status=response.status_code, requested_model=captured[0].model, forwarded_channels=sorted(captured[0].allowed_channels), forwarded_principal=captured[0].principal_id, key_quota_already_exhausted=True)

# Response redaction requested by an explicit rule.
secret="sk-"+"A"*24
payload=json.dumps({"choices":[{"message":{"content":secret}}]})
scanner=SecurityScanner()
settings=SecuritySettings(enabled=True,mode="redact",scan_response=True)
rule=SecurityCustomRuleEntity(id="redact",name="redact",pattern=r"sk-[A-Za-z0-9]{20,}",action="redact",enabled=1,severity="critical")
security_repo=Mock()
security_repo.get_all_custom_rules.return_value=[rule]
security_repo.get_all_builtin_rules.return_value=[]
async def respond(request):
    return ProxyResponseEntity(body=payload,content_type="application/json")
proxy=ProxyService(NS(forward=respond),scanner,settings,Mock(),security_repo)
status, value=proxy.forward(json.dumps({"model":"demo","messages":[{"role":"user","content":"hello"}]}),{})
scan=scanner.scan(payload,"response",settings,[rule],[])
emit("response_redaction", scanner_sanitized=scan.sanitized, scanner_removed_secret=secret not in (scan.sanitized_body or ""), http_status=status, downstream_contains_secret=secret in json.dumps(value))

# Protocol conversion silently drops function calls.
for target in ("responses","anthropic"):
    codec=StreamCodec("openai",target,"demo"); output=[]
    values=[{"choices":[{"delta":{"tool_calls":[{"index":0,"id":"call_1","type":"function","function":{"name":"lookup","arguments":"{}"}}]},"finish_reason":None}]},{"choices":[{"delta":{},"finish_reason":"tool_calls"}]}]
    for value in values:
        for line in ("data: "+json.dumps(value),""):
            output.extend(codec.feed_line(line))
    for line in ("data: [DONE]",""):
        output.extend(codec.feed_line(line))
    result="".join(output)
    emit("stream_tool_calls_"+target, tool_name_preserved="lookup" in result, tool_id_preserved="call_1" in result, result=result)

# The nonstream Anthropic adapter also discards tool_use.
from app.infrastructure.adapters.channel_adapters import AnthropicAdapter
value=json.loads(AnthropicAdapter().normalize_response(json.dumps({"id":"m","content":[{"type":"tool_use","id":"t","name":"lookup","input":{}}],"stop_reason":"tool_use","usage":{}}),"demo"))
emit("anthropic_nonstream_tool", normalized=value)

# Stream EOF without any success terminal marker is reported completed.
async def eof_case():
    channel=ChannelEntity(id="c",base_url="https://example.invalid",models=["demo"])
    dispatch=NS(candidates=lambda model,excluded=None:[DispatchResult(channel,"demo")] if "c" not in (excluded or set()) else [])
    gateway=GatewayService(dispatch,None); await gateway.aclose()
    async def handle(request):
        return httpx.Response(200,headers={"content-type":"text/event-stream"},content='data: {"choices":[{"delta":{"content":"partial"}}]}\n\n',request=request)
    gateway.client=httpx.AsyncClient(transport=httpx.MockTransport(handle))
    log=Mock()
    proxy=ProxyService(gateway,None,SecuritySettings(enabled=False),log)
    output="".join([x async for x in proxy.forward_stream_async('{"model":"demo","stream":true}',{})])
    emit("premature_stream_eof", downstream_done="[DONE]" in output, logged_status=log.insert_log.call_args.args[0].stream_status, upstream_attempt_succeeded=log.insert_attempt.call_args.args[1].succeeded)
    await gateway.aclose()
asyncio.run(eof_case())

# A successful chunk commit followed by a metadata failure is retried as inserts.
repo=Mock()
kb_entity=KbKnowledgeBaseEntity(id="kb",name="kb")
doc=KbDocumentEntity(id="doc",kb_id="kb",name="x.txt")
repo.find_kb_by_id.return_value=kb_entity
repo.find_doc_by_id.return_value=doc
saved=[]
repo.save_chunk_batch.side_effect=lambda chunks:saved.extend(chunks)
repo.find_doc_by_kb_id.return_value=[doc]
repo.find_chunk_by_kb_id.side_effect=lambda kb:saved[:]
repo.update_doc.side_effect=[RuntimeError("injected post-commit failure"),None]
embed=Mock(); embed.embed_batch.return_value=[[1.0,0.0]]
service=KbService(repo,None,TextSplitter(),embed)
dto=UploadDocDTO(filename="x.txt",content="reference text",file_type="txt")
try: service.run_import_pipeline("kb","doc","task",dto)
except RuntimeError: pass
service.run_import_pipeline("kb","doc","task",dto)
emit("kb_import_retry", chunks_after_retry=len(saved), distinct_chunk_ids=len({x.id for x in saved}), contents=[x.content for x in saved])

# An old worker can fail/requeue a task already owned by another worker.
from app.infrastructure.repositories.kb_repo import KbRepository
task_engine=memory()
with task_engine.begin() as db:
    db.execute(text("CREATE TABLE kb_tasks(id TEXT PRIMARY KEY,attempt_count INTEGER,doc_id TEXT,status TEXT,worker_id TEXT,lease_until TEXT,error_message TEXT,completed_at TEXT)"))
    db.execute(text("CREATE TABLE kb_documents(id TEXT PRIMARY KEY,status TEXT,error_message TEXT,updated_at TEXT)"))
    db.execute(text("INSERT INTO kb_tasks VALUES ('task',2,'doc','running','worker-B','2099',NULL,NULL)"))
    db.execute(text("INSERT INTO kb_documents VALUES ('doc','processing',NULL,NULL)"))
@contextmanager
def task_db():
    with task_engine.begin() as db: yield db
with patch("app.infrastructure.repositories.kb_repo.get_db",task_db):
    KbRepository().fail_or_retry_task("task","worker-A late failure",3)
with task_engine.connect() as db:
    emit("kb_stale_worker", task=dict(db.execute(text("SELECT * FROM kb_tasks")).mappings().one()))

# HNSW row positions are not stable chunk identities.
import app.domain.index_service as index_module
index_home=Path(tempfile.mkdtemp(prefix="llm-api-review-index-"))
a=KbChunkEntity(id="a",kb_id="kb",doc_id="a-doc",chunk_index=0,content="alpha",embedding=serialize_embedding([1,0]))
b=KbChunkEntity(id="b",kb_id="kb",doc_id="b-doc",chunk_index=0,content="beta",embedding=serialize_embedding([0,1]))
idx_repo=Mock(); idx_repo.find_chunk_by_kb_id.side_effect=[[a,b],[b,a]]
with patch.object(index_module,"INDEX_DIR",str(index_home)):
    idx=index_module.IndexService(idx_repo); idx.build_index("kb")
    result=idx.search_with_index("kb",[1,0],1)
emit("hnsw_unstable_identity", expected="a", returned=result[0]["chunk_id"], score=result[0]["score"], temp=str(index_home))


engine.dispose(); task_engine.dispose()

~~~

## 附录 B：模型快照、阻塞、配额、输入与取消复现

~~~python

import asyncio, json, time
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import Mock, patch
from contextlib import contextmanager
from datetime import UTC,datetime,timedelta
from sqlalchemy import create_engine,text
from sqlalchemy.pool import StaticPool
import httpx
from fastapi import FastAPI
from app.config import config,SecuritySettings
from app.infrastructure.database.migrations import execute_migration
from app.infrastructure.repositories.provider_repo import ProviderRepository
from app.application.services.provider_service import ProviderService
from app.types.provider import ProviderAccountInput,ProviderTokenInput
from app.types.provider_sync import ProviderSyncSettings
from app.application.services.misc_services import ProxyService,McpService
from app.domain.entities import ProxyResponseEntity,ApiKeyEntity
from app.types.auth import AuthContext
from app.api.middleware.auth import ApiKeyAuthMiddleware

def emit(name,**v): print(json.dumps({"case":name,**v}),flush=True)
def memory(): return create_engine("sqlite://",poolclass=StaticPool,connect_args={"check_same_thread":False})
engine=memory()
with engine.begin() as db:
    for path in sorted(Path("docs/migrations").glob("*.sql")):
        if path.name.startswith(("014_","017_","020_","021_","022_")): execute_migration(db,path)
service=ProviderService(ProviderRepository(engine))
account=service.create_account(ProviderAccountInput(provider="codex",name="test",client_config={"gateway_url":"https://example.invalid/v1"}))
service.set_token(account["id"],ProviderTokenInput(access_token="synthetic"))
repo=service.repo; generation=repo.synchronization_state(account["id"])["generation"]
repo.save_snapshot(account["id"],"models",generation,{"models":["supported"]})
fresh=service.routing_channels("unsupported",preview=True)
with engine.begin() as db:
    db.execute(text("UPDATE provider_snapshots SET fetched_at=:when"),{"when":(datetime.now(UTC)-timedelta(minutes=16)).isoformat()})
stale=service.routing_channels("unsupported",preview=True)
emit("provider_stale_models", default_interval=ProviderSyncSettings().models_interval, rejected_when_fresh=not fresh, accepted_after_16_minutes=bool(stale), model_list_after_expiry=stale[0].models if stale else None)
engine.dispose()

# Authentication's synchronous repository call blocks the serving loop.
async def blocking_auth():
    ticks=[]
    async def ticker():
        await asyncio.sleep(.02); ticks.append(time.perf_counter())
    repo=Mock()
    def read(key):
        time.sleep(.2); return ApiKeyEntity(id="key")
    repo.get_api_key_by_key.side_effect=read
    container=NS(channel_repo=repo,admin_service=NS(auth=NS(verify_admin_token=lambda token:None)))
    from starlette.requests import Request
    from starlette.responses import Response
    middleware=ApiKeyAuthMiddleware(lambda scope,receive,send:None)
    request=Request({"type":"http","method":"POST","path":"/v1/chat/completions","headers":[(b"authorization",b"Bearer synthetic")],"query_string":b""})
    async def next_call(request): return Response("ok")
    timer=asyncio.create_task(ticker()); await asyncio.sleep(0)
    start=time.perf_counter()
    with patch("app.api.middleware.auth.get_container",return_value=container):
        await middleware.dispatch(request,next_call)
    await timer
    emit("auth_blocks_event_loop", expected_tick_ms=20,actual_tick_ms=round((ticks[0]-start)*1000,1))
asyncio.run(blocking_auth())

# Quota reservation survives a settlement failure with no repair.
from app.infrastructure.repositories.quota_repo import QuotaRepository
engine=memory()
with engine.begin() as db:
    db.execute(text("CREATE TABLE api_keys(id TEXT PRIMARY KEY,status INTEGER,quota_limit INTEGER,quota_used INTEGER,updated_at TEXT)"))
    db.execute(text("CREATE TABLE api_key_quota_ledger(id TEXT PRIMARY KEY,api_key_id TEXT,request_id TEXT UNIQUE,reserved_tokens INTEGER,actual_tokens INTEGER,released_tokens INTEGER,status TEXT,created_at TEXT,settled_at TEXT)"))
    db.execute(text("INSERT INTO api_keys VALUES ('key',1,100000,0,NULL)"))
@contextmanager
def quota_db():
    with engine.begin() as db: yield db
quota=QuotaRepository()
async def respond(request): return ProxyResponseEntity(body='{"choices":[{"message":{"content":"ok"}}]}',total_tokens=5)
proxy=ProxyService(NS(forward=respond),None,SecuritySettings(enabled=False),Mock(),quota_repository=quota)
with patch("app.infrastructure.repositories.quota_repo.get_db",quota_db),patch.object(quota,"settle",side_effect=RuntimeError("injected database failure")):
    result=proxy.forward('{"model":"demo"}',{},auth_context=AuthContext("api_key","key"))[0]
with engine.connect() as db:
    emit("lost_quota_settlement",http_status=result,quota_used=db.execute(text("SELECT quota_used FROM api_keys")).scalar(),ledger_status=db.execute(text("SELECT status FROM api_key_quota_ledger")).scalar(),actual_tokens=5)
engine.dispose()

# Non-object JSON passes parse but crashes the service.
proxy=ProxyService(NS(forward=respond),None,SecuritySettings(enabled=False),Mock())
try: proxy.forward("[]",{})
except Exception as exc: emit("json_array_input",error_type=type(exc).__name__,error=str(exc))

# Stateless MCP cancellation is keyed without caller identity.
async def mcp_cancel():
    import threading
    from app.api.controllers import mcp_routes
    began=threading.Event(); finished=threading.Event()
    svc=NS(validate_arguments=McpService.validate_arguments)
    def call_tool(*args):
        began.set(); finished.wait(2); return {"content":[{"type":"text","text":"done"}]}
    svc.call_tool=call_tool
    app=FastAPI();app.include_router(mcp_routes.router)
    @app.middleware("http")
    async def identify(request,next_call):
        request.state.auth_context=AuthContext("api_key",request.headers.get("x-test-principal",""))
        return await next_call(request)
    headers={"Content-Type":"application/json","Accept":"application/json, text/event-stream"}
    container=NS(mcp_service=svc,mcp_session_repo=None)
    with patch.object(mcp_routes,"get_container",return_value=container):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url="http://test") as client:
            victim=asyncio.create_task(client.post("/mcp",headers={**headers,"x-test-principal":"victim"},json={"jsonrpc":"2.0","id":42,"method":"tools/call","params":{"name":"list_knowledge_bases","arguments":{}}}))
            while not began.is_set(): await asyncio.sleep(.005)
            attacker=await client.post("/mcp",headers={**headers,"x-test-principal":"attacker"},json={"jsonrpc":"2.0","method":"notifications/cancelled","params":{"requestId":42}})
            response=await victim
            finished.set()
            emit("mcp_cross_principal_cancel",attacker_status=attacker.status_code,victim_response=response.json())
asyncio.run(mcp_cancel())

~~~

## 附录 C：动态软件 MCP 双重规范化复现

~~~python
import json
from types import SimpleNamespace as NS
from unittest.mock import Mock,patch
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.application.services.misc_services import McpService
from app.application.services.software_service import SoftwareService
from app.api.controllers.mcp_routes import router, PROTOCOL_VERSION
from app.types.auth import AuthContext
repo=Mock()
repo.get_tool.return_value={"id":"tool-1","instance_id":"i","name":"echo","enabled":1,"risk_level":"low","approval_mode":"none","config":{},"input_schema":{"type":"object","properties":{"message":{"type":"string"}},"required":["message"],"additionalProperties":False}}
repo.get_instance.return_value={"id":"i","connector_type":"http","enabled":1,"config":{}}
software=SoftwareService(repo)
software._invoke_connector=Mock(side_effect=lambda instance,tool,args:args)
service=McpService(Mock(),software_service=software)
ctx=AuthContext("admin","review")
name="software.tool-1.echo"
direct=service.call_tool(name,{"message":"hello"},ctx)
app=FastAPI()
@app.middleware("http")
async def auth(request,call_next):
    request.state.auth_context=ctx
    return await call_next(request)
app.include_router(router)
with patch("app.api.controllers.mcp_routes.get_container",return_value=NS(mcp_service=service)):
    with TestClient(app) as client:
        result=client.post("/mcp",headers={"Accept":"application/json, text/event-stream","MCP-Protocol-Version":PROTOCOL_VERSION},json={"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":name,"arguments":{"message":"hello"}}})
print(json.dumps({"direct":direct.get("result"),"http_status":result.status_code,"http":result.json(),"connector_calls":software._invoke_connector.call_count}))

~~~

## 附录 D：React 上传成功后的事件生命周期复现

~~~javascript

const fs=require("fs"), path=require("path"), Module=require("module");
const front=path.join(process.cwd(),"frontend");
const req=Module.createRequire(path.join(front,"package.json"));
const {JSDOM}=req("jsdom");
const dom=new JSDOM('<html><body><div id="host"></div></body></html>',{url:"http://localhost/admin/#/knowledge"});
global.window=dom.window;global.document=dom.window.document;
Object.defineProperty(global,"navigator",{value:dom.window.navigator,configurable:true});
global.IS_REACT_ACT_ENVIRONMENT=true;
const React=req("react"),{act}=React,{createRoot}=req("react-dom/client");
let loads=0,uploads=0;
const api={
 get:async url=>url.includes("auth/session")?{authenticated:true}:(loads++, [{id:"kb",name:"kb",doc_count:0,chunk_count:0}]),
 upload:async()=>{uploads++;return {id:"doc"}},post:async()=>({}),put:async()=>({}),del:async()=>({})
};
const transformed=req("vite").transformWithOxc(fs.readFileSync(path.join(front,"src/App.tsx"),"utf8"),path.join(front,"src/App.tsx"),{jsx:{runtime:"automatic"}});
transformed.then(async ({code})=>{
const imports=[];
let compiled=code.replace(/^import (.+?) from "([^"]+)";$/gm,(_,what,from)=>{ if(what.startsWith("{")) return "const "+what.replace(/ as /g,": ")+" = require("+JSON.stringify(from)+");"; return "const "+what+" = require("+JSON.stringify(from)+");"; }).replace(/^import "[^"]+";$/gm,"").replace(/export /g,"");
compiled+="\nmodule.exports={App};";
const component=new Module(path.join(front,"src/review-memory.cjs"),module);
component.filename=path.join(front,"src/review-memory.cjs");
component.paths=Module._nodeModulePaths(path.join(front,"src"));
component.require=id=>{
 if(id==="./api") return api;
 if(id==="./navigation") return {usePage:()=>"knowledge",PageBoundary:({children})=>React.createElement(React.Fragment,null,children)};
 if(id.endsWith(".css")) return {};
 if(id.startsWith("./")) return new Proxy({}, {get:()=>()=>null});
 return req(id);
};
component._compile(compiled,component.filename);
(async()=>{
 const root=createRoot(document.getElementById("host"));
 await act(async()=>{root.render(React.createElement(component.exports.App));});
 const select=document.querySelector("select");
 await act(async()=>{select.value="kb";select.dispatchEvent(new dom.window.Event("change",{bubbles:true}));});
 const input=document.querySelector('input[type="file"]');
 Object.defineProperty(input,"files",{value:[new dom.window.File(["reference"],"x.txt",{type:"text/plain"})],configurable:true});
 await act(async()=>{input.dispatchEvent(new dom.window.Event("change",{bubbles:true}));});
 console.log(JSON.stringify({case:"knowledge_upload_currentTarget",uploads,knowledge_list_reads:loads,error:document.querySelector('[role="alert"]')?.textContent}));
 await act(async()=>{root.unmount();});
 dom.window.close();
})().catch(e=>{console.error(e);process.exitCode=1;});
}).catch(e=>{console.error(e);process.exitCode=1;});

~~~
