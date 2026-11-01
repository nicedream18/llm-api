# 第一阶段可靠性改造

## 本地验证

```bash
python3 -m compileall -q app tests
pytest -q
python3 -m app.migrations validate
python3 -m app.migrations upgrade
```

迁移执行器使用 MySQL advisory lock、版本号和 SHA-256 校验和。重复执行 `upgrade` 是幂等的；`docs/waliapi.sql` 用于新库初始化，旧库由兼容迁移补齐字段。

## 运行配置

复制 `.env.example` 并在部署环境填写真实值。生产环境必须设置 `DB_PASSWORD`、`ADMIN_TOKEN`、至少 32 字符的 `ADMIN_SESSION_SECRET`，以及 `ADMIN_PASSWORD_HASH` 或首次初始化用的 `ADMIN_PASSWORD`。

管理员接口使用会话 Cookie 或 `Authorization: Bearer <ADMIN_TOKEN>`。网关和只读知识库接口使用下游 API Key；知识库写操作始终需要管理员权限。

## 已覆盖的关键路径

- 管理员会话、密码哈希、失败限流和审计。
- API Key 启用、过期、模型/渠道权限和 Token 配额预占、结算、释放。
- 请求 ID、统一错误结构、网关候选渠道、重试退避、SSE 转发和流生命周期。
- 安全扫描净化结果接入、响应扫描开关、自定义规则校验和 finding 持久化。
- 数据库任务 worker、租约续期、重启恢复、有限重试和取消。
- 迁移状态、升级、校验和详细健康检查。

当前仓库测试在本机通过；Docker daemon 未启动，因此 Docker MySQL/testcontainers 场景需要在 CI 或部署环境中执行。当前全仓覆盖率仍低于计划中的 85% 门槛，后续应继续为已有 KB、Agent、Importer、Index 和完整路由补齐集成测试后再将覆盖率门禁设为 85%。
