import { useEffect, useState } from "react";
import { del, get, post, put } from "./api";
import type { Provider } from "./types";
import "./provider.css";

type Props = { onError: (message: string) => void };
type AccountForm = { provider: string; name: string; priority: string; clientConfig: string; modelMapping: string };
const emptyForm: AccountForm = { provider: "codex", name: "", priority: "0", clientConfig: "{}", modelMapping: "{}" };
const providerNames = ["codex", "gemini", "grok", "kimi", "qoder", "workbuddy"];

function parseObject(value: string, label: string): Record<string, unknown> {
  const parsed: unknown = JSON.parse(value || "{}");
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) throw new Error(`${label}必须是 JSON 对象`);
  return parsed as Record<string, unknown>;
}

export function ProviderManager({ onError }: Props) {
  const [accounts, setAccounts] = useState<Provider[]>([]);
  const [form, setForm] = useState<AccountForm>(emptyForm);
  const [editing, setEditing] = useState<string | null>(null);
  const [token, setToken] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);

  const load = () => get<Provider[]>("/api/v1/providers").then(setAccounts).catch((error: Error) => onError(error.message));
  useEffect(() => { load(); }, []);
  const setField = (key: keyof AccountForm, value: string) => setForm(current => ({ ...current, [key]: value }));
  const reset = () => { setEditing(null); setForm(emptyForm); setToken(""); };
  const beginEdit = (account: Provider) => {
    setEditing(account.id);
    setForm({ provider: account.provider, name: account.name, priority: String(account.priority), clientConfig: JSON.stringify(account.client_config || {}, null, 2), modelMapping: JSON.stringify(account.model_mapping || {}, null, 2) });
    setToken(""); setMessage("");
  };
  const save = async () => {
    if (!form.name.trim()) return;
    setBusy(true); setMessage("");
    try {
      const payload = { provider: form.provider, name: form.name.trim(), priority: Number(form.priority) || 0, client_config: parseObject(form.clientConfig, "Client 配置"), model_mapping: parseObject(form.modelMapping, "模型映射") };
      if (editing) await put(`/api/v1/providers/${encodeURIComponent(editing)}`, payload);
      else await post("/api/v1/providers", payload);
      setMessage(editing ? "账号已更新" : "账号已创建"); reset(); await load();
    } catch (error) { onError(error instanceof Error ? error.message : "保存 Provider 账号失败"); }
    finally { setBusy(false); }
  };
  const remove = async (account: Provider) => {
    if (!window.confirm(`删除账号“${account.name}”？`)) return;
    try { await del(`/api/v1/providers/${encodeURIComponent(account.id)}`); if (editing === account.id) reset(); await load(); }
    catch (error) { onError(error instanceof Error ? error.message : "删除 Provider 账号失败"); }
  };
  const authorize = async (account: Provider) => {
    try {
      const result = await post<{ authorization_url: string }>(`/api/v1/providers/${encodeURIComponent(account.id)}/authorize`, {});
      window.open(result.authorization_url, "waliapi-provider-oauth", "noopener,noreferrer");
      setMessage("授权页面已打开；完成授权后刷新账号状态。");
    } catch (error) { onError(error instanceof Error ? error.message : "启动 OAuth 授权失败"); }
  };
  const saveToken = async (account: Provider) => {
    if (!token.trim()) return;
    try { await post(`/api/v1/providers/${encodeURIComponent(account.id)}/token`, { access_token: token.trim() }); setToken(""); setMessage("Token 已安全保存"); await load(); }
    catch (error) { onError(error instanceof Error ? error.message : "保存 Token 失败"); }
  };
  const action = async (account: Provider, operation: "refresh" | "logout" | "quota" | "models") => {
    try {
      if (operation === "logout") { await post(`/api/v1/providers/${encodeURIComponent(account.id)}/logout`, {}); setMessage("账号已退出"); }
      else if (operation === "refresh") { await post(`/api/v1/providers/${encodeURIComponent(account.id)}/refresh`, {}); setMessage("Token 已刷新"); }
      else if (operation === "quota") { const result = await get<Record<string, unknown>>(`/api/v1/providers/${encodeURIComponent(account.id)}/quota`); setMessage(`额度：${JSON.stringify(result)}`); }
      else { const result = await get<{ models: string[] }>(`/api/v1/providers/${encodeURIComponent(account.id)}/models`); setMessage(`已同步 ${result.models.length} 个模型`); }
      await load();
    } catch (error) { onError(error instanceof Error ? error.message : "Provider 操作失败"); }
  };
  return <section className="provider-manager">
    <div className="panel provider-form"><div className="panel-head"><div><h2>{editing ? "编辑 Provider 账号" : "添加 Auth Provider 账号"}</h2><p className="muted">OAuth 配置只保存在服务端；管理台不会回显访问 Token。</p></div>{editing && <button className="secondary" onClick={reset}>取消编辑</button>}</div>
      <div className="provider-form-grid"><label className="field-label">Provider<select value={form.provider} onChange={event => setField("provider", event.target.value)}>{providerNames.map(name => <option key={name} value={name}>{name}</option>)}</select></label><label className="field-label">显示名称<input value={form.name} maxLength={128} onChange={event => setField("name", event.target.value)} placeholder="个人账号" /></label><label className="field-label">优先级<input type="number" min={-1000} max={1000} value={form.priority} onChange={event => setField("priority", event.target.value)} /></label></div>
      <div className="provider-json-grid"><label className="field-label">Client 配置<textarea value={form.clientConfig} onChange={event => setField("clientConfig", event.target.value)} spellCheck={false} placeholder={'{"authorization_url":"https://…","client_id":"…","token_url":"https://…"}'} /></label><label className="field-label">模型映射<textarea value={form.modelMapping} onChange={event => setField("modelMapping", event.target.value)} spellCheck={false} placeholder={'{"公开模型":"Provider 模型"}'} /></label></div>
      <button className="primary" onClick={save} disabled={busy || !form.name.trim()}>{busy ? "保存中…" : editing ? "保存账号" : "创建账号"}</button>{message && <p className="success" role="status">{message}</p>}
    </div>
    <div className="provider-list">{accounts.map(account => <article className="panel provider-card" key={account.id}><div className="provider-card-head"><div><span className="provider-badge">{account.provider}</span><h3>{account.name}</h3><small>优先级 {account.priority} · 状态 {account.status}{account.failure_count ? ` · 连续失败 ${account.failure_count}` : ""}{account.cooldown_until ? ` · 冷却至 ${new Date(account.cooldown_until).toLocaleString()}` : ""}</small></div><div className="provider-actions"><button className="secondary" onClick={() => beginEdit(account)}>编辑</button><button className="danger" onClick={() => void remove(account)}>删除</button></div></div><div className="provider-actions"><button className="primary" onClick={() => void authorize(account)}>OAuth 授权</button><button className="secondary" onClick={() => void action(account, "refresh")} disabled={account.status !== "active"}>刷新 Token</button><button className="secondary" onClick={() => void action(account, "models")} disabled={account.status !== "active"}>同步模型</button><button className="secondary" onClick={() => void action(account, "quota")} disabled={account.status !== "active"}>查询额度</button><button className="secondary" onClick={() => void action(account, "logout")} disabled={account.status !== "active"}>退出账号</button></div><div className="provider-token"><input type="password" autoComplete="off" placeholder="手动设置访问 Token（可选）" value={editing === account.id ? token : ""} onChange={event => { setEditing(account.id); setToken(event.target.value); }} /><button className="secondary" onClick={() => void saveToken(account)} disabled={!token.trim()}>保存 Token</button></div>{account.models?.length > 0 && <p className="muted">模型：{account.models.join(" · ")}</p>}</article>)}{accounts.length === 0 && <div className="panel"><p className="muted">暂无 Provider 账号。</p></div>}</div>
  </section>;
}
