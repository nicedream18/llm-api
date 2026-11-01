async function api(path,opts={}){
  try{
    const r=await fetch('/api/v1'+path,{headers:{'Content-Type':'application/json'},...opts});
    if(!r.ok){
      if(r.status===401&&!path.startsWith('/auth/')&&typeof showAdminLogin==='function')showAdminLogin();
      let msg='请求失败 ('+r.status+')';
      try{const j=await r.json();if(j.info)msg=j.info;else if(j.detail)msg=typeof j.detail==='string'?j.detail:'请检查输入内容'}catch(e){}
      return{code:'ERR',info:msg};
    }
    return await r.json();
  }catch(e){
    return{code:'ERR',info:'网络错误：'+e.message};
  }
}
