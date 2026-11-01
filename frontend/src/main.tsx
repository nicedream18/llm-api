import React, { useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import { get } from "./api";
import type { Dashboard } from "./types";
import "./styles.css";

type Page = "dashboard" | "channels" | "software" | "providers" | "wiki" | "knowledge" | "settings";

const nav: Array<[Page, string]> = [["dashboard", "仪表盘"], ["channels", "渠道"], ["knowledge", "知识库"], ["wiki", "Wiki"], ["software", "Software"], ["providers", "Auth Provider"], ["settings", "设置"]];

function App() {
  const [page, setPage] = useState<Page>("dashboard");
  const [error, setError] = useState("");
  return <div className="shell"><aside><strong>WaLiAPI</strong><small>AI Gateway Admin</small><nav>{nav.map(([id, label]) => <button className={page === id ? "active" : ""} key={id} onClick={() => { setPage(id); setError(""); }}>{label}</button>)}</nav></aside><main><header><div><span className="eyebrow">CONTROL CENTER</span><h1>{nav.find(([id]) => id === page)?.[1]}</h1></div><span className="status">● 管理员模式</span></header>{error && <div className="error" role="alert">{error}</div>}<PageView page={page} onError={setError} /></main></div>;
}

function PageView({ page, onError }: { page: Page; onError: (message: string) => void }) {
  if (page === "dashboard") return <DashboardPage onError={onError} />;
  if (page === "channels") return <ListPage title="渠道" path="/api/v1/channels" columns={["name", "type", "status"]} onError={onError} />;
  if (page === "software") return <ListPage title="Software 工具" path="/api/v1/software/tools" columns={["name", "risk_level", "enabled"]} onError={onError} />;
  if (page === "providers") return <ListPage title="Auth Provider 账号" path="/api/v1/providers" columns={["provider", "name", "status", "priority"]} onError={onError} />;
  return <EmptyPage title={nav.find(([id]) => id === page)?.[1] ?? page} />;
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
  return <section><div className="panel"><div className="panel-head"><h2>{title}</h2><button className="primary" onClick={() => setReload(value => value + 1)}>刷新</button></div><div className="table-wrap"><table><thead><tr>{columns.map(column => <th key={column}>{column}</th>)}</tr></thead><tbody>{rows.map((row, index) => <tr key={String(row.id ?? index)}>{columns.map(column => <td key={column}>{String(row[column] ?? "—")}</td>)}</tr>)}</tbody></table>{rows.length === 0 && <p className="muted">暂无数据或需要管理员登录。</p>}</div></div></section>;
}

function EmptyPage({ title }: { title: string }) { return <section><div className="panel"><h2>{title}</h2><p className="muted">该模块 API 已就绪，页面组件正在逐步接入。</p></div></section>; }

createRoot(document.getElementById("root")!).render(<React.StrictMode><App /></React.StrictMode>);
