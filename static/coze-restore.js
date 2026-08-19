/* Selectively restored from the Coze project archive. */
(function(){
  'use strict';
  if(window.__cozeRestoreLoaded) return;
  window.__cozeRestoreLoaded = true;

  var restoredStyle = document.createElement('style');
  restoredStyle.id = 'cozeRestoreStyle';
  restoredStyle.textContent = [
    '.xa-dash{position:absolute;top:8%;left:50%;transform:translateX(-50%);z-index:2;display:flex;flex-direction:column;align-items:center;gap:18px;width:92%;max-width:520px}',
    /* 每日一言 */
    '.xa-quote{width:100%;text-align:center;padding:14px 22px;border-radius:16px;background:linear-gradient(135deg,rgba(255,255,255,.12),rgba(255,255,255,.04));backdrop-filter:blur(16px);-webkit-backdrop-filter:blur(16px);border:1px solid rgba(255,255,255,.13);color:rgba(255,255,255,.75);font-size:13.5px;line-height:1.7;opacity:0;animation:xaFadeIn 1.5s .5s forwards;box-shadow:0 4px 24px rgba(0,0,0,.15)}',
    '.xa-quote em{display:block;margin-top:6px;font-style:normal;font-size:11px;color:rgba(255,255,255,.4)}',
    '@keyframes xaFadeIn{to{opacity:1}}',
    '@keyframes xaPulse{0%,100%{box-shadow:0 0 8px rgba(255,255,255,.1)}50%{box-shadow:0 0 20px rgba(255,255,255,.18)}}',
    '@keyframes xaShimmer{0%{background-position:-200% 0}100%{background-position:200% 0}}',
    /* 主指标行：3 大卡片 */
    '.xa-main{display:flex;gap:14px;width:100%;justify-content:center}',
    '.xa-main-card{flex:1;max-width:160px;display:flex;flex-direction:column;align-items:center;gap:6px;padding:18px 14px 14px;border-radius:20px;background:linear-gradient(160deg,rgba(255,255,255,.14),rgba(255,255,255,.04));backdrop-filter:blur(16px);-webkit-backdrop-filter:blur(16px);border:1px solid rgba(255,255,255,.15);cursor:default;transition:all .4s;box-shadow:0 4px 20px rgba(0,0,0,.12);position:relative;overflow:hidden}',
    '.xa-main-card:hover{transform:translateY(-4px) scale(1.03);box-shadow:0 8px 32px rgba(0,0,0,.2)}',
    '.xa-main-card::before{content:"";position:absolute;top:0;left:0;right:0;height:3px;border-radius:20px 20px 0 0}',
    '.xa-main-card.c-pink::before{background:linear-gradient(90deg,#f472b6,#ec4899)}',
    '.xa-main-card.c-green::before{background:linear-gradient(90deg,#34d399,#10b981)}',
    '.xa-main-card.c-gold::before{background:linear-gradient(90deg,#fbbf24,#f59e0b)}',
    /* 大环形进度 */
    '.xa-lg-ring{width:100px;height:100px;position:relative}',
    '.xa-lg-ring svg{width:100%;height:100%;transform:rotate(-90deg)}',
    '.xa-lg-ring-bg{fill:none;stroke:rgba(255,255,255,.1);stroke-width:6}',
    '.xa-lg-ring-fg{fill:none;stroke-width:6;stroke-linecap:round;transition:stroke-dashoffset 1.2s cubic-bezier(.4,0,.2,1)}',
    '.xa-lg-ring-glow{fill:none;stroke-width:10;stroke-linecap:round;opacity:.2;filter:blur(4px);transition:stroke-dashoffset 1.2s cubic-bezier(.4,0,.2,1)}',
    '.xa-lg-ring-text{position:absolute;inset:0;display:flex;flex-direction:column;align-items:center;justify-content:center}',
    '.xa-lg-ring-val{font-size:22px;font-weight:800;color:#fff;text-shadow:0 2px 10px rgba(0,0,0,.3)}',
    '.xa-lg-ring-lbl{font-size:10px;color:rgba(255,255,255,.5);margin-top:1px}',
    '.xa-main-label{font-size:11.5px;color:rgba(255,255,255,.55);letter-spacing:.6px}',
    /* 副指标行：4 个中等卡片 */
    '.xa-sub{display:flex;gap:12px;width:100%;justify-content:center;flex-wrap:wrap}',
    '.xa-sub-card{flex:1;min-width:105px;max-width:125px;display:flex;flex-direction:column;align-items:center;gap:5px;padding:14px 10px 12px;border-radius:16px;backdrop-filter:blur(14px);-webkit-backdrop-filter:blur(14px);border:1px solid rgba(255,255,255,.1);cursor:default;transition:all .35s;position:relative;overflow:hidden}',
    '.xa-sub-card:hover{transform:translateY(-3px);border-color:rgba(255,255,255,.22)}',
    '.xa-sub-card.c-blue{background:linear-gradient(160deg,rgba(96,165,250,.18),rgba(96,165,250,.04))}',
    '.xa-sub-card.c-purple{background:linear-gradient(160deg,rgba(192,132,252,.18),rgba(192,132,252,.04))}',
    '.xa-sub-card.c-orange{background:linear-gradient(160deg,rgba(251,146,60,.18),rgba(251,146,60,.04))}',
    '.xa-sub-card.c-teal{background:linear-gradient(160deg,rgba(45,212,191,.18),rgba(45,212,191,.04))}',
    /* 中环形进度 */
    '.xa-md-ring{width:68px;height:68px;position:relative}',
    '.xa-md-ring svg{width:100%;height:100%;transform:rotate(-90deg)}',
    '.xa-md-ring-bg{fill:none;stroke:rgba(255,255,255,.1);stroke-width:5}',
    '.xa-md-ring-fg{fill:none;stroke-width:5;stroke-linecap:round;transition:stroke-dashoffset 1.2s cubic-bezier(.4,0,.2,1)}',
    '.xa-md-ring-text{position:absolute;inset:0;display:flex;flex-direction:column;align-items:center;justify-content:center}',
    '.xa-md-ring-val{font-size:16px;font-weight:700;color:#fff}',
    '.xa-md-ring-lbl{font-size:8px;color:rgba(255,255,255,.45)}',
    '.xa-sub-label{font-size:10px;color:rgba(255,255,255,.5);letter-spacing:.4px}',
    /* 底部条形指标行 */
    '.xa-bars{display:flex;flex-direction:column;gap:10px;width:100%}',
    '.xa-bar-row{display:flex;align-items:center;gap:12px;padding:12px 16px;border-radius:14px;background:rgba(255,255,255,.06);backdrop-filter:blur(10px);-webkit-backdrop-filter:blur(10px);border:1px solid rgba(255,255,255,.08);transition:all .3s}',
    '.xa-bar-row:hover{background:rgba(255,255,255,.1)}',
    '.xa-bar-icon{font-size:22px;width:30px;text-align:center}',
    '.xa-bar-info{display:flex;flex-direction:column;gap:3px;min-width:60px}',
    '.xa-bar-val{font-size:18px;font-weight:700;color:#fff}',
    '.xa-bar-label{font-size:9.5px;color:rgba(255,255,255,.45)}',
    '.xa-bar-track{flex:1;height:6px;border-radius:3px;background:rgba(255,255,255,.08);overflow:hidden}',
    '.xa-bar-fill{height:100%;border-radius:3px;transition:width 1.2s cubic-bezier(.4,0,.2,1);position:relative}',
    '.xa-bar-fill::after{content:"";position:absolute;inset:0;background:linear-gradient(90deg,transparent,rgba(255,255,255,.25),transparent);background-size:200% 100%;animation:xaShimmer 3s infinite}',

    'body.mode-a .chat-panel{display:none!important}',
    'body.mode-a .xa-dash{right:4vw;left:auto;transform:none;width:min(520px,42vw);max-height:78vh;overflow:auto;scrollbar-width:thin}',
    '#xaEditBar button{min-height:44px}',
    '#xumoHomeA .xa-widget:focus-visible,#xaEditBar button:focus-visible{outline:3px solid rgba(255,255,255,.9);outline-offset:3px}',
    '@media(max-width:1020px){body.mode-a .xa-dash{top:calc(62px + env(safe-area-inset-top));right:auto;left:50%;transform:translateX(-50%);width:min(94vw,520px);max-height:calc(100vh - 150px);padding-bottom:calc(18px + env(safe-area-inset-bottom))}}',
    '@media(prefers-reduced-motion:reduce){body.mode-a .xa-dash *,#xaEditBar *{animation:none!important;transition:none!important}}'
  ].join('\n');
  document.head.appendChild(restoredStyle);

  function installDashboard(){
    var homeA = document.getElementById('xumoHomeA');
    if(!homeA){ setTimeout(installDashboard, 250); return; }
    var chatAction = homeA.querySelector('.xa-actions [data-act="chat"]');
    if(chatAction) chatAction.remove();
    var actions = homeA.querySelector('.xa-actions');
    if(actions && !actions.querySelector('[data-act="edit"]')){
      var editButton = document.createElement('button');
      editButton.type = 'button';
      editButton.setAttribute('data-act', 'edit');
      editButton.setAttribute('aria-label', '编辑沉浸布局');
      editButton.setAttribute('aria-pressed', 'false');
      editButton.title = '编辑布局';
      editButton.innerHTML = '<i aria-hidden="true">✏️</i><span>编辑</span>';
      editButton.addEventListener('click', function(event){
        event.stopPropagation();
        var editing = document.body.classList.toggle('xa-edit');
        editButton.setAttribute('aria-pressed', editing ? 'true' : 'false');
      });
      actions.appendChild(editButton);
    }
    if(document.getElementById('xaDash')) return;
    var dashboardHost = document.createElement('div');
    dashboardHost.innerHTML =
    '<div class="xa-dash xa-draggable" id="xaDash">' +
    '<div class="xa-quote" id="xaQuote"></div>' +
    '<div class="xa-main">' +
      '<div class="xa-main-card c-pink" title="相伴天数">' +
        '<div class="xa-lg-ring"><svg viewBox="0 0 100 100"><circle class="xa-lg-ring-bg" cx="50" cy="50" r="42"/><circle class="xa-lg-ring-glow" id="xaGlowDays" cx="50" cy="50" r="42" stroke="#f472b6" stroke-dasharray="263.9" stroke-dashoffset="263.9"/><circle class="xa-lg-ring-fg" id="xaRingDays" cx="50" cy="50" r="42" stroke="#f472b6" stroke-dasharray="263.9" stroke-dashoffset="263.9"/></svg><div class="xa-lg-ring-text"><span class="xa-lg-ring-val" id="xaDays">0</span><span class="xa-lg-ring-lbl">天</span></div></div>' +
        '<span class="xa-main-label">相伴时光</span>' +
      '</div>' +
      '<div class="xa-main-card c-green" title="世界活力">' +
        '<div class="xa-lg-ring"><svg viewBox="0 0 100 100"><circle class="xa-lg-ring-bg" cx="50" cy="50" r="42"/><circle class="xa-lg-ring-glow" id="xaGlowVitality" cx="50" cy="50" r="42" stroke="#34d399" stroke-dasharray="263.9" stroke-dashoffset="263.9"/><circle class="xa-lg-ring-fg" id="xaRingVitality" cx="50" cy="50" r="42" stroke="#34d399" stroke-dasharray="263.9" stroke-dashoffset="263.9"/></svg><div class="xa-lg-ring-text"><span class="xa-lg-ring-val" id="xaVitality">0</span><span class="xa-lg-ring-lbl">%</span></div></div>' +
        '<span class="xa-main-label">世界活力</span>' +
      '</div>' +
      '<div class="xa-main-card c-gold" title="成就等级">' +
        '<div class="xa-lg-ring"><svg viewBox="0 0 100 100"><circle class="xa-lg-ring-bg" cx="50" cy="50" r="42"/><circle class="xa-lg-ring-glow" id="xaGlowLevel" cx="50" cy="50" r="42" stroke="#fbbf24" stroke-dasharray="263.9" stroke-dashoffset="263.9"/><circle class="xa-lg-ring-fg" id="xaRingLevel" cx="50" cy="50" r="42" stroke="#fbbf24" stroke-dasharray="263.9" stroke-dashoffset="263.9"/></svg><div class="xa-lg-ring-text"><span class="xa-lg-ring-val" id="xaLevel">0</span><span class="xa-lg-ring-lbl">Lv</span></div></div>' +
        '<span class="xa-main-label">探索等级</span>' +
      '</div>' +
    '</div>' +
    '<div class="xa-sub">' +
      '<div class="xa-sub-card c-blue" title="连续签到">' +
        '<div class="xa-md-ring"><svg viewBox="0 0 68 68"><circle class="xa-md-ring-bg" cx="34" cy="34" r="28"/><circle class="xa-md-ring-fg" id="xaRingStreak" cx="34" cy="34" r="28" stroke="#60a5fa" stroke-dasharray="175.9" stroke-dashoffset="175.9"/></svg><div class="xa-md-ring-text"><span class="xa-md-ring-val" id="xaStreak">0</span><span class="xa-md-ring-lbl">天</span></div></div>' +
        '<span class="xa-sub-label">签到连击</span>' +
      '</div>' +
      '<div class="xa-sub-card c-purple" title="经验值">' +
        '<div class="xa-md-ring"><svg viewBox="0 0 68 68"><circle class="xa-md-ring-bg" cx="34" cy="34" r="28"/><circle class="xa-md-ring-fg" id="xaRingXP" cx="34" cy="34" r="28" stroke="#c084fc" stroke-dasharray="175.9" stroke-dashoffset="175.9"/></svg><div class="xa-md-ring-text"><span class="xa-md-ring-val" id="xaXP">0</span><span class="xa-md-ring-lbl">XP</span></div></div>' +
        '<span class="xa-sub-label">经验积累</span>' +
      '</div>' +
      '<div class="xa-sub-card c-orange" title="专注时长">' +
        '<div class="xa-md-ring"><svg viewBox="0 0 68 68"><circle class="xa-md-ring-bg" cx="34" cy="34" r="28"/><circle class="xa-md-ring-fg" id="xaRingFocus" cx="34" cy="34" r="28" stroke="#fb923c" stroke-dasharray="175.9" stroke-dashoffset="175.9"/></svg><div class="xa-md-ring-text"><span class="xa-md-ring-val" id="xaFocus">0</span><span class="xa-md-ring-lbl">分</span></div></div>' +
        '<span class="xa-sub-label">专注时刻</span>' +
      '</div>' +
      '<div class="xa-sub-card c-teal" title="成就解锁">' +
        '<div class="xa-md-ring"><svg viewBox="0 0 68 68"><circle class="xa-md-ring-bg" cx="34" cy="34" r="28"/><circle class="xa-md-ring-fg" id="xaRingAchv" cx="34" cy="34" r="28" stroke="#2dd4bf" stroke-dasharray="175.9" stroke-dashoffset="175.9"/></svg><div class="xa-md-ring-text"><span class="xa-md-ring-val" id="xaAchv">0</span><span class="xa-md-ring-lbl">项</span></div></div>' +
        '<span class="xa-sub-label">成就收藏</span>' +
      '</div>' +
    '</div>' +
    '<div class="xa-bars">' +
      '<div class="xa-bar-row">' +
        '<span class="xa-bar-icon">📐</span>' +
        '<div class="xa-bar-info"><span class="xa-bar-val" id="xaStudy">0</span><span class="xa-bar-label">解题数</span></div>' +
        '<div class="xa-bar-track"><div class="xa-bar-fill" id="xaStudyBar" style="width:0;background:linear-gradient(90deg,#60a5fa,#818cf8)"></div></div>' +
      '</div>' +
      '<div class="xa-bar-row">' +
        '<span class="xa-bar-icon">📝</span>' +
        '<div class="xa-bar-info"><span class="xa-bar-val" id="xaWork">0</span><span class="xa-bar-label">创作篇数</span></div>' +
        '<div class="xa-bar-track"><div class="xa-bar-fill" id="xaWorkBar" style="width:0;background:linear-gradient(90deg,#f472b6,#fb923c)"></div></div>' +
      '</div>' +
      '<div class="xa-bar-row">' +
        '<span class="xa-bar-icon">✨</span>' +
        '<div class="xa-bar-info"><span class="xa-bar-val" id="xaGen">0</span><span class="xa-bar-label">生成次数</span></div>' +
        '<div class="xa-bar-track"><div class="xa-bar-fill" id="xaGenBar" style="width:0;background:linear-gradient(90deg,#34d399,#fbbf24)"></div></div>' +
      '</div>' +
    '</div>' +
  '</div>';
    homeA.appendChild(dashboardHost.firstElementChild);
  }
  installDashboard();

(function(){
  if(window.__xumoLayoutEditorInited) return;
  window.__xumoLayoutEditorInited = true;

  /* ── 工具函数 ── */
  function ls(k,v){ try{ if(v===undefined){ var s=localStorage.getItem(k); return s?JSON.parse(s):null; } localStorage.setItem(k,JSON.stringify(v)); }catch(e){} }
  function curMode(){ var m=(document.body.className.match(/mode-([a-z])/)||[,'c'])[1]; return ('abcdefghjkl'.indexOf(m)>-1)?m:'c'; }
  function homeEl(){ return document.getElementById('xumoHome'+curMode().toUpperCase()); }

  /* ── DOM: 编辑栏 ── */
  var bar = document.createElement('div');
  bar.id = 'xaEditBar';
  bar.innerHTML = '<button type="button" data-xa="add-app">+ 应用</button>' +
    '<button type="button" data-xa="add-text">+ 文本</button>' +
    '<button type="button" data-xa="reset-layout">重置布局</button>' +
    '<button type="button" data-xa="close-edit" style="background:rgba(244,63,94,.25)">完成</button>';
  document.body.appendChild(bar);

  /* ── DOM: 添加面板 ── */
  var panel = document.createElement('div');
  panel.id = 'xaAddPanel';
  panel.innerHTML = '<h4>添加应用快捷方式</h4><div id="xaAddGrid"></div>' +
    '<h4 style="margin-top:12px">添加自定义文本</h4>' +
    '<div style="display:flex;gap:8px;margin-top:4px">' +
      '<input id="xaTextInput" type="text" placeholder="输入文本内容…" style="flex:1;background:rgba(255,255,255,.1);border:1px solid rgba(255,255,255,.2);border-radius:10px;padding:8px 12px;color:#fff;font-size:14px;outline:none;font-family:inherit">' +
      '<button id="xaTextAdd" type="button" style="border:none;background:rgba(139,92,246,.5);color:#fff;border-radius:10px;padding:8px 14px;cursor:pointer;font-family:inherit">添加</button>' +
    '</div>';
  document.body.appendChild(panel);

  /* ── 应用列表（复用主页面的 appList） ── */
  var appList = window.appList || [];

  function fillAddGrid(){
    var grid = document.getElementById('xaAddGrid');
    if(!grid) return;
    grid.innerHTML = '';
    appList.forEach(function(a){
      var b = document.createElement('button');
      b.type = 'button';
      b.setAttribute('data-xa-app', a.app);
      b.innerHTML = '<span style="font-size:20px">'+(a.icon||'📋')+'</span><span style="font-size:11px;margin-top:2px;display:block;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:72px">'+(a.name||a.app)+'</span>';
      b.style.cssText = 'border:none;background:rgba(255,255,255,.08);color:#fff;border-radius:12px;padding:10px 6px;cursor:pointer;display:flex;flex-direction:column;align-items:center;gap:2px;font-family:inherit;transition:background .15s';
      b.onmouseenter = function(){ this.style.background='rgba(255,255,255,.2)'; };
      b.onmouseleave = function(){ this.style.background='rgba(255,255,255,.08)'; };
      grid.appendChild(b);
    });
  }

  /* ── 编辑栏按钮事件 ── */
  bar.addEventListener('click', function(e){
    var b = e.target.closest('button[data-xa]');
    if(!b) return;
    var act = b.getAttribute('data-xa');
    if(act === 'add-app'){
      fillAddGrid();
      panel.classList.toggle('open');
    } else if(act === 'add-text'){
      var ti = document.getElementById('xaTextInput');
      if(ti) ti.focus();
      panel.classList.add('open');
    } else if(act === 'reset-layout'){
      var m = curMode();
      ls('xumo_layout_'+m, null);
      document.body.classList.remove('xa-edit');
      if(window.xumoApplyAll) window.xumoApplyAll();
    } else if(act === 'close-edit'){
      document.body.classList.remove('xa-edit');
      panel.classList.remove('open');
    }
  });

  /* ── 添加面板 - 应用快捷方式 ── */
  panel.addEventListener('click', function(e){
    var b = e.target.closest('button[data-xa-app]');
    if(!b) return;
    var appId = b.getAttribute('data-xa-app');
    var a = appList.find(function(x){ return x.app === appId; });
    if(!a) return;
    addWidget('app', {app: a.app, icon: a.icon||'📋', name: a.name||a.app});
    panel.classList.remove('open');
  });

  /* ── 添加面板 - 文本组件 ── */
  var textBtn = document.getElementById('xaTextAdd');
  if(textBtn) textBtn.addEventListener('click', function(){
    var ti = document.getElementById('xaTextInput');
    if(!ti || !ti.value.trim()) return;
    addWidget('text', {text: ti.value.trim()});
    ti.value = '';
    panel.classList.remove('open');
  });

  /* ── 添加组件到当前模式容器 ── */
  function addWidget(type, data){
    var home = homeEl();
    if(!home) return;
    var el = document.createElement('div');
    el.className = 'xa-widget' + (type === 'text' ? ' xa-widget-text' : '');
    el.setAttribute('data-xa-type', type);
    if(type === 'app'){
      el.innerHTML = '<i class="xa-wg">'+data.icon+'</i><span>'+data.name+'</span>';
      el.setAttribute('data-app', data.app);
      el.addEventListener('click', function(e){
        if(document.body.classList.contains('xa-edit')) return;
        if(window.openApp) window.openApp(data.app);
      });
    } else {
      el.innerHTML = '<div class="xa-txt">'+data.text+'</div>';
    }
    // 初始位置：视口中心附近随机
    var vw = window.innerWidth, vh = window.innerHeight;
    el.style.left = Math.round(vw*0.3 + Math.random()*vw*0.3) + 'px';
    el.style.top = Math.round(vh*0.3 + Math.random()*vh*0.3) + 'px';
    home.appendChild(el);
    addDelBtn(el);
    saveLayout();
  }

  /* ── 删除按钮 ── */
  function addDelBtn(el){
    var d = document.createElement('span');
    d.className = 'xa-del';
    d.textContent = '✕';
    d.addEventListener('click', function(e){
      e.stopPropagation();
      el.remove();
      saveLayout();
    });
    el.appendChild(d);
  }

  /* ── 拖动引擎（通用，支持鼠标+触摸） ── */
  var dragEl = null, dragSX = 0, dragSY = 0, dragPX = 0, dragPY = 0, dragMoved = false;

  function isEditable(){ return document.body.classList.contains('xa-edit'); }
  function dragTarget(t){
    // 优先匹配 xa-widget / xa-char / xa-draggable / xa-actions
    return t.closest('.xa-widget, .xa-char, .xa-card, .xa-actions, .xa-draggable');
  }
  function isNoDrag(t){ return t.closest('button, a, input, textarea, select, .xa-del, [data-no-drag]'); }

  function dragStart(e){
    if(!isEditable()) return;
    if(isNoDrag(e.target)) return;
    var t = dragTarget(e.target);
    if(!t) return;
    // 不拖动编辑按钮本身
    if(t.closest('[data-act="edit"]') || t.closest('[data-act="close-edit"]')) return;
    if(e.button !== undefined && e.button !== 0) return;
    dragEl = t;
    dragMoved = false;
    var p = e.touches ? e.touches[0] : e;
    dragSX = p.clientX; dragSY = p.clientY;
    var rect = t.getBoundingClientRect();
    // 切换为 fixed 定位以支持自由拖动
    t.style.position = 'fixed';
    t.style.left = rect.left + 'px';
    t.style.top = rect.top + 'px';
    t.style.right = 'auto';
    t.style.bottom = 'auto';
    t.style.margin = '0';
    t.style.zIndex = '60';
    dragPX = rect.left; dragPY = rect.top;
    t.classList.add('xa-dragging');
    if(e.cancelable) e.preventDefault();
  }

  function dragMove(e){
    if(!dragEl) return;
    var p = e.touches ? e.touches[0] : e;
    var dx = p.clientX - dragSX, dy = p.clientY - dragSY;
    if(Math.abs(dx) > 3 || Math.abs(dy) > 3) dragMoved = true;
    var nx = dragPX + dx, ny = dragPY + dy;
    var w = dragEl.offsetWidth, h = dragEl.offsetHeight;
    nx = Math.max(-w+60, Math.min(window.innerWidth-60, nx));
    ny = Math.max(0, Math.min(window.innerHeight-60, ny));
    dragEl.style.left = nx + 'px';
    dragEl.style.top = ny + 'px';
    if(e.cancelable) e.preventDefault();
  }

  function dragEnd(){
    if(!dragEl) return;
    dragEl.classList.remove('xa-dragging');
    dragEl.classList.add('xa-moved');
    dragEl = null;
    if(dragMoved) saveLayout();
  }

  document.addEventListener('mousedown', dragStart);
  document.addEventListener('mousemove', dragMove);
  document.addEventListener('mouseup', dragEnd);
  document.addEventListener('touchstart', dragStart, {passive:false});
  document.addEventListener('touchmove', dragMove, {passive:false});
  document.addEventListener('touchend', dragEnd);
  document.addEventListener('touchcancel', dragEnd);

  /* ── 点击 xa-actions 按钮上的删除标记 ── */
  document.addEventListener('click', function(e){
    if(!isEditable()) return;
    // 检查是否点击了按钮的伪元素删除区域（右上角红点）
    var btn = e.target.closest('.xa-actions button');
    if(!btn) return;
    var act = btn.getAttribute('data-act');
    if(act === 'edit' || act === 'close-edit') return;
    // 检查是否点击在按钮右上角区域
    var rect = btn.getBoundingClientRect();
    var x = e.clientX - rect.left, y = e.clientY - rect.top;
    if(x > rect.width - 22 && y < 22){
      e.stopPropagation();
      e.preventDefault();
      btn.remove();
      saveLayout();
    }
  }, true);

  /* ── 布局保存/加载 ── */
  function saveLayout(){
    var m = curMode();
    var home = document.getElementById('xumoHome'+m.toUpperCase());
    if(!home) return;
    var items = [];
    home.querySelectorAll('.xa-char, .xa-card, .xa-actions, .xa-widget, .xa-draggable').forEach(function(el){
      var info = {
        sel: getSelector(el, home),
        left: el.style.left || '',
        top: el.style.top || '',
        position: el.style.position || '',
        right: el.style.right || '',
        bottom: el.style.bottom || '',
        margin: el.style.margin || ''
      };
      if(el.classList.contains('xa-widget')){
        info.type = 'widget';
        info.xaType = el.getAttribute('data-xa-type') || '';
        if(info.xaType === 'app'){
          info.app = el.getAttribute('data-app') || '';
          info.icon = el.querySelector('.xa-wg') ? el.querySelector('.xa-wg').textContent : '';
          info.name = el.querySelector('span') ? el.querySelector('span').textContent : '';
        } else if(info.xaType === 'text'){
          info.text = el.querySelector('.xa-txt') ? el.querySelector('.xa-txt').textContent : '';
        }
      }
      info.moved = el.classList.contains('xa-moved');
      items.push(info);
    });
    ls('xumo_layout_'+m, items);
  }

  function getSelector(el, root){
    if(el === root) return '';
    var path = [];
    while(el && el !== root){
      var s = el.tagName.toLowerCase();
      if(el.id) s += '#'+el.id;
      else if(el.className){
        var cls = el.className.split(/\s+/).filter(function(c){ return c && c.indexOf('xa-')!==0 && c.indexOf('xumo-')!==0; });
        if(cls.length) s += '.'+cls.join('.');
      }
      path.unshift(s);
      el = el.parentElement;
    }
    return path.join('>');
  }

  /* ── xaApplyAll: 加载布局到当前模式 ── */
  window.xaApplyAll = function(){
    var m = curMode();
    var home = document.getElementById('xumoHome'+m.toUpperCase());
    if(!home) return;
    var items = ls('xumo_layout_'+m);
    if(!items) return;
    // 先清除旧的 widget（自定义组件）
    home.querySelectorAll('.xa-widget').forEach(function(w){ w.remove(); });
    items.forEach(function(info){
      if(info.type === 'widget'){
        // 重建自定义组件
        var el = document.createElement('div');
        el.className = 'xa-widget' + (info.xaType === 'text' ? ' xa-widget-text' : '');
        el.setAttribute('data-xa-type', info.xaType || 'app');
        if(info.xaType === 'app'){
          el.innerHTML = '<i class="xa-wg">'+(info.icon||'📋')+'</i><span>'+(info.name||'')+'</span>';
          if(info.app) el.setAttribute('data-app', info.app);
          el.addEventListener('click', function(e){
            if(document.body.classList.contains('xa-edit')) return;
            if(window.openApp && info.app) window.openApp(info.app);
          });
        } else if(info.xaType === 'text'){
          el.innerHTML = '<div class="xa-txt">'+(info.text||'')+'</div>';
        }
        if(info.left) el.style.left = info.left;
        if(info.top) el.style.top = info.top;
        if(info.position) el.style.position = info.position;
        if(info.right) el.style.right = info.right;
        if(info.bottom) el.style.bottom = info.bottom;
        if(info.margin) el.style.margin = info.margin;
        if(info.moved) el.classList.add('xa-moved');
        home.appendChild(el);
        addDelBtn(el);
      } else {
        // 还原原生组件位置
        var el = null;
        try{ el = info.sel ? home.querySelector(info.sel.split('>').pop()) : null; }catch(e){}
        if(el){
          if(info.left) el.style.left = info.left;
          if(info.top) el.style.top = info.top;
          if(info.position) el.style.position = info.position;
          if(info.right) el.style.right = info.right;
          if(info.bottom) el.style.bottom = info.bottom;
          if(info.margin) el.style.margin = info.margin;
          if(info.moved) el.classList.add('xa-moved');
        }
      }
    });
  };

  /* ── 为每个模式添加编辑按钮 ── */
  function addEditBtnToModes(){
    // Mode B: 心象阁
    var hb = document.getElementById('xumoHomeB');
    if(hb){
      var bBtn = hb.querySelector('.xb-head');
      if(bBtn && !bBtn.querySelector('[data-act="edit"]')){
        var eb = document.createElement('button');
        eb.type = 'button';
        eb.setAttribute('data-act', 'edit');
        eb.title = '编辑布局';
        eb.innerHTML = '✏️';
        eb.style.cssText = 'border:none;background:none;color:inherit;font-size:16px;cursor:pointer;padding:4px 8px;opacity:.6';
        eb.onclick = function(){ document.body.classList.toggle('xa-edit'); };
        bBtn.appendChild(eb);
      }
    }
    // Mode D: 时光长卷
    var hd = document.getElementById('xumoHomeD');
    if(hd){
      var dRuler = hd.querySelector('.xd-ruler');
      if(dRuler && !dRuler.querySelector('[data-act="edit"]')){
        var ed = document.createElement('button');
        ed.type = 'button'; ed.setAttribute('data-act','edit'); ed.title='编辑布局';
        ed.innerHTML = '✏️'; ed.style.cssText = 'border:none;background:none;color:rgba(178,58,58,.7);font-size:14px;cursor:pointer;padding:2px 6px;margin-left:8px';
        ed.onclick = function(){ document.body.classList.toggle('xa-edit'); };
        dRuler.querySelector('.xd-logo').appendChild(ed);
      }
    }
    // Mode E: 星图谱
    var he = document.getElementById('xumoHomeE');
    if(he){
      var eTop = he.querySelector('.xe-topbar');
      if(eTop && !eTop.querySelector('[data-act="edit"]')){
        var ee = document.createElement('button');
        ee.type = 'button'; ee.setAttribute('data-act','edit'); ee.title='编辑布局';
        ee.innerHTML = '✏️'; ee.style.cssText = 'border:none;background:none;color:rgba(255,255,255,.5);font-size:14px;cursor:pointer;padding:4px 8px';
        ee.onclick = function(){ document.body.classList.toggle('xa-edit'); };
        eTop.appendChild(ee);
      }
    }
    // Mode F: 夜波电台
    var hf = document.getElementById('xumoHomeF');
    if(hf){
      var fBrand = hf.querySelector('.xf-brand-row');
      if(fBrand && !fBrand.querySelector('[data-act="edit"]')){
        var ef = document.createElement('button');
        ef.type = 'button'; ef.setAttribute('data-act','edit'); ef.title='编辑布局';
        ef.innerHTML = '✏️'; ef.style.cssText = 'border:none;background:none;color:rgba(255,255,255,.4);font-size:12px;cursor:pointer;padding:2px 6px;margin-left:6px';
        ef.onclick = function(){ document.body.classList.toggle('xa-edit'); };
        fBrand.appendChild(ef);
      }
    }
    // Mode J: 心境潮汐
    var hj = document.getElementById('xumoHomeJ');
    if(hj){
      var jTable = hj.querySelector('.xj-tide-table');
      if(jTable && !jTable.querySelector('[data-act="edit"]')){
        var ej = document.createElement('button');
        ej.type = 'button'; ej.setAttribute('data-act','edit'); ej.title='编辑布局';
        ej.innerHTML = '✏️'; ej.style.cssText = 'border:none;background:none;color:rgba(255,255,255,.4);font-size:12px;cursor:pointer;padding:2px 6px;margin-left:6px';
        ej.onclick = function(){ document.body.classList.toggle('xa-edit'); };
        jTable.appendChild(ej);
      }
    }
    // Mode K: 书桌
    var hk = document.getElementById('xumoHomeK');
    if(hk){
      var kHead = hk.querySelector('.xk-header');
      if(kHead && !kHead.querySelector('[data-act="edit"]')){
        var ek = document.createElement('button');
        ek.type = 'button'; ek.setAttribute('data-act','edit'); ek.title='编辑布局';
        ek.innerHTML = '✏️'; ek.style.cssText = 'border:none;background:none;color:rgba(255,255,255,.4);font-size:12px;cursor:pointer;padding:2px 6px;margin-left:6px';
        ek.onclick = function(){ document.body.classList.toggle('xa-edit'); };
        kHead.appendChild(ek);
      }
    }
    // Mode L: 实验室
    var hl = document.getElementById('xumoHomeL');
    if(hl){
      var lCons = hl.querySelector('.xl-console');
      if(lCons && !lCons.querySelector('[data-act="edit"]')){
        var el2 = document.createElement('button');
        el2.type = 'button'; el2.setAttribute('data-act','edit'); el2.title='编辑布局';
        el2.innerHTML = '✏️'; el2.style.cssText = 'border:none;background:none;color:rgba(255,255,255,.4);font-size:11px;cursor:pointer;padding:1px 4px;margin-left:6px';
        el2.onclick = function(){ document.body.classList.toggle('xa-edit'); };
        lCons.appendChild(el2);
      }
    }
  }

  /* ── 为现有组件添加删除按钮 ── */
  function initDelBtns(){
    document.querySelectorAll('.xa-char, .xa-card, .xa-actions, .xa-widget').forEach(function(el){
      if(!el.querySelector('.xa-del')) addDelBtn(el);
    });
  }

  /* ── 初始化 ── */
  function init(){
    addEditBtnToModes();
    initDelBtns();
  }

  if(document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();

  // 延迟再执行一次（确保动态创建的 home 元素已就绪）
  setTimeout(init, 2000);
})();

/* ═══ 沉浸页面数据面板 v2 ═══ */
(function(){
  var CIRC_LG = 2 * Math.PI * 42;  // 263.9 — large ring (r=42)
  var CIRC_MD = 2 * Math.PI * 28;  // 175.9 — medium ring (r=28)
  var _timer = null;

  function setRing(id, val, max, circ){
    var el = document.getElementById(id);
    if(!el) return;
    var ratio = Math.min(val / Math.max(max, 1), 1);
    el.style.strokeDashoffset = circ * (1 - ratio);
  }

  function setGlow(id, val, max, circ){
    var el = document.getElementById(id);
    if(!el) return;
    var ratio = Math.min(val / Math.max(max, 1), 1);
    el.style.strokeDashoffset = circ * (1 - ratio);
  }

  function animNum(id, target){
    var el = document.getElementById(id);
    if(!el) return;
    var cur = parseInt(el.textContent) || 0;
    if(cur === target){ el.textContent = target; return; }
    var step = Math.ceil(Math.abs(target - cur) / 25) || 1;
    var iv = setInterval(function(){
      if(cur < target) cur = Math.min(cur + step, target);
      else cur = Math.max(cur - step, target);
      el.textContent = cur;
      if(cur === target) clearInterval(iv);
    }, 25);
  }

  function setBar(id, val, max){
    var el = document.getElementById(id);
    if(!el) return;
    el.style.width = Math.min(val / Math.max(max, 1) * 100, 100) + '%';
  }

  function loadAll(){
    // diary
    fetch('/api/diary').then(function(r){return r.json()}).then(function(d){
      animNum('xaDays', d.days_together || 0);
      setRing('xaRingDays', d.days_together || 0, 365, CIRC_LG);
      setGlow('xaGlowDays', d.days_together || 0, 365, CIRC_LG);
      animNum('xaStreak', d.streak || 0);
      setRing('xaRingStreak', d.streak || 0, 30, CIRC_MD);
    }).catch(function(){});
    // world pulse
    fetch('/api/world/pulse').then(function(r){return r.json()}).then(function(d){
      animNum('xaVitality', d.vitality || 0);
      setRing('xaRingVitality', d.vitality || 0, 100, CIRC_LG);
      setGlow('xaGlowVitality', d.vitality || 0, 100, CIRC_LG);
      animNum('xaGen', d.gen_count || 0);
      setBar('xaGenBar', d.gen_count || 0, 200);
    }).catch(function(){});
    // achievements
    fetch('/api/achv/list').then(function(r){return r.json()}).then(function(d){
      animNum('xaLevel', d.level || 1);
      setRing('xaRingLevel', d.level || 1, 50, CIRC_LG);
      setGlow('xaGlowLevel', d.level || 1, 50, CIRC_LG);
      animNum('xaXP', d.xp || 0);
      setRing('xaRingXP', d.xp || 0, Math.max(d.xp || 0, 500), CIRC_MD);
      animNum('xaAchv', d.claimed || 0);
      setRing('xaRingAchv', d.claimed || 0, d.total || 1, CIRC_MD);
    }).catch(function(){});
    // focus
    fetch('/api/coach/focus/stats').then(function(r){return r.json()}).then(function(d){
      animNum('xaFocus', d.total_minutes || 0);
      setRing('xaRingFocus', d.total_minutes || 0, 500, CIRC_MD);
    }).catch(function(){});
    // study
    fetch('/api/study/stats').then(function(r){return r.json()}).then(function(d){
      animNum('xaStudy', d.total_solved || 0);
      setBar('xaStudyBar', d.total_solved || 0, 100);
    }).catch(function(){});
    // work
    fetch('/api/work/stats').then(function(r){return r.json()}).then(function(d){
      animNum('xaWork', d.total_docs || 0);
      setBar('xaWorkBar', d.total_docs || 0, 50);
    }).catch(function(){});
    // daily quote
    fetch('/api/quotes/daily').then(function(r){return r.json()}).then(function(d){
      var q = document.getElementById('xaQuote');
      if(q && d.daily) q.innerHTML = d.daily + (d.author ? '<em>\u2014 ' + d.author + '</em>' : '');
    }).catch(function(){});
  }

  function start(){
    if(!document.getElementById('xaDash')) return;
    loadAll();
    if(_timer) clearInterval(_timer);
    _timer = setInterval(loadAll, 120000);
  }

  var obs = new MutationObserver(function(){
    if(document.body.classList.contains('mode-a') && document.getElementById('xaDash')){
      start();
      obs.disconnect();
    }
  });
  obs.observe(document.body, {attributes:true, attributeFilter:['class']});
  if(document.body.classList.contains('mode-a')) setTimeout(start, 1500);
})();
})();
