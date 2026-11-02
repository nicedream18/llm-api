import { useCallback, useEffect, useRef, useState } from "react";
import { get, post, put } from "./api";
import { RequestChart } from "./RequestChart";

type Bucket = { group: string; requests: number; errors: number; attempts: number; total_tokens: number; unknown_usage: number; unknown_price: number; estimated_usage: number; costs: Record<string, string>; latency_p50: number | null; latency_p95: number | null; latency_p99: number | null; first_token_p95: number | null };
type Report = { start: string; end: string; timezone: string; group_by: string; items: Bucket[] };
type UsageEvent = { id: string; request_id: string; kind: string; outcome: string; total_tokens: number | null; usage_source: string; cost: string | null; currency: string | null; pricing_status: string };
type Alert = { id: string; message: string; severity: string; status: string; last_seen_at: string };
type Rule = { id: string; enabled: boolean; metric: string; threshold: number; min_samples: number; window_minutes: number; severity: string };
const dimensions = ["provider", "account_id", "model", "api_key_id", "route_group", "endpoint"];
const labels: Record<string, string> = { day: "日期", hour: "小时", provider: "供应商", account_id: "账号 ID", model: "模型", api_key_id: "访问密钥 ID", route_group: "路由组", endpoint: "Endpoint" };
const emptyFilters = Object.fromEntries(dimensions.map(name => [name, ""])) as Record<string, string>;

export function OperationsPage({ onError }: { onError: (message: string) => void }) {
  const [groupBy, setGroupBy] = useState("day");
  const [timezone, setTimezone] = useState("Asia/Shanghai");
  const [filters, setFilters] = useState(emptyFilters);
  const [start, setStart] = useState(""); const [end, setEnd] = useState("");
  const [report, setReport] = useState<Report | null>(null);
  const [events, setEvents] = useState<UsageEvent[]>([]); const [offset, setOffset] = useState(0); const [total, setTotal] = useState(0);
  const [drillFilters, setDrillFilters] = useState<Record<string, string> | null>(null);
  const [alerts, setAlerts] = useState<Alert[]>([]); const [rules, setRules] = useState<Rule[]>([]);
  const [ruleId, setRuleId] = useState("failure-rate"); const [metric, setMetric] = useState("failure_rate"); const [threshold, setThreshold] = useState("0.1");
  const [busy, setBusy] = useState(false); const [message, setMessage] = useState("");
  const [loadError, setLoadError] = useState("");
  const requestVersion = useRef(0);
  const query = useCallback(() => Object.fromEntries(Object.entries({ group_by: groupBy, timezone, ...filters,
    start: start ? new Date(start).toISOString() : "", end: end ? new Date(end).toISOString() : "" }).filter(([, value]) => value !== "")), [groupBy, timezone, filters, start, end]);
  const loadAlerts = useCallback(async () => { const [items, policies] = await Promise.all([get<Alert[]>("/api/v1/operations/alerts"), get<Rule[]>("/api/v1/operations/alerts/rules")]); setAlerts(items); setRules(policies); }, []);
  const load = async () => {
    const version = ++requestVersion.current;
    setBusy(true); setLoadError(""); setReport(null);
    try { const value = await get<Report>(`/api/v1/operations/analytics?${new URLSearchParams(query())}`); if (version === requestVersion.current) { setReport(value); setEvents([]); setDrillFilters(null); } }
    catch (error) { if (version === requestVersion.current) { const message = error instanceof Error ? error.message : "统计加载失败"; setLoadError(message); onError(message); } }
    finally { if (version === requestVersion.current) setBusy(false); }
  };
  useEffect(() => { void load(); void loadAlerts().catch(error => onError(error.message)); return () => { requestVersion.current++; }; }, []);
  const run = async (action: () => Promise<void>) => { setBusy(true); setMessage(""); try { await action(); } catch (error) { onError(error instanceof Error ? error.message : "操作失败"); } finally { setBusy(false); } };
  const drill = async (bucketFilters: Record<string, string>, next = 0) => {
    const data = await post<{ items: UsageEvent[]; total: number }>(`/api/v1/operations/events/query?offset=${next}&limit=25`, bucketFilters);
    setDrillFilters(bucketFilters); setEvents(data.items); setTotal(data.total); setOffset(next);
  };
  return <section className="management-page operations-page">
    {loadError && <div className="error inline-error" role="alert"><span>统计加载失败：{loadError}</span><button className="secondary" onClick={() => void load()}>重试</button></div>}
    <form className="panel" onSubmit={event => { event.preventDefault(); void load(); }}><h2>用量与可靠性</h2><p>请求数来自最终结果；Token 和费用来自各次尝试。未知费用、估算用量会单独显示，货币分别汇总。</p><div className="provider-filter-grid">
      <label>分组<select value={groupBy} onChange={event => setGroupBy(event.target.value)}>{["day", "hour", ...dimensions].map(value => <option key={value} value={value}>{labels[value]}</option>)}</select></label>
      <label>统计时区<input value={timezone} onChange={event => setTimezone(event.target.value)} required /></label>
      <label>开始时间<input type="datetime-local" value={start} onChange={event => setStart(event.target.value)} /></label><label>结束时间<input type="datetime-local" value={end} onChange={event => setEnd(event.target.value)} /></label>
      <details className="advanced-filter"><summary>更多维度筛选</summary><div className="provider-filter-grid">{dimensions.map(name => <label key={name}>{labels[name]}筛选<input value={filters[name]} onChange={event => setFilters({ ...filters, [name]: event.target.value })} /></label>)}</div></details></div><button className="primary" disabled={busy}>查询统计</button></form>
    <div className="panel"><h2>统计结果</h2>{busy && !report && <p role="status" className="muted">正在查询统计…</p>}{report && report.items.length <= 48 && <RequestChart items={report.items} label="统计请求分布" />}{report && report.items.length > 48 && <p className="muted">当前分组超过 48 项，请缩小范围以显示图表。</p>}{report && <p>{report.start} 至 {report.end} · {report.timezone}</p>}<div className="table-wrap"><table className="management-table"><thead><tr><th>分组</th><th>请求 / 错误 / 尝试</th><th>Token</th><th>未知用量 / 估算 / 未定价</th><th>费用</th><th>延迟 P50 / P95 / P99</th><th>首 Token P95</th><th>明细</th></tr></thead><tbody>{report?.items.map(row => <tr key={row.group}><td>{row.group}</td><td>{row.requests} / {row.errors} / {row.attempts}</td><td>{row.total_tokens}</td><td>{row.unknown_usage} / {row.estimated_usage} / {row.unknown_price}</td><td>{Object.entries(row.costs).map(([currency, value]) => `${currency} ${value}`).join("；") || "未知"}</td><td>{row.latency_p50 ?? "—"} / {row.latency_p95 ?? "—"} / {row.latency_p99 ?? "—"} ms</td><td>{row.first_token_p95 ?? "—"} ms</td><td><button disabled={busy} onClick={() => void run(() => drill({ ...query(), start: report.start, end: report.end, ...(dimensions.includes(report.group_by) ? { [report.group_by]: row.group } : { bucket: row.group }) }))}>查看明细 {row.group}</button></td></tr>)}</tbody></table></div></div>
    {drillFilters && <div className="panel"><h2>用量明细（{total} 条）</h2><div className="table-wrap"><table className="management-table"><thead><tr><th>Trace</th><th>事件</th><th>结果</th><th>Token / 来源</th><th>费用 / 定价状态</th></tr></thead><tbody>{events.map(row => <tr key={row.id}><td>{row.request_id}</td><td>{row.kind}</td><td>{row.outcome}</td><td>{row.total_tokens ?? "未知"} / {row.usage_source}</td><td>{row.cost ?? "未知"} {row.currency || ""} / {row.pricing_status}</td></tr>)}</tbody></table></div><button disabled={busy || !offset} onClick={() => void run(() => drill(drillFilters, Math.max(0, offset - 25)))}>上一页明细</button><button disabled={busy || offset + 25 >= total} onClick={() => void run(() => drill(drillFilters, offset + 25))}>下一页明细</button></div>}
    <div className="panel"><h2>站内告警</h2><p>规则默认不启用；保存新规则后每 30 秒在服务端评估，同一持续问题只保留一个告警。</p><button disabled={busy} onClick={() => void run(async () => { await post("/api/v1/operations/alerts/evaluate", {}); await loadAlerts(); })}>立即评估与刷新</button><ul>{alerts.map(alert => <li key={alert.id}>{alert.severity} · {alert.message} · {alert.status} {alert.status === "open" && <button disabled={busy} onClick={() => void run(async () => { await post(`/api/v1/operations/alerts/${alert.id}/acknowledge`, {}); await loadAlerts(); })}>确认告警</button>}</li>)}</ul>
      <form onSubmit={event => { event.preventDefault(); void run(async () => { await put(`/api/v1/operations/alerts/rules/${encodeURIComponent(ruleId)}`, { enabled: true, metric, threshold: Number(threshold), min_samples: 20, window_minutes: 10, severity: "warning" }); await loadAlerts(); setMessage("告警规则已保存并启用"); }); }}><div className="provider-filter-grid"><label>规则 ID<input value={ruleId} onChange={event => setRuleId(event.target.value)} pattern="[A-Za-z0-9-]+" required /></label><label>指标<select value={metric} onChange={event => setMetric(event.target.value)}><option value="failure_rate">失败率（0–1）</option><option value="latency_p95">延迟 P95（ms）</option><option value="unknown_price">未知费用次数</option></select></label><label>阈值<input type="number" min="0" step="any" value={threshold} onChange={event => setThreshold(event.target.value)} required /></label></div><button disabled={busy}>保存并启用规则</button></form>
      <ul>{rules.map(rule => <li key={rule.id}>{rule.id} · {rule.metric} ≥ {rule.threshold} · {rule.enabled ? "启用" : "停用"}<button disabled={busy} onClick={() => void run(async () => { const { id, ...policy } = rule; await put(`/api/v1/operations/alerts/rules/${id}`, { ...policy, enabled: !rule.enabled }); await loadAlerts(); })}>切换规则状态</button></li>)}</ul>{message && <p role="status">{message}</p>}</div>
  </section>;
}
