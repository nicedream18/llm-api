import { useCallback, useEffect, useRef, useState } from "react";
import { get, post, put } from "./api";

type Settings = { enabled: boolean; quota_interval: number; models_interval: number };
type Snapshot = { fetched_at: string | null; error_code: string | null; payload: { status?: string; models?: string[]; windows?: Array<{ window: string; unit: string; remaining: string | null; limit: string | null; currency: string | null; reset_at: string | null }> } | null };
type State = { settings: Settings; snapshots: Record<string, Snapshot>; jobs: Array<{ id: string; kind: string; status: string; attempts: number; error_code: string | null }> };

export function ProviderSyncPanel({ accountId, onError, onClose }: { accountId: string; onError: (message: string) => void; onClose: () => void }) {
  const [state, setState] = useState<State | null>(null);
  const [settings, setSettings] = useState<Settings>({ enabled: false, quota_interval: 300, models_interval: 21600 });
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const requestVersion = useRef(0);
  const load = useCallback(async () => {
    const version = ++requestVersion.current;
    try { const value = await get<State>(`/api/v1/providers/${accountId}/sync`); if (version !== requestVersion.current) return; setState(value); setSettings({ enabled: !!value.settings.enabled, quota_interval: value.settings.quota_interval, models_interval: value.settings.models_interval }); }
    catch (error) { if (version === requestVersion.current) onError(error instanceof Error ? error.message : "加载同步状态失败"); }
  }, [accountId, onError]);
  useEffect(() => { setState(null); void load(); return () => { requestVersion.current++; }; }, [load]);
  const run = async (action: () => Promise<void>) => {
    setBusy(true); setMessage("");
    try { await action(); await load(); } catch (error) { onError(error instanceof Error ? error.message : "同步操作失败"); }
    finally { setBusy(false); }
  };
  const quota = state?.snapshots.quota;
  return <section className="panel" aria-label="配额与模型同步"><div className="panel-head"><h2>配额与模型同步</h2><div><button onClick={() => void load()} disabled={busy}>刷新状态</button><button onClick={onClose}>关闭同步面板</button></div></div>
    <p>配额：{quota?.payload?.status || "unknown"} · 更新时间：{quota?.fetched_at ? new Date(quota.fetched_at).toLocaleString() : "尚未同步"}</p>
    {quota?.error_code && <p role="alert">最近同步失败：{quota.error_code}，保留上次有效快照。</p>}
    <div className="table-wrap"><table><thead><tr><th>窗口</th><th>单位</th><th>剩余</th><th>上限</th><th>重置时间</th></tr></thead><tbody>{quota?.payload?.windows?.map((window, index) => <tr key={index}><td>{window.window}</td><td>{window.unit} {window.currency || ""}</td><td>{window.remaining ?? "未知"}</td><td>{window.limit ?? "未知"}</td><td>{window.reset_at || "未知"}</td></tr>)}</tbody></table></div>
    <p>已同步模型：{state?.snapshots.models?.payload?.models?.join("、") || "无"}</p>
    <ul>{state?.jobs.map(job => <li key={job.id}>{job.kind}：{job.status} · 尝试 {job.attempts} 次 {job.error_code || ""}</li>)}</ul>
    <button disabled={busy} onClick={() => void run(async () => { await post(`/api/v1/providers/${accountId}/sync`, {}); setMessage("同步任务已提交，可刷新查看进度。"); })}>提交配额和模型同步</button>
    <form onSubmit={event => { event.preventDefault(); void run(async () => { await put(`/api/v1/providers/${accountId}/sync/settings`, settings); setMessage("同步设置已保存"); }); }}><div className="provider-filter-grid">
      <label className="checkbox-label"><input type="checkbox" checked={settings.enabled} onChange={event => setSettings({ ...settings, enabled: event.target.checked })} />启用自动同步</label>
      <label>配额同步间隔（秒）<input type="number" min={60} max={86400} value={settings.quota_interval} onChange={event => setSettings({ ...settings, quota_interval: Number(event.target.value) })} /></label>
      <label>模型同步间隔（秒）<input type="number" min={300} max={604800} value={settings.models_interval} onChange={event => setSettings({ ...settings, models_interval: Number(event.target.value) })} /></label></div><button disabled={busy}>保存同步设置</button></form>
    {message && <p role="status">{message}</p>}
  </section>;
}
