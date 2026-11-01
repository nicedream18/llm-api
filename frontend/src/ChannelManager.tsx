import { useState } from "react";
import { del, downloadFile, post, put } from "./api";
import { lines, useAction, useResource } from "./adminHooks";

export type ManagedChannel = { id?: string; name: string; type: string; base_url: string; api_key?: string | null; status: number; priority: number; weight: number; models: string[]; model_mapping?: Record<string, string> | null; config?: Record<string, unknown> | null };
type UpstreamKey = { id?: string; name: string; api_key?: string | null; status: number; weight: number; last_error?: string | null };
const initial: ManagedChannel = { name: "", type: "openai", base_url: "", status: 1, priority: 0, weight: 1, models: [] };
const endpointOptions = ["/v1/chat/completions", "/v1/embeddings", "/v1/images/generations", "/v1/audio/transcriptions", "/v1/audio/speech"];

export function ChannelManager({ onError }: { onError: (message: string) => void }) {
  const [channels, reload] = useResource<ManagedChannel[]>("/api/v1/channels", onError);
  const [draft, setDraft] = useState<ManagedChannel>({ ...initial });
  const [secret, setSecret] = useState(""); const [models, setModels] = useState("");
  const [mapping, setMapping] = useState<Array<[string, string]>>([]);
  const [endpoints, setEndpoints] = useState<string[]>([]);
  const [keyChannel, setKeyChannel] = useState<ManagedChannel | null>(null);
  const [importText, setImportText] = useState(""); const [importRows, setImportRows] = useState<ManagedChannel[] | null>(null);
  const [replace, setReplace] = useState(false);
  const [message, setMessage] = useState(""); const [busy, run] = useAction(onError);
  const reset = () => { setDraft({ ...initial }); setSecret(""); setModels(""); setMapping([]); setEndpoints([]); };
  const edit = (row: ManagedChannel) => { setDraft(row); setSecret(""); setModels(row.models.join("\n")); setMapping(Object.entries(row.model_mapping || {})); setEndpoints(Array.isArray(row.config?.endpoints) ? row.config.endpoints as string[] : []); setMessage(""); };
  const payload = () => {
    const config = { ...draft.config }; delete config.endpoints;
    if (endpoints.length) config.endpoints = endpoints;
    return { id: draft.id, name: draft.name, type: draft.type, base_url: draft.base_url, status: draft.status, priority: draft.priority, weight: draft.weight, api_key: secret || null, models: lines(models), model_mapping: Object.fromEntries(mapping.filter(([publicName, upstream]) => publicName.trim() && upstream.trim()).map(([publicName, upstream]) => [publicName.trim(), upstream.trim()])), config };
  };
  const action = (row: ManagedChannel, operation: string) => run(async () => {
    const result = await post<{ success?: boolean; message?: string }>(`/api/v1/channels/${encodeURIComponent(row.id!)}/${operation}`, {});
    setMessage(operation === "test" ? (result.success ? "渠道测试通过" : `渠道测试失败：${result.message || "请检查连接配置"}`) : operation === "clone" ? "渠道已复制" : "模型列表已同步"); reload();
  });
  return <section>
    <div className="panel"><div className="panel-head"><h2>渠道列表</h2><button onClick={reload}>刷新渠道</button></div><div className="table-wrap"><table><thead><tr><th>名称 / 协议</th><th>状态 / 优先级 / 权重</th><th>模型</th><th>操作</th></tr></thead><tbody>{channels?.map(row => <tr key={row.id}><td>{row.name} / {row.type}</td><td>{row.status ? "启用" : "停用"} / {row.priority} / {row.weight}</td><td>{row.models.join("、")}</td><td className="actions"><button disabled={busy} onClick={() => edit(row)}>编辑 {row.name}</button><button disabled={busy} onClick={() => void action(row, "test")}>测试 {row.name}</button><button disabled={busy} onClick={() => void action(row, "clone")}>复制 {row.name}</button><button disabled={busy} onClick={() => void action(row, "sync-models")}>同步模型 {row.name}</button><button onClick={() => setKeyChannel(row)}>管理多 Key {row.name}</button><button disabled={busy} className="danger" onClick={() => { if (window.confirm(`删除渠道“${row.name}”？`)) void run(async () => { await del(`/api/v1/channels/${row.id}`); reload(); }); }}>删除 {row.name}</button></td></tr>)}</tbody></table></div>{channels?.length === 0 && <p>暂无渠道，请使用下方表单创建。</p>}</div>
    <form className="panel channel-form" onSubmit={event => { event.preventDefault(); void run(async () => { if (draft.id) await put("/api/v1/channels", payload()); else await post("/api/v1/channels", payload()); reset(); reload(); setMessage("渠道已保存"); }); }}><h2>{draft.id ? "编辑渠道" : "创建渠道"}</h2><div className="provider-filter-grid">
      <label>渠道名称<input required maxLength={128} value={draft.name} onChange={event => setDraft({ ...draft, name: event.target.value })} /></label>
      <label>渠道协议<select value={draft.type} onChange={event => setDraft({ ...draft, type: event.target.value })}>{["openai", "claude", "gemini", "ollama", "azure", "deepseek", "qwen", "moonshot", "zhipu", "doubao", "custom"].map(type => <option key={type}>{type}</option>)}</select></label>
      <label>Base URL<input required type="url" value={draft.base_url || ""} onChange={event => setDraft({ ...draft, base_url: event.target.value })} /></label>
      <label>主 Key（留空保留已有值）<input type="password" autoComplete="new-password" value={secret} onChange={event => setSecret(event.target.value)} /></label>
      <label>优先级<input type="number" min={-1000} max={1000} value={draft.priority} onChange={event => setDraft({ ...draft, priority: Number(event.target.value) })} /></label>
      <label>渠道权重<input type="number" min={1} max={1000} value={draft.weight} onChange={event => setDraft({ ...draft, weight: Number(event.target.value) })} /></label>
      <label className="checkbox-label"><input type="checkbox" checked={!!draft.status} onChange={event => setDraft({ ...draft, status: event.target.checked ? 1 : 0 })} />启用渠道</label>
      <label>模型列表（每行一个）<textarea value={models} onChange={event => setModels(event.target.value)} /></label></div>
      <fieldset><legend>模型映射</legend>{mapping.map(([publicName, upstream], index) => <div className="inline-form" key={index}><input aria-label={`公开模型 ${index + 1}`} value={publicName} onChange={event => setMapping(mapping.map((pair, position) => position === index ? [event.target.value, pair[1]] : pair))} /><input aria-label={`上游模型 ${index + 1}`} value={upstream} onChange={event => setMapping(mapping.map((pair, position) => position === index ? [pair[0], event.target.value] : pair))} /><button type="button" onClick={() => setMapping(mapping.filter((_, position) => position !== index))}>移除映射 {index + 1}</button></div>)}<button type="button" onClick={() => setMapping([...mapping, ["", ""]])}>添加模型映射</button></fieldset>
      <fieldset><legend>Endpoint 能力（未指定时使用协议默认能力）</legend>{endpointOptions.map(endpoint => <label className="checkbox-label" key={endpoint}><input type="checkbox" checked={endpoints.includes(endpoint)} onChange={event => setEndpoints(event.target.checked ? [...endpoints, endpoint] : endpoints.filter(value => value !== endpoint))} />{endpoint}</label>)}</fieldset>
      <div className="actions"><button disabled={busy}>保存渠道</button><button type="button" disabled={busy} onClick={() => void run(async () => { const result = await post<{ success: boolean }>("/api/v1/channels/test-draft", payload()); setMessage(result.success ? "草稿测试通过，尚未保存" : "草稿测试失败，请检查配置"); })}>测试当前草稿</button><button type="button" onClick={reset}>新建 / 取消编辑</button></div></form>
    {keyChannel && <UpstreamKeys key={keyChannel.id} channel={keyChannel} onError={onError} onClose={() => setKeyChannel(null)} />}
    <div className="panel"><h2>渠道导入与导出</h2><button disabled={busy} onClick={() => void run(() => downloadFile("/api/v1/channels/export", "channels.json"))}>导出配置（不含密钥）</button><label>导入 JSON<textarea value={importText} onChange={event => { setImportText(event.target.value); setImportRows(null); }} /></label><button disabled={busy} onClick={() => void run(async () => { if (importText.length > 2_000_000) throw new Error("导入文件不得超过 2 MB"); const value: unknown = JSON.parse(importText); const rows = Array.isArray(value) ? value : (value as { channels?: unknown })?.channels; if (!Array.isArray(rows) || !rows.length || rows.length > 500 || rows.some(row => !row || typeof row.name !== "string")) throw new Error("导入需包含 1–500 个有名称的渠道"); setImportRows(rows); })}>预览导入</button>
      {importRows && <div><p>将导入 {importRows.length} 个渠道：{importRows.map(row => row.name).join("、")}</p><label className="checkbox-label"><input type="checkbox" checked={replace} onChange={event => setReplace(event.target.checked)} />替换相同 ID 的配置</label><button disabled={busy} onClick={() => void run(async () => { if (replace && !window.confirm("确认覆盖相同 ID 的渠道配置？")) return; const result = await post<{ created: string[]; updated: string[]; skipped: string[] }>("/api/v1/channels/import", { channels: importRows, replace_existing: replace }); setMessage(`导入完成：创建 ${result.created.length}，更新 ${result.updated.length}，跳过 ${result.skipped.length}`); setImportRows(null); setImportText(""); reload(); })}>确认导入</button></div>}</div>
    {message && <p role="status">{message}</p>}
  </section>;
}

function UpstreamKeys({ channel, onError, onClose }: { channel: ManagedChannel; onError: (message: string) => void; onClose: () => void }) {
  const path = `/api/v1/channels/${encodeURIComponent(channel.id!)}/api-keys`;
  const [keys, reload] = useResource<UpstreamKey[]>(path, onError);
  const [draft, setDraft] = useState<UpstreamKey>({ name: "", status: 1, weight: 1 }); const [secret, setSecret] = useState("");
  const [message, setMessage] = useState(""); const [busy, run] = useAction(onError);
  return <section className="panel"><div className="panel-head"><h2>{channel.name} 的多 Key</h2><button onClick={onClose}>关闭多 Key 面板</button></div><ul>{keys?.map(key => <li key={key.id}>{key.name} · {key.api_key} · 权重 {key.weight} · {key.status ? "启用" : "停用"} {key.last_error || ""}<button onClick={() => { setDraft(key); setSecret(""); }}>编辑 Key {key.name}</button><button disabled={busy} onClick={() => void run(async () => { const result = await post<{ success: boolean }>(`${path}/${key.id}/test`, {}); setMessage(result.success ? "单 Key 测试通过" : "单 Key 测试失败"); reload(); })}>测试 Key {key.name}</button><button disabled={busy} onClick={() => { if (window.confirm(`删除 Key“${key.name}”？`)) void run(async () => { await del(`${path}/${key.id}`); reload(); }); }}>删除 Key {key.name}</button></li>)}</ul>
    <form onSubmit={event => { event.preventDefault(); void run(async () => { const value = { ...draft, api_key: secret || null }; if (draft.id) await put(`${path}/${draft.id}`, value); else await post(path, value); setDraft({ name: "", status: 1, weight: 1 }); setSecret(""); reload(); setMessage("上游 Key 已保存"); }); }}><div className="provider-filter-grid"><label>Key 名称<input required value={draft.name} onChange={event => setDraft({ ...draft, name: event.target.value })} /></label><label>Key 密钥（编辑时留空保留）<input type="password" autoComplete="new-password" required={!draft.id} value={secret} onChange={event => setSecret(event.target.value)} /></label><label>Key 权重<input type="number" min={1} max={1000} value={draft.weight} onChange={event => setDraft({ ...draft, weight: Number(event.target.value) })} /></label><label className="checkbox-label"><input type="checkbox" checked={!!draft.status} onChange={event => setDraft({ ...draft, status: event.target.checked ? 1 : 0 })} />启用此 Key</label></div><button disabled={busy}>保存上游 Key</button></form>{message && <p role="status">{message}</p>}
  </section>;
}
