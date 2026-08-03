// 主题管理
function initTheme(){
  const saved=localStorage.getItem('waliapi-theme')||'light';
  document.documentElement.setAttribute('data-theme',saved);
  updateThemeBtn();
}
function toggleTheme(){
  const cur=document.documentElement.getAttribute('data-theme')||'light';
  const next=cur==='light'?'dark':'light';
  document.documentElement.setAttribute('data-theme',next);
  localStorage.setItem('waliapi-theme',next);
  updateThemeBtn();
}
function updateThemeBtn(){
  const dark=document.documentElement.getAttribute('data-theme')==='dark';
  const btn=document.getElementById('themeBtn');
  if(btn)btn.innerHTML=dark
    ?'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="5"/><path d="M12 1v2M12 21v2M4.2 4.2l1.4 1.4M18.4 18.4l1.4 1.4M1 12h2M21 12h2M4.2 19.8l1.4-1.4M18.4 5.6l1.4-1.4"/></svg>'
    :'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 12.79A9 9 0 1111.21 3 7 7 0 0021 12.79z"/></svg>';
}

// 移动端侧边栏
function toggleSidebar(){
  document.getElementById('sidebar').classList.toggle('open');
  document.getElementById('backdrop').classList.toggle('show');
}

// 导航菜单（分组）
const menus=[
  {section:'核心',items:[
    {id:'dashboard',label:'仪表盘',icon:I.dashboard},
    {id:'channels',label:'渠道管理',icon:I.channels},
    {id:'apikeys',label:'API 密钥',icon:I.keys},
  ]},
  {section:'智能',items:[
    {id:'agents',label:'Agent 管理',icon:I.agents},
    {id:'knowledge',label:'知识库',icon:I.knowledge},
  ]},
  {section:'运维',items:[
    {id:'logs',label:'请求日志',icon:I.logs},
    {id:'security',label:'安全审计',icon:I.security},
    {id:'usage',label:'接入示例',icon:I.usage},
  ]}
];

function renderNav(){
  let html='';
  menus.forEach(g=>{
    html+=`<div class="nav-section-label">${g.section}</div>`;
    html+=g.items.map(m=>
      `<div class="nav-item${state.activeTab===m.id?' active':''}" data-tab="${m.id}" onclick="switchTab('${m.id}')">
        <span class="nav-icon-box">${m.icon}</span>
        <span>${m.label}</span>
        <svg class="nav-chevron" viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="2"><path d="M9 18l6-6-6-6"/></svg>
      </div>`
    ).join('');
  });
  document.getElementById('nav').innerHTML=html;
}

// 侧边栏底部服务状态卡
async function renderSidebarFooter(){
  const el=document.getElementById('sidebarFooter');
  if(!el)return;
  let running=false,url='等待服务启动';
  try{
    const r=await fetch('/api/v1/dashboard',{headers:{'Content-Type':'application/json'}});
    if(r.ok){running=true;url=location.protocol+'//'+location.host+'/v1'}
  }catch(e){}
  el.innerHTML=`<div class="srv-card">
    <div class="srv-row">
      <div>
        <div style="font-size:12px;color:var(--muted-foreground)">服务状态</div>
        <div style="margin-top:4px;font-size:14px;font-weight:600;color:var(--foreground)">${running?'运行中':'未启动'}</div>
      </div>
      <span class="srv-dot ${running?'on':'off'}"></span>
    </div>
    <div class="srv-url-box">
      <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="${running?'#10b981':'#f43f5e'}" stroke-width="2"><rect x="2" y="2" width="20" height="8" rx="2"/><rect x="2" y="14" width="20" height="8" rx="2"/><line x1="6" y1="6" x2="6.01" y2="6"/><line x1="6" y1="18" x2="6.01" y2="18"/></svg>
      <div style="min-width:0;flex:1">
        <div style="margin-bottom:4px">API BaseUrl 地址</div>
        <code>${esc(url)}</code>
      </div>
    </div>
  </div>`;
}
