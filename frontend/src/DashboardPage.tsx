import { useState } from "react";
import { useResource } from "./adminHooks";
import type { Channel, Dashboard, SoftwareApproval, SoftwareTool } from "./types";
import { RequestChart, type ChartBucket } from "./RequestChart";

type RecentLog = { id: string; model?: string; status_code?: number; error_message?: string; created_at?: string };
type Trend = { start: string; end: string; items: ChartBucket[]; timezone: string };

function recentRange() {
    const end = new Date(); const start = new Date(end);
    start.setUTCDate(start.getUTCDate() - 6); start.setUTCHours(0, 0, 0, 0);
    return new URLSearchParams({ group_by: "day", timezone: "UTC", start: start.toISOString(), end: end.toISOString() }).toString();
}

export function DashboardPage({ onError }: { onError: (message: string) => void }) {
  const [range, setRange] = useState(recentRange);
  const [stats, reloadStats, statsState] = useResource<Dashboard>("/api/v1/dashboard", onError);
  const [trend, reloadTrend, trendState] = useResource<Trend>("/api/v1/operations/analytics?" + range, onError);
  const [channels, reloadChannels, channelsState] = useResource<Channel[]>("/api/v1/channels", onError);
  const [logs, reloadLogs, logsState] = useResource<RecentLog[]>("/api/v1/logs?page=1&size=20", onError);
  const [approvals, reloadApprovals, approvalsState] = useResource<SoftwareApproval[]>("/api/v1/software/approvals?status=pending&limit=5", onError);
  const [tools, reloadTools] = useResource<SoftwareTool[]>("/api/v1/software/tools", onError);
  const [accessKeys, reloadAccessKeys] = useResource<Array<{ id: string; name: string }>>("/api/v1/api-keys", onError);
  const refresh = () => { setRange(recentRange()); reloadStats(); reloadTrend(); reloadChannels(); reloadLogs(); reloadApprovals(); reloadTools(); reloadAccessKeys(); };
  const toolNames = new Map((tools || []).map(tool => [tool.id, tool.name]));
  const keyNames = new Map((accessKeys || []).map(key => [key.id, key.name]));
  const recentErrors = (logs || []).filter(log => (log.status_code || 0) >= 400);
  const trendItems = trend?.items.length ? Array.from({ length: 7 }, (_, offset) => {
    const day = new Date(new URLSearchParams(range).get("start")!);
    day.setUTCDate(day.getUTCDate() + offset);
    const group = day.toISOString().slice(0, 10);
    return trend.items.find(item => item.group === group) || { group, requests: 0, errors: 0 };
  }) : [];
  const errorRate = stats && stats.total_requests > 0 ? (stats.total_errors / stats.total_requests * 100).toFixed(1) + "%" : "—";
  const cards = [
    { label: "请求量", value: stats?.total_requests?.toLocaleString() ?? "—", detail: "当前保留日志累计" },
    { label: "Token 用量", value: stats?.total_tokens?.toLocaleString() ?? "—", detail: "当前保留日志累计" },
    { label: "错误率", value: errorRate, detail: stats ? stats.total_errors + " 条错误记录" : "等待统计结果" },
    { label: "平均延迟", value: stats && stats.total_requests ? Math.round(stats.avg_duration_ms).toLocaleString() : "—", detail: "ms · 保留日志中的请求" },
  ];
  return <section className="management-page dashboard-page">
    <div className="management-toolbar"><div><h2>运行概览</h2><p>累计指标以当前保留日志为准；趋势单独使用最近 7 天（UTC）。</p></div><div className="toolbar-actions"><a className="button-link secondary" href="#/logs">查看请求日志</a><button className="secondary" onClick={refresh}>刷新概览</button></div></div>
    {statsState.error && <div className="error inline-error" role="alert"><span>概览加载失败：{statsState.error}</span><button className="secondary" onClick={reloadStats}>重试</button></div>}
    <div className="metric-grid" aria-busy={statsState.loading}>{cards.map(card => <article className="metric-card" key={card.label}><span>{card.label}</span><strong className="numeric-value">{card.value}</strong><small>{statsState.loading ? "正在加载…" : statsState.error ? "统计暂不可用" : card.detail}</small></article>)}</div>
    {stats?.total_requests === 0 && <div className="onboarding-panel"><div><span className="eyebrow">开始使用网关</span><h2>完成三个步骤，发起第一个请求</h2><p>渠道和访问密钥准备好后，请求记录会自动出现在这里。</p></div><ol><li><span>01</span><a href="#/channels">添加上游渠道</a></li><li><span>02</span><a href="#/channels">测试连接</a></li><li><span>03</span><a href="#/api-keys">创建访问密钥</a></li></ol></div>}
    <div className="dashboard-middle"><article className="panel trend-panel"><div className="table-heading"><div><h2>请求趋势</h2><p>最近 7 天 · UTC · 按日聚合</p></div><span className="chart-legend"><i />请求 <i className="error-dot" />错误</span></div>{trendState.error ? <div className="error inline-error" role="alert"><span>趋势加载失败</span><button className="secondary" onClick={reloadTrend}>重试趋势</button></div> : trendState.loading ? <div className="empty-state" role="status"><span className="loading-mark" /><strong>正在加载请求趋势</strong></div> : <RequestChart items={trendItems} />}</article>
      <article className="panel channel-summary"><div className="table-heading"><div><h2>渠道状态</h2><p>当前配置 · 启用状态不代表连接测试结果</p></div><a href="#/channels">管理</a></div>{channelsState.error ? <div className="empty-state"><strong>渠道状态加载失败</strong><button className="secondary" onClick={reloadChannels}>重试渠道</button></div> : channelsState.loading ? <p className="muted">正在加载渠道…</p> : channels?.length ? <ul className="summary-list">{channels.slice(0, 5).map(channel => <li key={channel.id}><div><strong>{channel.name}</strong><small>{channel.type} · {channel.models.length} 个模型</small></div><span className={"status-pill " + (channel.status ? "is-active" : "is-disabled")}><i />{channel.status ? "已启用" : "已停用"}</span></li>)}</ul> : <div className="empty-state compact-empty"><strong>还没有渠道</strong><a href="#/channels">添加第一个渠道</a></div>}</article></div>
    <div className="dashboard-bottom"><article className="panel"><div className="table-heading"><div><h2>近期错误</h2><p>最近 20 条请求记录中的错误</p></div><a href="#/logs">全部日志</a></div>{logsState.error ? <div className="empty-state"><strong>错误记录加载失败</strong><button className="secondary" onClick={reloadLogs}>重试日志</button></div> : logsState.loading ? <p className="muted">正在加载错误记录…</p> : recentErrors.length ? <ul className="summary-list">{recentErrors.slice(0, 4).map(log => <li key={log.id}><div><strong>{log.model || "未知模型"}</strong><small>{log.error_message || log.created_at || log.id}</small></div><span className="failure-tag">HTTP {log.status_code}</span></li>)}</ul> : <div className="quiet-state"><span className="status-pill is-active"><i />最近记录中没有错误</span></div>}</article>
      <article className="panel"><div className="table-heading"><div><h2>待审批工具调用</h2><p>仅显示最近 5 条，处理前请检查调用参数。</p></div><a href="#/software?view=approvals">进入审批</a></div>{approvalsState.error ? <div className="empty-state"><strong>审批数据加载失败</strong><button className="secondary" onClick={reloadApprovals}>重试审批</button></div> : approvalsState.loading ? <p className="muted">正在加载审批…</p> : approvals?.length ? <ul className="summary-list">{approvals.map(item => <li key={item.id}><div><strong>{toolNames.get(item.tool_id) || item.tool_id}</strong><small>{(item.principal_id && keyNames.get(item.principal_id)) || (item.principal_id ? "其他主体" : "未标注主体")} · {item.created_at}</small></div><span className="pending-tag">待审批</span></li>)}</ul> : <div className="quiet-state"><span className="status-pill is-active"><i />当前没有待审批调用</span></div>}</article></div>
  </section>;
}
