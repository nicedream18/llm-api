import { useEffect, useState } from "react";
import { del, get, post, put } from "./api";
import { DialogA11y } from "./DialogA11y";
import "./security.css";

type Settings = {
  enabled: boolean; mode: string; scan_unicode: boolean; scan_tools: boolean; scan_network: boolean;
  scan_response: boolean; redact_secrets: boolean; block_on_critical: boolean; fail_closed: boolean;
  capabilities?: { stream_response_scan: boolean; binary_attachment_scan: boolean };
};
type BuiltinRule = { id: string; rule_id: string; name: string; description: string; category: string; severity: string; action: string; enabled: number; toggle_key?: string; pattern?: string };
type CustomRule = { id?: string; name: string; description: string; category: string; severity: string; action: string; enabled: number; pattern: string; rule_type: string; match_type: string };
type Finding = { id: string; log_id: string; title: string; severity: string; phase: string; location: string; evidence_masked: string; action: string; created_at: string };
const base = "/api/v1/security";
const switches = [
  ["enabled", "安全扫描"], ["redact_secrets", "密钥自动脱敏"], ["scan_unicode", "Unicode 扫描"],
  ["scan_network", "网络扫描"], ["scan_tools", "工具扫描"], ["scan_response", "普通响应扫描"],
  ["block_on_critical", "block 模式拦截 Critical"], ["fail_closed", "扫描失败时拒绝转发"],
] as const;
const severities = ["info", "low", "medium", "high", "critical"];
const actions = ["warn", "allow", "redact", "sanitize", "block"];
const emptyRule = (): CustomRule => ({ name: "", description: "", category: "keyword", severity: "medium", action: "warn", enabled: 1, pattern: "", rule_type: "blacklist", match_type: "literal" });

export function SecurityPage({ onError }: { onError: (message: string) => void }) {
  const [settings, setSettings] = useState<Settings | null>(null);
  const [draft, setDraft] = useState<Settings | null>(null);
  const [builtin, setBuiltin] = useState<BuiltinRule[]>([]);
  const [custom, setCustom] = useState<CustomRule[]>([]);
  const [findings, setFindings] = useState<Finding[]>([]);
  const [page, setPage] = useState(1);
  const [filter, setFilter] = useState("");
  const [editBuiltin, setEditBuiltin] = useState<BuiltinRule | null>(null);
  const [editCustom, setEditCustom] = useState<CustomRule | null>(null);
  const [logDetail, setLogDetail] = useState<unknown>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const report = (value: unknown) => { const text = value instanceof Error ? value.message : "安全配置操作失败"; setError(text); onError(text); };
  const load = async () => {
    const [policy, builtins, customs, rows] = await Promise.all([
      get<Settings>(`${base}/settings`), get<BuiltinRule[]>(`${base}/rules/builtin`),
      get<CustomRule[]>(`${base}/rules/custom`), get<Finding[]>(`${base}/findings?page=${page}&size=20`),
    ]);
    setSettings(policy); setDraft(policy); setBuiltin(builtins); setCustom(customs); setFindings(rows);
  };
  useEffect(() => { setLoading(true); void load().catch(report).finally(() => setLoading(false)); }, [page]);
  const run = async (operation: () => Promise<void>, success: string) => {
    if (busy) return;
    setBusy(true); setError(""); setMessage("");
    try { await operation(); await load(); setMessage(success); }
    catch (value) { report(value); }
    finally { setBusy(false); }
  };
  const closeEditor = () => { if (!busy) { setEditBuiltin(null); setEditCustom(null); } };
  const visible = builtin.filter(rule => `${rule.name} ${rule.rule_id} ${rule.category} ${rule.severity}`.toLowerCase().includes(filter.toLowerCase()));
  return <section className="security-page" aria-busy={loading || busy}>
    {error && <div className="error" role="alert">{error}<button onClick={() => void run(async () => {}, "已刷新")}>重试加载</button></div>}
    {message && <p className="success" role="status">{message}</p>}
    {loading && <p role="status">正在加载安全配置…</p>}
    <div className="panel">
      <div className="table-heading"><div><h2>安全策略</h2><p>设置保存后立即用于新请求；每个请求使用固定策略快照。</p></div><span className="badge">当前模式：{settings?.mode || "加载中"}</span></div>
      {draft && <form onSubmit={event => { event.preventDefault(); void run(async () => { const { capabilities: _capabilities, ...values } = draft; await put(`${base}/settings`, values); }, "安全策略已保存"); }}>
        <fieldset disabled={busy || loading} className="security-policy-fields"><legend className="sr-only">策略设置</legend>
          <label>策略模式<select value={draft.mode} onChange={event => setDraft({ ...draft, mode: event.target.value })}>{["audit", "warn", "redact", "block"].map(mode => <option key={mode}>{mode}</option>)}</select></label>
          <div className="security-switches">{switches.map(([key, label]) => <label className="checkbox-label" key={key}><input type="checkbox" checked={draft[key]} onChange={event => setDraft({ ...draft, [key]: event.target.checked })} />{label}</label>)}</div>
          <p className="muted">密钥自动脱敏在 audit 模式下同样生效。白名单不会豁免凭证保护。</p>
          <p className="muted">不扫描二进制附件内容；流式响应扫描暂不支持。{draft.scan_response ? "开启普通响应扫描后，流式请求将在连接上游前被拒绝。" : "流式请求体仍会接受扫描和脱敏。"}</p>
          <button className="primary" disabled={busy}>{busy ? "保存中…" : "保存安全策略"}</button>
        </fieldset>
      </form>}
    </div>
    <div className="panel">
      <div className="table-heading"><div><h2>内置规则</h2><p>启用 {builtin.filter(rule => rule.enabled).length} / {builtin.length} 条；检测表达式只读。</p></div><button className="secondary" disabled={busy || loading} onClick={() => { if (window.confirm("恢复全部内置规则的默认配置？自定义规则会保留。")) void run(async () => { await post(`${base}/rules/builtin/reset`, {}); }, "内置规则已恢复默认值"); }}>恢复默认规则</button></div>
      <label className="security-filter">筛选内置规则<input value={filter} onChange={event => setFilter(event.target.value)} placeholder="名称、类别、严重度或标识" /></label>
      <div className="table-wrap"><table><thead><tr><th>规则</th><th>类别</th><th>严重度 / 动作</th><th>有效状态</th><th>操作</th></tr></thead><tbody>{visible.map(rule => {
        const key = rule.toggle_key?.replace("security.", "") as keyof Settings | undefined;
        const categoryEnabled = !key || settings?.[key] !== false;
        return <tr key={rule.id}><td><strong>{rule.name}</strong><small className="security-rule-id">{rule.rule_id}</small></td><td>{rule.category}</td><td>{rule.severity} / {rule.action}</td><td>{rule.enabled ? categoryEnabled ? "已启用" : "类别开关已关闭" : "已停用"}</td><td><div className="actions"><button disabled={busy} onClick={() => setEditBuiltin({ ...rule })}>编辑 {rule.name}</button><button disabled={busy} onClick={() => void run(async () => { await put(`${base}/rules/builtin/${encodeURIComponent(rule.id)}`, { enabled: rule.enabled ? 0 : 1 }); }, "内置规则状态已保存")}>{rule.enabled ? "停用" : "启用"}</button></div></td></tr>;
      })}</tbody></table>{!loading && visible.length === 0 && <p className="muted">没有匹配的内置规则。</p>}</div>
    </div>
    <div className="panel">
      <div className="table-heading"><div><h2>黑白名单与自定义规则</h2><p>显式黑名单优先；白名单仅豁免对应值的类别检测。</p></div><button className="primary" disabled={busy || loading} onClick={() => setEditCustom(emptyRule())}>添加自定义规则</button></div>
      <div className="table-wrap"><table><thead><tr><th>名称 / 模式</th><th>类型 / 类别</th><th>匹配 / 动作</th><th>状态</th><th>操作</th></tr></thead><tbody>{custom.map(rule => <tr key={rule.id}><td><strong>{rule.name || "未命名规则"}</strong><small className="security-rule-id">{rule.pattern}</small></td><td>{rule.rule_type === "whitelist" ? "白名单" : "黑名单"} / {rule.category}</td><td>{rule.match_type} / {rule.action}</td><td>{rule.enabled ? "已启用" : "已停用"}</td><td><div className="actions"><button disabled={busy} onClick={() => setEditCustom({ ...rule })}>编辑 {rule.name}</button><button disabled={busy} onClick={() => void run(async () => { await put(`${base}/rules/custom/${encodeURIComponent(rule.id!)}`, { enabled: rule.enabled ? 0 : 1 }); }, "自定义规则状态已保存")}>{rule.enabled ? "停用" : "启用"}</button><button className="danger" disabled={busy} onClick={() => { if (window.confirm(`删除规则“${rule.name}”？`)) void run(async () => { await del(`${base}/rules/custom/${encodeURIComponent(rule.id!)}`); }, "自定义规则已删除"); }}>删除 {rule.name}</button></div></td></tr>)}</tbody></table>{!loading && !custom.length && <p className="muted">暂无自定义规则。</p>}</div>
    </div>
    <div className="panel">
      <div className="table-heading"><div><h2>安全发现</h2><p>证据已脱敏，可查看关联请求记录。</p></div><div className="actions"><button disabled={busy || page === 1} onClick={() => setPage(page - 1)}>上一页</button><span>第 {page} 页</span><button disabled={busy || findings.length < 20} onClick={() => setPage(page + 1)}>下一页</button></div></div>
      <div className="table-wrap"><table><thead><tr><th>发现</th><th>严重度 / 动作</th><th>位置</th><th>证据</th><th>请求</th></tr></thead><tbody>{findings.map(row => <tr key={row.id}><td>{row.title}<small className="security-rule-id">{row.created_at}</small></td><td>{row.severity} / {row.action}</td><td>{row.phase}：{row.location}</td><td>{row.evidence_masked}</td><td><button disabled={busy || !row.log_id} onClick={() => void run(async () => { setLogDetail(await get(`/api/v1/logs/${encodeURIComponent(row.log_id)}`)); }, "请求详情已加载")}>查看请求</button></td></tr>)}</tbody></table>{!loading && !findings.length && <p className="muted">暂无安全发现。</p>}</div>
    </div>
    {(editBuiltin || editCustom) && <div className="drawer-backdrop" role="presentation"><section className="edit-drawer" role="dialog" aria-modal="true" aria-labelledby="security-editor-title"><DialogA11y onClose={closeEditor} /><header className="drawer-header"><h2 id="security-editor-title">{editBuiltin ? "编辑内置规则" : editCustom?.id ? "编辑自定义规则" : "添加自定义规则"}</h2><button className="icon-button" aria-label="关闭规则编辑" disabled={busy} onClick={closeEditor}>×</button></header>
      <form onSubmit={event => { event.preventDefault(); void run(async () => {
        if (editBuiltin) { const { name, description, severity, action, enabled } = editBuiltin; await put(`${base}/rules/builtin/${encodeURIComponent(editBuiltin.id)}`, { name, description, severity, action, enabled }); }
        if (editCustom) { if (editCustom.id) await put(`${base}/rules/custom/${encodeURIComponent(editCustom.id)}`, editCustom); else await post(`${base}/rules/custom`, editCustom); }
        setEditBuiltin(null); setEditCustom(null);
      }, "规则已保存"); }}>
        <fieldset disabled={busy} className="drawer-content security-rule-fields"><legend className="sr-only">规则内容</legend>
          <label>规则名称<input required maxLength={256} value={(editBuiltin || editCustom)!.name} onChange={event => editBuiltin ? setEditBuiltin({ ...editBuiltin, name: event.target.value }) : setEditCustom({ ...editCustom!, name: event.target.value })} /></label>
          <label>规则描述<textarea value={(editBuiltin || editCustom)!.description || ""} onChange={event => editBuiltin ? setEditBuiltin({ ...editBuiltin, description: event.target.value }) : setEditCustom({ ...editCustom!, description: event.target.value })} /></label>
          {editCustom && <>
            <label>规则类型<select value={editCustom.rule_type} onChange={event => setEditCustom({ ...editCustom, rule_type: event.target.value, action: event.target.value === "whitelist" ? "allow" : "warn", match_type: "literal" })}><option value="blacklist">黑名单</option><option value="whitelist">白名单</option></select></label>
            <label>匹配类型<select value={editCustom.match_type} onChange={event => setEditCustom({ ...editCustom, match_type: event.target.value })}><option value="literal">字面匹配</option>{editCustom.rule_type === "blacklist" && <option value="regex">高级正则</option>}</select></label>
            <label>规则类别<select value={editCustom.category || "keyword"} onChange={event => setEditCustom({ ...editCustom, category: event.target.value })}>{["keyword", "domain", "path", "tool", ...(!["keyword", "domain", "path", "tool"].includes(editCustom.category) && editCustom.category ? [editCustom.category] : [])].map(category => <option key={category}>{category}</option>)}</select></label>
            <label>匹配模式<input required maxLength={4096} value={editCustom.pattern} onChange={event => setEditCustom({ ...editCustom, pattern: event.target.value })} /></label>
            <p className="muted">域名精确匹配主机名，*.example.com 仅含子域；路径按目录边界；工具名称区分大小写；关键词忽略大小写。</p>
          </>}
          {editBuiltin && <p className="muted">标识：{editBuiltin.rule_id}<br />类别开关：{editBuiltin.toggle_key || "无"}<br />检测表达式：<code>{editBuiltin.pattern || "结构化检测器"}</code></p>}
          <label>严重度<select value={(editBuiltin || editCustom)!.severity} onChange={event => editBuiltin ? setEditBuiltin({ ...editBuiltin, severity: event.target.value }) : setEditCustom({ ...editCustom!, severity: event.target.value })}>{severities.map(value => <option key={value}>{value}</option>)}</select></label>
          <label>处置动作<select disabled={editCustom?.rule_type === "whitelist"} value={(editBuiltin || editCustom)!.action} onChange={event => editBuiltin ? setEditBuiltin({ ...editBuiltin, action: event.target.value }) : setEditCustom({ ...editCustom!, action: event.target.value })}>{actions.map(value => <option key={value}>{value}</option>)}</select></label>
          <label className="checkbox-label"><input type="checkbox" checked={!!(editBuiltin || editCustom)!.enabled} onChange={event => editBuiltin ? setEditBuiltin({ ...editBuiltin, enabled: +event.target.checked }) : setEditCustom({ ...editCustom!, enabled: +event.target.checked })} />启用此规则</label>
        </fieldset><footer className="drawer-footer"><button type="button" className="secondary" disabled={busy} onClick={closeEditor}>取消</button><button className="primary" disabled={busy}>{busy ? "保存中…" : "保存规则"}</button></footer>
      </form>
    </section></div>}
    {logDetail !== null && <div className="drawer-backdrop"><section className="edit-drawer" role="dialog" aria-modal="true" aria-labelledby="security-log-title"><DialogA11y onClose={() => setLogDetail(null)} /><header className="drawer-header"><h2 id="security-log-title">关联请求详情</h2><button aria-label="关闭请求详情" onClick={() => setLogDetail(null)}>×</button></header><div className="drawer-content"><pre className="detail-json">{JSON.stringify(logDetail, null, 2)}</pre></div></section></div>}
  </section>;
}
