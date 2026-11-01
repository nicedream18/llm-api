import { useState } from "react";
import { del, post, put } from "./api";
import { lines, useAction, useResource } from "./adminHooks";

type AccessKey = { id?: string; name: string; key?: string | null; status: number; allowed_models: string[]; allowed_channels: string[]; quota_limit: number; quota_used?: number; expires_at?: string | null };
const initial: AccessKey = { name: "", status: 1, allowed_models: [], allowed_channels: [], quota_limit: 0 };

export function ApiKeyManager({ onError }: { onError: (message: string) => void }) {
  const [rows, reload] = useResource<AccessKey[]>("/api/v1/api-keys", onError);
  const [draft, setDraft] = useState<AccessKey>({ ...initial });
  const [models, setModels] = useState(""); const [channels, setChannels] = useState("");
  const [expires, setExpires] = useState(""); const [createdSecret, setCreatedSecret] = useState("");
  const [busy, run] = useAction(onError);
  const reset = () => { setDraft({ ...initial }); setModels(""); setChannels(""); setExpires(""); };
  return <section><div className="panel"><h2>访问密钥列表</h2><button onClick={reload}>刷新密钥</button><div className="table-wrap"><table><thead><tr><th>名称</th><th>状态</th><th>用量 / 上限</th><th>到期时间</th><th>操作</th></tr></thead><tbody>{rows?.map(row => <tr key={row.id}><td>{row.name} · {row.key}</td><td>{row.status ? "启用" : "停用"}</td><td>{row.quota_used} / {row.quota_limit || "未设上限"}</td><td>{row.expires_at || "未设置"}</td><td><button disabled={busy} onClick={() => { setDraft(row); setModels(row.allowed_models.join("\n")); setChannels(row.allowed_channels.join("\n")); setExpires(row.expires_at || ""); setCreatedSecret(""); }}>编辑密钥 {row.name}</button><button disabled={busy} onClick={() => { if (window.confirm(`删除访问密钥“${row.name}”？`)) void run(async () => { await del(`/api/v1/api-keys/${encodeURIComponent(row.id!)}`); reload(); }); }}>删除密钥 {row.name}</button></td></tr>)}</tbody></table></div>{rows?.length === 0 && <p>暂无访问密钥。</p>}</div>
    <form className="panel access-key-form" onSubmit={event => { event.preventDefault(); void run(async () => {
      if (expires && Number.isNaN(Date.parse(expires))) throw new Error("请输入带时区的有效到期时间");
      const value = { id: draft.id, name: draft.name, status: draft.status, allowed_models: lines(models), allowed_channels: lines(channels), quota_limit: draft.quota_limit, expires_at: expires ? new Date(expires).toISOString() : null };
      if (draft.id) await put("/api/v1/api-keys", value);
      else { const created = await post<AccessKey>("/api/v1/api-keys", value); setCreatedSecret(created.key || ""); }
      reset(); reload();
    }); }}><h2>{draft.id ? "编辑访问密钥" : "创建访问密钥"}</h2><div className="provider-filter-grid"><label>密钥名称<input required maxLength={128} value={draft.name} onChange={event => setDraft({ ...draft, name: event.target.value })} /></label><label>Token 配额（0 为未设上限）<input type="number" min={0} step={1} value={draft.quota_limit} onChange={event => setDraft({ ...draft, quota_limit: Number(event.target.value) })} /></label><label>到期时间（ISO，含时区）<input placeholder="2027-01-01T00:00:00Z" value={expires} onChange={event => setExpires(event.target.value)} /></label><label>允许的公开模型（空为不限）<textarea value={models} onChange={event => setModels(event.target.value)} /></label><label>允许的渠道 ID（空为不限）<textarea value={channels} onChange={event => setChannels(event.target.value)} /></label><label className="checkbox-label"><input type="checkbox" checked={!!draft.status} onChange={event => setDraft({ ...draft, status: event.target.checked ? 1 : 0 })} />启用访问密钥</label></div><button disabled={busy}>保存访问密钥</button><button type="button" onClick={reset}>取消密钥编辑</button></form>
    {createdSecret && <div className="panel" role="status"><h2>新密钥（仅此次显示）</h2><code>{createdSecret}</code><button onClick={() => setCreatedSecret("")}>隐藏新密钥</button></div>}
  </section>;
}
