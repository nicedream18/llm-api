const wikiState={projects:[],projectId:null,pages:[],page:null,total:0,offset:0,query:'',tag:'',tab:'pages',sources:[],tags:[],graph:null};
let wikiEditingPage=null;

function wikiRoot(){return '/wiki/projects/'+encodeURIComponent(wikiState.projectId)}

function pgWiki(){
  const project=wikiState.projects.find(p=>p.id===wikiState.projectId);
  return '<div class="page-shell"><div class="page-header"><div><div class="page-title">Wiki</div>'+
    '<div class="page-subtitle">Markdown 页面 · 关联图谱 · 可追溯问答</div></div>'+
    '<div class="page-header-actions"><button class="btn btn-secondary" onclick="restoreWikiFile()">恢复备份</button>'+
    '<button class="btn btn-primary" onclick="showWikiProject()">创建项目</button></div></div>'+
    '<div class="wiki-toolbar"><label for="wikiProject">项目</label><select class="input" id="wikiProject" onchange="selectWikiProject(this.value)">'+
    '<option value="">选择项目</option>'+wikiState.projects.map(p=>'<option value="'+esc(p.id)+'"'+(p.id===wikiState.projectId?' selected':'')+'>'+esc(p.name)+'</option>').join('')+'</select>'+
    (project?'<button class="btn btn-secondary" onclick="showWikiProject(true)">编辑项目</button>'+
      '<button class="btn btn-secondary" onclick="downloadWikiBackup()">备份</button>'+
      '<button class="btn btn-danger" onclick="deleteWikiProject()">删除项目</button>':'')+'</div>'+
    (project?'<div class="kb-tabs" style="margin:16px 0">'+['pages','sources','graph','ask'].map(tab=>'<button class="kb-tab '+(wikiState.tab===tab?'active':'')+
      '" onclick="switchWikiView(\''+tab+'\')">'+({pages:'页面',sources:'来源',graph:'图谱',ask:'问答'})[tab]+'</button>').join('')+'</div>'+
      '<div id="wikiPanel">'+renderWikiPanel()+'</div>':emptyState('创建你的第一个 Wiki 项目','项目中的页面、来源和附件独立管理。'))+'</div>';
}

async function loadWiki(){
  const response=await api('/wiki/projects');
  if(response.code!=='0000')return toast(response.info,'error');
  wikiState.projects=response.data;
  if(!wikiState.projects.some(p=>p.id===wikiState.projectId))wikiState.projectId=wikiState.projects[0]?.id||null;
  if(wikiState.projectId)await loadWikiProject();
  updatePage('wiki');
}

async function selectWikiProject(id){
  wikiState.projectId=id||null;wikiState.page=null;wikiState.offset=0;wikiState.query='';wikiState.tag='';
  if(id)await loadWikiProject();
  updatePage('wiki');
}

async function loadWikiProject(){
  const projectId=wikiState.projectId;
  const [pages,sources,tags,graph]=await Promise.all([
    api(wikiRoot()+'/pages?limit=100&offset='+wikiState.offset+'&query='+encodeURIComponent(wikiState.query)+'&tag='+encodeURIComponent(wikiState.tag)),
    api(wikiRoot()+'/sources'),api(wikiRoot()+'/tags'),api(wikiRoot()+'/graph')
  ]);
  if(projectId!==wikiState.projectId)return;
  for(const response of [pages,sources,tags,graph])if(response.code!=='0000')return toast(response.info,'error');
  wikiState.pages=pages.data.items;wikiState.total=pages.data.total;wikiState.sources=sources.data;wikiState.tags=tags.data;wikiState.graph=graph.data;
  if(wikiState.page){
    const response=await api(wikiRoot()+'/pages/'+wikiState.page.id);
    wikiState.page=response.code==='0000'?response.data:null;
  }
}

function switchWikiView(tab){wikiState.tab=tab;updatePage('wiki');if(tab==='graph')drawWikiGraph()}

function renderWikiPanel(){
  if(wikiState.tab==='sources')return '<button class="btn btn-primary" onclick="importWikiSource()">导入文本来源</button>'+
    '<div class="table-wrap" style="margin-top:16px"><table><thead><tr><th>文件</th><th>状态</th><th>操作</th></tr></thead><tbody>'+
    wikiState.sources.map(s=>'<tr><td>'+esc(s.filename)+'</td><td>'+esc(s.status)+'</td><td>'+
      '<button class="btn btn-secondary btn-sm" onclick="ingestWikiSource(\''+s.id+'\')">摄入 / 重新摄入</button> '+
      '<button class="btn btn-danger btn-sm" onclick="removeWikiSource(\''+s.id+'\')">删除来源</button></td></tr>').join('')+'</tbody></table></div>';
  if(wikiState.tab==='graph')return '<div class="wiki-graph"><svg id="wikiGraph" viewBox="0 0 720 420" role="img" aria-label="Wiki 页面关系图"></svg></div>'+
    '<p>实线表示已解析的页面关系；未找到的链接列在下方。</p>'+
    (wikiState.graph?.edges||[]).filter(e=>!e.resolved).map(e=>'<p>'+esc(e.path)+'（未找到）</p>').join('');
  if(wikiState.tab==='ask')return '<form onsubmit="askWiki(event)"><label class="input-label" for="wikiAskModel">模型</label>'+
    '<input class="input" id="wikiAskModel" required placeholder="填写已配置渠道中的模型">'+
    '<label class="input-label" for="wikiQuestion" style="margin-top:16px">问题</label>'+
    '<textarea class="input" id="wikiQuestion" required rows="4" maxlength="32768"></textarea>'+
    '<button class="btn btn-primary" type="submit" style="margin-top:12px">提问</button></form>'+
    '<div id="wikiAnswer" aria-live="polite" class="wiki-document"></div>';
  return '<form class="wiki-toolbar" onsubmit="searchWiki(event)"><input class="input" id="wikiQuery" aria-label="搜索 Wiki 页面" placeholder="搜索标题和正文" value="'+esc(wikiState.query)+'">'+
    '<select class="input" id="wikiTag" aria-label="筛选标签"><option value="">全部标签</option>'+
    wikiState.tags.map(t=>'<option value="'+esc(t.tag)+'"'+(t.tag===wikiState.tag?' selected':'')+'>'+esc(t.tag)+' ('+t.count+')</option>').join('')+'</select>'+
    '<button class="btn btn-secondary" type="submit">搜索</button><button class="btn btn-primary" type="button" onclick="showWikiPage()">新建页面</button></form>'+
    '<div class="wiki-layout"><aside class="wiki-page-list">'+wikiState.pages.map(p=>'<button class="wiki-page-item'+(wikiState.page?.id===p.id?' active':'')+
      '" onclick="openWikiPage(\''+p.id+'\')"><strong>'+esc(p.title)+'</strong><small>'+esc(p.path)+'</small></button>').join('')+
      '<div class="wiki-toolbar"><button class="btn btn-ghost btn-sm" onclick="pageWiki(-100)"'+(wikiState.offset===0?' disabled':'')+'>上一页</button>'+
      '<span>'+wikiState.total+' 页</span><button class="btn btn-ghost btn-sm" onclick="pageWiki(100)"'+(wikiState.offset+100>=wikiState.total?' disabled':'')+'>下一页</button></div></aside>'+
      '<article class="wiki-document">'+renderWikiPage()+'</article></div>';
}

function renderWikiPage(){
  const page=wikiState.page;
  if(!page)return emptyState('选择或创建页面','支持目录路径、标签和 [[页面链接]]。');
  return '<div class="wiki-toolbar"><h2 style="flex:1">'+esc(page.title)+'</h2>'+
    '<button class="btn btn-secondary" onclick="showWikiPage(true)">编辑页面</button>'+
    '<button class="btn btn-secondary" onclick="uploadWikiAttachment()">上传附件</button>'+
    '<button class="btn btn-danger" onclick="deleteWikiPage()">删除页面</button></div>'+
    '<p class="page-subtitle">'+esc(page.path)+' · 修订 '+page.revision+'</p>'+renderWikiMarkdown(page.content);
}

// A deliberately small, safe Markdown renderer. Raw HTML and external links remain text.
function renderWikiMarkdown(content){
  const lines=String(content).split('\n');let html='',code=false,codeLines=[];
  const inline=text=>esc(text).replace(/\*\*([^*]+)\*\*/g,'<strong>$1</strong>');
  for(const line of lines){
    if(/^\s*(`{3,}|~{3,})/.test(line)){
      if(code){html+='<pre><code>'+esc(codeLines.join('\n'))+'</code></pre>';codeLines=[]}
      code=!code;continue;
    }
    if(code){codeLines.push(line);continue}
    const heading=/^(#{1,6})\s+(.+)$/.exec(line);
    if(heading){const level=heading[1].length;html+='<h'+level+'>'+inline(heading[2])+'</h'+level+'>';continue}
    if(line.trim())html+='<p>'+inline(line)+'</p>';
  }
  if(codeLines.length)html+='<pre><code>'+esc(codeLines.join('\n'))+'</code></pre>';
  return html;
}

async function openWikiPage(id){
  const response=await api(wikiRoot()+'/pages/'+encodeURIComponent(id));
  if(response.code!=='0000')return toast(response.info,'error');
  wikiState.page=response.data;updatePage('wiki');
}

async function searchWiki(event){
  event.preventDefault();wikiState.query=val('wikiQuery');wikiState.tag=val('wikiTag');wikiState.offset=0;
  await loadWikiProject();updatePage('wiki');
}
async function pageWiki(delta){wikiState.offset=Math.max(0,wikiState.offset+delta);await loadWikiProject();updatePage('wiki')}

function showWikiProject(edit=false){
  const project=edit?wikiState.projects.find(p=>p.id===wikiState.projectId):null;
  showModal('<form onsubmit="saveWikiProject(event,'+Boolean(edit)+')"><div class="modal-header"><div class="modal-title">'+(edit?'编辑':'创建')+' Wiki 项目</div></div>'+
    '<div class="modal-body"><label class="input-label" for="wikiProjectName">名称</label><input class="input" id="wikiProjectName" required maxlength="128" value="'+esc(project?.name||'')+'">'+
    '<label class="input-label" for="wikiProjectDesc" style="margin-top:16px">描述</label><textarea class="input" id="wikiProjectDesc" maxlength="4096">'+esc(project?.description||'')+'</textarea></div>'+
    '<div class="modal-actions"><button type="button" class="btn btn-secondary" onclick="closeModal()">取消</button><button class="btn btn-primary" type="submit">保存项目</button></div></form>');
}
async function saveWikiProject(event,edit){
  event.preventDefault();
  const response=await api(edit?wikiRoot():'/wiki/projects',{method:edit?'PUT':'POST',body:JSON.stringify({name:val('wikiProjectName'),description:val('wikiProjectDesc')})});
  if(response.code!=='0000')return toast(response.info,'error');
  wikiState.projectId=response.data.id;closeModal();await loadWiki();toast('项目已保存');
}
function deleteWikiProject(){
  const project=wikiState.projects.find(p=>p.id===wikiState.projectId);
  confirmDel('Wiki 项目',project.name,async()=>{const response=await api(wikiRoot(),{method:'DELETE'});if(response.code!=='0000')return toast(response.info,'error');wikiState.page=null;await loadWiki()});
}

function showWikiPage(edit=false){
  wikiEditingPage=edit?{...wikiState.page}:null;
  const page=wikiEditingPage;
  showModal('<form onsubmit="saveWikiPage(event)"><div class="modal-header"><div class="modal-title">'+(edit?'编辑':'新建')+' Wiki 页面</div></div>'+
    '<div class="modal-body"><label class="input-label" for="wikiPagePath">路径</label><input class="input" id="wikiPagePath" required placeholder="guide/start.md" value="'+esc(page?.path||'')+'">'+
    '<label class="input-label" for="wikiPageTitle" style="margin-top:12px">标题</label><input class="input" id="wikiPageTitle" required maxlength="256" value="'+esc(page?.title||'')+'">'+
    '<label class="input-label" for="wikiPageTags" style="margin-top:12px">标签（逗号分隔）</label><input class="input" id="wikiPageTags" value="'+esc((page?.tags||[]).join(','))+'">'+
    '<label class="input-label" for="wikiPageContent" style="margin-top:12px">Markdown 正文</label><textarea class="input" id="wikiPageContent" rows="12" maxlength="1000000">'+esc(page?.content||'')+'</textarea></div>'+
    '<div class="modal-actions"><button class="btn btn-secondary" type="button" onclick="closeModal()">取消</button><button class="btn btn-primary" type="submit">保存页面</button></div></form>');
}
async function saveWikiPage(event){
  event.preventDefault();const button=event.target.querySelector('button[type=submit]');button.disabled=true;
  const dto={path:val('wikiPagePath'),title:val('wikiPageTitle'),content:val('wikiPageContent'),tags:val('wikiPageTags').split(',').map(t=>t.trim()).filter(Boolean)};
  if(wikiEditingPage)dto.revision=wikiEditingPage.revision;
  const response=await api(wikiRoot()+'/pages'+(wikiEditingPage?'/'+wikiEditingPage.id:''),{method:wikiEditingPage?'PUT':'POST',body:JSON.stringify(dto)});
  if(response.code!=='0000'){button.disabled=false;return toast(response.info,'error')}
  wikiState.page=response.data;closeModal();await loadWikiProject();updatePage('wiki');toast('页面已保存');
}
function deleteWikiPage(){
  const page=wikiState.page;
  confirmDel('页面',page.title,async()=>{const response=await api(wikiRoot()+'/pages/'+page.id,{method:'DELETE'});if(response.code!=='0000')return toast(response.info,'error');wikiState.page=null;await loadWikiProject();updatePage('wiki')});
}

function importWikiSource(){
  const input=document.createElement('input');input.type='file';input.accept='.md,.markdown,.txt';
  input.onchange=async()=>{
    const file=input.files[0];if(!file)return;if(file.size>1000000)return toast('来源文件不能超过 1 MB','error');
    const response=await api(wikiRoot()+'/sources',{method:'POST',body:JSON.stringify({filename:file.name,content:await file.text()})});
    if(response.code!=='0000')return toast(response.info,'error');
    await loadWikiProject();updatePage('wiki');toast('来源已导入，点击摄入生成页面');
  };input.click();
}
async function ingestWikiSource(id){const response=await api(wikiRoot()+'/sources/'+id+'/ingest',{method:'POST'});if(response.code!=='0000')toast(response.info,'error');await loadWikiProject();updatePage('wiki')}
function removeWikiSource(id){const source=wikiState.sources.find(s=>s.id===id);confirmDel('来源',source.filename,async()=>{const response=await api(wikiRoot()+'/sources/'+id,{method:'DELETE'});if(response.code!=='0000')return toast(response.info,'error');await loadWikiProject();updatePage('wiki')})}

async function downloadWikiBackup(){
  const response=await fetch('/api/v1'+wikiRoot()+'/backup');if(!response.ok)return toast('备份下载失败','error');
  const url=URL.createObjectURL(await response.blob());const link=document.createElement('a');link.href=url;link.download='wiki-backup.json';link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
}
function restoreWikiFile(){
  const input=document.createElement('input');input.type='file';input.accept='.json';
  input.onchange=async()=>{const file=input.files[0];if(!file)return;if(file.size>32*1024*1024)return toast('备份不能超过 32 MiB','error');
    const response=await api('/wiki/restore',{method:'POST',body:await file.text()});if(response.code!=='0000')return toast(response.info,'error');
    wikiState.projectId=response.data.id;wikiState.page=null;await loadWiki();toast('已恢复为新项目')};input.click();
}
function uploadWikiAttachment(){
  const input=document.createElement('input');input.type='file';input.accept='image/png,image/jpeg,image/gif,image/webp,application/pdf,text/plain';
  input.onchange=async()=>{const file=input.files[0];if(!file)return;if(file.size>10*1024*1024)return toast('附件不能超过 10 MiB','error');
    const response=await fetch('/api/v1'+wikiRoot()+'/pages/'+wikiState.page.id+'/attachments?filename='+encodeURIComponent(file.name),{method:'POST',headers:{'Content-Type':file.type||'application/octet-stream'},body:file});
    if(!response.ok)return toast('附件上传失败','error');
    const result=await response.json();toast('附件已上传');
    const url='/api/v1'+wikiRoot()+'/attachments/'+result.data.id;
    showModal('<div class="modal-header"><div class="modal-title">附件上传成功</div></div><div class="modal-body"><a href="'+url+'" download>'+esc(file.name)+'</a><p>下载地址可作为页面中的附件引用。</p><input class="input" aria-label="附件地址" readonly value="'+esc(url)+'"></div><div class="modal-actions"><button class="btn btn-primary" onclick="closeModal()">完成</button></div>');
  };input.click();
}
async function askWiki(event){
  event.preventDefault();const button=event.target.querySelector('button');button.disabled=true;
  const response=await api(wikiRoot()+'/ask',{method:'POST',body:JSON.stringify({question:val('wikiQuestion'),model:val('wikiAskModel')})});
  button.disabled=false;if(response.code!=='0000')return toast(response.info,'error');
  document.getElementById('wikiAnswer').innerHTML=renderWikiMarkdown(response.data.answer)+'<h3>引用页面</h3>'+response.data.sources.map(s=>'<p>'+esc(s.path)+'</p>').join('');
}

function drawWikiGraph(){
  const svg=document.getElementById('wikiGraph');if(!svg)return;
  const nodes=wikiState.graph?.nodes||[];const positions=new Map();
  nodes.forEach((node,index)=>{const angle=index*2*Math.PI/Math.max(nodes.length,1);positions.set(node.id,{x:360+250*Math.cos(angle),y:210+150*Math.sin(angle)})});
  function element(name,attributes){const node=document.createElementNS('http://www.w3.org/2000/svg',name);for(const [key,value] of Object.entries(attributes))node.setAttribute(key,String(value));return node}
  for(const edge of wikiState.graph?.edges||[]){const from=positions.get(edge.source),to=positions.get(edge.target);if(from&&to)svg.appendChild(element('line',{x1:from.x,y1:from.y,x2:to.x,y2:to.y,stroke:'currentColor',opacity:.35}))}
  for(const node of nodes){const point=positions.get(node.id);const circle=element('circle',{cx:point.x,cy:point.y,r:7,fill:'currentColor'});svg.appendChild(circle);
    const label=element('text',{x:point.x,y:point.y+24,'text-anchor':'middle',fill:'currentColor','font-size':12});label.textContent=node.title.slice(0,20);svg.appendChild(label)}
}
