import { useState } from "react";
import { del, post } from "./api";
import { useAction, useResource } from "./adminHooks";

type Session = { id: string; created_at: number; expires_at: number; revoked_at: number | null };
export function AdministrationPanel({ onError }: { onError: (message: string) => void }) {
  const [sessions, reload] = useResource<Session[]>("/api/v1/auth/sessions", onError);
  const [diagnostics, refresh] = useResource<Record<string, unknown>>("/api/v1/administration/diagnostics", onError);
  const [offset, setOffset] = useState(0);
  const [events, refreshAudit] = useResource<Array<{ id: string; action: string; username: string; success: boolean; request_id: string; created_at: string }>>(`/api/v1/administration/audit?limit=50&offset=${offset}`, onError);
  const [password, setPassword] = useState(""); const [busy, run] = useAction(onError);
  return <div className="panel"><h2>会话与运行诊断</h2><button onClick={() => { reload(); refresh(); refreshAudit(); }}>刷新运行状态</button><pre className="detail-json" aria-label="运行诊断">{JSON.stringify(diagnostics, null, 2)}</pre><h3>管理员会话</h3><ul>{sessions?.map(session => <li key={session.id}>{new Date(session.created_at * 1000).toLocaleString()} → {new Date(session.expires_at * 1000).toLocaleString()} · {session.revoked_at ? "已撤销" : "未撤销"}<button disabled={busy || !!session.revoked_at} onClick={() => { if (window.confirm("撤销此会话？当前会话也可能退出。")) void run(async () => { await del(`/api/v1/auth/sessions/${session.id}`); reload(); }); }}>撤销会话 {session.id.slice(0, 8)}</button></li>)}</ul><form onSubmit={event => { event.preventDefault(); void run(async () => { await post("/api/v1/auth/change-password", { password }); setPassword(""); window.dispatchEvent(new Event("admin-session-expired")); }); }}><label>新管理员密码<input type="password" minLength={12} maxLength={512} autoComplete="new-password" required value={password} onChange={event => setPassword(event.target.value)} /></label><button disabled={busy}>修改密码并退出所有旧会话</button></form><h3>管理审计</h3><div className="table-wrap"><table><thead><tr><th>时间</th><th>主体</th><th>动作</th><th>结果 / Request ID</th></tr></thead><tbody>{events?.map(event => <tr key={event.id}><td>{event.created_at}</td><td>{event.username}</td><td>{event.action}</td><td>{event.success ? "成功" : "失败"} · {event.request_id}</td></tr>)}</tbody></table></div><button disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - 50))}>上一页审计</button><button disabled={!events || events.length < 50} onClick={() => setOffset(offset + 50)}>下一页审计</button></div>;
}
