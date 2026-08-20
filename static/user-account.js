(function(){
  'use strict';
  var icon=function(name){
    var paths={chevron:'<path d="m6 9 6 6 6-6"/>',user:'<path d="M20 21a8 8 0 0 0-16 0"/><circle cx="12" cy="7" r="4"/>',shield:'<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10"/><path d="m9 12 2 2 4-4"/>',settings:'<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .34 1.88l.06.06-2.83 2.83-.06-.06A1.7 1.7 0 0 0 15 19.4a1.7 1.7 0 0 0-1 .6 1.7 1.7 0 0 0-.4 1.1V21H9.6v-.09A1.7 1.7 0 0 0 8.5 19.4a1.7 1.7 0 0 0-1.88.34l-.06.06-2.83-2.83.06-.06A1.7 1.7 0 0 0 4.6 15a1.7 1.7 0 0 0-.6-1 1.7 1.7 0 0 0-1.1-.4H3V9.6h.09A1.7 1.7 0 0 0 4.6 8.5a1.7 1.7 0 0 0-.34-1.88l-.06-.06 2.83-2.83.06.06A1.7 1.7 0 0 0 9 4.6a1.7 1.7 0 0 0 1-.6 1.7 1.7 0 0 0 .4-1.1V3h4v.09A1.7 1.7 0 0 0 15.5 4.6a1.7 1.7 0 0 0 1.88-.34l.06-.06 2.83 2.83-.06.06A1.7 1.7 0 0 0 19.4 9c.15.38.38.73.7 1 .3.27.69.4 1.1.4h.09v4h-.09a1.7 1.7 0 0 0-1.8.6Z"/>',logout:'<path d="M10 17l5-5-5-5"/><path d="M15 12H3"/><path d="M15 3h4a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2h-4"/>'};
    return '<svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">'+paths[name]+'</svg>';
  };
  function esc(v){return String(v==null?'':v).replace(/[&<>"']/g,function(c){return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c];});}
  function avatar(profile,name){var src=profile&&profile.avatar;if(src)return '<img src="'+esc(src)+'" alt="">';return esc((name||'用').slice(0,1).toUpperCase());}
  function close(shell,trigger){shell.dataset.open='false';trigger.setAttribute('aria-expanded','false');}
  async function start(){
    var me;
    try{var response=await fetch('/api/auth/me',{credentials:'include',cache:'no-store'});me=await response.json();}catch(e){return;}
    if(!me||!me.authenticated)return;
    var profile={};
    if(me.username){try{var pr=await fetch('/api/auth/profile',{credentials:'include',cache:'no-store'});if(pr.ok)profile=(await pr.json()).profile||{};}catch(e){}}
    var isOwner=me.scope==='owner'&&!me.username;
    var isAdmin=!!(me.is_admin||me.role==='admin');
    var display=profile.nickname||me.username||(isOwner?'本地主人':'已登录');
    var sub=isOwner?'主人口令身份':(isAdmin?'管理员 · @'+me.username:'@'+me.username);
    var shell=document.createElement('div');shell.className='xumo-account-shell';shell.dataset.open='false';
    shell.innerHTML='<button class="xumo-account-trigger" type="button" aria-haspopup="menu" aria-expanded="false" aria-controls="xumoAccountMenu">'
      +'<span class="xumo-account-avatar">'+avatar(profile,display)+'</span><span class="xumo-account-trigger-copy"><strong>'+esc(display)+'</strong><small>'+esc(sub)+'</small></span><span class="xumo-account-chevron">'+icon('chevron')+'</span></button>'
      +'<section class="xumo-account-menu" id="xumoAccountMenu" role="menu" aria-label="用户账号"><div class="xumo-account-head"><span class="xumo-account-avatar">'+avatar(profile,display)+'</span><div class="xumo-account-identity"><strong>'+esc(display)+'</strong><span>'+esc(sub)+'</span></div></div>'
      +'<div class="xumo-account-status">'+icon('shield')+'<span><strong>数据已隔离保护</strong><br>'+(isOwner?'当前使用本地主人数据空间':'对话、记忆与相册仅保存在你的账号下')+'</span></div>'
      +'<nav class="xumo-account-links"><a href="/account.html" role="menuitem">'+icon('user')+'<span>'+(isOwner?'数据与存档管理':'个人资料与账号安全')+'</span></a><a href="/account.html#data" role="menuitem">'+icon('settings')+'<span>数据导出、导入与快照</span></a><button class="xumo-account-logout" type="button" role="menuitem">'+icon('logout')+'<span>退出登录</span></button></nav></section><span class="xumo-account-live" aria-live="polite"></span>';
    document.body.appendChild(shell);
    document.body.classList.add('xumo-account-ready');
    function syncTriggerWidth(){
      var width=Math.ceil(shell.querySelector('.xumo-account-trigger').getBoundingClientRect().width||44);
      document.documentElement.style.setProperty('--xumo-account-trigger-width',width+'px');
    }
    function syncHeaderClearance(){
      var mode=document.getElementById('xumoModeSw');
      if(!mode||window.innerWidth<=640){document.documentElement.style.removeProperty('--xumo-account-top');return;}
      var rect=mode.getBoundingClientRect();
      if(rect.height>0)document.documentElement.style.setProperty('--xumo-account-top',Math.ceil(rect.bottom+8)+'px');
    }
    syncTriggerWidth();
    syncHeaderClearance();
    if(window.ResizeObserver){try{new ResizeObserver(syncTriggerWidth).observe(shell);}catch(e){}}
    if(window.ResizeObserver){try{new ResizeObserver(syncHeaderClearance).observe(document.getElementById('xumoModeSw'));}catch(e){}}
    window.addEventListener('resize',syncHeaderClearance,{passive:true});
    var trigger=shell.querySelector('.xumo-account-trigger'),logout=shell.querySelector('.xumo-account-logout'),live=shell.querySelector('.xumo-account-live');
    trigger.addEventListener('click',function(){var open=shell.dataset.open!=='true';shell.dataset.open=String(open);trigger.setAttribute('aria-expanded',String(open));if(open)setTimeout(function(){shell.querySelector('[role="menuitem"]').focus();},0);});
    document.addEventListener('click',function(e){if(!shell.contains(e.target))close(shell,trigger);});
    document.addEventListener('keydown',function(e){if(e.key==='Escape'&&shell.dataset.open==='true'){close(shell,trigger);trigger.focus();}});
    logout.addEventListener('click',async function(){logout.disabled=true;logout.querySelector('span').textContent='正在退出…';live.textContent='正在退出登录';try{await fetch('/api/auth/logout',{method:'POST',credentials:'include'});}finally{location.href='/';}});
  }
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',start);else start();
})();
