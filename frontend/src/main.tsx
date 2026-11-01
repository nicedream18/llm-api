import { FormEvent, useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import { del, get, post, put } from "./api";
import type { Dashboard, KnowledgeBase, PromptTemplate, Provider, SoftwareTool, WikiPage, WikiProject } from "./types";
import "./styles.css";

type Page = "dashboard" | "channels" | "software" | "providers" | "wiki" | "knowledge" | "settings";
const nav: Array<[Page, string]> = [["dashboard", "仪表盘"], ["channels", "渠道"], ["knowledge", "知识库"], ["wiki", "Wiki"], ["software", "Software"], ["providers", "Auth Provider"], ["settings", "设置"]];

function App() {
  const [authenticated, setAuthenticated] = useState<boolean | null>(null);
  const [page, setPage] = useState<Page>("dashboard");
  const [error, setError] = useState("");
  useEffect(() => { get<{ authenticated: boolean }>("/api/v1/auth/session").then(session => setAuthenticated(session.authenticated)).catch(() => setAuthenticated(false)); }, []);
  if (authenticated === null) return <div className="centered">正在验证管理员会话…</div>;
  if (!authenticated) return <LoginPage onSuccess={() => setAuthenticated(true)} />;
  return <div className="shell"><aside><strong>WaLiAPI</strong><small>AI Gateway Admin</small><nav>{nav.map(([id, label]) => <button className={page === id ? "active" : ""} key={id} onClick={() => { setPage(id); setError(""); }}>{label}</button>)}</nav><button className="logout" onClick={() => { post("/api/v1/auth/logout", {}).finally(() => setAuthenticated(false)); }}>退出登录</button></aside><main><header><div><span className="eyebrow">CONTROL CENTER</span><h1>{nav.find(([id]) => id === page)?.[1]}</h1></div><span className="status">● 管理员模式</span></header>{error && <div className="error" role="alert">{error}</div>}<PageView page={page} onError={setError} /></main></div>;
}

function LoginPage({ onSuccess }: { onSuccess: () => void }) {
  const [username, setUsername] = useState("admin");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const submit = (event: FormEvent) => { event.preventDefault(); setError(""); post("/api/v1/auth/login", { username, password }).then(onSuccess).catch((err: Error) => setError(err.message)); };
  return <div className="centered"><form className="login panel" onSubmit={submit}><span className="eyebrow">WALIAPI ADMIN</span><h1>管理员登录</h1><label>用户名<input value={username} onChange={event => setUsername(event.target.value)} autoComplete="username" required /></label><label>密码<input value={password} onChange={event => setPassword(event.target.value)} type="password" autoComplete="current-password" required /></label>{error && <div className="error" role="alert">{error}</div>}<button className="primary" type="submit">登录</button></form></div>;
}

function PageView({ page, onError }: { page: Page; onError: (message: string) => void }) {
  if (page === "dashboard") return <DashboardPage onError={onError} />;
  if (page === "channels") return <ListPage title="渠道" path="/api/v1/channels" columns={["name", "type", "status"]} onError={onError} />;
  if (page === "software") return <SoftwarePage onError={onError} />;
  if (page === "providers") return <ProviderPage onError={onError} />;
  if (page === "knowledge") return <KnowledgePage onError={onError} />;
  if (page === "wiki") return <WikiPageView onError={onError} />;
  return <SettingsPage onError={onError} />;
}

function DashboardPage({ onError }: { onError: (message: string) => void }) {
  const [data, setData] = useState<Dashboard | null>(null);
  useEffect(() => { get<Dashboard>("/api/v1/dashboard").then(setData).catch((error: Error) => onError(error.message)); }, [onError]);
  const cards: Array<[string, string | number]> = [["请求数", data?.total_requests ?? "—"], ["Token", data?.total_tokens ?? "—"], ["错误数", data?.total_errors ?? "—"], ["健康分", data?.health_score ?? "—"]];
  return <section><div className="grid">{cards.map(([label, value]) => <article key={label}><span>{label}</span><strong>{value}</strong></article>)}</div><div className="panel"><h2>系统状态</h2><p>{data ? `当前状态：${data.health_badge}` : "正在加载…"}</p></div></section>;
}

function ListPage({ title, path, columns, onError }: { title: string; path: string; columns: string[]; onError: (message: string) => void }) {
  const [rows, setRows] = useState<Record<string, unknown>[]>([]);
  const [reload, setReload] = useState(0);
  useEffect(() => { get<Record<string, unknown>[]>(path).then(setRows).catch((error: Error) => onError(error.message)); }, [path, reload, onError]);
  return <section><div className="panel"><div className="panel-head"><h2>{title}</h2><button className="primary" onClick={() => setReload(value => value + 1)}>刷新</button></div><Table rows={rows} columns={columns} /></div></section>;
}

function Table({ rows, columns }: { rows: Record<string, unknown>[]; columns: string[] }) {
  return <div className="table-wrap"><table><thead><tr>{columns.map(column => <th key={column}>{column}</th>)}</tr></thead><tbody>{rows.map((row, index) => <tr key={String(row.id ?? index)}>{columns.map(column => <td key={column}>{String(row[column] ?? "—")}</td>)}</tr>)}</tbody></table>{rows.length === 0 && <p className="muted">暂无数据。</p>}</div>;
}

function KnowledgePage({ onError }: { onError: (message: string) => void }) {
  const [rows, setRows] = useState<KnowledgeBase[]>([]);
  const [name, setName] = useState("");
  const load = () => get<KnowledgeBase[]>("/api/v1/kb").then(setRows).catch((error: Error) => onError(error.message));
  useEffect(() => { load(); }, []);
  const create = () => { if (!name.trim()) return; post<KnowledgeBase>("/api/v1/kb", { name: name.trim() }).then(() => { setName(""); load(); }).catch((error: Error) => onError(error.message)); };
  return <section><div className="panel"><div className="panel-head"><h2>知识库</h2><button className="primary" onClick={load}>刷新</button></div><div className="inline-form"><input placeholder="新知识库名称" value={name} onChange={event => setName(event.target.value)} /><button className="primary" onClick={create}>创建</button></div><div className="card-list">{rows.map(row => <article className="subcard" key={row.id}><strong>{row.name}</strong><span>{row.description || "暂无描述"}</span><small>{row.doc_count} 文档 · {row.chunk_count} 分块 · {row.index_status}</small></article>)}</div>{rows.length === 0 && <p className="muted">暂无知识库。</p>}</div></section>;
}

function WikiPageView({ onError }: { onError: (message: string) => void }) {
  const [projects, setProjects] = useState<WikiProject[]>([]);
  const [projectId, setProjectId] = useState("");
  const [pages, setPages] = useState<WikiPage[]>([]);
  const [name, setName] = useState("");
  const [title, setTitle] = useState("");
  const loadProjects = () => get<WikiProject[]>("/api/v1/wiki/projects").then(items => { setProjects(items); if (!projectId && items[0]) setProjectId(items[0].id); }).catch((error: Error) => onError(error.message));
  useEffect(() => { loadProjects(); }, []);
  useEffect(() => { if (!projectId) return; get<{ items: WikiPage[] }>(`/api/v1/wiki/projects/${projectId}/pages`).then(result => setPages(result.items)).catch((error: Error) => onError(error.message)); }, [projectId]);
  const createProject = () => { if (!name.trim()) return; post<WikiProject>("/api/v1/wiki/projects", { name: name.trim() }).then(() => { setName(""); loadProjects(); }).catch((error: Error) => onError(error.message)); };
  const createPage = () => { if (!projectId || !title.trim()) return; post<WikiPage>(`/api/v1/wiki/projects/${projectId}/pages`, { path: `${title.trim().toLowerCase().replace(/\s+/g, "-")}.md`, title: title.trim(), content: "" }).then(() => { setTitle(""); return get<{ items: WikiPage[] }>(`/api/v1/wiki/projects/${projectId}/pages`); }).then(result => result && setPages(result.items)).catch((error: Error) => onError(error.message)); };
  return <section><div className="panel"><div className="panel-head"><h2>Wiki 项目</h2><button className="primary" onClick={loadProjects}>刷新</button></div><div className="inline-form"><input placeholder="新项目名称" value={name} onChange={event => setName(event.target.value)} /><button className="primary" onClick={createProject}>创建项目</button></div><select value={projectId} onChange={event => setProjectId(event.target.value)}><option value="">选择项目</option>{projects.map(project => <option key={project.id} value={project.id}>{project.name}</option>)}</select><div className="inline-form"><input placeholder="新页面标题" value={title} onChange={event => setTitle(event.target.value)} disabled={!projectId} /><button className="primary" onClick={createPage} disabled={!projectId}>创建页面</button></div><div className="card-list">{pages.map(page => <article className="subcard" key={page.id}><strong>{page.title}</strong><span>{page.path}</span><small>{page.tags?.join(" · ") || "无标签"}</small></article>)}</div>{projectId && pages.length === 0 && <p className="muted">该项目暂无页面。</p>}</div></section>;
}

function SoftwarePage({ onError }: { onError: (message: string) => void }) {
  const [tools, setTools] = useState<SoftwareTool[]>([]);
  const load = () => get<SoftwareTool[]>("/api/v1/software/tools").then(setTools).catch((error: Error) => onError(error.message));
  useEffect(() => { load(); }, []);
  const toggle = (tool: SoftwareTool) => put<SoftwareTool>(`/api/v1/software/tools/${tool.id}/enabled?enabled=${tool.enabled ? "false" : "true"}`, {}).then(load).catch((error: Error) => onError(error.message));
  return <section><div className="panel"><div className="panel-head"><h2>Software 工具</h2><button className="primary" onClick={load}>刷新</button></div><div className="card-list">{tools.map(tool => <article className="subcard" key={tool.id}><strong>{tool.name}</strong><span>{tool.description || "暂无描述"}</span><small>风险：{tool.risk_level} · {tool.enabled ? "已启用" : "已停用"}</small><button className="secondary" onClick={() => toggle(tool)}>{tool.enabled ? "停用" : "启用"}</button></article>)}</div>{tools.length === 0 && <p className="muted">暂无工具。</p>}</div></section>;
}

function ProviderPage({ onError }: { onError: (message: string) => void }) {
  const [providers, setProviders] = useState<Provider[]>([]);
  const load = () => get<Provider[]>("/api/v1/providers").then(setProviders).catch((error: Error) => onError(error.message));
  useEffect(() => { load(); }, []);
  return <section><div className="panel"><div className="panel-head"><h2>Auth Provider 账号</h2><button className="primary" onClick={load}>刷新</button></div><Table rows={providers as unknown as Record<string, unknown>[]} columns={["provider", "name", "status", "priority"]} /></div></section>;
}

function SettingsPage({ onError }: { onError: (message: string) => void }) {
  const [prompts, setPrompts] = useState<PromptTemplate[]>([]);
  const [target, setTarget] = useState("codex");
  const [message, setMessage] = useState("");
  const load = () => get<PromptTemplate[]>("/api/v1/platform/prompts").then(setPrompts).catch((error: Error) => onError(error.message));
  useEffect(() => { load(); }, []);
  const preview = () => post<{ path: string }>("/api/v1/platform/config/preview", { target, values: {} }).then(result => setMessage(`配置预览：${result.path}`)).catch((error: Error) => onError(error.message));
  const clearCache = () => del("/api/v1/platform/cache").then(() => setMessage("语义缓存已清理")).catch((error: Error) => onError(error.message));
  return <section><div className="panel"><h2>平台设置</h2><div className="inline-form"><select value={target} onChange={event => setTarget(event.target.value)}><option value="codex">Codex CLI</option><option value="claude">Claude Code</option><option value="gemini">Gemini CLI</option></select><button className="primary" onClick={preview}>预览配置</button><button className="secondary" onClick={clearCache}>清理语义缓存</button></div>{message && <p className="success">{message}</p>}<h3>Prompt 模板</h3><div className="card-list">{prompts.map(prompt => <article className="subcard" key={prompt.id}><strong>{prompt.name}</strong><span>{prompt.description || prompt.template}</span><small>{prompt.enabled ? "已启用" : "已停用"}</small></article>)}</div>{prompts.length === 0 && <p className="muted">暂无 Prompt 模板。</p>}</div></section>;
}

createRoot(document.getElementById("root")!).render(<App />);
