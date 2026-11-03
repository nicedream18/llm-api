# Ant Design 独立开发者落地页

本次基于安全功能分支 `f903922`，在独立 worktree `/Users/nicedream/xm/waliapi-antd-landing` 的 `codex/antd-ai-landing` 分支实现；原工作区的未提交改动不迁入、不覆盖。

## 页面与设计

- 参考 Linear.app 的克制排版、深色层次和留白；沿用 WaLiAPI 品牌与项目已有能力，使用原创文案和代码绘制的产品预览。
- 使用 Ant Design 6.6.8、@ant-design/icons 6.3.4，ConfigProvider.darkAlgorithm 及品牌 Token；Button、Segmented、Tag、Collapse、Drawer 提供实际组件交互。
- 近黑背景、灰白大标题、低饱和紫色细节、细边框和轻光晕；字体使用本机系统字体，无外部图片、字体或分析服务请求。
- 内容包括首屏、可切换产品预览、模型生态、三项能力、开发者示例、部署说明、常见问题与底部 CTA。演示明确标识为示例，不展示虚构客户、订阅价格或性能承诺。
- Python/cURL/Node.js 示例切换与复制，复制成功与失败分开反馈；移动端导航按需加载。遵循 reduced-motion、键盘焦点、跳转链接和单一 h1。

生产首页 `/` 返回新落地页，资源位于 `/landing/`。`/admin/` 继续使用既有 React 管理台，旧版 `/index.html` 保留。根页面和落地页静态资源无需会话或数据库查询，管理员 API 的鉴权保持有效。独立入口隔离样式，避免影响管理台。

开发：`cd frontend && npm ci && npm run dev:landing`，访问 `http://localhost:9902/landing/`。`npm run dev` 仍启动管理台。`npm run build` 同时生成两套页面；新增产物提交在 `app/static/landing/`。

## 验证（2026-11-03）

| 检查 | 结果 |
|---|---|
| React/Vitest | 14 文件、74 项通过；新增 5 项落地页测试 |
| 新交互场景 | 锚点/控制台链接、演示切换、不调用真实模型 API、三语言复制、失败反馈、移动导航及 FAQ |
| TypeScript、管理台构建、落地页构建 | 通过；管理台产物无变化 |
| 首页和认证回归 | 15 项通过；公开页面不初始化数据库容器，安全管理接口仍返回 401 |
| 后端全量（未启用 MySQL） | 715 通过、1 失败、17 跳过；失败仍为基线 test_managed_helper_process_identity_and_stop |
| 覆盖率 | 89.7988264878%，高于仓库基线 85.6299212598%；关键模块均达到基线 |
| Ruff、Mypy、compileall、旧前端 Node 测试、git diff --check | 通过；Node 6 项通过 |
| 真实浏览器 DOM 检查 | 首页和资源 200；390px 时 body 宽度 375px，无横向溢出；移动导航、演示状态及示例语言切换通过 |

完整全量输出与覆盖率保留在本 worktree 的 `data/landing-verification/`。本次未改数据库，不重复运行真实 MySQL；上一批已记录的 MySQL 并发失败仍是既有问题。全量门禁因本机进程身份校验失败，未记为通过。

构建仍有主 JS 包略超 Vite 500kB 提示（约 507kB，gzip 约 166kB），未放宽警告阈值；移动导航已拆为 约 24kB 的按需加载包。测试环境 JSDOM 对伪元素 getComputedStyle 有未实现提示，交互测试通过。

## 失败尝试与限制

- 首轮 TypeScript 构建因 JSX 代码示例中的花括号没有转义而失败（TS1005/TS1381）；改为字符串代码渲染后，类型检查与构建通过。
- agent-browser 截图调用持续超时，doctor 未报告安装错误；在仅含 SVG 的页面也复现。重建本次浏览器会话、JPEG 输出和独立 Chrome 捕获仍未获得截图。备用 Computer Use 浏览器宿主不可用（cgWindowNotFound）。因此本次没有将截图或像素视觉验收记为通过；实际完成了浏览器 DOM、计算样式、尺寸及交互检查。
- DevBugKB 已搜索依赖兼容、TS1005/TS1381、Chrome 截图超时。命中的 BUG-20261103-001、BUG-20261031-003、BUG-20261031-007、BUG-20261031-002 和 BUG-20261031-006 均不直接适用，没有照搬或提交知识库。

参考资料：[Linear](https://linear.app/)、[Ant Design Vite 集成](https://ant.design/docs/react/use-with-vite/)、[Ant Design 主题](https://ant.design/docs/react/customize-theme/)。
