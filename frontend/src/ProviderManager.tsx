import { ActionMenu } from "./ActionMenu";
import { DialogA11y } from "./DialogA11y";
import { FormEvent, useCallback, useEffect, useRef, useState } from "react";
import { get, post, put } from "./api";
import type { Provider, ProviderPage } from "./types";
import { ProviderSyncPanel } from "./ProviderSyncPanel";
import "./provider.css";

const providers = ["codex", "gemini", "grok", "kimi", "qoder", "workbuddy"];
const fields = [["client_id", "Client ID"], ["authorization_url", "授权地址"], ["token_url", "Token 地址"], ["redirect_uri", "回调地址"], ["gateway_url", "网关地址"], ["quota_url", "配额地址"], ["models_url", "模型地址"]] as const;
type AccountForm = { provider: string; name: string; priority: number; config: Record<string, unknown>; mapping: string; group: string; tags: string };
const emptyForm = (): AccountForm => ({ provider: "codex", name: "", priority: 0, config: {}, mapping: "{}", group: "", tags: "" });
const errorMessage = (error: unknown) => error instanceof Error ? error.message : "操作失败";

export function ProviderManager({ onError }: { onError: (message: string) => void }) {
  const [page, setPage] = useState<ProviderPage>({ items: [], total: 0, offset: 0, limit: 25 });
  const [filters, setFilters] = useState({ search: "", provider: "", group_name: "", tag: "", enabled: "", status: "", sort: "priority", archived: false });
  const [query, setQuery] = useState("");
  const [offset, setOffset] = useState(0);
  const [selected, setSelected] = useState<string[]>([]);
  const [form, setForm] = useState<AccountForm>(emptyForm);
  const [editing, setEditing] = useState<string | null>(null);
  const [token, setToken] = useState("");
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState("");
  const [message, setMessage] = useState("");
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [events, setEvents] = useState<Array<{ id: string; action: string; created_at: string }> | null>(null);
  const [syncAccount, setSyncAccount] = useState<string | null>(null);
  const request = useRef(0);
  useEffect(() => {
    if (!drawerOpen && !events) return;
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      if (drawerOpen) setDrawerOpen(false);
      else setEvents(null);
    };
    window.addEventListener("keydown", closeOnEscape); return () => window.removeEventListener("keydown", closeOnEscape);
  }, [drawerOpen, events]);
  const load = useCallback(async () => {
    const serial = ++request.current; setLoading(true); setLoadError("");
    try {
      const result = await get<ProviderPage>(`/api/v1/providers/accounts?limit=25&offset=${offset}${query}`);
      if (serial === request.current) { setPage(result); setSelected([]); }
    } catch (error) { if (serial === request.current) { setLoadError(errorMessage(error)); onError(errorMessage(error)); } }
    finally { if (serial === request.current) setLoading(false); }
  }, [offset, query, onError]);
  useEffect(() => { void load(); return () => { request.current++; }; }, [load]);
  const run = async (action: () => Promise<void>) => {
    if (busy) return; setBusy(true); setMessage("");
    try { await action(); } catch (error) { onError(errorMessage(error)); }
    finally { setBusy(false); }
  };
  const operate = async (account: Provider, operation: string, values = {}) => {
    if (operation === "archive" && !window.confirm(`归档“${account.name}”将清除本地凭据，恢复后需要重新授权。继续？`)) return;
    await run(async () => { await post(`/api/v1/providers/${account.id}/operations`, { operation, ...values }); await load(); setMessage("账号状态已更新"); });
  };
  const bulk = (enabled: boolean) => run(async () => {
    const result = await post<{ results: Array<{ id: string; success: boolean; error?: string }> }>("/api/v1/providers/bulk", { account_ids: selected, operation: "enabled", enabled });
    const failures = result.results.filter(item => !item.success);
    setMessage(`成功 ${result.results.length - failures.length} 项，失败 ${failures.length} 项${failures.length ? `：${failures.map(item => `${item.id} (${item.error})`).join("、")}` : ""}`);
    await load();
  });
  const edit = (account: Provider) => {
    setEditing(account.id); setToken("");
    setForm({ provider: account.provider, name: account.name, priority: account.priority, config: account.client_config || {}, mapping: JSON.stringify(account.model_mapping || {}, null, 2), group: account.group_name || "", tags: (account.tags || []).join(", ") });
    setDrawerOpen(true);
  };
  const create = () => { setEditing(null); setToken(""); setForm(emptyForm()); setDrawerOpen(true); };
  const save = (event: FormEvent) => {
    event.preventDefault();
    void run(async () => {
      const mapping: unknown = JSON.parse(form.mapping);
      if (!mapping || typeof mapping !== "object" || Array.isArray(mapping) || Object.values(mapping).some(value => typeof value !== "string")) throw new Error("模型映射必须是字符串映射对象");
      const payload = { provider: form.provider, name: form.name.trim(), priority: form.priority, client_config: form.config, model_mapping: mapping };
      const account = editing ? await put<Provider>(`/api/v1/providers/${editing}`, payload) : await post<Provider>("/api/v1/providers", payload);
      setEditing(account.id);
      await post(`/api/v1/providers/${account.id}/operations`, { operation: "group_name", group_name: form.group.trim() });
      await post(`/api/v1/providers/${account.id}/operations`, { operation: "tags", tags: form.tags.split(/[,，]/).map(tag => tag.trim()).filter(Boolean) });
      setMessage("账号与分组标签已保存"); await load();
    });
  };
  const providerAction = (account: Provider, action: "authorize" | "refresh" | "logout" | "quota" | "models") => run(async () => {
    const path = `/api/v1/providers/${account.id}/${action}`;
    if (action === "authorize") {
      const result = await post<{ authorization_url: string }>(path, {});
      if (!result.authorization_url) throw new Error("请先配置 OAuth 授权地址");
      const url = new URL(result.authorization_url);
      if (!["https:", "http:"].includes(url.protocol)) throw new Error("无效的授权地址");
      window.open(url.href, "_blank", "noopener,noreferrer"); setMessage("请在授权页面完成登录，然后刷新账号状态。");
    } else {
      const result = ["quota", "models"].includes(action) ? await get<unknown>(path) : await post<unknown>(path, {});
      setMessage(["quota", "models"].includes(action) ? JSON.stringify(result) : "操作成功"); await load();
    }
  });
  const filter = (event: FormEvent) => {
    event.preventDefault(); const params = new URLSearchParams();
    Object.entries(filters).forEach(([key, value]) => { if (value !== "") params.set(key, String(value)); });
    setOffset(0); setQuery(params.size ? "&" + params.toString() : "");
  };
  const hasFilters = Boolean(filters.search || filters.provider || filters.group_name || filters.tag || filters.enabled || filters.status || filters.archived || filters.sort !== "priority");
  const clearFilters = () => { setFilters({ search: "", provider: "", group_name: "", tag: "", enabled: "", status: "", sort: "priority", archived: false }); setOffset(0); setQuery(""); };
  return <section className="provider-manager management-page" aria-label="Provider 账号中心">
    {loadError && <div className="error inline-error" role="alert"><span>加载失败：{loadError}</span><button className="secondary" onClick={() => void load()}>重试</button></div>}
    <form className="panel provider-filter-panel" onSubmit={filter}><div className="management-toolbar"><div><h2>上游账号</h2><p>{page.total} 个账号 · 按供应商、授权状态和运行健康筛选</p></div><div className="toolbar-actions"><button type="button" className="secondary" onClick={() => void load()} disabled={loading}>刷新</button><button type="button" className="primary" onClick={create}>＋ 添加账号</button></div></div>
      <div className="provider-filter-grid"><label>搜索账号<input aria-label="搜索账号" placeholder="账号名称" value={filters.search} onChange={event => setFilters({ ...filters, search: event.target.value })} /></label>
        <label>供应商<select aria-label="筛选供应商" value={filters.provider} onChange={event => setFilters({ ...filters, provider: event.target.value })}><option value="">全部</option>{providers.map(name => <option key={name}>{name}</option>)}</select></label>
        <label>分组<input placeholder="分组名称" value={filters.group_name} onChange={event => setFilters({ ...filters, group_name: event.target.value })} /></label><label>标签<input placeholder="标签" value={filters.tag} onChange={event => setFilters({ ...filters, tag: event.target.value })} /></label>
        <label>启停<select value={filters.enabled} onChange={event => setFilters({ ...filters, enabled: event.target.value })}><option value="">全部</option><option value="true">已启用</option><option value="false">已停用</option></select></label>
        <label>授权<select value={filters.status} onChange={event => setFilters({ ...filters, status: event.target.value })}><option value="">全部</option><option value="active">已授权</option><option value="pending">待授权</option><option value="signed_out">已退出</option></select></label>
        <label>排序<select value={filters.sort} onChange={event => setFilters({ ...filters, sort: event.target.value })}><option value="priority">优先级</option><option value="name">名称</option><option value="created_at">创建时间</option></select></label>
        <label className="checkbox-label"><input type="checkbox" checked={filters.archived} onChange={event => setFilters({ ...filters, archived: event.target.checked })} />查看已归档</label><button type="submit" className="secondary" disabled={loading}>应用筛选</button>{hasFilters && <button type="button" className="secondary" onClick={clearFilters} disabled={loading}>清除筛选</button>}
      </div>
      <div className="bulk-toolbar"><span>已选择 {selected.length} 项</span><button type="button" className="secondary" disabled={!selected.length || busy} onClick={() => void bulk(true)}>批量启用</button><button type="button" className="secondary" disabled={!selected.length || busy} onClick={() => void bulk(false)}>批量停用</button></div>
    </form>
    {message && <p className="success provider-message" role="status">{message}</p>}{loading && <p role="status">正在加载账号…</p>}
    <div className="panel management-table-panel"><div className="table-heading"><div><h2>账号列表</h2><p>当前显示 {page.items.length} 个账号</p></div></div><div className="table-wrap"><table className="management-table provider-table"><thead><tr><th><span className="sr-only">选择</span></th><th>账号</th><th>授权 / 启停</th><th>健康状态</th><th>分组与标签</th><th>优先级</th><th><span className="sr-only">操作</span></th></tr></thead><tbody>{page.items.map(account => <tr key={account.id}><td><input type="checkbox" aria-label={`选择 ${account.name}`} checked={selected.includes(account.id)} onChange={event => setSelected(current => event.target.checked ? [...current, account.id] : current.filter(id => id !== account.id))} /></td><td><div className="provider-account-cell"><span className="provider-badge">{account.provider}</span><strong>{account.name}</strong>{account.cooldown_until && <small className="table-secondary">冷却至 {new Date(account.cooldown_until).toLocaleString()}</small>}</div></td><td><div className="status-stack"><span className={`status-pill ${account.enabled ? "is-active" : "is-disabled"}`}><i />{account.enabled ? "已启用" : "已停用"}</span><span className="table-secondary">{account.auth_status || account.status}</span></div></td><td><span className={`health-label ${(account.health_status || "unknown").toLowerCase()}`}>{account.health_status || "状态未知"}</span></td><td><strong>{account.group_name || "未分组"}</strong><small className="table-secondary">{account.tags?.join(" · ") || "无标签"}</small></td><td><span className="numeric-value">{account.priority}</span></td><td><ActionMenu label={`更多操作 ${account.name}`}><button onClick={() => edit(account)}>编辑</button>{account.archived_at ? <button disabled={busy} onClick={() => void operate(account, "restore")}>恢复（需重新授权）</button> : <><button disabled={busy} onClick={() => void operate(account, "enabled", { enabled: !account.enabled })}>{account.enabled ? "停用" : "启用"}</button><button disabled={busy} onClick={() => void operate(account, "archive")}>归档</button><hr />{(["authorize", "refresh", "models", "quota", "logout"] as const).map((action, index) => <button key={action} disabled={busy || (action !== "authorize" && account.status !== "active")} onClick={() => void providerAction(account, action)}>{["OAuth 授权", "刷新 Token", "同步模型", "查询配额", "退出账号"][index]}</button>)}<button onClick={() => setSyncAccount(account.id)}>配额与同步中心</button></>}<button onClick={() => void run(async () => setEvents(await get(`/api/v1/providers/${account.id}/events`)))}>操作记录</button></ActionMenu></td></tr>)}</tbody></table></div>{!loading && !page.items.length && <div className="empty-state"><strong>没有符合条件的账号</strong><p>可以调整筛选条件或创建一个新账号。</p><button className="primary" onClick={create}>添加账号</button></div>}</div>
    <div className="pagination-bar"><button className="secondary" disabled={offset === 0 || loading} onClick={() => setOffset(Math.max(0, offset - 25))}>上一页</button><span>第 {Math.floor(offset / 25) + 1} 页 · 共 {page.total} 个账号</span><button className="secondary" disabled={offset + 25 >= page.total || loading} onClick={() => setOffset(offset + 25)}>下一页</button></div>
    {events && <div className="drawer-backdrop" role="presentation" onMouseDown={event => { if (event.target === event.currentTarget) setEvents(null); }}><section className="edit-drawer" role="dialog" aria-modal="true" aria-labelledby="provider-events-title"><DialogA11y onClose={() => setEvents(null)} /><div className="drawer-header"><h2 id="provider-events-title">账号操作记录</h2><button className="icon-button" aria-label="关闭记录" onClick={() => setEvents(null)}>×</button></div><div className="drawer-content">{events.length ? events.map(item => <p key={item.id}>{item.action} · {new Date(item.created_at).toLocaleString()}</p>) : <p>暂无操作记录。</p>}</div></section></div>}
    {syncAccount && <ProviderSyncPanel key={syncAccount} accountId={syncAccount} onError={onError} onClose={() => setSyncAccount(null)} />}
    {drawerOpen && <div className="drawer-backdrop" role="presentation" onMouseDown={event => { if (event.target === event.currentTarget) setDrawerOpen(false); }}><section className="edit-drawer" role="dialog" aria-modal="true" aria-labelledby="provider-form-title"><DialogA11y onClose={() => setDrawerOpen(false)} /><div className="drawer-header"><div><span className="eyebrow">OAuth 与模型映射</span><h2 id="provider-form-title">{editing ? "编辑上游账号" : "添加上游账号"}</h2></div><button className="icon-button" aria-label="关闭账号编辑" onClick={() => setDrawerOpen(false)}>×</button></div><form className="provider-form" onSubmit={save}><div className="drawer-content"><div className="provider-filter-grid"><label>供应商<select value={form.provider} onChange={event => setForm({ ...form, provider: event.target.value })}>{providers.map(name => <option key={name}>{name}</option>)}</select></label><label>账号名称<input required maxLength={128} value={form.name} onChange={event => setForm({ ...form, name: event.target.value })} /></label><label>优先级<input type="number" min={-1000} max={1000} value={form.priority} onChange={event => setForm({ ...form, priority: Number(event.target.value) })} /></label><label>分组<input maxLength={128} value={form.group} onChange={event => setForm({ ...form, group: event.target.value })} /></label><label>标签（逗号分隔）<input value={form.tags} onChange={event => setForm({ ...form, tags: event.target.value })} /></label></div><details className="drawer-advanced"><summary>OAuth 与网关连接配置</summary><p className="muted">支持已配置的标准 OAuth 服务。敏感配置使用服务端环境变量引用。</p><div className="provider-filter-grid">{fields.map(([key, label]) => <label key={key}>{label}<input value={typeof form.config[key] === "string" ? form.config[key] as string : ""} onChange={event => setForm({ ...form, config: { ...form.config, [key]: event.target.value } })} /></label>)}</div><label>模型映射 JSON<textarea value={form.mapping} onChange={event => setForm({ ...form, mapping: event.target.value })} /></label></details>{editing && <label>手动访问 Token<input type="password" aria-label="手动访问 Token" value={token} autoComplete="off" onChange={event => setToken(event.target.value)} /></label>}</div><footer className="drawer-footer"><span className="muted">密钥仅在受保护的服务端处理</span><div><button className="secondary" type="button" onClick={() => setDrawerOpen(false)}>取消</button>{editing && <button type="button" className="secondary" disabled={busy || !token.trim()} onClick={() => void run(async () => { await post(`/api/v1/providers/${editing}/token`, { access_token: token.trim() }); setToken(""); setMessage("Token 已保存"); await load(); })}>保存 Token</button>}<button className="primary" disabled={busy || !form.name.trim()} type="submit">{busy ? "处理中…" : "保存账号"}</button></div></footer></form></section></div>}
  </section>;
}
