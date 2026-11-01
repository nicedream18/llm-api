# WaLiAPI-Python — AI 网关与知识库平台（Python 版）

> 与 [WaLiAPI-Java](https://github.com/fuzhengwei/WaLiAPI-Java) 功能对等的 Python 实现，采用 FastAPI + DDD 分层架构。
>
> 作者：小傅哥 [bugstack.cn](https://bugstack.cn)

---

## 📖 目录

1. [项目简介](#项目简介)
2. [架构设计](#架构设计)
3. [技术栈](#技术栈)
4. [项目结构](#项目结构)
5. [功能模块](#功能模块)
6. [快速启动](#快速启动)
7. [配置说明](#配置说明)
8. [API 端点](#api-端点)
9. [数据库设计](#数据库设计)
10. [与 Java 版对照](#与-java-版对照)
11. [学习指南](#学习指南)
12. [Docker 部署](#docker-部署)

---

## 项目简介

WaLiAPI-Python 是 WaLiAPI-Java 的 Python 对等实现。将多种 AI 能力（OpenAI、Anthropic、自定义渠道等）聚合到统一网关入口，提供渠道管理、密钥管理、安全扫描、知识库 RAG、Agent 对话等完整功能。

**核心能力：**
- 🔀 **多渠道路由**：10 种渠道类型，优先级 + 加权随机调度
- 🔒 **安全扫描**：6 个子扫描器，约 40 条正则规则，支持 audit/block/redact 模式
- 📚 **知识库 RAG**：文档上传→分块→向量化→混合检索→LLM 回答，支持深度研究（多轮追问）
- 🔍 **HNSW 索引**：纯 Python 实现的 HNSW 向量索引（与 Java 版参数一致）
- 📥 **导入策略**：Git 仓库 / URL / 本地目录三种导入方式
- 🔄 **协议转换**：OpenAI ↔ Anthropic ↔ Responses 三种协议自动检测与转换
- 📊 **仪表盘**：请求统计、健康评分、日志查询

**适合学习：**
- DDD 分层架构在 Python 项目中的实践
- FastAPI 异步 Web 框架的企业级使用
- AI 网关的设计与实现（协议转换、渠道调度、安全扫描）
- RAG 知识库的完整实现（分块、向量化、检索、HNSW 索引）
- Java → Python 的架构迁移对照

---

## 架构设计

### DDD 分层架构图

```
                        ┌──────────────────────────────────────────────────────┐
                        │              API Layer（API 层）                       │
                        │  routes.py（8 个 Router 合一）                        │
                        │  Gateway · Channel · ApiKey · Dashboard                │
                        │  KB · Agent · Security · MCP                           │
                        │  + ApiKeyAuthMiddleware（API Key 认证）                 │
                        └──────────────────┬────────────────────────────────────┘
                                           │
                        ┌──────────────────▼────────────────────────────────────┐
                        │          Application Layer（应用层）                    │
                        │  ChannelService · DashboardService                    │
                        │  KbService · SecurityService · AgentService           │
                        │  ProxyService · McpService                            │
                        │  职责：编排领域服务，DTO ↔ Entity 转换                   │
                        └──────────────────┬────────────────────────────────────┘
                                           │
                        ┌──────────────────▼────────────────────────────────────┐
                        │       Domain Layer（领域层 — 核心业务逻辑）              │
                        │                                                       │
                        │  ┌──────────┐ ┌───────────┐ ┌────────────┐           │
                        │  │ Gateway  │ │Dispatcher │ │ Security   │           │
                        │  │ Service  │ │ (调度器)   │ │ Scanner    │           │
                        │  └──────────┘ └───────────┘ └────────────┘           │
                        │  ┌──────────┐ ┌───────────┐ ┌────────────┐           │
                        │  │ knowledge│ │ protocol  │ │  agent_    │           │
                        │  │ .py      │ │ .py       │ │  service   │           │
                        │  │ 分块/嵌入/│ │ 协议检测+  │ │ .py        │           │
                        │  │ 检索/RAG  │ │ 转换器    │ │            │           │
                        │  └──────────┘ └───────────┘ └────────────┘           │
                        │  ┌──────────┐ ┌───────────┐ ┌────────────┐           │
                        │  │ importer │ │ index_    │ │ responses_ │           │
                        │  │ .py      │ │ service   │ │ converter  │           │
                        │  │ 导入策略  │ │ .py HNSW  │ │ .py        │           │
                        │  └──────────┘ └───────────┘ └────────────┘           │
                        └──────────────────┬────────────────────────────────────┘
                                           │
                        ┌──────────────────▼────────────────────────────────────┐
                        │       Infrastructure Layer（基础设施层）                │
                        │  database/connection.py (SQLAlchemy 连接池)            │
                        │  repositories/ (5 个仓储：channel/log/kb/agent/security)│
                        │  adapters/http_adaptors.py (10 种渠道 HTTP 适配)        │
                        └───────────────────────────────────────────────────────┘
```

### 架构原则

| 原则 | 说明 |
|------|------|
| **领域层纯逻辑** | `domain/` 下无 FastAPI/SQLAlchemy 依赖，可独立测试 |
| **依赖注入** | `container.py` 单例容器，启动时装配所有依赖 |
| **DTO 隔离** | `types/models.py` 用 Pydantic 定义全部 DTO，与领域 Entity 分离 |
| **仓储模式** | `infrastructure/repositories/` 封装所有数据库操作 |

### Java vs Python 架构对照

| 层级 | Java | Python |
|------|------|--------|
| 入口 | `Application.java` (@SpringBootApplication) | `main.py` (FastAPI app) |
| 装配 | `DomainConfiguration.java` (@Bean) | `container.py` (手动 new + lru_cache) |
| 路由 | 10 个 Controller 类 | `routes.py` 8 个 APIRouter |
| 用例层 | 7 个 ServiceCase 类 | application/services/ 下 3 个文件 |
| 领域层 | 109 个 Java 文件 | 9 个 .py 文件 |
| 持久层 | DAO 接口 + PO + MyBatis XML | Repository 类 + raw SQL |
| DTO | 32 个 Java DTO | 1 个 models.py 集中定义 |

---

## 技术栈

| 技术 | 版本 | 用途 |
|------|------|------|
| **FastAPI** | 0.115.6 | 异步 Web 框架 |
| **Uvicorn** | 0.34.0 | ASGI 服务器 |
| **SQLAlchemy** | 2.0.36 | 数据库连接池（raw SQL，不用 ORM） |
| **PyMySQL** | 1.1.1 | MySQL 驱动 |
| **httpx** | 0.28.1 | HTTP 客户端（同步 + 流式） |
| **Pydantic** | 2.10.4 | DTO 数据验证 |
| **sse-starlette** | 2.2.1 | SSE 流式响应 |
| **python-dotenv** | 1.0.1 | 环境变量加载 |

---

## 项目结构

```
WaLiAPI-Python/
├── app/
│   ├── main.py                    # FastAPI 应用入口
│   ├── config.py                  # 配置（从环境变量加载）
│   ├── container.py               # 依赖注入容器（装配所有服务）
│   │
│   ├── types/                     # 类型层
│   │   ├── enums.py               # ResponseCode, ChannelType, ProtocolFormat, RiskLevel
│   │   ├── response.py            # 统一 Response 包装 + AppException
│   │   └── models.py              # 全部 DTO（Pydantic models）
│   │
│   ├── domain/                    # 领域层（核心业务逻辑，无框架依赖）
│   │   ├── entities.py            # 所有领域实体（dataclass）
│   │   ├── dispatcher.py          # 渠道调度：优先级分组 + 加权随机
│   │   ├── protocol.py            # 协议检测（OpenAI/Anthropic/Responses）
│   │   ├── gateway.py             # 网关代理：同步/流式转发
│   │   ├── security.py            # 安全扫描：6 个子扫描器
│   │   ├── knowledge.py           # 知识库：分块/嵌入/检索/RAG/搜索回退
│   │   ├── agent_service.py       # Agent 对话服务
│   │   ├── importer.py            # 导入策略：Git/Url/LocalDir + FileWalker
│   │   ├── index_service.py      # HNSW 向量索引（纯 Python 实现）
│   │   └── responses_converter.py # Responses API ↔ OpenAI 转换器
│   │
│   ├── infrastructure/            # 基础设施层
│   │   ├── database/connection.py # SQLAlchemy 连接池
│   │   ├── adapters/http_adaptors.py  # 10 种渠道 HTTP 适配器
│   │   └── repositories/          # 5 个仓储
│   │       ├── channel_repo.py
│   │       ├── log_repo.py
│   │       ├── kb_repo.py
│   │       ├── agent_repo.py
│   │       └── security_repo.py
│   │
│   ├── application/               # 应用层
│   │   └── services/
│   │       ├── channel_dashboard.py  # ChannelService + DashboardService
│   │       ├── kb_service.py         # KbService（知识库应用服务）
│   │       └── misc_services.py      # SecurityService + AgentService + ProxyService + McpService
│   │
│   ├── api/                       # API 层
│   │   ├── controllers/routes.py  # 全部路由（8 个 APIRouter）
│   │   └── middleware/auth.py    # API Key 认证中间件
│   │
│   └── static/                    # 前端静态资源（与 Java 版共用）
│
├── docs/
│   └── waliapi.sql                # 建表 SQL
├── requirements.txt
├── start.sh                       # 启动脚本
├── Dockerfile
└── README.md
```

仓库包含 FastAPI 后端、React/TypeScript 管理端、版本化数据库迁移和 Python/前端自动化测试。当前能力边界及未完成事项见 [`docs/part1-review.md`](docs/part1-review.md)。

---

## 功能模块

### 1. 网关代理（Gateway）

```
客户端请求 → ProtocolDetector 协议检测 → SecurityScanner 安全扫描
    → [Responses 协议自动转换] → Dispatcher 渠道调度 → GatewayService 转发
    → [响应转换回 Responses 格式] → LogRepository 记录日志
```

**支持协议：**
| 协议 | 端点 | 说明 |
|------|------|------|
| OpenAI | POST /v1/chat/completions | Chat Completions（支持 SSE 流式） |
| OpenAI | POST /v1/completions | 文本补全 |
| Responses | POST /v1/responses | Responses API（自动转换为 OpenAI 格式转发） |
| Anthropic | POST /v1/messages | Claude Messages API |
| OpenAI | POST /v1/embeddings | 嵌入 |
| OpenAI | POST /v1/images/generations | 图片生成 |
| OpenAI | POST /v1/audio/transcriptions | 语音转文字 |
| OpenAI | POST /v1/audio/speech | 文字转语音 |
| — | GET /v1/models | 根据启用渠道和 Provider 映射动态聚合；按 API Key 权限过滤 |
| — | GET /health | 健康检查 |

### 2. 渠道调度（Channel & Dispatcher）

```
请求进来 → 按优先级取渠道组 → 组内加权随机 → 选中渠道 → 转发
    ↓ 如果失败
    重试（可配置次数）→ 下一渠道
```

配置可选择 OpenAI 兼容、Anthropic、Gemini、Ollama 等渠道类型；除专用实现外，其他类型按 OpenAI 兼容格式处理，特殊供应商需确认其上游 API 是否兼容。

适配逻辑集中在 `app/infrastructure/adapters/channel_adapters.py`。当前有 OpenAI 兼容、Anthropic、Gemini 和 Ollama 适配器；不要将配置项存在误解为已完成每家供应商的协议验证。

### 3. 安全扫描（Security）

6 个子扫描器并行扫描请求内容：

| 扫描器 | 检测内容 | Java 对应 |
|--------|----------|-----------|
| CredentialScanner | API Key、Token、密码、私钥 | CredentialScanner |
| PathScanner | 文件路径、目录遍历 | PathScanner |
| UnicodeScanner | 零宽字符、RTL 覆写 | UnicodeScanner |
| NetworkScanner | IP、URL、域名 | NetworkScanner |
| ToolRiskScanner | 工具调用注入 | ToolRiskScanner |
| TrackingScanner | 追踪参数、指纹 Cookie | TrackingScanner |

**模式：**
- `audit` — 仅记录安全发现，不阻止请求
- `block` — Critical 风险时返回 403 阻止请求
- `redact` — High/Critical 风险时净化敏感信息

### 4. 知识库 RAG（Knowledge）

```
上传文档 → TextSplitter 分块 → EmbedderService 向量化 → 存入 kb_chunks
    ↓
提问 → 向量化查询 → RetrieverService 检索 → RagContextBuilder 构建上下文
    → LLM 回答 → 返回答案 + 来源引用
```

**核心组件（均在 `domain/knowledge.py` 中）：**

| 组件 | 功能 | 关键参数 |
|------|------|----------|
| TextSplitter | 文本分块 | chunk_size=512, overlap=50, Markdown 标题分块 |
| EmbedderService | 向量化 | 小端 float32 序列化，通过网关转发 |
| RetrieverService | 检索 | vector / keyword / hybrid(0.7+0.3)，CJK 全文搜索 |
| RagContextBuilder | 上下文构建 | 模型上下文限制映射，裁剪保留头 1/3 + 尾 2/3 |
| RagService | RAG 问答 | ask / ask_with_config / deep_research |

**搜索策略回退**（对齐 Java SearchStrategyFactory）：
- 请求 vector 或 hybrid 模式 → 失败或空结果 → 自动回退 keyword 搜索

**深度研究（deep_research）：**
- 多轮追问（默认 3 轮）
- 每轮：检索 → 生成回答 → 提取后续问题 → 继续检索
- 按 chunk_id 去重，取前 top_k

### 5. HNSW 索引（`domain/index_service.py`）

纯 Python 实现的 HNSW（Hierarchical Navigable Small World）向量索引：

| 参数 | 值 | 说明 |
|------|-----|------|
| maxM | 16 | 每层最大连接数 |
| efConstruction | 200 | 构建时搜索宽度 |
| efSearch | 50 | 查询时搜索宽度 |
| 距离 | 1-余弦相似度 | 余弦距离 |

- `build_index()` — 构建索引并序列化到文件
- `search_with_index()` — 使用索引加速向量搜索
- `drop_index()` — 清除索引
- 索引元数据存储在 `kb_index_meta` 表

### 6. 导入策略（`domain/importer.py`）

| 策略 | sourceType | 说明 |
|------|------------|------|
| GitImportStrategy | git | git clone --depth 1 --branch，遍历后清理临时目录 |
| UrlImportStrategy | url | httpx GET 下载文件，User-Agent: WaLiAPI/1.0 |
| LocalDirImportStrategy | local_dir | 遍历本地目录 |

**FileWalker**（文件遍历器）：
- 忽略目录：.git, node_modules, target, __pycache__, .idea, .vscode 等
- 支持扩展名：md, txt, json, yaml, xml, csv, py, java, js, ts, go, rs 等 30+
- 默认最大文件：512KB

### 7. Responses 协议转换（`domain/responses_converter.py`）

双向转换 Responses API ↔ OpenAI Chat Completions：

| 方向 | 转换规则 |
|------|----------|
| Responses → OpenAI | input → messages, max_output_tokens → max_tokens, instructions → system, tools flat → nested |
| OpenAI → Responses | choices[0] → output items, tool_calls → function_call, usage 映射 |

集成在 `ProxyService.forward()` 中：检测到 responses 协议时，转发前转换请求体，返回前转换响应体。

### 8. 仪表盘 & 日志

- **健康评分**（对齐 Java StatsService）：
  - 初始 100 分
  - errorRate > 5% → -30 分
  - errorRate > 20% → 直接置 40 分
  - avgDurationMs > 5000ms → -20 分
  - activeChannels == 0 → 置 0 分
  - 徽标：≥90 healthy / ≥70 warning / 否则 critical

---

## 快速启动

### 前置条件

- Python 3.11+
- MySQL 8.0+（或使用 Docker）

### 1. 克隆项目

```bash
git clone <repo-url>
cd WaLiAPI-Python
```

### 2. 安装依赖

```bash
pip install -r requirements.txt
```

依赖列表：
```
fastapi==0.115.6
uvicorn[standard]==0.34.0
sqlalchemy==2.0.36
pymysql==1.1.1
cryptography==44.0.0
httpx==0.28.1
pydantic==2.10.4
python-dotenv==1.0.1
sse-starlette==2.2.1
```

### 3. 初始化数据库

```bash
# 使用已有 MySQL
mysql -u root -p < docs/waliapi.sql

# 或使用 Docker 启动 MySQL（与 Java 版共用同一套基础设施）
cd /path/to/WaLiAPI-Java/docs/dev-ops
docker-compose -f docker-compose-environment-aliyun.yml up -d
```

### 4. 配置

创建 `.env` 文件（或使用环境变量）：

```bash
# 数据库
DB_HOST=127.0.0.1
DB_PORT=3306
DB_NAME=waliapi
DB_USER=waliapi
DB_PASSWORD=<set-in-deployment>

# 服务
SERVER_PORT=9900
APP_ENV=development

# 管理员（首次启动 ADMIN_PASSWORD 用于初始化；生产建议预先配置密码哈希）
ADMIN_USERNAME=admin
ADMIN_PASSWORD=<temporary-bootstrap-password>
ADMIN_TOKEN=<long-random-token>
ADMIN_SESSION_SECRET=<at-least-32-random-characters>
PROVIDER_TOKEN_KEY=<long-random-encryption-key>
CORS_ALLOWED_ORIGINS=http://localhost:9900

# 安全
SECURITY_ENABLED=true
SECURITY_MODE=audit

# 日志
LOG_LEVEL=info
```

### 5. 启动

```bash
# 方式一：启动脚本
./start.sh

# 方式二：直接运行
python -m uvicorn app.main:app --host 0.0.0.0 --port 9900

# 方式三：开发模式（热重载）
python -m uvicorn app.main:app --host 0.0.0.0 --port 9900 --reload
```

### 6. 验证

```bash
# 健康检查
curl http://localhost:9900/health
# {"status":"ok","service":"WaLiAPI-Python","version":"1.0.0"}

# 登录管理后台后在浏览器使用管理员界面。管理 API 要求管理员会话或 ADMIN_TOKEN。
# 网关请求使用已创建的下游 API Key，例如：
curl http://localhost:9900/v1/models -H "Authorization: Bearer <downstream-api-key>"

# 标准 MCP 使用 POST /mcp；配置 MCP_TOKEN 后通过 Authorization: Bearer <mcp-token> 调用。
```

---

## 配置说明

### config.py

所有配置通过环境变量加载，有合理默认值：

```python
# 数据库
DB_HOST=192.168.1.108       # MySQL 地址
DB_PORT=13306               # MySQL 端口
DB_NAME=waliapi             # 数据库名
DB_USER=root                # 用户名
DB_PASSWORD=123456          # 密码
DB_POOL_SIZE=15             # 连接池大小
DB_MAX_OVERFLOW=10          # 连接池溢出

# 服务
SERVER_PORT=9900            # 服务端口

# 网关
GATEWAY_RETRY_TIMES=2      # 网关重试次数

# 安全
SECURITY_ENABLED=true       # 启用安全扫描
SECURITY_MODE=audit         # audit / block / redact
SCAN_UNICODE=true           # Unicode 扫描
SCAN_TOOLS=true             # 工具风险扫描
SCAN_NETWORK=true           # 网络信息扫描
SCAN_RESPONSE=false         # 响应扫描
REDACT_SECRETS=true         # 净化密钥
BLOCK_ON_CRITICAL=true      # Critical 风险阻止

# 日志
LOG_LEVEL=info              # 日志级别
```

---

## API 端点

### 网关代理（需 API Key 认证）

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | /v1/chat/completions | OpenAI 聊天（支持流式） |
| POST | /v1/completions | 文本补全 |
| POST | /v1/responses | Responses API（自动协议转换） |
| POST | /v1/messages | Anthropic Messages |
| POST | /v1/embeddings | 嵌入 |
| POST | /v1/images/generations | 图片生成 |
| POST | /v1/audio/transcriptions | 语音转文字 |
| POST | /v1/audio/speech | 文字转语音 |
| GET | /v1/models | 模型列表 |
| GET | /health | 健康检查 |

### 管理后台

| 方法 | 路径 | 说明 |
|------|------|------|
| GET/POST/PUT/DELETE | /api/v1/channels | 渠道管理 |
| GET/POST/PUT/DELETE | /api/v1/api-keys | API Key 管理 |
| GET | /api/v1/dashboard | 仪表盘统计 |
| GET/DELETE | /api/v1/logs | 请求日志 |
| GET/POST/PUT/DELETE | /api/v1/kb | 知识库 CRUD |
| POST | /api/v1/kb/{id}/ask | RAG 问答 |
| POST | /api/v1/kb/{id}/deep-research | 深度研究 |
| POST | /api/v1/kb/{id}/search | 知识库搜索 |
| GET | /api/v1/kb/{id}/stats | 知识库统计 |
| DELETE | /api/v1/kb/{id}/conversations | 清空对话 |
| POST | /api/v1/kb/{id}/documents/{docId}/reindex | 文档重索引 |
| GET | /api/v1/kb/{id}/documents/{docId} | 文档详情 |
| GET/POST/DELETE | /api/v1/kb/{id}/index | 索引管理 |
| GET/POST/DELETE | /api/v1/kb/{id}/sources | 来源管理 |
| GET/POST | /api/v1/kb/{id}/tags | 标签管理 |
| GET/POST/PUT/DELETE | /api/v1/agents | Agent 管理 |
| GET/PUT | /api/v1/security/rules/* | 安全规则 |
| GET | /api/v1/security/findings | 安全发现 |
| GET/POST/PUT/DELETE | /api/v1/wiki/* | Wiki 项目、页面、来源、附件、图谱与备份 |
| GET/POST/PUT/DELETE | /api/v1/software/* | Software 实例、工具、启停、调用与调用记录 |
| GET/POST/PUT/DELETE | /api/v1/providers/* | Provider 账户、OAuth、Token、配额与模型 |
| GET/POST/PUT/DELETE | /api/v1/platform/* | Prompt、语义缓存和客户端配置 |
| GET/POST/DELETE | /api/v1/access/* | 按资源和主体配置授权 |
| POST | /api/v1/auth/login | 管理员登录并建立会话 |
| POST | /mcp | 标准 MCP JSON-RPC Streamable HTTP 入口 |
| GET/POST | /api/mcp/* | MCP 兼容 REST 入口与审计查询 |

---

## 数据库设计

新库初始化使用 `docs/waliapi.sql`。现有库升级由 `docs/migrations/` 下带版本与校验和的迁移完成；迁移覆盖渠道及多 Key、管理员和 API Key 配额、请求日志与网关尝试、安全发现、KB/Wiki、资源授权、Software、Provider、Prompt 和语义缓存等数据域。Python 与其他语言版本使用的 SQL/schema 不应假定完全相同。

## 与其他 WaLiAPI 实现的关系

本仓库提供可独立运行的 Python 实现，不承诺与 Rust/Java 版本的功能或 API 完全对等。已实现范围、测试证据及尚未完成项见 [`docs/part1-review.md`](docs/part1-review.md) 和 [`docs/part1-progress.md`](docs/part1-progress.md)。

### 技术信息

| 方面 | Java 版 | Python 版 |
|------|---------|-----------|
| 语言 | Java 17 | Python 3.11 |
| 框架 | Spring Boot 3.4.3 | FastAPI 0.115.6 |
| ORM | MyBatis 3.0.4 | SQLAlchemy 2.0 (raw SQL) |
| HTTP 客户端 | OkHttp | httpx |
| JSON | Fastjson 2.0.28 | 标准库 json |
| DTO | Java 数据类 | app/types/ 下按功能拆分的 Pydantic 模型 |
| 依赖注入 | Spring @Bean | 手动 Container + lru_cache |
| 异步工作 | Spring @Async | asyncio 与 `asyncio.to_thread` |
| 流式响应 | WebFlux SSE | SSE codec 与异步流转发 |
| 架构状态 | 与 Python 项目分别维护 | FastAPI、SQLAlchemy、React/TypeScript |

---

## 学习指南

### 推荐阅读顺序

1. **入门**：`main.py`（入口）→ `config.py`（配置）→ `container.py`（依赖装配，理解服务如何串联）
2. **网关流程**：`routes.py`（Gateway 路由）→ `misc_services.py`（ProxyService）→ `protocol.py`（协议检测）→ `security.py`（安全扫描）→ `dispatcher.py`（渠道调度）→ `gateway.py`（转发）
3. **知识库**：`routes.py`（KB 路由）→ `kb_service.py`（应用服务）→ `knowledge.py`（领域核心：分块/嵌入/检索/RAG）→ `index_service.py`（HNSW 索引）→ `importer.py`（导入策略）
4. **协议转换**：`protocol.py`（检测）→ `responses_converter.py`（Responses 转换）
5. **安全扫描**：`routes.py`（Security 路由）→ `misc_services.py`（SecurityService）→ `security.py`（6 个子扫描器）
6. **数据层**：`database/connection.py`（连接池）→ `repositories/`（5 个仓储，看 raw SQL 怎么写）

### Java → Python 对照学习

| 想学什么 | 先看 Java | 再看 Python | 对照点 |
|----------|-----------|-------------|--------|
| DDD 装配 | DomainConfiguration.java | container.py | Bean 装配 vs 手动 new |
| 网关代理 | ProxyServiceCase + ProxyService | misc_services.py ProxyService | 同步/流式转发 |
| 协议检测 | ProtocolDetector.java | protocol.py | 静态方法 vs 模块函数 |
| 安全扫描 | SecurityScanner + 6 子扫描器 | security.py | 类继承 vs 同文件 |
| 知识库 | TextSplitter/Embedder/Retriever/RagService | knowledge.py | 4 个类合一文件 |
| 搜索策略 | SearchStrategyFactory + 3 策略 | knowledge.py search_by_mode | 策略模式 vs 方法内分支 |
| HNSW | HnswIndex.java + IndexService | index_service.py | Java 对象 vs Python 类 |
| 导入策略 | 3 ImportStrategy + FileWalker | importer.py | 策略接口 vs 函数分发 |
| 仓储 | DAO 接口 + PO + MyBatis XML | repositories/*.py | MyBatis vs raw SQL |

### 关键设计模式

| 模式 | 使用场景 | Java 位置 | Python 位置 |
|------|----------|-----------|-------------|
| 策略模式 | 搜索策略 / 导入策略 | SearchStrategyFactory / ImportStrategy | knowledge.py / importer.py |
| 工厂模式 | Agent 构建器注册表 | AgentArmoryService | ❌（未实现装配框架） |
| 适配器模式 | 10 种渠道 HTTP 适配 | IChannelAdaptor 实现 | http_adaptors.py |
| 依赖倒置 | Domain port → Infrastructure adapter | IDao → DAO 实现 | Repository 类 |
| 单例模式 | 容器 | Spring @Bean（默认单例） | @lru_cache(maxsize=1) |

---

## Docker 部署

### 基础设施

```bash
# 使用 Java 版提供的 Docker Compose（共用 MySQL 等基础设施）
cd /path/to/WaLiAPI-Java/docs/dev-ops
docker-compose -f docker-compose-environment-aliyun.yml up -d
```

### 应用容器

```bash
# 构建镜像
docker build -t waliapi-python:1.0.0 .

# 运行
docker run -d \
  --name WaLiAPI-Python \
  -p 9900:9900 \
  -e DB_HOST=192.168.1.108 \
  -e DB_PORT=13306 \
  -e DB_PASSWORD=123456 \
  waliapi-python:1.0.0
```

### Dockerfile

```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
EXPOSE 9900
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "9900"]
```

---

## License

Apache License 2.0
