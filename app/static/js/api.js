async function api(path,opts={}){
  try{
    const r=await fetch('/api/v1'+path,{headers:{'Content-Type':'application/json'},...opts});
    if(!r.ok){
      let msg='请求失败 ('+r.status+')';
      try{const j=await r.json();if(j.info)msg=j.info}catch(e){}
      return{code:'ERR',info:msg};
    }
    return await r.json();
  }catch(e){
    return{code:'ERR',info:'网络错误：'+e.message};
  }
}
