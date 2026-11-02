import { useState, type FormEvent } from "react";
import { post, upload } from "./api";
import { useAction, useResource } from "./adminHooks";
import { DialogA11y } from "./DialogA11y";
import type { KnowledgeBase } from "./types";

const indexLabels: Record<string, string> = { ready: "已就绪", indexed: "已索引", building: "构建中", pending: "待处理", failed: "构建失败" };

export function KnowledgePage({ onError }: { onError: (message: string) => void }) {
  const [rows, reload, resource] = useResource<KnowledgeBase[]>("/api/v1/kb", onError);
  const [name, setName] = useState(""); const [query, setQuery] = useState("");
  const [selectedKb, setSelectedKb] = useState(""); const [createOpen, setCreateOpen] = useState(false);
  const [message, setMessage] = useState(""); const [uploading, setUploading] = useState(false);
  const [busy, run] = useAction(onError);
  const create = (event: FormEvent) => { event.preventDefault(); if (!name.trim()) return; void run(async () => { const created = await post<KnowledgeBase>("/api/v1/kb", { name: name.trim() }); setName(""); setCreateOpen(false); setSelectedKb(created.id); setMessage("知识库已创建，可以上传文档。"); reload(); }); };
  const handleUpload = async (event: FormEvent<HTMLInputElement>) => {
    const input = event.currentTarget; const file = input.files?.[0]; const kbId = selectedKb;
    if (!file || !kbId || uploading) return;
    setUploading(true); setMessage("");
    try {
      await upload("/api/v1/kb/" + encodeURIComponent(kbId) + "/documents/upload", file);
      input.value = ""; setMessage("文档已上传，索引状态将在处理完成后更新。"); reload();
    } catch (error) { onError(error instanceof Error ? error.message : "上传失败"); }
    finally { setUploading(false); }
  };
  const filtered = (rows || []).filter(row => (row.name + " " + (row.description || "")).toLocaleLowerCase().includes(query.trim().toLocaleLowerCase()));
  return <section className="management-page knowledge-page">
    <div className="management-toolbar"><label className="search-field"><span className="sr-only">搜索知识库</span><input type="search" placeholder="搜索知识库名称或描述" value={query} onChange={event => setQuery(event.target.value)} /></label><div className="toolbar-actions"><button className="secondary" onClick={reload}>刷新</button><button className="primary" onClick={() => setCreateOpen(true)}>＋ 创建知识库</button></div></div>
    {resource.error && <div className="error inline-error" role="alert"><span>知识库加载失败：{resource.error}</span><button className="secondary" onClick={reload}>重试</button></div>}
    {message && <p className="success" role="status">{message}</p>}
    <div className="knowledge-workspace"><div className="panel kb-library"><div className="table-heading"><div><h2>知识库</h2><p>{rows ? rows.length + " 个知识库" : resource.error ? "暂不可用" : "正在加载…"}</p></div></div><div className="kb-card-list">{filtered.map(row => <button className={"kb-card " + (selectedKb === row.id ? "selected" : "")} key={row.id} onClick={() => setSelectedKb(row.id)} aria-pressed={selectedKb === row.id}><span className="kb-card-icon" aria-hidden="true">▤</span><div><strong>{row.name}</strong><p>{row.description || "暂无描述"}</p><small>{row.doc_count} 文档 · {row.chunk_count} 分块</small></div><span className={"index-state " + row.index_status}>{indexLabels[row.index_status] || row.index_status || "待建立索引"}</span></button>)}</div>{resource.loading && <div className="empty-state"><span className="loading-mark" /><strong>正在加载知识库</strong></div>}{rows?.length === 0 && <div className="empty-state"><strong>建立你的第一个知识库</strong><p>集中管理文档，为模型回答提供可追溯的知识来源。</p><button className="primary" onClick={() => setCreateOpen(true)}>创建知识库</button></div>}{rows && rows.length > 0 && !filtered.length && <div className="empty-state compact-empty"><strong>没有匹配的知识库</strong><button className="secondary" onClick={() => setQuery("")}>清除搜索</button></div>}</div>
      <div className="panel kb-upload-panel"><span className="eyebrow">文档导入</span><h2>上传文档</h2><p>先选择目标知识库，再选择文档文件。上传过程中切换目标不会改变当前文件的归属。</p><label>目标知识库<select value={selectedKb} onChange={event => setSelectedKb(event.target.value)}><option value="">选择上传目标</option>{(rows || []).map(row => <option key={row.id} value={row.id}>{row.name}</option>)}</select></label><label className="upload-dropzone"><span aria-hidden="true">↑</span><strong>{uploading ? "正在上传文档…" : "选择本地文件"}</strong><small>{selectedKb ? "点击浏览文件" : "请先选择目标知识库"}</small><input aria-label="上传知识库文档" type="file" onChange={handleUpload} disabled={!selectedKb || uploading} /></label><p className="muted">文件类型及大小由服务端校验；上传成功不代表索引已经完成。</p></div></div>
    {createOpen && <div className="drawer-backdrop" role="presentation"><section className="edit-drawer" role="dialog" aria-modal="true" aria-labelledby="kb-create-title"><DialogA11y onClose={() => setCreateOpen(false)} /><div className="drawer-header"><div><span className="eyebrow">知识工作区</span><h2 id="kb-create-title">创建知识库</h2></div><button className="icon-button" aria-label="关闭知识库创建" onClick={() => setCreateOpen(false)}>×</button></div><form onSubmit={create}><div className="drawer-content"><label>知识库名称<input autoComplete="off" maxLength={128} required value={name} onChange={event => setName(event.target.value)} /></label><p className="muted">创建后可以立即上传文档并等待索引完成。</p></div><footer className="drawer-footer"><span /><div><button className="secondary" type="button" onClick={() => setCreateOpen(false)}>取消</button><button className="primary" disabled={busy || !name.trim()}>创建知识库</button></div></footer></form></section></div>}
  </section>;
}
