import { useEffect, useState, type FormEvent } from "react";
import { get, post, uploadWithProgress } from "./api";
import { useAction, useResource } from "./adminHooks";
import { DialogA11y } from "./DialogA11y";
import type { KnowledgeBase, KnowledgeDocument } from "./types";

const indexLabels: Record<string, string> = { ready: "已就绪", indexed: "已索引", building: "构建中", pending: "待处理", failed: "构建失败" };
function documentFailureMessage(document: KnowledgeDocument): string {
  const detail = document.task_error_message || document.error_message || "";
  const missingModel = detail.match(/No channel supports model:\s*([^\s]+)/i);
  if (missingModel) return `没有可用渠道支持嵌入模型 ${missingModel[1]}。请检查渠道是否启用了 Embeddings 接口及该模型，修复后可直接重试。`;
  return detail || "文档处理失败，请检查知识库配置后重试。";
}

function documentState(document: KnowledgeDocument): { label: string; active: boolean; failed: boolean } {
  if (document.task_status === "pending") return { label: "排队处理中", active: true, failed: false };
  if (document.task_status === "running") return { label: document.task_progress ? `建立索引 ${document.task_progress}%` : "解析文档并生成向量", active: true, failed: false };
  if (document.task_status === "failed" || document.status === "error") return { label: "处理失败", active: false, failed: true };
  if (document.task_status === "completed" || document.status === "ready") return { label: "已完成", active: false, failed: false };
  return { label: document.status === "pending" ? "等待处理" : document.status || "状态未知", active: document.status === "pending", failed: false };
}

export function KnowledgePage({ onError }: { onError: (message: string) => void }) {
  const [rows, reload, resource] = useResource<KnowledgeBase[]>("/api/v1/kb", onError);
  const [name, setName] = useState(""); const [query, setQuery] = useState("");
  const [selectedKb, setSelectedKb] = useState(""); const [createOpen, setCreateOpen] = useState(false);
  const [message, setMessage] = useState(""); const [uploading, setUploading] = useState(false); const [uploadProgress, setUploadProgress] = useState<number | null>(0);
  const [documents, setDocuments] = useState<KnowledgeDocument[]>([]); const [documentsLoading, setDocumentsLoading] = useState(false);
  const [documentsError, setDocumentsError] = useState(""); const [documentsRevision, setDocumentsRevision] = useState(0);
  const [retrying, setRetrying] = useState<string[]>([]);
  const [busy, run] = useAction(onError);
  const reloadDocuments = () => setDocumentsRevision(value => value + 1);
  useEffect(() => {
    if (!selectedKb) { setDocuments([]); setDocumentsLoading(false); setDocumentsError(""); return; }
    const controller = new AbortController(); let active = true; let timer: number | undefined;
    const poll = async () => {
      if (!active) return;
      try {
        const rows = await get<KnowledgeDocument[]>(`/api/v1/kb/${encodeURIComponent(selectedKb)}/documents`, { signal: controller.signal });
        if (!active) return;
        setDocuments(Array.isArray(rows) ? rows : []); setDocumentsError(""); setDocumentsLoading(false);
        if (rows.some(document => document.task_status === "pending" || document.task_status === "running" || (!document.task_status && document.status === "pending"))) {
          timer = window.setTimeout(poll, 1200);
        }
      } catch (error) {
        if (!active || controller.signal.aborted) return;
        setDocumentsError(error instanceof Error ? error.message : "无法读取文档处理状态"); setDocumentsLoading(false);
      }
    };
    setDocumentsLoading(true); setDocumentsError(""); void poll();
    return () => { active = false; controller.abort(); if (timer) window.clearTimeout(timer); };
  }, [selectedKb, documentsRevision]);
  const create = (event: FormEvent) => { event.preventDefault(); if (!name.trim()) return; void run(async () => { const created = await post<KnowledgeBase>("/api/v1/kb", { name: name.trim() }); setName(""); setCreateOpen(false); setSelectedKb(created.id); setMessage("知识库已创建，可以上传文档。"); reload(); }); };
  const handleUpload = async (event: FormEvent<HTMLInputElement>) => {
    const input = event.currentTarget; const file = input.files?.[0]; const kbId = selectedKb;
    if (!file || !kbId || uploading) return;
    setUploading(true); setUploadProgress(0); setMessage("");
    try {
      const uploaded = await uploadWithProgress<KnowledgeDocument>("/api/v1/kb/" + encodeURIComponent(kbId) + "/documents/upload", file, setUploadProgress);
      input.value = "";
      setDocuments(current => [uploaded, ...current.filter(document => document.id !== uploaded.id)]);
      setMessage("文件已接收，正在等待后台建立索引。你可以继续浏览其他页面。");
      reloadDocuments(); reload();
    } catch (error) { onError(error instanceof Error ? error.message : "上传失败"); }
    finally { setUploading(false); setUploadProgress(null); }
  };
  const retryDocument = async (document: KnowledgeDocument) => {
    setRetrying(current => [...current, document.id]);
    try {
      const retried = await post<KnowledgeDocument>(`/api/v1/kb/${encodeURIComponent(document.kb_id)}/documents/${encodeURIComponent(document.id)}/retry`, {});
      setDocuments(current => current.map(item => item.id === document.id ? retried : item));
      setMessage(`“${document.name}”已重新排队处理。`); reloadDocuments(); reload();
    } catch (error) { onError(error instanceof Error ? error.message : "无法重新处理文档"); }
    finally { setRetrying(current => current.filter(id => id !== document.id)); }
  };
  const filtered = (rows || []).filter(row => (row.name + " " + (row.description || "")).toLocaleLowerCase().includes(query.trim().toLocaleLowerCase()));
  return <section className="management-page knowledge-page">
    <div className="management-toolbar"><label className="search-field"><span className="sr-only">搜索知识库</span><input type="search" placeholder="搜索知识库名称或描述" value={query} onChange={event => setQuery(event.target.value)} /></label><div className="toolbar-actions"><button className="secondary" onClick={reload}>刷新</button><button className="primary" onClick={() => setCreateOpen(true)}>＋ 创建知识库</button></div></div>
    {resource.error && <div className="error inline-error" role="alert"><span>知识库加载失败：{resource.error}</span><button className="secondary" onClick={reload}>重试</button></div>}
    {message && <p className="success" role="status">{message}</p>}
    <div className="knowledge-workspace"><div className="panel kb-library"><div className="table-heading"><div><h2>知识库</h2><p>{rows ? rows.length + " 个知识库" : resource.error ? "暂不可用" : "正在加载…"}</p></div></div><div className="kb-card-list">{filtered.map(row => <button className={"kb-card " + (selectedKb === row.id ? "selected" : "")} key={row.id} onClick={() => setSelectedKb(row.id)} aria-pressed={selectedKb === row.id}><span className="kb-card-icon" aria-hidden="true">▤</span><div><strong>{row.name}</strong><p>{row.description || "暂无描述"}</p><small>{row.doc_count} 文档 · {row.chunk_count} 分块</small></div><span className={"index-state " + row.index_status}>{indexLabels[row.index_status] || row.index_status || "待建立索引"}</span></button>)}</div>{resource.loading && <div className="empty-state"><span className="loading-mark" /><strong>正在加载知识库</strong></div>}{rows?.length === 0 && <div className="empty-state"><strong>建立你的第一个知识库</strong><p>集中管理文档，为模型回答提供可追溯的知识来源。</p><button className="primary" onClick={() => setCreateOpen(true)}>创建知识库</button></div>}{rows && rows.length > 0 && !filtered.length && <div className="empty-state compact-empty"><strong>没有匹配的知识库</strong><button className="secondary" onClick={() => setQuery("")}>清除搜索</button></div>}</div>
      <div className="panel kb-upload-panel"><span className="eyebrow">文档导入</span><h2>上传文档</h2><p>先选择目标知识库，再选择文档文件。上传过程中切换目标不会改变当前文件的归属。</p><label>目标知识库<select value={selectedKb} onChange={event => setSelectedKb(event.target.value)} disabled={uploading}><option value="">选择上传目标</option>{(rows || []).map(row => <option key={row.id} value={row.id}>{row.name}</option>)}</select></label><label className={`upload-dropzone${uploading ? " is-uploading" : ""}`}><span aria-hidden="true">{uploading ? "↥" : "↑"}</span><strong>{uploading ? "正在传输文件…" : "选择本地文件"}</strong><small>{uploading ? (uploadProgress === null ? "正在上传，浏览器暂无法计算进度" : `文件传输 ${uploadProgress}% · 完成后开始后台索引`) : selectedKb ? "点击浏览文件" : "请先选择目标知识库"}</small>{uploading && <div className="upload-progress" role="progressbar" aria-label="文件上传进度" aria-valuemin={0} aria-valuemax={100} aria-valuenow={uploadProgress ?? undefined}><span className={uploadProgress === null ? "indeterminate" : ""} style={uploadProgress === null ? undefined : { width: `${uploadProgress}%` }} /></div>}<input aria-label="上传知识库文档" type="file" onChange={handleUpload} disabled={!selectedKb || uploading} /></label><p className="muted">文件传输完成后，后台还会解析文档并生成向量；处理状态会显示在下方。</p></div></div>
    <div className="panel kb-documents-panel"><div className="table-heading"><div><h2>文档处理</h2><p>{selectedKb ? `${rows?.find(row => row.id === selectedKb)?.name || "所选知识库"} · ${documents.length} 个文档` : "选择知识库后查看文件传输和索引状态。"}</p></div>{selectedKb && <button className="secondary" disabled={documentsLoading} onClick={reloadDocuments}>刷新状态</button>}</div>
      {!selectedKb && <div className="empty-state compact-empty"><strong>尚未选择知识库</strong><p>选择左侧知识库或上传区域中的目标知识库后，可以查看其文档处理记录。</p></div>}
      {selectedKb && documentsError && <div className="error inline-error" role="alert"><span>文档状态读取失败：{documentsError}</span><button className="secondary" onClick={reloadDocuments}>重试</button></div>}
      {selectedKb && documentsLoading && documents.length === 0 && !documentsError && <p role="status" className="muted">正在读取文档列表…</p>}
      {selectedKb && !documentsLoading && !documentsError && documents.length === 0 && <div className="empty-state compact-empty"><strong>还没有上传文档</strong><p>上传完成后，文件会先进入处理队列，再生成可检索的索引。</p></div>}
      {selectedKb && documents.length > 0 && <div className="kb-document-list">{documents.map(document => {
        const state = documentState(document); const progress = Math.max(0, Math.min(100, document.task_progress || 0));
        return <article className={`kb-document-row${state.failed ? " has-error" : ""}`} key={document.id}>
          <div className="kb-document-main"><div><strong>{document.name}</strong><small>{document.chunk_count} 个分块 · {document.total_tokens} Tokens</small></div><span className={`status-pill ${state.failed ? "is-disabled" : state.active ? "is-pending" : "is-active"}`}><i />{state.label}</span></div>
          {state.active && <div className="kb-task-progress" role="progressbar" aria-label={`${document.name} 处理进度`} aria-valuemin={0} aria-valuemax={100} aria-valuenow={state.label.includes("%") ? progress : undefined}><span className={document.task_status === "running" && progress === 0 ? "indeterminate" : ""} style={document.task_status === "running" && progress === 0 ? undefined : { width: `${progress}%` }} /></div>}
          {state.active && <small className="kb-task-detail">{document.task_status === "pending" ? "后台任务排队中，完成后会自动更新。" : document.task_total_items ? `已处理 ${document.task_done_items || 0} / ${document.task_total_items} 项` : "正在解析内容并请求嵌入模型，初始阶段可能暂时没有百分比进度。"}</small>}
          {state.failed && <div className="kb-document-error"><p>{documentFailureMessage(document)}</p><div><a href="#/channels">检查渠道配置</a>{document.task_status === "failed" && <button className="secondary" disabled={retrying.includes(document.id)} onClick={() => void retryDocument(document)}>{retrying.includes(document.id) ? "重新排队中…" : "修复配置后重试"}</button>}</div></div>}
        </article>;
      })}</div>}
    </div>
    {createOpen && <div className="drawer-backdrop" role="presentation"><section className="edit-drawer" role="dialog" aria-modal="true" aria-labelledby="kb-create-title"><DialogA11y onClose={() => setCreateOpen(false)} /><div className="drawer-header"><div><span className="eyebrow">知识工作区</span><h2 id="kb-create-title">创建知识库</h2></div><button className="icon-button" aria-label="关闭知识库创建" onClick={() => setCreateOpen(false)}>×</button></div><form onSubmit={create}><div className="drawer-content"><label>知识库名称<input autoComplete="off" maxLength={128} required value={name} onChange={event => setName(event.target.value)} /></label><p className="muted">创建后可以立即上传文档并等待索引完成。</p></div><footer className="drawer-footer"><span /><div><button className="secondary" type="button" onClick={() => setCreateOpen(false)}>取消</button><button className="primary" disabled={busy || !name.trim()}>创建知识库</button></div></footer></form></section></div>}
  </section>;
}
