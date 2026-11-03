import { useState } from "react";
import { get, post } from "./api";
import { useResource } from "./adminHooks";
import "./mcp.css";

type Props = { onError: (message: string) => void };
type McpTool = { name: string; description?: string; inputSchema?: Record<string, unknown> };
type Audit = { id: string; request_id?: string; principal_id?: string; tool_name: string; success: number; error_type?: string; duration_ms: number; created_at: string };
type AccessKey = { id: string; name: string };

function pretty(value: unknown): string { return JSON.stringify(value, null, 2); }

export function McpManager({ onError }: Props) {
  const [toolData, reloadTools, toolsState] = useResource<{ tools: McpTool[] }>("/api/v1/mcp/tools", onError);
  const [auditData, reloadAudits, auditState] = useResource<Audit[]>("/api/v1/mcp/audit?limit=50", onError);
  const [accessKeys, reloadAccessKeys] = useResource<AccessKey[]>("/api/v1/api-keys", onError);
  const tools = toolData?.tools || [];
  const [latestAudits, setAudits] = useState<Audit[] | null>(null);
  const audits = latestAudits || auditData || [];
  const [selected, setSelected] = useState("");
  const [argumentsText, setArgumentsText] = useState("{}");
  const [resultText, setResultText] = useState("");
  const [busy, setBusy] = useState(false);
  const load = () => { setAudits(null); reloadTools(); reloadAudits(); reloadAccessKeys(); };
  const selectedTool = tools.find(tool => tool.name === selected) || tools[0];
  const call = async () => {
    if (!selectedTool) return;
    setBusy(true); setResultText("");
    try {
      const parsed: unknown = JSON.parse(argumentsText || "{}");
      if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) throw new Error("参数必须是 JSON 对象");
      const result = await post<unknown>(`/api/v1/mcp/tools/${encodeURIComponent(selectedTool.name)}/call`, { arguments: parsed });
      setResultText(pretty(result));
      const refreshed = await get<Audit[]>("/api/v1/mcp/audit?limit=50"); setAudits(refreshed);
    } catch (error) { onError(error instanceof Error ? error.message : "MCP 工具调用失败"); }
    finally { setBusy(false); }
  };
  return <section className="mcp-manager">
    <div className="panel"><div className="panel-head"><div><h2>MCP 工具调试台</h2><p className="muted">使用管理员会话查看已授权工具并执行一次受审计的调用。</p></div><button className="secondary" onClick={load}>刷新</button></div>
      {toolsState.error && <div className="error inline-error" role="alert"><span>工具加载失败：{toolsState.error}</span><button className="secondary" onClick={reloadTools}>重试工具</button></div>}{toolsState.loading && <p role="status">正在加载 MCP 工具…</p>}<div className="mcp-grid"><div className="mcp-tool-list">{tools.map(tool => <button className={`mcp-tool ${tool.name === selectedTool?.name ? "selected" : ""}`} key={tool.name} onClick={() => { setSelected(tool.name); setResultText(""); }}><strong>{tool.name}</strong><small>{tool.description || "无描述"}</small></button>)}{!toolsState.loading && !toolsState.error && tools.length === 0 && <p className="muted">暂无可用工具。</p>}</div><div className="mcp-call-pane">{selectedTool ? <><h3>{selectedTool.name}</h3><p className="muted">{selectedTool.description || "无描述"}</p><details><summary>输入 schema</summary><pre>{pretty(selectedTool.inputSchema || {})}</pre></details><label className="field-label">JSON 参数<textarea className="mcp-input" value={argumentsText} onChange={event => setArgumentsText(event.target.value)} spellCheck={false} /></label><button className="primary" onClick={call} disabled={busy}>{busy ? "调用中…" : "调用工具"}</button>{resultText && <><h3>调用结果</h3><pre className="mcp-result">{resultText}</pre></>}</> : <p className="muted">选择左侧工具开始调试。</p>}</div></div>
    </div>
    <div className="panel"><div className="panel-head"><div><h2>调用审计</h2><p className="muted">仅保存工具名称、主体、状态和耗时，不保存参数或响应正文。</p></div></div>{auditState.error && <div className="error inline-error" role="alert"><span>审计加载失败：{auditState.error}</span><button className="secondary" onClick={reloadAudits}>重试审计</button></div>}{auditState.loading && <p role="status">正在加载调用审计…</p>}<div className="table-wrap"><table><thead><tr><th>工具</th><th>主体</th><th>状态</th><th>耗时</th><th>时间</th></tr></thead><tbody>{audits.map(audit => <tr key={audit.id}><td>{audit.tool_name}</td><td>{accessKeys?.find(key => key.id === audit.principal_id)?.name || (audit.principal_id ? "其他主体" : "—")}</td><td className={audit.success ? "success" : "error-cell"}>{audit.success ? "成功" : audit.error_type || "失败"}</td><td>{audit.duration_ms} ms</td><td>{new Date(audit.created_at).toLocaleString()}</td></tr>)}</tbody></table>{!auditState.loading && !auditState.error && audits.length === 0 && <p className="muted">暂无调用记录。</p>}</div></div>
  </section>;
}
