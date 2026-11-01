# 第一阶段工程质量与回归门禁

## 本地验证

GitHub Actions 全量测试命令执行 85% 行覆盖率门槛，项目依赖包含 `pytest-cov`。本地提交前运行：

```bash
python -m pytest --cov=app --cov-fail-under=85 -q
ruff check app tests
mypy --follow-imports=silent app
python -m compileall -q app tests
node --test tests/frontend/*.test.cjs
cd frontend && npm test && npm run build
git diff --check
```

当前完整 Python 回归：**306 passed, 2 skipped，覆盖率 86.33%**。两项跳过测试是隔离 MySQL 集成测试；本机没有可用的 MySQL 测试服务。另有一条来自已安装 Starlette/AnyIO 依赖的弃用警告。

隔离 MySQL 测试通过 `WALIAPI_TEST_MYSQL_SOCKET` 显式启用。测试会创建随机名称的临时库并在结束后清理，不应指向应用或生产数据库。远程模型服务没有参与上述自动化测试；网关和 Provider HTTP 行为由模拟响应覆盖。

## 已有回归范围

- 管理员会话、密码哈希、登录限流、API Key 到期和模型/渠道授权。
- 配额预占、重复请求幂等、结算、超限结算回退和释放。
- 请求 ID、网关重试计划、SSE 流、协议转换、安全扫描和日志持久化。
- KB 文档/分块/来源/任务仓储、导入边界、索引一致性、Worker 租约与失败恢复。
- Wiki 页面、附件、备份恢复、授权、MCP 工具、Software connector 和 Provider OAuth 生命周期。
- 迁移 SQL 解析、校验和及部分 SQLite/隔离 MySQL 行为验证。
- React 管理端 API 客户端及 Markdown 渲染安全测试；前端类型检查与生产构建。

85% 是全仓总覆盖率门槛，不代表每个模块均达到 85%。高风险和仍较低覆盖模块需在后续节点继续单独补测。没有 MySQL 服务时，不能将 SQLite 测试描述为真实 MySQL 验收。
