(function(){
  'use strict';
  if(window.XumoFreeCanvas) return;

  var ICONS = {
    edit:'<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 20h4L19 9l-4-4L4 16v4Z"/><path d="m13.5 6.5 4 4"/></svg>',
    plus:'<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 5v14M5 12h14"/></svg>',
    reset:'<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 12a8 8 0 1 0 2.34-5.66L4 8.68"/><path d="M4 4v4.68h4.68"/></svg>',
    check:'<svg viewBox="0 0 24 24" aria-hidden="true"><path d="m5 12 4 4L19 6"/></svg>',
    arrange:'<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="3" y="4" width="7" height="6" rx="1"/><rect x="14" y="4" width="7" height="6" rx="1"/><rect x="3" y="14" width="7" height="6" rx="1"/><rect x="14" y="14" width="7" height="6" rx="1"/></svg>',
    trash:'<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 7h16M9 7V4h6v3m3 0-1 13H7L6 7"/><path d="M10 11v5M14 11v5"/></svg>',
    resize:'<svg viewBox="0 0 24 24" aria-hidden="true"><path d="m8 16 8-8M12 16h4v-4"/></svg>'
  };
  var MODE = null, active = null, zTop = 40, saveTimer = null;
  var defaults = {a:{},k:{}}, custom = {a:{},k:{}};
  var storeKeys = {a:'xumo_free_canvas_a_v3',k:'xumo_free_canvas_k_v2'};

  function $(id){ return document.getElementById(id); }
  function clamp(n,min,max){ return Math.max(min,Math.min(max,n)); }
  function esc(s){ return String(s==null?'':s).replace(/[&<>"']/g,function(c){return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c];}); }
  function read(mode){ try{return JSON.parse(localStorage.getItem(storeKeys[mode])||'{}')||{};}catch(e){return {};} }
  function write(mode,data){ try{localStorage.setItem(storeKeys[mode],JSON.stringify(data));}catch(e){} }
  function state(mode){ var s=read(mode); if(!s.items)s.items={}; if(!s.custom)s.custom={}; return s; }
  function currentMode(){ var m=(document.body.className.match(/mode-([a-z])/)||[])[1]; return m==='a'||m==='k'?m:null; }
  function root(mode){ return mode==='a'?$('xumoHomeA'):$('xumoHomeK'); }
  function isNarrowViewport(){ return !!(window.matchMedia&&window.matchMedia('(max-width:760px)').matches); }
  function pct(n){ return (Math.round(n*1000)/1000)+'%'; }
  function toast(msg){ if(typeof window.showToast==='function')window.showToast(msg); }

  function register(mode,el,id,label,def,opts){
    if(!el||!id)return;
    opts=opts||{};
    var shell=el.classList.contains('xfc-item')?el:(el.parentElement&&el.parentElement.classList.contains('xfc-item')?el.parentElement:null);
    if(!shell){
      shell=document.createElement('div');
      shell.className='xfc-item';
      el.parentNode.insertBefore(shell,el);
      shell.appendChild(el);
      el.classList.add('xfc-content');
    }
    shell.setAttribute('data-xfc-id',id);
    shell.setAttribute('data-xfc-mode',mode);
    shell.setAttribute('data-xfc-label',label||id);
    if(opts.dynamic)shell.setAttribute('data-xfc-dynamic',opts.dynamic);
    defaults[mode][id]=def;
    if(!shell.querySelector(':scope > .xfc-item-tools')){
      var tools=document.createElement('span'); tools.className='xfc-item-tools';
      tools.innerHTML='<button type="button" class="xfc-item-tool xfc-delete" aria-label="删除 '+esc(label)+'" title="删除">'+ICONS.trash+'</button>';
      var resize=document.createElement('span'); resize.className='xfc-resize'; resize.setAttribute('role','button'); resize.setAttribute('aria-label','缩放 '+label); resize.tabIndex=0; resize.innerHTML=ICONS.resize;
      var name=document.createElement('span'); name.className='xfc-item-name'; name.textContent=label;
      shell.appendChild(tools); shell.appendChild(resize); shell.appendChild(name);
    }
    shell.tabIndex=0;
    bindItem(shell);
    applyOne(mode,shell);
    return shell;
  }

  function applyOne(mode,el){
    var id=el.getAttribute('data-xfc-id'), s=state(mode), d=defaults[mode][id]||{x:10,y:10,w:15,h:12,z:5}, p=s.items[id]||{};
    var v={x:p.x!=null?p.x:d.x,y:p.y!=null?p.y:d.y,w:p.w!=null?p.w:d.w,h:p.h!=null?p.h:d.h,z:p.z!=null?p.z:(d.z||5),rot:p.rot!=null?p.rot:(d.rot||0)};
    el.style.setProperty('--xfc-x',pct(v.x));el.style.setProperty('--xfc-y',pct(v.y));el.style.setProperty('--xfc-w',pct(v.w));el.style.setProperty('--xfc-h',pct(v.h));el.style.setProperty('--xfc-z',v.z);el.style.setProperty('--xfc-rot',v.rot+'deg');
    el.classList.toggle('xfc-hidden',!!p.hidden);
    zTop=Math.max(zTop,+v.z||5);
  }
  function applyAll(mode){ var r=root(mode); if(!r)return; r.querySelectorAll('.xfc-item[data-xfc-mode="'+mode+'"]').forEach(function(el){applyOne(mode,el);}); }
  function itemValues(el){ return {x:parseFloat(el.style.getPropertyValue('--xfc-x'))||0,y:parseFloat(el.style.getPropertyValue('--xfc-y'))||0,w:parseFloat(el.style.getPropertyValue('--xfc-w'))||10,h:parseFloat(el.style.getPropertyValue('--xfc-h'))||10,z:parseFloat(el.style.getPropertyValue('--xfc-z'))||5,rot:parseFloat(el.style.getPropertyValue('--xfc-rot'))||0}; }
  function persist(el,hidden){
    var mode=el.getAttribute('data-xfc-mode'),id=el.getAttribute('data-xfc-id'),s=state(mode),v=itemValues(el);
    if(hidden!=null)v.hidden=hidden; else if(s.items[id]&&s.items[id].hidden)v.hidden=true;
    s.items[id]=v; write(mode,s);
  }
  function queuePersist(el){ clearTimeout(saveTimer); saveTimer=setTimeout(function(){persist(el);},80); }

  function bindItem(el){
    if(el.__xfcBound)return; el.__xfcBound=true;
    el.addEventListener('click',function(e){
      if(!document.body.classList.contains('xfc-edit'))return;
      e.preventDefault();e.stopPropagation();
      if(e.target.closest('.xfc-delete')){ hideItem(el); return; }
      select(el);
    },true);
    el.addEventListener('keydown',function(e){
      if(!document.body.classList.contains('xfc-edit'))return;
      if(e.key==='Delete'||e.key==='Backspace'){e.preventDefault();hideItem(el);return;}
      var dx=0,dy=0,step=e.shiftKey?2:0.3,isResizeKey=!!(e.altKey||e.target.closest('.xfc-resize'));
      if(e.key==='ArrowLeft')dx=-step;else if(e.key==='ArrowRight')dx=step;else if(e.key==='ArrowUp')dy=-step;else if(e.key==='ArrowDown')dy=step;else return;
      e.preventDefault();var v=itemValues(el);
      if(isResizeKey){v.w=clamp(v.w+dx,4,100-v.x);v.h=clamp(v.h+dy,4,100-v.y);}else{v.x=clamp(v.x+dx,0,100-v.w);v.y=clamp(v.y+dy,0,100-v.h);}
      setValues(el,v);persist(el);
    });
    el.addEventListener('pointerdown',function(e){
      if(!document.body.classList.contains('xfc-edit')||e.button!==0)return;
      if(e.target.closest('.xfc-delete'))return;
      e.preventDefault();e.stopPropagation();select(el);
      var isResize=!!e.target.closest('.xfc-resize'), r=root(el.getAttribute('data-xfc-mode')).getBoundingClientRect(), v=itemValues(el);
      active={el:el,id:e.pointerId,resize:isResize,sx:e.clientX,sy:e.clientY,base:v,rect:r};
      el.setPointerCapture(e.pointerId);el.classList.add('xfc-active');
    },true);
    el.addEventListener('pointermove',function(e){
      if(!active||active.el!==el||active.id!==e.pointerId)return;
      e.preventDefault();var dx=(e.clientX-active.sx)/active.rect.width*100,dy=(e.clientY-active.sy)/active.rect.height*100,v=Object.assign({},active.base);
      if(active.resize){v.w=clamp(v.w+dx,4,100-v.x);v.h=clamp(v.h+dy,4,100-v.y);}else{v.x=clamp(v.x+dx,0,100-v.w);v.y=clamp(v.y+dy,0,100-v.h);}
      setValues(el,v);queuePersist(el);
    },true);
    function end(e){if(!active||active.el!==el)return;try{el.releasePointerCapture(active.id);}catch(err){}el.classList.remove('xfc-active');persist(el);active=null;}
    el.addEventListener('pointerup',end,true);el.addEventListener('pointercancel',end,true);
  }
  function setValues(el,v){el.style.setProperty('--xfc-x',pct(v.x));el.style.setProperty('--xfc-y',pct(v.y));el.style.setProperty('--xfc-w',pct(v.w));el.style.setProperty('--xfc-h',pct(v.h));if(v.z!=null)el.style.setProperty('--xfc-z',v.z);}
  function select(el){ document.querySelectorAll('.xfc-item.xfc-active').forEach(function(x){if(x!==el)x.classList.remove('xfc-active');}); zTop++;el.style.setProperty('--xfc-z',zTop);queuePersist(el); }
  function hideItem(el){ el.classList.add('xfc-hidden');persist(el,true);renderAddPanel();toast('已从面板移除，可在“添加”中恢复'); }

  function moveChild(parent,child){ if(child&&child.parentElement!==parent)parent.appendChild(child); }
  function prepareA(){
    if(isNarrowViewport())return;
    var home=$('xumoHomeA');if(!home)return;
    var compact=window.matchMedia&&window.matchMedia('(max-width:1020px)').matches;
    var layout=compact?{
      dashboard:{x:2,y:6,w:35,h:86,z:18},character:{x:39,y:9,w:49,h:88,z:2},actions:{x:40,y:84,w:56,h:10,z:20}
    }:{
      dashboard:{x:1.7,y:6,w:25,h:88,z:18},character:{x:33,y:7,w:39,h:91,z:2},actions:{x:31,y:86,w:43,h:10,z:20}
    };
    register('a',home.querySelector('.xa-char'),'character','许墨立绘',layout.character);
    register('a',$('uiImmersivePanel'),'dashboard','共生仪表盘',layout.dashboard);
    register('a',home.querySelector('.xa-actions'),'actions','快捷操作栏',layout.actions);
    restoreCustom('a');applyAll('a');
  }

  function prepareK(){
    if(isNarrowViewport())return;
    var home=$('xumoHomeK'),desk=home&&home.querySelector('.xk-desk');if(!desk)return;
    var header=desk.querySelector('.xk-header');
    if(header){Array.from(header.children).forEach(function(x){x.classList.add('xk-header-piece');moveChild(desk,x);});header.remove();}
    var decor=desk.querySelector('.xk-decor');if(decor){Array.from(decor.children).forEach(function(x){moveChild(desk,x);});decor.remove();}
    var paperBox=$('xkPapers');if(paperBox){Array.from(paperBox.querySelectorAll('.xk-paper')).forEach(function(p){p.setAttribute('data-xfc-dynamic','paper');moveChild(desk,p);});}
    register('k',$('xkLamp'),'lamp','台灯',{x:86,y:3,w:11,h:12,z:5});
    register('k',desk.querySelector('.xk-pen-stand'),'pen-stand','笔与墨水',{x:3,y:4,w:6,h:9,z:4});
    register('k',$('xkDate'),'date','日期',{x:33,y:4,w:16,h:5,z:5});
    register('k',$('xkWeather'),'weather','今日句子',{x:50,y:4,w:20,h:5,z:5});
    register('k',$('xkMood'),'mood','心情',{x:71,y:4,w:12,h:5,z:5});
    register('k',$('xkSticky'),'sticky','今日便签',{x:39,y:15,w:22,h:18,z:8,rot:-1});
    register('k',$('xkBook'),'book','全部应用',{x:92,y:87,w:5,h:8,z:8});
    register('k',desk.querySelector('.xk-decor-pin1'),'decor:pin1','红色图钉',{x:25,y:25,w:1,h:1.7,z:3});
    register('k',desk.querySelector('.xk-decor-pin2'),'decor:pin2','红色图钉',{x:69,y:80,w:1,h:1.7,z:3});
    register('k',desk.querySelector('.xk-decor-clip'),'decor:clip','回形夹',{x:77,y:28,w:2,h:5,z:3});
    register('k',desk.querySelector('.xk-decor-coffee'),'decor:coffee','咖啡渍',{x:35,y:81,w:5,h:6,z:2});
    var papers=Array.from(desk.querySelectorAll('.xk-paper[data-app]'));
    papers.forEach(function(p,i){var key=p.getAttribute('data-app'),row=Math.floor(i/5),col=i%5;register('k',p,'paper:'+key,(p.querySelector('.xk-paper-label')||{}).textContent||key,{x:4+col*18,y:38+row*22,w:13,h:13,z:5,rot:(i%3-1)*4},{dynamic:'paper'});});
    restoreCustom('k');applyAll('k');
  }

  function appMeta(){
    var out={};document.querySelectorAll('#iconGrid .app-icon[data-app],.dock .app-icon[data-app]').forEach(function(el){var k=el.getAttribute('data-app');if(out[k])return;var l=el.querySelector('.label'),g=el.querySelector('.glyph');out[k]={key:k,label:(l&&l.textContent.trim())||k,glyph:g?g.innerHTML:'<span>□</span>'};});return out;
  }
  function addApp(mode,key,label,glyph,id){
    var r=root(mode),s=state(mode),itemId=id||('app:'+key),el;
    if(mode==='a'){
      el=document.createElement('button');el.type='button';el.className='xa-action xfc-added-app';el.setAttribute('data-app',key);el.innerHTML='<i>'+glyph+'</i><span>'+esc(label)+'</span>';
      r.appendChild(el);el=register(mode,el,itemId,label,{x:45,y:45,w:9,h:12,z:++zTop},{dynamic:'app'});
    }else{
      el=document.createElement('div');el.className='xk-paper xk-paper-grid xfc-added-app';el.setAttribute('data-app',key);el.style.background='#F4E9D8';el.innerHTML='<div class="xk-paper-icon">'+glyph+'</div><div class="xk-paper-label">'+esc(label)+'</div><div class="xk-paper-cat">自定义</div>';
      el.addEventListener('dblclick',function(){if(!document.body.classList.contains('xfc-edit')&&window.openApp)window.openApp(key);});
      r.querySelector('.xk-desk').appendChild(el);el=register(mode,el,itemId,label,{x:43,y:43,w:14,h:13,z:++zTop},{dynamic:'app'});
    }
    s.custom[itemId]={type:'app',key:key,label:label,glyph:glyph};s.items[itemId]=itemValues(el);write(mode,s);select(el);return el;
  }
  function addText(mode,text,id){
    var host=mode==='a'?root(mode):root(mode).querySelector('.xk-desk'),el=document.createElement('div'),itemId=id||('text:'+Date.now());
    el.className='xfc-custom-text';el.textContent=text;host.appendChild(el);el=register(mode,el,itemId,'自定义文字',{x:38,y:36,w:24,h:10,z:++zTop},{dynamic:'text'});
    var s=state(mode);s.custom[itemId]={type:'text',text:text,label:'自定义文字'};s.items[itemId]=itemValues(el);write(mode,s);select(el);return el;
  }
  function restoreCustom(mode){
    var s=state(mode),r=root(mode);Object.keys(s.custom).forEach(function(id){if(r.querySelector('[data-xfc-id="'+CSS.escape(id)+'"]'))return;var c=s.custom[id];if(c.type==='app')addApp(mode,c.key,c.label,c.glyph,id);else if(c.type==='text')addText(mode,c.text,id);});
  }

  function renderAddPanel(){
    if(!MODE)return;var r=root(MODE),s=state(MODE),cards=[];
    r.querySelectorAll('.xfc-item.xfc-hidden').forEach(function(el){cards.push('<button type="button" class="xfc-add-card" data-restore="'+esc(el.getAttribute('data-xfc-id'))+'"><span class="xfc-app-glyph">'+ICONS.plus+'</span>'+esc(el.getAttribute('data-xfc-label'))+'</button>');});
    var apps=appMeta(),present={};r.querySelectorAll('[data-app]').forEach(function(x){present[x.getAttribute('data-app')]=true;});
    Object.keys(apps).filter(function(k){return !present[k];}).slice(0,36).forEach(function(k){var a=apps[k];cards.push('<button type="button" class="xfc-add-card" data-add-app="'+esc(k)+'"><span class="xfc-app-glyph">'+a.glyph+'</span>'+esc(a.label)+'</button>');});
    $('xfcAddGrid').innerHTML=cards.join('')||'<div class="xfc-add-empty">当前没有可添加的组件</div>';
  }
  function openAdd(){renderAddPanel();$('xfcAddPanel').classList.add('open');setTimeout(function(){$('xfcCustomText').focus();},30);}
  function closeAdd(){$('xfcAddPanel').classList.remove('open');}
  function enterEdit(){if(isNarrowViewport()){toast('手机端使用紧凑布局，请在平板或电脑上自定义面板');return;}MODE=currentMode();if(!MODE)return;document.body.classList.add('xfc-edit');prepare(MODE);closeAdd();toast('拖动组件改变位置，拖右下角调整大小');}
  function leaveEdit(){document.body.classList.remove('xfc-edit');closeAdd();active=null;MODE=null;}
  function resetMode(){if(!MODE)return;if(!window.confirm('恢复当前面板的默认布局？自定义添加的组件也会移除。'))return;localStorage.removeItem(storeKeys[MODE]);root(MODE).querySelectorAll('[data-xfc-dynamic="app"],[data-xfc-dynamic="text"]').forEach(function(x){x.remove();});if(MODE==='k'&&originalRenderK){originalRenderK();setTimeout(prepareK,0);}else{prepare(MODE);}toast('已恢复默认布局');}
  function arrangeMode(){
    if(!MODE)return;
    var s=state(MODE),r=root(MODE),customItems=[];
    Object.keys(s.items).forEach(function(id){if(!s.custom[id])delete s.items[id];});
    r.querySelectorAll('.xfc-item[data-xfc-mode="'+MODE+'"]').forEach(function(el){if(s.custom[el.getAttribute('data-xfc-id')])customItems.push(el);});
    customItems.forEach(function(el,index){
      var id=el.getAttribute('data-xfc-id'),col=index%3,row=Math.floor(index/3);
      s.items[id]={x:MODE==='a'?74+col*8:68+col*9,y:MODE==='a'?12+row*12:14+row*14,w:MODE==='a'?7:8,h:MODE==='a'?10:12,z:30+index,rot:0};
    });
    write(MODE,s);prepare(MODE);applyAll(MODE);toast('已按当前屏幕自动排列');
  }
  function prepare(mode){if(isNarrowViewport())return;if(mode==='a')prepareA();else if(mode==='k')prepareK();}

  function buildUI(){
    var toggle=document.createElement('button');toggle.id='xfcEditToggle';toggle.type='button';toggle.setAttribute('aria-label','自定义面板布局');toggle.innerHTML=ICONS.edit+'<span>自定义布局</span>';
    var bar=document.createElement('div');bar.className='xfc-toolbar';bar.setAttribute('role','toolbar');bar.setAttribute('aria-label','布局编辑工具');bar.innerHTML='<button type="button" data-xfc="add">'+ICONS.plus+'<span>添加</span></button><button type="button" data-xfc="arrange">'+ICONS.arrange+'<span>自动排列</span></button><button type="button" data-xfc="reset">'+ICONS.reset+'<span>恢复默认</span></button><button type="button" class="xfc-done" data-xfc="done">'+ICONS.check+'<span>完成</span></button>';
    var panel=document.createElement('section');panel.id='xfcAddPanel';panel.className='xfc-add-panel';panel.setAttribute('aria-label','添加组件');panel.innerHTML='<div class="xfc-add-head"><strong>添加组件<span>已删除的内容与其他应用都可以重新放回面板</span></strong><button type="button" class="xfc-add-close" aria-label="关闭">×</button></div><div class="xfc-add-grid" id="xfcAddGrid"></div><div class="xfc-add-custom"><input id="xfcCustomText" maxlength="80" placeholder="输入一段自定义文字"><button type="button" id="xfcAddText">添加文字</button></div>';
    document.body.appendChild(toggle);document.body.appendChild(bar);document.body.appendChild(panel);
    toggle.addEventListener('click',enterEdit);
    bar.addEventListener('click',function(e){var b=e.target.closest('[data-xfc]');if(!b)return;var a=b.getAttribute('data-xfc');if(a==='add')openAdd();else if(a==='arrange')arrangeMode();else if(a==='reset')resetMode();else if(a==='done')leaveEdit();});
    panel.addEventListener('click',function(e){
      if(e.target.closest('.xfc-add-close')){closeAdd();return;}
      var restore=e.target.closest('[data-restore]');if(restore){var el=root(MODE).querySelector('[data-xfc-id="'+CSS.escape(restore.getAttribute('data-restore'))+'"]');if(el){el.classList.remove('xfc-hidden');persist(el,false);select(el);renderAddPanel();}return;}
      var app=e.target.closest('[data-add-app]');if(app){var k=app.getAttribute('data-add-app'),m=appMeta()[k];if(m){addApp(MODE,k,m.label,m.glyph);renderAddPanel();}return;}
    });
    $('xfcAddText').addEventListener('click',function(){var inp=$('xfcCustomText'),v=inp.value.trim();if(!v)return;addText(MODE,v);inp.value='';closeAdd();});
    $('xfcCustomText').addEventListener('keydown',function(e){if(e.key==='Enter')$('xfcAddText').click();});
    document.addEventListener('keydown',function(e){if(e.key==='Escape'){if($('xfcAddPanel').classList.contains('open'))closeAdd();else if(document.body.classList.contains('xfc-edit'))leaveEdit();}});
  }

  var originalRenderK=null;
  function wrapK(){
    if(window.xumoRenderK&&window.xumoRenderK.__xfcWrapped)return;
    if(window.xumoRenderK){originalRenderK=window.xumoRenderK;window.xumoRenderK=function(){var desk=$('xumoHomeK')&&$('xumoHomeK').querySelector('.xk-desk');if(desk)desk.querySelectorAll('[data-xfc-dynamic="paper"]').forEach(function(x){x.remove();});var out=originalRenderK.apply(this,arguments);setTimeout(prepareK,0);return out;};window.xumoRenderK.__xfcWrapped=true;}
  }
  function init(){buildUI();wrapK();setTimeout(function(){prepareA();prepareK();},120);new MutationObserver(function(){var m=currentMode();if(m){setTimeout(function(){prepare(m);},60);}else if(document.body.classList.contains('xfc-edit'))leaveEdit();}).observe(document.body,{attributes:true,attributeFilter:['class']});}
  window.XumoFreeCanvas={prepare:prepare,edit:enterEdit,done:leaveEdit,reset:resetMode};
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',init);else init();
})();
