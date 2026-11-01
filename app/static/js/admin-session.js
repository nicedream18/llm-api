let adminSessionReady=false;

function showAdminLogin(){
  if(document.getElementById('adminLoginForm')&&document.getElementById('modalOverlay').classList.contains('show'))return;
  showModal('<form id="adminLoginForm" onsubmit="submitAdminLogin(event)">'+
    '<div class="modal-header"><div class="modal-title">管理员登录</div></div>'+
    '<div class="modal-body"><label class="input-label" for="adminUsername">用户名</label>'+
    '<input class="input" id="adminUsername" name="username" autocomplete="username" required maxlength="128">'+
    '<label class="input-label" for="adminPassword" style="margin-top:16px">密码</label>'+
    '<input class="input" type="password" id="adminPassword" name="password" autocomplete="current-password" required maxlength="512">'+
    '<p id="adminLoginError" role="alert" style="color:var(--danger)"></p></div>'+
    '<div class="modal-actions"><button class="btn btn-primary" type="submit">登录</button></div></form>');
  document.getElementById('adminUsername').focus();
}

async function submitAdminLogin(event){
  event.preventDefault();
  const button=event.target.querySelector('button[type=submit]');
  button.disabled=true;
  const response=await api('/auth/login',{method:'POST',body:JSON.stringify({
    username:val('adminUsername'),password:val('adminPassword')
  })});
  if(response.code!=='0000'){
    document.getElementById('adminLoginError').textContent=response.info||'登录失败';
    button.disabled=false;
    return;
  }
  document.getElementById('adminPassword').value='';
  closeModal();
  adminSessionReady=true;
  renderAccountControls(response.data.username);
  loadDashboard();
  renderSidebarFooter();
}

function renderAccountControls(username){
  document.getElementById('accountControls').innerHTML='<div style="padding:12px 20px">'+
    '<span>'+esc(username)+'</span> <button class="btn btn-ghost btn-sm" onclick="logoutAdmin()">退出登录</button></div>';
}

async function initializeAdminSession(){
  const response=await api('/auth/session');
  if(response.code==='0000'&&response.data.authenticated){
    adminSessionReady=true;
    renderAccountControls(response.data.username);
    loadDashboard();
    renderSidebarFooter();
  }else showAdminLogin();
}

async function logoutAdmin(){
  const response=await api('/auth/logout',{method:'POST'});
  if(response.code==='0000')location.reload();
  else toast(response.info,'error');
}
