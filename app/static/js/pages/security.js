function pgSecurity(){
  const builtinRules=state.data.security.builtin||[];
  const customRules=state.data.security.custom||[];
  const findings=state.data.security.findings||[];
  const policy=state.data.security.settings||{};
  const secCount=builtinRules.filter(r=>r.enabled).length;
  return`<div class="page-shell">
  <div class="page-header"><div><div class="page-title">安全审计</div><div class="page-subtitle">安全策略 · 规则管理 · 审计日志</div></div>
    <div class="page-header-actions"><button class="btn btn-secondary btn-sm" onclick="loadSecurity()">${I.refresh}刷新</button></div>
  </div>
  <div class="grid grid-4" style="margin-bottom:16px">
    <div class="card stat-card"><div class="stat-icon" style="background:var(--green-soft);color:var(--green)">${I.security}</div><div class="stat-value" style="margin-top:10px">${secCount}</div><div class="stat-label">启用规则</div></div>
    <div class="card stat-card"><div class="stat-icon" style="background:var(--primary-soft);color:var(--primary)">${I.plus}</div><div class="stat-value" style="margin-top:10px">${customRules.length}</div><div class="stat-label">自定义规则</div></div>
    <div class="card stat-card"><div class="stat-icon" style="background:var(--amber-soft);color:var(--amber)">${I.logs}</div><div class="stat-value" style="margin-top:10px">${findings.length}</div><div class="stat-label">安全发现</div></div>
    <div class="card stat-card"><div class="stat-icon" style="background:var(--red-soft);color:var(--red)">${I.test}</div><div class="stat-value" style="margin-top:10px">${findings.filter(f=>f.severity==='CRITICAL'||f.severity==='HIGH').length}</div><div class="stat-label">高危发现</div></div>
  </div>
  <div class="grid grid-2" style="margin-bottom:16px">
    <div class="surface" style="padding:24px">
      <div style="font-weight:700;margin-bottom:14px">安全策略配置</div><p style="font-size:12px">当前模式：${esc(policy.mode||"未加载")} · <a href="/admin/#/security">完整策略与规则编辑</a></p><p style="font-size:12px">普通响应扫描开启时拒绝流式请求；不扫描二进制附件。密钥自动脱敏在 audit 模式同样生效。</p>
      <div>
        ${secToggleRow('安全审计总开关','audit',!!policy.enabled)}
        ${secToggleRow('Unicode 混淆扫描','unicode',!!policy.scan_unicode)}
        ${secToggleRow('网络请求扫描','network',!!policy.scan_network)}
        ${secToggleRow('工具调用风险扫描','tool',!!policy.scan_tools)}
        ${secToggleRow('响应内容扫描','response',!!policy.scan_response)}
        ${secToggleRow('密钥自动脱敏','mask',!!policy.redact_secrets)}
      </div>
    </div>
    <div class="surface" style="padding:24px">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:14px">
        <span style="font-weight:700">自定义规则</span>
        <button class="btn btn-primary btn-sm" onclick="showSecRuleModal()">${I.plus}添加规则</button>
      </div>
      <div>
        ${customRules.length?customRules.map(r=>`<div class="rule-item">
          <div style="min-width:0"><span class="badge badge-blue">${esc(r.rule_type||r.ruleType||r.type)}</span><span style="margin-left:8px;font-size:13px;font-weight:500">${esc(r.name||r.pattern)}</span></div>
          <div style="display:flex;align-items:center;gap:8px;flex-shrink:0">
            <span class="badge ${r.severity==='CRITICAL'?'badge-red':r.severity==='HIGH'?'badge-amber':'badge-slate'}">${esc(r.severity)}</span>
            <button class="btn btn-secondary btn-sm" onclick="showSecRuleModal('${r.id}')">编辑</button>
            <button class="btn btn-danger btn-sm btn-icon" onclick="confirmDel('规则','${esc(r.name||r.pattern)}',()=>delCustomRule('${r.id}'))" title="删除">${I.trash}</button>
          </div>
        </div>`).join(''):emptyState('暂无自定义规则','点击右上角添加')}
      </div>
    </div>
  </div>
  <div class="surface" style="margin-bottom:16px;overflow:hidden">
    <div style="padding:14px 16px;border-bottom:1px solid var(--border);font-weight:700;font-size:13px;background:var(--slate-l);display:flex;align-items:center;gap:8px">内置规则 <span class="badge badge-slate">${builtinRules.length}</span></div>
    <div class="table-wrap"><table class="table"><thead><tr><th>规则名称</th><th>类别</th><th>严重度</th><th>状态</th></tr></thead><tbody>
    ${builtinRules.length?builtinRules.map(r=>`<tr>
      <td style="font-weight:600">${esc(r.name||r.ruleName)}</td>
      <td><span class="badge badge-slate">${esc(r.category||r.type)}</span></td>
      <td><span class="badge ${r.severity==='CRITICAL'?'badge-red':r.severity==='HIGH'?'badge-amber':r.severity==='MEDIUM'?'badge-blue':'badge-slate'}">${esc(r.severity)}</span></td>
      <td><div class="switch ${r.enabled?'on':''}" onclick="toggleBuiltinRule('${r.id||r.ruleId}',${!r.enabled})" title="${r.enabled?'点击禁用':'点击启用'}"><div class="switch-knob"></div></div></td>
    </tr>`).join(''):emptyRow(4,'暂无内置规则','')}
    </tbody></table></div>
  </div>
  <div class="surface" style="overflow:hidden">
    <div style="padding:14px 16px;border-bottom:1px solid var(--border);font-weight:700;font-size:13px;background:var(--slate-l);display:flex;align-items:center;gap:8px">安全发现 <span class="badge badge-slate">${findings.length}</span></div>
    <div class="table-wrap"><table class="table"><thead><tr><th>时间</th><th>规则</th><th>严重度</th><th>内容</th><th>处理动作</th></tr></thead><tbody>
    ${findings.length?findings.map(f=>`<tr>
      <td style="font-size:12px;color:var(--muted-foreground);white-space:nowrap">${fmtDate(f.created_at||f.createdAt||f.timestamp)}</td>
      <td style="font-weight:600">${esc(f.title||f.ruleName||f.rule_id)}</td>
      <td><span class="badge ${f.severity==='CRITICAL'?'badge-red':f.severity==='HIGH'?'badge-amber':'badge-slate'}">${esc(f.severity)}</span></td>
      <td style="font-size:12px;max-width:320px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:var(--muted-foreground)">${esc(f.evidence_masked||f.content||f.detail||'-')}</td>
      <td><span class="badge badge-slate">${esc(f.action||f.resolution||'audit')}</span></td>
    </tr>`).join(''):emptyRow(5,'暂无安全发现记录','')}
    </tbody></table></div>
  </div></div>`;
}

function secToggleRow(label,key,on){
  return`<div class="sec-toggle-row">
    <span style="font-size:13px;color:var(--muted-foreground);font-weight:500">${label}</span>
    <div style="display:flex;align-items:center;gap:10px">
      <span style="font-size:12px;font-weight:600;color:${on?'var(--green)':'var(--border-strong)'}">${on?'已启用':'已禁用'}</span>
      <div class="switch${on?' on':''}" onclick="toggleSecPolicy('${key}')" title="切换"><div class="switch-knob"></div></div>
    </div>
  </div>`;
}

async function loadSecurity(){
  const [b,c,f,p]=await Promise.all([api('/security/rules/builtin'),api('/security/rules/custom'),api('/security/findings'),api('/security/settings')]);
  if([b,c,f,p].some(r=>r.code!=='0000')){toast('安全配置加载失败，请重试','error');return}
  state.data.security.settings=p.data;
  if(b.code==='0000')state.data.security.builtin=b.data||[];
  if(c.code==='0000')state.data.security.custom=c.data||[];
  if(f.code==='0000')state.data.security.findings=f.data||[];
  updatePage('security');
}
async function toggleBuiltinRule(id,enabled){const r=await api('/security/rules/builtin/'+id,{method:'PUT',body:JSON.stringify({enabled})});if(r.code==='0000'){toast('规则已更新');loadSecurity()}else toast(r.info||'操作失败','error')}
function secOptions(values,current){return values.map(v=>`<option value="${esc(v)}" ${v===current?'selected':''}>${esc(v)}</option>`).join('')}
function showSecRuleModal(id){
  const rule=(state.data.security.custom||[]).find(r=>r.id===id)||{name:'',category:'keyword',rule_type:'blacklist',match_type:'literal',action:'warn',severity:'medium',pattern:'',enabled:1};
  showModal(`<div class="modal-header"><div class="modal-title">${id?'编辑':'添加'}自定义规则</div></div><div class="modal-body">
  <div class="input-group"><label class="input-label">规则名称</label><input class="input" id="sr-name" value="${esc(rule.name)}"></div>
  <div class="input-group"><label class="input-label">黑白名单</label><select class="input" id="sr-rule-type">${secOptions(['blacklist','whitelist'],rule.rule_type)}</select></div>
  <div class="input-group"><label class="input-label">类别</label><select class="input" id="sr-category">${secOptions(['keyword','domain','path','tool'],rule.category)}</select></div>
  <div class="input-group"><label class="input-label">匹配方式</label><select class="input" id="sr-match-type">${secOptions(['literal','regex'],rule.match_type)}</select></div>
  <div class="input-group"><label class="input-label">匹配模式</label><input class="input" id="sr-pattern" value="${esc(rule.pattern)}"></div>
  <div class="input-group"><label class="input-label">严重度</label><select class="input" id="sr-severity">${secOptions(['info','low','medium','high','critical'],rule.severity)}</select></div>
  <div class="input-group"><label class="input-label">处置动作</label><select class="input" id="sr-action">${secOptions(['warn','allow','redact','block'],rule.action)}</select></div>
  <label><input type="checkbox" id="sr-enabled" ${rule.enabled?'checked':''}>启用规则</label>
  <p>白名单保存为 literal + allow。域名按主机名、路径按目录边界、工具按完整名称匹配；关键词忽略大小写。</p>
  </div><div class="modal-actions"><button class="btn btn-secondary" onclick="closeModal()">取消</button><button class="btn btn-primary" onclick="addCustomRule('${id||''}')">保存</button></div>`);
}
async function addCustomRule(id){
  const white=val('sr-rule-type')==='whitelist';
  const body={name:val('sr-name'),rule_type:val('sr-rule-type'),category:val('sr-category'),match_type:white?'literal':val('sr-match-type'),pattern:val('sr-pattern'),severity:val('sr-severity'),action:white?'allow':val('sr-action'),enabled:document.getElementById('sr-enabled').checked?1:0};
  if(!body.name||!body.pattern){toast('请填写完整','error');return}
  const r=await api('/security/rules/custom'+(id?'/'+encodeURIComponent(id):''),{method:id?'PUT':'POST',body:JSON.stringify(body)});
  if(r.code==='0000'){toast('规则已保存');closeModal();await loadSecurity()}else toast(r.info||'保存失败','error');
}
async function delCustomRule(id){const r=await api('/security/rules/custom/'+encodeURIComponent(id),{method:'DELETE'});if(r.code==='0000'){toast('规则已删除');await loadSecurity()}else toast(r.info||'删除失败','error')}
let securitySaving=false;
async function toggleSecPolicy(key){
  if(securitySaving)return;
  const fields={audit:'enabled',unicode:'scan_unicode',network:'scan_network',tool:'scan_tools',response:'scan_response',mask:'redact_secrets'};
  const field=fields[key];const settings=state.data.security.settings;
  if(!field||!settings){toast('请先加载安全配置','error');return}
  securitySaving=true;
  try{
    const r=await api('/security/settings',{method:'PUT',body:JSON.stringify({[field]:!settings[field]})});
    if(r.code==='0000'){state.data.security.settings=r.data;toast('策略已保存');updatePage('security')}
    else toast(r.info||'策略保存失败','error');
  }finally{securitySaving=false}
}
