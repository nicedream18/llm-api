function pgLogs(){
  const logs=state.data.logs||[];
  return`<div class="page-shell">
  <div class="page-header"><div><div class="page-title">请求日志</div><div class="page-subtitle">API 调用记录 · 安全审计 · 链路追踪</div></div>
    <div class="page-header-actions"><button class="btn btn-secondary btn-sm" onclick="loadLogs()">${I.refresh}刷新</button><button class="btn btn-danger btn-sm" onclick="confirmDel('所有日志','全部日志',()=>clearLogs())">${I.trash}清空</button></div>
  </div>
  <div class="surface" style="margin-bottom:16px">
    <div class="filter-bar">
      <input class="input" id="log-search" placeholder="搜索关键词..." style="flex:1;min-width:160px" onkeydown="if(event.key==='Enter')loadLogs()" value="${esc(state._logKw||'')}">
      <input class="input" id="log-model" placeholder="模型筛选" style="width:150px" onkeydown="if(event.key==='Enter')loadLogs()" value="${esc(state._logModel||'')}">
      <button class="btn btn-primary btn-sm" onclick="loadLogs()">${I.search}搜索</button>
    </div>
  </div>
  <div class="surface" style="overflow:hidden"><div class="table-wrap">
    <table class="table"><thead><tr><th>时间</th><th>TraceID</th><th>渠道</th><th>模型</th><th>上游模型</th><th>状态</th><th>Token</th><th>耗时</th><th>模式</th><th>安全</th></tr></thead><tbody>
    ${logs.map(l=>`
    <tr class="log-row" onclick="toggleLogExpand('${l.id||l.traceId}')">
      <td style="color:var(--muted-foreground);font-size:12px;white-space:nowrap">${fmtDate(l.createdAt)}</td>
      <td><span class="log-code">${esc((l.traceId||'').substring(0,8))}</span></td>
      <td style="font-size:12px">${esc(l.channelName||'-')}</td>
      <td style="font-weight:600">${esc(l.model||'-')}</td>
      <td style="font-size:12px;color:var(--muted-foreground)">${esc(l.upstreamModel||'-')}</td>
      <td>${codeBadge(l.statusCode)}</td>
      <td style="font-variant-numeric:tabular-nums">${l.totalTokens||0}</td>
      <td style="font-variant-numeric:tabular-nums">${(l.durationMs||0)+'ms'}</td>
      <td>${l.isStream?'<span class="badge badge-blue">Stream</span>':'<span class="badge badge-slate">Sync</span>'}</td>
      <td>${riskBadge(l.riskLevel)}</td>
    </tr>
    ${state.expandedLogId===(l.id||l.traceId)?`<tr class="expand-row"><td colspan="10"><div class="expand-content">
      <div class="expand-grid">
        <div><strong>TraceID</strong> <span class="log-code">${esc(l.traceId||'-')}</span></div>
        <div><strong>安全动作</strong> ${securityActionBadge(l.securityAction)}</div>
        <div><strong>API Key</strong> ${esc(l.apiKeyId||l.apiKeyName||'-')}</div>
        <div><strong>渠道</strong> ${esc(l.channelName||'-')} ${l.channelId?`<span class="log-code">${esc(l.channelId.substring(0,8))}</span>`:''}</div>
        <div><strong>模型</strong> ${esc(l.model||'-')} → ${esc(l.upstreamModel||'-')}</div>
        <div><strong>模式</strong> ${esc(l.mode||'chat')} ${l.isStream?'· Stream':''} ${l.isRetry?'· Retry':''}</div>
        <div><strong>状态码</strong> ${esc(l.statusCode)}</div>
        <div><strong>耗时</strong> ${l.durationMs||0}ms</div>
        <div><strong>Token</strong> P:${l.promptTokens||0} C:${l.completionTokens||0} T:${l.totalTokens||0}</div>
        <div><strong>风险</strong> ${riskBadge(l.riskLevel)} ${l.riskScore!=null?'(分数 '+l.riskScore+')':''} ${l.riskSummary?'· '+esc(l.riskSummary):''}</div>
        <div><strong>时间</strong> ${fmtDate(l.createdAt,true)}</div>
        <div><strong>客户端 IP</strong> ${esc(l.clientIp||'-')}</div>
      </div>
      ${l.sanitized?'<div style="color:var(--amber);margin-top:10px;font-size:12px"><strong>⚠ 已脱敏处理</strong></div>':''}
      ${l.blockedReason?`<div style="color:var(--red);margin-top:8px;font-size:12px"><strong>阻断原因:</strong> ${esc(l.blockedReason)}</div>`:''}
      ${l.errorMessage?`<div style="color:var(--red);margin-top:8px;font-size:12px"><strong>错误:</strong> ${esc(l.errorMessage)}</div>`:''}
      ${l.requestBody?`<details style="margin-top:12px"><summary style="cursor:pointer;font-weight:600;color:var(--muted-foreground);font-size:13px">请求体</summary><pre class="expand-pre" style="margin-top:8px">${esc(formatJSON(l.requestBody))}</pre></details>`:''}
      ${l.responseChoices?`<details style="margin-top:8px"><summary style="cursor:pointer;font-weight:600;color:var(--muted-foreground);font-size:13px">响应内容</summary><pre class="expand-pre" style="margin-top:8px">${esc(formatJSON(l.responseChoices))}</pre></details>`:''}
    </div></td></tr>`:''}`).join('')||emptyRow(10,'暂无日志','请求后将在此展示')}
    </tbody></table>
  </div></div></div>`;
}

function toggleLogExpand(id){state.expandedLogId=state.expandedLogId===id?null:id;updatePage('logs')}

async function loadLogs(){
  const keyword=val('log-search')||'';const model=val('log-model')||'';
  state._logKw=keyword;state._logModel=model;
  let path='/logs?limit=50';
  if(keyword)path+='&keyword='+encodeURIComponent(keyword);
  if(model)path+='&model='+encodeURIComponent(model);
  const r=await api(path);if(r.code==='0000')state.data.logs=r.data||[];updatePage('logs');
}
async function clearLogs(){const r=await api('/logs',{method:'DELETE'});if(r.code==='0000'){toast('日志已清空');loadLogs();loadDashboard()}else toast(r.info||'清空失败','error')}
