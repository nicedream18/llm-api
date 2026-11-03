# 安全能力实施与验证记录

## 交付范围

基于 `5a73c89`，在 `/Users/nicedream/xm/waliapi-security-rules` 独立 worktree 的 `codex/security-rules-redaction` 分支实施。原工作区的知识库、渠道、管理台其他页面、会话认证修改没有迁入；高熵检测、027 迁移及对应测试作为必要依赖移入。未合并主分支，未强推，未操作生产数据库。

实现范围和首次升级行为见 [升级说明](upgrade.md)；教程 25 项行为与当前 60 条规则目录对应见 [对应表](rule-coverage.md)。流式响应和二进制附件扫描明确不在范围内。

## 基线及知识库检索

- 原始提交初次测试：610 passed / 1 failed / 15 skipped；失败为本机 ManagedService 进程身份校验 `Process command identity mismatch`。
- 原始 Ruff 通过；最初 Mypy 因缺少 requirements-observability.txt 中四个可选模块而失败。本分支新建虚拟环境并安装项目及可选遥测依赖，未修改原环境或降低检查要求。
- 在原始提交的第二个独立 worktree `/tmp/waliapi-security-baseline`，使用同一个隔离 MySQL，定向复现三项并发失败：route_capacity、usage_ledger、operational_alert。结果均失败，错误与功能分支一致。
- 已按 `/Users/nicedream/.agents/skills/bug-triage/SKILL.md` 搜索 DevBugKB：安全脱敏、AWS、白名单、私钥残留、显式脱敏动作、管理台 403、移动端布局。阅读 BUG-20261031-001（verified，MySQL 认证）与 BUG-20261102-001（unresolved，会话排序规则冲突）；后者被 admin/session 查询命中，但两案均不适用于本次安全脱敏问题，没有照搬。未提交或推送知识库。

## 验收覆盖

| 能力 | 验证位置及结果 |
|---|---|
| 目录、教程正反例、类别开关、元数据 | test_security.py、test_security_catalog.py；每个正则检测器均注册，结构化字段和高熵规则单独验证 |
| 幂等、补插、配置保留、恢复回滚 | test_security_repository.py；真实 MySQL 并发播种及历史主键保留见 test_security_mysql.py |
| 字面边界、局部豁免、冲突 | test_security_matching.py：伪装域名、子域、目录前缀、Windows/POSIX、工具名、显式黑名单及凭证；支持 OpenAI/Anthropic/Responses 结构化工具 |
| 递归脱敏、动作优先级 | test_security_redaction.py：深层容器、短密码、各格式凭证、完整/截断私钥、重复替换、重叠范围、实际变更标记、旧大写严重度及内置显式动作 |
| 实际 HTTP 请求内容 | test_security_forwarding.py：真实扫描器 + 真实 GatewayService + httpx MockTransport，检查四协议普通/流式请求的实际 body、原始字段拦截、日志安全和普通响应 |
| multipart | 同一转发测试检查重复文本字段顺序、文件内容逐字节相等、boundary/content-type 和 model；相等性比单纯哈希校验更强 |
| 策略保存及失败行为 | test_security_policy.py、test_security_forwarding.py；独立进程读取持久化值见 test_security_mysql.py，读取失败及扫描超限在连接上游前拒绝 |
| API | test_security_routes.py：未授权拒绝、非法输入、部分更新、CRUD 及恢复默认值；启动测试假容器随新启动流程更新 |
| 前端 | SecurityPage.test.tsx 6 项工作流；旧安全页 Node 测试 2 项；其他既有前端测试全部执行 |
| 真实浏览器 | agent-browser 连接本次随机 QA 数据库：登录、策略保存、刷新保持、创建 domain 白名单、失败反馈、深浅色桌面及 390px 手机检查 |
| MySQL | 独立本地 mysqld 26.7.0，禁用 TCP，只使用测试 socket；每个测试新建随机数据库，退出时删除。覆盖当前新库、旧规则升级、重复迁移、并发初始化、配置保留、跨进程读取 |

普通响应和请求使用同一策略快照；测试模拟处理中修改策略，确认只影响下个请求。超限不被当作 JSON 解析失败后继续扫描截断内容。所有新增功能均有对应回归测试。

## 失败尝试及修正

1. SSH 文件规则初稿将 id_ed25519.pubkey 视作私钥文件；正反例失败后加严边界并保留回归。
2. 高熵计数字典、脱敏范围数组缺少类型标注及新增导入排序曾导致静态检查失败；补齐标注和整理导入后通过。
3. 转发日志修改初稿使用了不存在的 response_body，10 项定向测试失败；改为实际 response_choices 后重新验证日志与响应路径。
4. 截断 PEM 初稿先替换头部，正文可能残留；加强测试为完整结果断言，先处理完整/截断块，再做格式替换。内置私钥显式脱敏同样覆盖完整正文。
5. 内置显式 redact 初稿仅触发自动凭证路径，没有对所有内置动作改写；使用目录检测器生成实际替换范围，保留局部白名单，并用实际 HTTP 上游测试验证。
6. 初次全量及 CI 的生命周期假容器没有新 security_repo，造成一项本次引入的测试失败；更新测试夹具后通过，未删除测试或修改其断言。
7. 手机浏览器初次发现 grid/fieldset 最小宽度导致横向溢出；局部 CSS 修正后 390px 视口 document.body.scrollWidth 为 375px（留有滚动条），无页面级溢出。
8. 随机端口 QA 服务初次未配置 CORS_ALLOWED_ORIGINS，写入返回 403；页面正确显示失败，配置本次测试 origin 后写入成功，未放宽认证逻辑。
9. 一轮全量与额外 MySQL 定向测试同时运行，争用项目全局迁移锁，额外触发 migration_lock 测试失败；保留该次结果，最终改为顺序执行数据库测试。

完整本机输出保留在 worktree 的 `data/security-verification/`（忽略目录，不推送凭证或环境状态），包括原始基线、原始 MySQL 复现和最终门禁；手机与桌面截图保留在该目录。最终结论以以下汇总为准，跳过不计通过。

## 分功能提交

| 批次 | 提交 | 内容 |
|---|---|---|
| 1 | a420a88 | 统一目录、播种、恢复默认值及高熵依赖 |
| 2 | e77663d | 教程检测补齐及对应表 |
| 3 | 054ae32 | 有边界的黑白名单和旧正则兼容 |
| 4 | 3571570 | 递归凭证脱敏与真实变更标记 |
| 5 | ed1eef7 | 策略持久化及实际转发脱敏 |
| 6 | 719b708 | React 安全管理及旧页面接口贯通 |
| 7 | 本文所在验收提交 | 真实 MySQL、跨进程/跨模块回归、验收发现修正、升级及验证记录 |

分支：[codex/security-rules-redaction](https://github.com/nicedream18/llm-api/tree/codex/security-rules-redaction)。

## 最终本地门禁（2026-11-03）

环境：macOS arm64、Python 3.13.9、Node 22.22.3、隔离 MySQL 26.7.0。

| 检查 | 结果 |
|---|---|
| 全量 pytest（真实 MySQL 开启） | 723 passed / 4 failed / 4 skipped；失败明细见下 |
| 安全功能定向集合（真实 MySQL 开启） | 106 passed，无跳过 |
| 全局覆盖率 | 90.2993208686%，基线 85.6299212598% |
| 7 个关键模块覆盖率 | 全部达到或超过基线，逐项数值见 coverage-results.json |
| Ruff app/tests/scripts | 通过 |
| Mypy app | 通过（120 文件；安装可选遥测依赖后执行） |
| Python compileall | 通过 |
| 旧前端 Node 测试 | 6 passed |
| React Vitest | 13 个文件、69 passed |
| TypeScript / 生产构建 | 通过；产物由隔离分支生成并提交 |
| git diff --check | 通过 |
| MySQL 专项 | 3 个安全专项通过，包括旧结构升级、并发播种和真正的另一个 Python 进程读取；全量其他 MySQL 失败见下 |

全量门禁命令：

```sh
PATH="$PWD/.venv/bin:$PATH" WALIAPI_TEST_MYSQL_SOCKET=/tmp/waliapi-security-mysql.sock \
  .venv/bin/python scripts/quality_gate.py
WALIAPI_TEST_MYSQL_SOCKET=/tmp/waliapi-security-mysql.sock \
  .venv/bin/python -m pytest tests/test_security*.py -q
```

`quality_gate.py` 在全量 pytest 的既有失败处退出，因此**整套门禁未通过**。其后续检查已用同样命令分别执行，通过并记录于上表；这不将整套门禁改记为通过。4 个跳过属于原有可选测试，不计通过。

| 既有失败 | 现象及证据 |
|---|---|
| test_local_service.py::test_managed_helper_process_identity_and_stop | macOS 子进程身份校验 ValueError；初始无 MySQL 基线即失败，运行中也偶发通过 |
| test_mysql_route_capacity_and_half_open_probe | InnoDB 并发死锁；在原始 5a73c89 定向复现 |
| test_mysql_usage_ledger_deduplication_and_decimal_prices | 并发去重写入冲突；在原始 5a73c89 定向复现 |
| test_mysql_operational_alert_deduplication_and_analytics | 并发写入冲突；在原始 5a73c89 定向复现 |

没有通过降低阈值、跳过失败测试或带入无关修复掩盖这些问题。

## 远端及 CI

前六批已逐批推送 origin。已检查 719b708 的 [quality 工作流](https://github.com/nicedream18/llm-api/actions/runs/41603085810)：frontend 通过，backend 失败。其生命周期测试夹具问题已在第七批修正；其余并发失败已按上文复现。最终提交的 CI 在推送后继续核对，实际结论随交付报告提供；[分支工作流列表](https://github.com/nicedream18/llm-api/actions?query=branch%3Acodex%2Fsecurity-rules-redaction) 可查看最新状态。未因本地覆盖率通过宣称 CI 全绿。
