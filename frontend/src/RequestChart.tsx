export type ChartBucket = { group: string; requests: number; errors: number };

/** Accessible chart; exact values remain available as text and tooltips. */
export function RequestChart({ items, label = "请求趋势" }: { items: ChartBucket[]; label?: string }) {
  const visible = items.slice(-48);
  const maximum = Math.max(1, ...visible.map(item => item.requests));
  if (!items.length) return <div className="empty-state compact-empty"><strong>该范围没有请求数据</strong><p>有请求记录后会显示趋势。</p></div>;
  return <div className="request-chart" role="group" aria-label={label}><div className="chart-scale"><span>{maximum.toLocaleString()}</span><span>0</span></div><ol className="chart-bars">{items.slice(-48).map(item => <li key={item.group} title={item.group + "：请求 " + item.requests + "，错误 " + item.errors}><div className="chart-value"><span>{item.requests.toLocaleString()}</span><span className="sr-only"> 次请求，{item.errors} 次错误</span></div><div className="chart-track"><div className="chart-bar" style={{ height: Math.max(item.requests > 0 ? 2 : 0, item.requests / maximum * 100) + "%" }}><div className="chart-error" style={{ height: (item.requests ? Math.min(100, item.errors / item.requests * 100) : 0) + "%" }} /></div></div><span className="chart-label">{item.group.match(/^\d{4}-\d{2}-\d{2}/) ? item.group.slice(5, 10) + (item.group.includes("T") ? " " + item.group.slice(11, 13) + "h" : "") : item.group}</span></li>)}</ol></div>;
}
