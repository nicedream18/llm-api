import { SoftwarePage } from "./SoftwarePage";
import { KnowledgePage } from "./KnowledgePage";
export { KnowledgePage } from "./KnowledgePage";
import { DashboardPage } from "./DashboardPage";
import { FormEvent, useEffect, useState, type ReactNode } from "react";
import { del, get, post, put } from "./api";
import type { AccessGrant, ClientConfig, PromptTemplate } from "./types";
import { WikiManager } from "./WikiManager";
import { ProviderManager } from "./ProviderManager";
import { McpManager } from "./McpManager";
import { OperationsPage } from "./OperationsPage";
import { ChannelManager } from "./ChannelManager";
import { ApiKeyManager } from "./ApiKeyManager";
import { RoutingManager } from "./RoutingManager";
import { LogManager } from "./LogManager";
import { AdministrationPanel } from "./AdministrationPanel";
import { PageBoundary, usePage } from "./navigation";
import "./styles.css";
import "./software.css";
import "./admin.css";
import "./console-refresh.css";

export type Page = "dashboard" | "channels" | "api-keys" | "routing" | "logs" | "software" | "providers" | "wiki" | "knowledge" | "mcp" | "operations" | "settings";
type IconName = "overview" | "chart" | "channels" | "key" | "route" | "logs" | "knowledge" | "wiki" | "tools" | "accounts" | "mcp" | "settings";
type NavItem = { id: Page; label: string; icon: IconName };
export const navigationGroups: Array<{ label: string; items: NavItem[] }> = [
  { label: "概览", items: [{ id: "dashboard", label: "仪表盘", icon: "overview" }, { id: "operations", label: "运营统计", icon: "chart" }] },
  { label: "模型网关", items: [{ id: "channels", label: "渠道", icon: "channels" }, { id: "api-keys", label: "访问密钥", icon: "key" }, { id: "routing", label: "路由", icon: "route" }, { id: "logs", label: "请求日志", icon: "logs" }] },
  { label: "知识与工具", items: [{ id: "knowledge", label: "知识库", icon: "knowledge" }, { id: "wiki", label: "Wiki", icon: "wiki" }, { id: "software", label: "工具集成", icon: "tools" }, { id: "mcp", label: "MCP 调试", icon: "mcp" }] },
  { label: "系统管理", items: [{ id: "providers", label: "上游账号", icon: "accounts" }, { id: "settings", label: "系统设置", icon: "settings" }] },
];
export const nav: Array<[Page, string]> = navigationGroups.flatMap(group => group.items.map(({ id, label }) => [id, label]));

const pageDescriptions: Record<Page, string> = {
  dashboard: "查看网关运行状态与近期用量。", operations: "分析请求、费用与渠道运营表现。", channels: "管理上游供应商、模型和连接状态。",
  "api-keys": "管理下游访问密钥与使用权限。", routing: "配置渠道分组和请求路由策略。", logs: "检索请求记录、失败尝试和安全事件。",
  knowledge: "管理知识库、文档和检索索引。", wiki: "整理可链接的团队知识页面。", software: "连接本机命令、HTTP API 和 MCP 工具。",
  mcp: "查看和调试可用的 MCP 工具。", providers: "管理上游授权账号与模型同步。", settings: "管理系统行为与管理台偏好。",
};

export function Icon({ name, size = 18 }: { name: IconName | "sun" | "moon" | "chevron" | "plus" | "search" | "more"; size?: number }) {
  const paths: Record<string, ReactNode> = {
    overview: <><rect x="3" y="3" width="8" height="8" rx="2"/><rect x="13" y="3" width="8" height="5" rx="2"/><rect x="13" y="10" width="8" height="11" rx="2"/><rect x="3" y="13" width="8" height="8" rx="2"/></>,
    chart: <><path d="M3 3v18h18"/><path d="m7 14 4-4 4 3 6-7"/></>, channels: <><rect x="3" y="4" width="18" height="6" rx="2"/><rect x="3" y="14" width="18" height="6" rx="2"/><path d="M7 7h.01M7 17h.01M11 7h6M11 17h6"/></>,
    key: <><circle cx="8" cy="15" r="5"/><path d="m11.5 11.5 8-8L22 6l-2 2 1 1-3 3-1-1-3 3"/></>, route: <><circle cx="6" cy="6" r="3"/><circle cx="18" cy="18" r="3"/><path d="M9 6h4a5 5 0 0 1 5 5v4M6 9v4a5 5 0 0 0 5 5h4"/></>,
    logs: <><path d="M8 6h13M8 12h13M8 18h13"/><path d="M3 6h.01M3 12h.01M3 18h.01"/></>, knowledge: <><path d="M4 5.5A2.5 2.5 0 0 1 6.5 3H20v17H6.5A2.5 2.5 0 0 0 4 22z"/><path d="M4 5v17M8 7h8M8 11h8"/></>,
    wiki: <><path d="M4 4h16v16H4z"/><path d="m7 8 2 8 3-5 3 5 2-8"/></>, tools: <><path d="m14.7 6.3 3 3M5 20l8.6-8.6M13 5a5 5 0 0 0 6 6l-3.5 3.5a3 3 0 0 1-4.2 0l-1.8-1.8a3 3 0 0 1 0-4.2z"/><path d="m4 16 4 4"/></>,
    accounts: <><circle cx="9" cy="8" r="4"/><path d="M3 21a6 6 0 0 1 12 0M17 11a4 4 0 1 0 0-8M19 14a5 5 0 0 1 2 4v3"/></>, mcp: <><circle cx="12" cy="12" r="9"/><path d="M8 16v-8l4 5 4-5v8"/></>,
    settings: <><circle cx="12" cy="12" r="3"/><path d="m19.4 15 .1.1 1.4 1.1-1.4 2.4-1.7-.7a8 8 0 0 1-1.7 1l-.3 1.8h-2.8l-.3-1.8a8 8 0 0 1-1.7-1l-1.7.7-1.4-2.4L7.3 15a8 8 0 0 1 0-2l-1.4-1.1 1.4-2.4 1.7.7a8 8 0 0 1 1.7-1l.3-1.8h2.8l.3 1.8a8 8 0 0 1 1.7 1l1.7-.7 1.4 2.4-1.4 1.1a8 8 0 0 1-.1 2Z"/></>,
    sun: <><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41m11.32 11.32 1.41 1.41M2 12h2m16 0h2M4.93 19.07l1.41-1.41M17.66 6.34l1.41-1.41"/></>, moon: <path d="M20.9 13A9 9 0 0 1 11 3.1 9 9 0 1 0 20.9 13Z"/>,
    chevron: <><path d="m9 18 6-6-6-6"/></>, plus: <><path d="M12 5v14M5 12h14"/></>, search: <><circle cx="11" cy="11" r="7"/><path d="m20 20-4-4"/></>, more: <><circle cx="5" cy="12" r="1"/><circle cx="12" cy="12" r="1"/><circle cx="19" cy="12" r="1"/></>,
  };
  return <svg className="icon" width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{paths[name]}</svg>;
}

export function App() {
  const [authenticated, setAuthenticated] = useState<boolean | null>(null);
  const page = usePage(nav.map(([id]) => id));
  const [error, setError] = useState("");
  const [theme, setTheme] = useState<"light" | "dark">(() => localStorage.getItem("waliapi-admin-theme") === "dark" ? "dark" : "light");
  const [collapsed, setCollapsed] = useState(() => localStorage.getItem("waliapi-admin-sidebar") === "collapsed");
  useEffect(() => { get<{ authenticated: boolean }>("/api/v1/auth/session").then(session => setAuthenticated(session.authenticated)).catch(() => setAuthenticated(false)); }, []);
  useEffect(() => { const expire = () => setAuthenticated(false); window.addEventListener("admin-session-expired", expire); return () => window.removeEventListener("admin-session-expired", expire); }, []);
  useEffect(() => { setError(""); document.getElementById("page-title")?.focus(); }, [page]);
  useEffect(() => { document.documentElement.dataset.theme = theme; localStorage.setItem("waliapi-admin-theme", theme); }, [theme]);
  useEffect(() => { localStorage.setItem("waliapi-admin-sidebar", collapsed ? "collapsed" : "expanded"); }, [collapsed]);
  if (authenticated === null) return <div className="centered">正在验证管理员会话…</div>;
  if (!authenticated) return <LoginPage onSuccess={() => setAuthenticated(true)} />;
  return <div className={`shell${collapsed ? " sidebar-collapsed" : ""}`}>
    <a className="skip-link" href="#main-content" onClick={event => { event.preventDefault(); document.getElementById("main-content")?.focus(); }}>跳到主要内容</a>
    <aside className="app-sidebar">
      <div className="brand-row"><div className="brand-mark" aria-hidden="true">W</div><div className="brand-copy"><strong>WaLiAPI</strong><small>AI Gateway</small></div><button className="sidebar-toggle" aria-label={collapsed ? "展开侧栏" : "收起侧栏"} title={collapsed ? "展开侧栏" : "收起侧栏"} onClick={() => setCollapsed(value => !value)}><Icon name="chevron" /></button></div>
      <nav className="app-nav" aria-label="管理台导航">{navigationGroups.map(group => <section className="nav-group" key={group.label} aria-label={group.label}><h2>{group.label}</h2>{group.items.map(item => <a href={`#/${item.id}`} aria-label={item.label} aria-current={page === item.id ? "page" : undefined} className={page === item.id ? "active" : ""} key={item.id} title={collapsed ? item.label : undefined}><Icon name={item.icon} /><span>{item.label}</span>{page === item.id && <i aria-hidden="true" />}</a>)}</section>)}</nav>
      <div className="sidebar-footer"><div className="account-chip"><span className="avatar">A</span><span className="account-copy"><strong>管理员</strong><small>本机工作区</small></span></div><div className="sidebar-actions"><button className="theme-toggle" onClick={() => setTheme(value => value === "light" ? "dark" : "light")} aria-label={theme === "light" ? "切换到深色模式" : "切换到浅色模式"} title={theme === "light" ? "深色模式" : "浅色模式"}><Icon name={theme === "light" ? "moon" : "sun"} /><span>{theme === "light" ? "深色模式" : "浅色模式"}</span></button><button className="logout" aria-label="退出登录" onClick={() => { post("/api/v1/auth/logout", {}).then(() => setAuthenticated(false)).catch(error => setError(error.message)); }}><span className="logout-symbol" aria-hidden="true">↗</span><span className="account-copy">退出登录</span></button></div></div>
    </aside>
    <main id="main-content" className="app-main" tabIndex={-1}>
      <header className="page-header"><div><span className="eyebrow">控制台 / {nav.find(([id]) => id === page)?.[1] || "页面不存在"}</span><h1 id="page-title" tabIndex={-1}>{nav.find(([id]) => id === page)?.[1] || "页面不存在"}</h1><p>{page !== "not-found" && pageDescriptions[page as Page]}</p></div><span className="session-status"><i />管理员模式</span></header>
      {error && <div className="error" role="alert">{error}</div>}
      <PageBoundary key={page}><PageView page={page} onError={setError} /></PageBoundary>
    </main>
  </div>;
}

function LoginPage({ onSuccess }: { onSuccess: () => void }) {
  const [username, setUsername] = useState("admin");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const submit = (event: FormEvent) => { event.preventDefault(); setError(""); post("/api/v1/auth/login", { username, password }).then(onSuccess).catch((err: Error) => setError(err.message)); };
  return <div className="login-screen"><div className="login-orbit" aria-hidden="true" /><form className="login panel" onSubmit={submit}><div className="login-brand"><div className="brand-mark">W</div><div><strong>WaLiAPI</strong><small>AI Gateway Console</small></div></div><span className="eyebrow">安全管理入口</span><h1>欢迎回来</h1><p className="login-intro">登录以管理模型渠道、访问密钥与网关运行状态。</p><label>用户名<input value={username} onChange={event => setUsername(event.target.value)} autoComplete="username" required /></label><label>密码<input value={password} onChange={event => setPassword(event.target.value)} type="password" autoComplete="current-password" required /></label>{error && <div className="error" role="alert">{error}</div>}<button className="primary" type="submit">登录控制台</button><small className="login-footnote">受保护的管理会话</small></form><div className="login-side-note"><span className="status-dot" /> 安全、统一的模型访问入口</div></div>;
}

function PageView({ page, onError }: { page: string; onError: (message: string) => void }) {
  if (page === "dashboard") return <DashboardPage onError={onError} />;
  if (page === "operations") return <OperationsPage onError={onError} />;
  if (page === "channels") return <ChannelManager onError={onError} />;
  if (page === "api-keys") return <ApiKeyManager onError={onError} />;
  if (page === "routing") return <RoutingManager onError={onError} />;
  if (page === "logs") return <LogManager onError={onError} />;
  if (page === "software") return <SoftwarePage onError={onError} />;
  if (page === "providers") return <ProviderManager onError={onError} />;
  if (page === "knowledge") return <KnowledgePage onError={onError} />;
  if (page === "wiki") return <WikiManager onError={onError} />;
  if (page === "mcp") return <McpManager onError={onError} />;
  if (page === "settings") return <SettingsPage onError={onError} />;
  return <div className="panel" role="alert">没有找到这个页面。<a href="#/dashboard">返回仪表盘</a></div>;
}

function Table({ rows, columns }: { rows: Record<string, unknown>[]; columns: string[] }) {
  return <div className="table-wrap"><table><thead><tr>{columns.map(column => <th key={column}>{column}</th>)}</tr></thead><tbody>{rows.map((row, index) => <tr key={String(row.id ?? index)}>{columns.map(column => <td key={column}>{String(row[column] ?? "—")}</td>)}</tr>)}</tbody></table>{rows.length === 0 && <p className="muted">暂无数据。</p>}</div>;
}

function SettingsPage({ onError }: { onError: (message: string) => void }) {
  const [prompts, setPrompts] = useState<PromptTemplate[]>([]);
  const [configs, setConfigs] = useState<ClientConfig[]>([]);
  const [grants, setGrants] = useState<AccessGrant[]>([]);
  const [principalType, setPrincipalType] = useState("api_key");
  const [principalId, setPrincipalId] = useState("");
  const [resourceType, setResourceType] = useState("mcp_tool");
  const [resourceId, setResourceId] = useState("*");
  const [grantAction, setGrantAction] = useState("execute");
  const [target, setTarget] = useState("codex");
  const [message, setMessage] = useState("");
  const load = () => Promise.all([get<PromptTemplate[]>("/api/v1/platform/prompts"), get<ClientConfig[]>("/api/v1/platform/config"), get<AccessGrant[]>("/api/v1/access/grants")]).then(([promptRows, configRows, grantRows]) => { setPrompts(promptRows); setConfigs(configRows); setGrants(grantRows); }).catch((error: Error) => onError(error.message));
  useEffect(() => { load(); }, []);
  const preview = () => post<{ path: string }>("/api/v1/platform/config/preview", { target, values: {} }).then(result => setMessage(`配置预览：${result.path}`)).catch((error: Error) => onError(error.message));
  const clearCache = () => del("/api/v1/platform/cache").then(() => setMessage("语义缓存已清理")).catch((error: Error) => onError(error.message));
  const removeConfig = (config: ClientConfig) => del(`/api/v1/platform/config/${encodeURIComponent(config.target)}`).then(load).catch((error: Error) => onError(error.message));
  const createGrant = () => {
    if (!principalId.trim() || !resourceId.trim()) return;
    post<AccessGrant>("/api/v1/access/grants", { principal_type: principalType, principal_id: principalId.trim(), resource_type: resourceType, resource_id: resourceId.trim(), action: grantAction }).then(() => { setPrincipalId(""); setResourceId("*"); return load(); }).catch((error: Error) => onError(error.message));
  };
  const removeGrant = (grant: AccessGrant) => del(`/api/v1/access/grants/${encodeURIComponent(grant.id)}`).then(load).catch((error: Error) => onError(error.message));
  return <section><AdministrationPanel onError={onError} /><div className="panel"><h2>平台设置</h2><div className="inline-form"><select value={target} onChange={event => setTarget(event.target.value)}><option value="codex">Codex CLI</option><option value="claude">Claude Code</option><option value="gemini">Gemini CLI</option></select><button className="primary" onClick={preview}>预览配置</button><button className="secondary" onClick={clearCache}>清理语义缓存</button></div>{message && <p className="success">{message}</p>}<h3>已生成客户端配置</h3><div className="card-list">{configs.map(config => <article className="subcard" key={config.target}><strong>{config.target}</strong><span>{config.path}</span><small>{config.size} bytes</small><button className="secondary" onClick={() => removeConfig(config)}>删除</button></article>)}</div>{configs.length === 0 && <p className="muted">暂无客户端配置。</p>}<h3>Prompt 模板</h3><div className="card-list">{prompts.map(prompt => <article className="subcard" key={prompt.id}><strong>{prompt.name}</strong><span>{prompt.description || prompt.template}</span><small>{prompt.enabled ? "已启用" : "已停用"}</small></article>)}</div>{prompts.length === 0 && <p className="muted">暂无 Prompt 模板。</p>}<h3>访问授权</h3><p className="muted">为 API Key 或 MCP 主体分配知识库、Wiki、Software 与 MCP 工具权限。默认拒绝未配置的主体。</p><div className="grant-form"><label className="field-label">主体类型<select value={principalType} onChange={event => setPrincipalType(event.target.value)}><option value="api_key">API Key</option><option value="mcp">MCP Token</option></select></label><label className="field-label">主体 ID<input value={principalId} maxLength={64} onChange={event => setPrincipalId(event.target.value)} placeholder="主体 ID" /></label><label className="field-label">资源类型<select value={resourceType} onChange={event => setResourceType(event.target.value)}><option value="mcp_tool">MCP 工具</option><option value="kb">知识库</option><option value="wiki">Wiki 项目</option><option value="software">Software 工具</option></select></label><label className="field-label">资源 ID<input value={resourceId} maxLength={128} onChange={event => setResourceId(event.target.value)} placeholder="具体 ID 或 *" /></label><label className="field-label">操作<select value={grantAction} onChange={event => setGrantAction(event.target.value)}><option value="execute">执行</option><option value="read">读取</option><option value="write">写入</option></select></label><button className="primary grant-submit" onClick={createGrant} disabled={!principalId.trim() || !resourceId.trim()}>添加授权</button></div><div className="table-wrap"><table><thead><tr><th>主体</th><th>资源</th><th>操作</th><th>创建时间</th><th /></tr></thead><tbody>{grants.map(grant => <tr key={grant.id}><td>{grant.principal_type}:{grant.principal_id}</td><td>{grant.resource_type}:{grant.resource_id}</td><td>{grant.action}</td><td>{new Date(grant.created_at).toLocaleString()}</td><td><button className="danger" onClick={() => removeGrant(grant)}>删除</button></td></tr>)}</tbody></table>{grants.length === 0 && <p className="muted">暂无授权。</p>}</div></div></section>;
}

