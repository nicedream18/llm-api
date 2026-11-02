import { DialogA11y } from "./DialogA11y";
import { useEffect, useState, type FormEvent } from "react";
import { del, post, put } from "./api";
import { lines, useAction, useResource } from "./adminHooks";

type AccessKey = { id?: string; name: string; key?: string | null; status: number; allowed_models: string[]; allowed_channels: string[]; quota_limit: number; quota_used?: number; expires_at?: string | null };
const initial: AccessKey = { name: "", status: 1, allowed_models: [], allowed_channels: [], quota_limit: 0 };

export function ApiKeyManager({ onError }: { onError: (message: string) => void }) {
  const [rows, reload, resource] = useResource<AccessKey[]>("/api/v1/api-keys", onError);
  const [draft, setDraft] = useState<AccessKey>({ ...initial });
  const [models, setModels] = useState(""); const [channels, setChannels] = useState("");
  const [expires, setExpires] = useState(""); const [createdSecret, setCreatedSecret] = useState("");
  const [query, setQuery] = useState(""); const [status, setStatus] = useState(""); const [drawerOpen, setDrawerOpen] = useState(false);
  const [busy, run] = useAction(onError);
  const reset = () => { setDraft({ ...initial }); setModels(""); setChannels(""); setExpires(""); setDrawerOpen(false); };
  useEffect(() => {
    if (!drawerOpen) return;
    const closeOnEscape = (event: KeyboardEvent) => { if (event.key === "Escape") reset(); };
    window.addEventListener("keydown", closeOnEscape); return () => window.removeEventListener("keydown", closeOnEscape);
  }, [drawerOpen]);
  const edit = (row: AccessKey) => { setDraft(row); setModels(row.allowed_models.join("\n")); setChannels(row.allowed_channels.join("\n")); setExpires(row.expires_at || ""); setCreatedSecret(""); setDrawerOpen(true); };
  const filtered = (rows || []).filter(row => {
    const search = `${row.name} ${row.key || ""} ${row.allowed_models.join(" ")}`.toLocaleLowerCase();
    return (!query.trim() || search.includes(query.trim().toLocaleLowerCase())) && (!status || String(Boolean(row.status)) === status);
  });
  const save = (event: FormEvent) => {
    event.preventDefault();
    void run(async () => {
      if (expires && Number.isNaN(Date.parse(expires))) throw new Error("请输入带时区的有效到期时间");
      const value = { id: draft.id, name: draft.name.trim(), status: draft.status, allowed_models: lines(models), allowed_channels: lines(channels), quota_limit: draft.quota_limit, expires_at: expires ? new Date(expires).toISOString() : null };
      if (draft.id) await put("/api/v1/api-keys", value);
      else { const created = await post<AccessKey>("/api/v1/api-keys", value); setCreatedSecret(created.key || ""); }
      reset(); reload();
    });
  };
  return <section className="management-page access-key-page">
    {resource.error && <div className="error inline-error" role="alert"><span>加载失败：{resource.error}</span><button className="secondary" onClick={reload}>重试</button></div>}
    <div className="management-toolbar"><div className="toolbar-filters"><label className="search-field"><span className="sr-only">搜索访问密钥</span><input type="search" placeholder="搜索名称或模型" value={query} onChange={event => setQuery(event.target.value)} /></label><label className="filter-field"><span className="sr-only">访问密钥状态</span><select aria-label="访问密钥状态" value={status} onChange={event => setStatus(event.target.value)}><option value="">全部状态</option><option value="true">已启用</option><option value="false">已停用</option></select></label></div><div className="toolbar-actions"><button className="secondary" disabled={busy} onClick={reload}>刷新</button><button className="primary" onClick={() => { setDraft({ ...initial }); setModels(""); setChannels(""); setExpires(""); setDrawerOpen(true); }}>＋ 新建访问密钥</button></div></div>
    {createdSecret && <div className="secret-reveal" role="status"><div><strong>访问密钥已创建</strong><p>完整密钥只显示这一次，请立即复制并妥善保存。</p><code>{createdSecret}</code></div><button className="secondary" onClick={() => setCreatedSecret("")}>隐藏密钥</button></div>}
    <div className="panel management-table-panel"><div className="table-heading"><div><h2>访问密钥</h2><p>{rows === null ? "正在读取密钥配置" : `共 ${rows.length} 个 · 显示 ${filtered.length} 个`}</p></div></div><div className="table-wrap"><table className="management-table"><thead><tr><th>名称</th><th>状态</th><th>用量</th><th>模型范围</th><th>到期时间</th><th>操作</th></tr></thead><tbody>{filtered.map(row => <tr key={row.id}><td><strong>{row.name}</strong><small className="table-secondary">{row.key || "密钥仅创建时显示"}</small></td><td><span className={`status-pill ${row.status ? "is-active" : "is-disabled"}`}><i />{row.status ? "已启用" : "已停用"}</span></td><td><span className="numeric-value">{row.quota_used ?? 0}</span><small className="table-secondary">/ {row.quota_limit || "不限"} Token</small></td><td><div className="model-tags">{row.allowed_models.length ? <>{row.allowed_models.slice(0, 2).map(model => <span className="model-tag" key={model}>{model}</span>)}{row.allowed_models.length > 2 && <span className="model-tag">+{row.allowed_models.length - 2}</span>}</> : <span className="muted">不限</span>}</div></td><td>{row.expires_at || <span className="muted">永不过期</span>}</td><td><div className="row-actions"><button className="table-action" aria-label={`编辑密钥 ${row.name}`} disabled={busy} onClick={() => edit(row)}>编辑</button><button className="table-action menu-danger" aria-label={`删除密钥 ${row.name}`} disabled={busy} onClick={() => { if (window.confirm(`删除访问密钥“${row.name}”？`)) void run(async () => { await del(`/api/v1/api-keys/${encodeURIComponent(row.id!)}`); reload(); }); }}>删除</button></div></td></tr>)}</tbody></table></div>{rows === null && !resource.error && <div className="empty-state"><span className="loading-mark" /><strong>正在加载访问密钥</strong></div>}{rows?.length === 0 && <div className="empty-state"><strong>还没有访问密钥</strong><p>创建密钥后，客户端即可使用网关。</p><button className="primary" onClick={() => setDrawerOpen(true)}>新建访问密钥</button></div>}{rows && rows.length > 0 && filtered.length === 0 && <div className="empty-state compact-empty"><strong>没有符合条件的密钥</strong><button className="secondary" onClick={() => { setQuery(""); setStatus(""); }}>清除筛选</button></div>}</div>
    {drawerOpen && <div className="drawer-backdrop" role="presentation" onMouseDown={event => { if (event.target === event.currentTarget) reset(); }}><section className="edit-drawer" role="dialog" aria-modal="true" aria-labelledby="key-drawer-title"><DialogA11y onClose={reset} /><div className="drawer-header"><div><span className="eyebrow">访问权限</span><h2 id="key-drawer-title">{draft.id ? "编辑访问密钥" : "新建访问密钥"}</h2></div><button className="icon-button" aria-label="关闭访问密钥编辑" onClick={reset}>×</button></div><form onSubmit={save}><div className="drawer-content"><p className="drawer-description">为下游客户端设置模型、渠道、配额和有效期限制。</p><div className="drawer-fields"><label>密钥名称<input required maxLength={128} value={draft.name} onChange={event => setDraft({ ...draft, name: event.target.value })} /></label><label>Token 配额 <span className="muted">0 表示不限</span><input type="number" min={0} step={1} value={draft.quota_limit} onChange={event => setDraft({ ...draft, quota_limit: Number(event.target.value) })} /></label><label>到期时间 <span className="muted">ISO 时间，须包含时区</span><input placeholder="2027-01-01T00:00:00Z" value={expires} onChange={event => setExpires(event.target.value)} /></label><label>允许的公开模型 <span className="muted">留空表示不限制，每行一个</span><textarea rows={4} value={models} onChange={event => setModels(event.target.value)} /></label><label>允许的渠道 ID <span className="muted">留空表示不限制，每行一个</span><textarea rows={4} value={channels} onChange={event => setChannels(event.target.value)} /></label><label className="checkbox-label"><input type="checkbox" checked={!!draft.status} onChange={event => setDraft({ ...draft, status: event.target.checked ? 1 : 0 })} />启用此密钥</label></div></div><footer className="drawer-footer"><span className="muted">当前已用 {draft.quota_used ?? 0} Token</span><div><button className="secondary" type="button" onClick={reset}>取消</button><button className="primary" disabled={busy}>{busy ? "保存中…" : "保存密钥"}</button></div></footer></form></section></div>}
  </section>;
}
