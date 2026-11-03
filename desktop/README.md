# WaLiAPI Python 桌面版

界面来自 /Users/nicedream/xm/waliapi-1 的桌面前端工作区快照（2026-11-03，源仓库 HEAD 为 5c9f1ee）。src、public 与原始 CSS 直接复制，再对 Python 接口和原生窗口做适配。上游许可保留在 LICENSE.upstream；macOS 图标来自该项目 src-tauri/icons/icon.icns。

## 启动

当前项目安装并构建后，可双击项目根目录的 start-desktop.command，或在终端执行：

    cd /Users/nicedream/xm/waliapi-python
    ./start-desktop.command

这会创建独立的 macOS WKWebView 桌面窗口。无需启动 Vite，也无需手动打开浏览器。运行时使用现有 .env、MySQL、管理员账号和数据目录。

首次安装或重新构建：

    .venv/bin/python -m pip install -r requirements-desktop.txt
    cd desktop
    npm ci
    npm run build
    cd ..
    .venv/bin/python -m app.desktop --check

默认在 127.0.0.1:9910 启动 Python 后端，窗口访问 localhost 的 /desktop/。可用 ./start-desktop.command --port 9911 或 DESKTOP_PORT 指定端口。已有同端口 WaLiAPI-Python 服务会被复用；关闭窗口只结束本窗口自行启动的后端。9910 与原有 9900 服务共享项目配置及数据库。

生成可双击的本机 App：

    .venv/bin/python -m scripts.build_desktop_launcher

输出 dist/WaLiAPI-Python-YYYYMMDD-HHMMSS.app，不覆盖旧版本。此包是引用当前项目、虚拟环境和 .env 的本机启动包，尚不是可复制到其他电脑独立安装的发行包。移动项目后须重新生成。构建脚本记录当前 Python 架构，避免 Finder 在 Apple Silicon 上以 Intel 模式加载 arm64 依赖。

## 接入范围

| 部分 | 当前状态 |
| --- | --- |
| 原生窗口、登录、侧栏和页面样式 | 已迁移，保留上游视觉设计；Python HttpOnly 管理员会话登录 |
| 仪表盘、Token 趋势和热力图 | 使用真实请求日志聚合，小时数据带 UTC 时区，兼容两种历史时间格式 |
| 渠道与密钥 | 基础增删改、启停、渠道测试、按需读取密钥、导入导出已适配；部分更新先读取原记录，保留其余字段 |
| 日志 | 查询、分页、时间与渠道等筛选、详情与清理基础接口已适配；风险等级规范化后再渲染 |
| 知识库 | 列表、基础管理、上传、文档状态、检索、问答、索引与会话接口已适配；PDF 上传保留扩展名 |
| Wiki | 列表、页面读取与保存、标签和图谱等部分接口已适配；高级摄入与项目模型配置尚未接入，拒绝保存以免丢失输入 |
| Provider 账号 | 列表、令牌刷新、模型同步、启停和删除已适配；上游 Rust 原生登录流程与凭据导入尚未接入 |
| 设置 | 安全设置和本窗口外观偏好；后端端口、代理、重试等仍由 Python 配置管理 |
| 原生文件与外链 | 系统选取/保存对话框；仅允许读取本窗口选中的文件，限制 32 MB；外链只允许 HTTP(S) |

源项目的页面代码复制过来不代表所有 Rust command 都已在 Python 实现。未接入的命令会明确抛出“Python 后端暂未支持此操作”，不会返回假保存结果。当前主要差异包括系统托盘/自启、Rust 自动更新、完整供应商预设、拖拽排序、客户端配置自动写入、Rust OAuth 流程、额外 Key 的单独管理、排除模型规则、部分高级 Wiki/知识库导入及备份操作、Skills 与部分 Link 操作。

缓存 Token、TTFT、请求消息构成、实时会话事件和原始 SSE 分段尚未由 Python 后端计量；页面顶部会说明限制。为兼容上游图表类型，少数缺失数值仍使用零占位，不应据此判断实际缓存命中率或首字延迟。今日缓存卡片明确显示“未计量”。

## 代码位置

- app/desktop.py：桌面窗口、后端进程生命周期、文件桥。
- src/lib/runtime.ts、python-api.ts、native.ts：Rust command 到 Python REST/原生桥的适配。
- app/api/controllers/desktop_routes.py：受现有管理员认证保护的统计、日志与按需密钥读取接口。
- app/static/desktop：Vite 生产构建，供桌面窗口加载。
- scripts/smoke_desktop.py：实际 WKWebView 冒烟检查。仅该测试脚本提供测试凭据桥，正式桌面入口没有该方法。

## 验证与故障记录

验证命令：

    PATH="$PWD/.venv/bin:$PATH" .venv/bin/pytest -q
    .venv/bin/ruff check app tests scripts
    .venv/bin/mypy --follow-imports=silent app/desktop.py app/api/controllers/desktop_routes.py
    cd desktop && npm test && npm run build
    cd .. && .venv/bin/python -m scripts.smoke_desktop

原生冒烟测试使用配置中的已有管理员凭据登录，依次打开渠道、Provider、密钥、日志、安全设置、RAG、Wiki、MCP，并截取本测试窗口；不调用收费模型，也不修改既有渠道、密钥或业务数据。截图在 logs/desktop-smoke-时间戳下。正常登录产生的会话/审计记录属于后端既有行为。

2026-11-03 最终验证结果：Python 全量测试 638 通过、17 跳过；前端测试 29 通过；TypeScript/Vite 生产构建、全项目 Ruff、新增 app 模块 mypy 和 git diff --check 均通过。实际 WKWebView 使用管理员 Cookie 登录，8 个页面冒烟检查通过，未记录到失败的接口请求。仪表盘与 Wiki 的可见窗口截图已人工检查，证据保存在 logs/desktop-smoke-20261103-202307/。本机启动包 dist/WaLiAPI-Python-20261103-201509.app 的 --check --port 9912 检查通过。

若仍开着迁移过程中的旧测试窗口，请先关闭旧窗口，再打开最新 App，以便使用更新后的后端代码。

保留的排查经过：

1. 初次类型检查仍引用 Rust updater-config.json：Python 版禁用上游二进制更新源后构建通过。
2. Vitest 将复制来的 Node 原生 .test.mjs 误判为空测试：改为分别运行 Vitest 和 node --test，两类测试均通过。
3. 初次 Python 回归有两项子进程找不到 python：以虚拟环境 PATH 复跑通过，未改业务模块。
4. 初次 Finder App 启动以 x86_64 加载 arm64 pydantic_core 而失败：启动器显式指定构建架构后，App 成功启动原生窗口。旧启动包及日志保留，正式使用新时间戳产物。
5. 验证中修正服务路由复用导致 Wiki 标签不切换、历史日期格式及风险等级大小写的契约差异，并补充回归测试。
6. 一次全量回归的既有 test_managed_helper_process_identity_and_stop 报 Process command identity mismatch；单独复跑及后续全量回归通过，未修改该业务模块。已检索 DevBugKB，无直接匹配案例。
7. 冒烟截图最初出现窗口不可见及背景空白，但 DOM 检查通过；测试脚本改为在截图前恢复、显示测试窗口，并等待可见状态及两次渲染帧后，仪表盘和 Wiki 截图均正常。失败截图与记录保留在原 logs 目录，未作为视觉通过证据。已检索 DevBugKB，无直接匹配案例。

已按项目要求检索 DevBugKB。泛匹配返回 BUG-20261103-001、BUG-20261102-001、BUG-20261102-002 等，但没有直接匹配本次桌面迁移、测试运行器或 Finder 架构问题的案例，未照搬其修复。未提交或推送知识库案例。

全量 mypy 仍有 6 项错误：遥测模块 4 项可选 OpenTelemetry 依赖缺失，以及既有 app/domain/security.py 和 app/infrastructure/repositories/security_repo.py 各 1 项类型错误，需另行处理；本次新增 app 模块单独类型检查通过。
