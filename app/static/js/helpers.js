function val(id){const el=document.getElementById(id);return el?el.value:''}
function esc(s){if(s==null)return'';return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#39;')}
function fmtDate(d,full){if(!d)return'-';try{const dt=new Date(d);if(full)return dt.toLocaleString('zh-CN');return dt.toLocaleString('zh-CN',{month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit'})}catch{return d}}
function fmtTime(d){if(!d)return'--';try{return new Date(d).toLocaleTimeString('zh-CN',{hour:'2-digit',minute:'2-digit',second:'2-digit'})}catch{return'--'}}
function fmtNum(n){if(n==null)return 0;if(n>=1e9)return(n/1e9).toFixed(1)+'B';if(n>=1e6)return(n/1e6).toFixed(1)+'M';if(n>=1e3)return(n/1e3).toFixed(1)+'K';return n}
function fmtBytes(n){if(!n)return'0 B';const u=['B','KB','MB','GB'];let i=0;while(n>=1024&&i<u.length-1){n/=1024;i++}return n.toFixed(n<10&&i>0?1:0)+' '+u[i]}
function relTime(d){if(!d)return'-';const now=Date.now();const t=new Date(d).getTime();const s=Math.floor((now-t)/1000);if(s<60)return s+'秒前';if(s<3600)return Math.floor(s/60)+'分钟前';if(s<86400)return Math.floor(s/3600)+'小时前';return Math.floor(s/86400)+'天前'}
function emptyState(title,desc,action){return`<div class="empty">${I.empty}<div class="empty-title">${esc(title)}</div><div class="empty-desc">${esc(desc||'')}</div>${action||''}</div>`}
function emptyRow(cols,title,desc){return`<tr><td colspan="${cols}">${emptyState(title,desc)}</td></tr>`}
function randomKey(){return Array.from({length:32},()=>'abcdefghijklmnopqrstuvwxyz0123456789'[Math.floor(Math.random()*36)]).join('')}
function formatJSON(str){try{return JSON.stringify(JSON.parse(str),null,2)}catch(e){return str}}
function copyText(text){navigator.clipboard?.writeText(text).then(()=>toast('已复制到剪贴板')).catch(()=>toast('复制失败','error'))}
function riskBadge(r){
  if(!r||r==='Clean'||r==='LOW'||r==='Low')return'<span class="badge badge-green">Clean</span>';
  if(r==='MEDIUM'||r==='Medium')return'<span class="badge badge-amber">'+esc(r)+'</span>';
  if(r==='High'||r==='HIGH'||r==='Critical'||r==='CRITICAL')return'<span class="badge badge-red">'+esc(r)+'</span>';
  return'<span class="badge badge-slate">'+esc(r||'Clean')+'</span>';
}
function securityActionBadge(a){
  if(!a||a==='Allow')return'<span class="badge badge-green">Allow</span>';
  if(a==='Sanitize')return'<span class="badge badge-amber">Sanitize</span>';
  if(a==='Block')return'<span class="badge badge-red">Block</span>';
  return'<span class="badge badge-slate">'+esc(a)+'</span>';
}
function docStatusBadge(s){
  if(s==='ready')return'badge-green';
  if(s==='error')return'badge-red';
  if(s==='processing'||s==='building')return'badge-amber';
  return'badge-slate';
}
function statusBadge(on){return on?'<span class="badge badge-green">启用</span>':'<span class="badge badge-slate">禁用</span>'}
function codeBadge(code){return code===200?'<span class="badge badge-green">'+esc(code)+'</span>':'<span class="badge badge-red">'+esc(code)+'</span>'}
function truncate(s,n){s=s||'';return s.length>n?s.substring(0,n)+'...':s}

// Toast 通知
function toast(msg,type='success'){
  const c=document.getElementById('toastContainer');
  const t=document.createElement('div');
  t.className='toast toast-'+type;
  const icon=type==='success'?'✓':type==='error'?'✕':'ℹ';
  t.innerHTML='<span style="font-weight:700">'+icon+'</span><span>'+esc(msg)+'</span>';
  c.appendChild(t);
  setTimeout(()=>{t.style.animation='slideOut .25s forwards';setTimeout(()=>t.remove(),250)},3000);
}

// Modal 弹窗
function showModal(html){
  document.getElementById('modalContent').innerHTML=html;
  document.getElementById('modalOverlay').classList.add('show');
}
function closeModal(){document.getElementById('modalOverlay').classList.remove('show')}

// 确认删除
function confirmDel(type,name,callback){
  showModal(`<div class="modal-header"><div class="modal-title">确认删除</div></div>
  <div class="modal-body">
  <div style="font-size:14px;color:var(--muted-foreground);margin-bottom:8px">确定要删除${type} <strong style="color:var(--foreground)">${esc(name)}</strong> 吗？</div>
  <div style="font-size:12px;color:var(--muted-foreground)">此操作不可撤销。</div>
  </div>
  <div class="modal-actions"><button class="btn btn-secondary" onclick="closeModal()">取消</button><button class="btn btn-danger" onclick="confirmDelOk()">确认删除</button></div>`);
  window._delCallback=callback;
}
function confirmDelOk(){closeModal();if(window._delCallback){window._delCallback();window._delCallback=null}}
