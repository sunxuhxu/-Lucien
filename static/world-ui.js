/* =========================================================================
 * 世界·恋语市 —— UI 层
 * 职责：HUD / 对话 / 任务·背包·技能·大地图面板 / 战斗 / 谜题 / 商店 /
 *       休息 / 结局 / 开场 / Toast；并通过 window.WorldGame 对接主应用
 * ========================================================================= */
(function () {
'use strict';

var E = window.WORLD_ENG, D = E.D;
var $ = function (id) { return document.getElementById(id); };
var root = null, built = false;
var dbgEl = null;
var modalOpen = false, modalKind = null;

function isModal() { return modalOpen; }
function esc(s) {
  return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
    return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
  });
}

/* ================= 构建骨架 ================= */
function build() {
  var app = $('app-world');
  if (!app) return;
  app.innerHTML = '' +
  '<div class="w-root">' +
    '<div class="w-canvas-wrap"><canvas id="wCanvas3d"></canvas><canvas id="wCanvas"></canvas></div>' +

    /* 顶部 HUD */
    '<div class="w-hud-top">' +
      '<div class="w-clock-box">' +
        '<div class="w-day" id="wDay">第 1 天</div>' +
        '<div class="w-time" id="wTime">08:00</div>' +
        '<div class="w-weather" id="wWeather">☀️ 晴</div>' +
        '<div class="w-season" id="wSeason" title="当前季节">🌱 春</div>' +
      '</div>' +
      '<div class="w-mini-box" id="wMiniBox" title="点击打开大地图">' +
        '<canvas id="wMini" width="288" height="288"></canvas>' +
        '<div class="w-explore" id="wExplore">探索 0%</div>' +
      '</div>' +
    '</div>' +

    /* 任务追踪条 */
    '<div class="w-track" id="wTrack" style="display:none" title="点击打开任务面板"></div>' +

    /* 底部状态 */
    '<div class="w-hud-bl">' +
      '<div class="w-lv" id="wLv">Lv.1</div>' +
      '<div class="w-bars">' +
        '<div class="w-bar w-hp"><i id="wHpBar"></i><span id="wHpTxt">100/100</span></div>' +
        '<div class="w-bar w-sp"><i id="wSpBar"></i><span id="wSpTxt">100/100</span></div>' +
      '</div>' +
      '<div class="w-money" id="wMoney">¥200</div>' +
    '</div>' +

    /* 右侧按钮列 */
    '<div class="w-btn-col">' +
      '<button class="w-fab" data-panel="quest" title="任务 (J)">📋</button>' +
      '<button class="w-fab" data-panel="bag" title="背包 (B)">🎒</button>' +
      '<button class="w-fab" data-panel="skill" title="技能 (K)">🌟</button>' +
      '<button class="w-fab" data-panel="map" title="地图 (M)">🗺️</button>' +
      '<button class="w-fab" data-panel="pulse" title="城市脉搏 (P)">📡</button>' +
      '<button class="w-fab" data-panel="chron" title="世界编年史 (H)">📜</button>' +
      '<button class="w-fab" data-panel="build" title="世界工坊 (C)">🛠️</button>' +
      '<button class="w-fab" data-panel="transport" title="交通与采集 (T)">🚲</button>' +
      '<button class="w-fab" id="wModeBtn" title="切换 2D/3D 视角">🧊</button>' +
      '<button class="w-fab" data-panel="set" title="设置">⚙️</button>' +
      '<button class="w-fab" id="wExitBtn" title="返回桌面">⏏</button>' +
    '</div>' +

    /* 3D 视角旋转按钮（仅 3D 模式显示） */
    '<div class="w-rot" id="wRotBox" style="display:none">' +
      '<button id="wRotL" title="向左旋转 (Q)">⟲</button>' +
      '<button id="wRotR" title="向右旋转 (Z)">⟳</button>' +
    '</div>' +

    /* 建造模式工具条 */
    '<div class="w-build-bar" id="wBuildBar" style="display:none">' +
      '<span class="wb-icon" id="wbIcon">🌿</span>' +
      '<span class="wb-name" id="wbName">草坪</span>' +
      '<button class="w-mini-btn wbs" data-wbs="1">1×</button>' +
      '<button class="w-mini-btn wbs" data-wbs="2">2×</button>' +
      '<button class="w-mini-btn wbs" data-wbs="3">3×</button>' +
      '<span class="wb-count" id="wbCount">已涂 0 格</span>' +
      '<button class="w-mini-btn" id="wbDone">✅ 完成</button>' +
    '</div>' +

    /* 交互提示 */
    '<div class="w-interact" id="wInteract" style="display:none"><b>E</b><span id="wInteractTxt"></span></div>' +

    /* 触屏方向键 */
    '<div class="w-dpad" id="wDpad">' +
      '<button data-dir="up">▲</button><button data-dir="left">◀</button>' +
      '<button data-dir="right">▶</button><button data-dir="down">▼</button>' +
      '<button class="w-dpad-e" id="wBtnE">E</button>' +
    '</div>' +

    /* Toast */
    '<div class="w-toasts" id="wToasts"></div>' +
  '</div>' +
  /* 模态层 */
  '<div class="w-modal" id="wModal" style="display:none"><div class="w-modal-box" id="wModalBox"></div></div>';

  root = app.querySelector('.w-root');
  bindEvents();
}

/* ================= 事件 ================= */
var panelKeys = { j: 'quest', b: 'bag', k: 'skill', m: 'map', c: 'build', p: 'pulse', h: 'chron' };
function bindEvents() {
  /* 引擎回调 */
  E.on('toast', showToast);
  E.on('isModal', function () { return modalOpen; });
  E.on('refresh', refreshHUD);
  E.on('dialog', openNpcDialog);
  E.on('shop', openShop);
  E.on('rest', openRest);
  E.on('puzzle', openPuzzle);
  E.on('ending', showEnding);
  E.on('battle', openBattle);
  E.on('prologue', openCafePrologue);
  E.on('place', openPlaceCard);
  E.on('pulseEvent', openPulseEventCard);
  E.on('pulseNews', showPulseNews);
  E.on('dialogNeedDone', function (id, text) { showToast(text); });
  E.on('setInteract', function (t) {
    var el = $('wInteract');
    if (!el) return;
    /* 引擎每帧回调：文本未变化时跳过 DOM 写入，避免无谓的重排/重绘 */
    var label = (t && !isModal()) ? (' ' + t.label) : null;
    if (label) {
      if (el.style.display === 'none' || el.style.display === '') el.style.display = 'inline-flex';
      var txt = $('wInteractTxt');
      if (txt.textContent !== label) txt.textContent = label;
    } else if (el.style.display !== 'none') {
      el.style.display = 'none';
    }
  });
  E.on('tick', function () { refreshClock(); });
  E.on('buildBar', updateBuildBar);

  /* 面板按钮 */
  root.querySelectorAll('.w-fab').forEach(function (btn) {
    btn.addEventListener('click', function () { togglePanel(btn.dataset.panel); });
  });
  $('wMiniBox').addEventListener('click', function () { togglePanel('map'); });
  /* 任务追踪条：点击开面板，✕ 取消追踪；周期刷新距离 */
  $('wTrack').addEventListener('click', function (e) {
    if (e.target && e.target.id === 'wTrackX') { E.setTrack(null); showToast('已取消追踪'); return; }
    togglePanel('quest');
  });
  setInterval(function () {
    var el = $('wTrack');
    if (el && el.style.display !== 'none') refreshTrack();
  }, 600);
  $('wBtnE').addEventListener('click', function () { if (!isModal()) E.doInteract(); });
  $('wExitBtn').addEventListener('click', function () {
    if (window.__phoneCloseApp) window.__phoneCloseApp();
    else { var hb = document.getElementById('homebar'); if (hb) hb.click(); }
  });

  /* 方向键（按住持续移动） */
  var dirHold = {};
  root.querySelectorAll('.w-dpad [data-dir]').forEach(function (btn) {
    var dir = btn.dataset.dir;
    function down(e) { e.preventDefault(); dirHold[dir] = true; }
    function up(e) { e.preventDefault(); dirHold[dir] = false; }
    btn.addEventListener('touchstart', down, { passive: false });
    btn.addEventListener('touchend', up);
    btn.addEventListener('mousedown', down);
    btn.addEventListener('mouseup', up);
    btn.addEventListener('mouseleave', function () { dirHold[dir] = false; });
  });
  /* 方向键融合进引擎输入（引擎主循环统一消费 joy） */
  setInterval(function () {
    if (!E.joy || dragJoy.on) return;
    var dx = 0, dy = 0;
    if (dirHold.up) dy -= 1;
    if (dirHold.down) dy += 1;
    if (dirHold.left) dx -= 1;
    if (dirHold.right) dx += 1;
    if (dx || dy) { E.joy.active = true; E.joy.dx = dx; E.joy.dy = dy; E.joy.mag = 1; }
    else E.joy.active = false;
  }, 50);

  /* 模态关闭 */
  $('wModal').addEventListener('click', function (e) {
    if (e.target === this) closeModal(true);
  });

  /* 建造模式：画布涂抹 / 普通模式：按住拖拽移动（虚拟摇杆） */
  var cvEl = $('wCanvas');
  var painting = false;
  var dragJoy = { on: false, id: null, sx: 0, sy: 0 };
  var joyBase = document.createElement('div');
  var joyKnob = document.createElement('div');
  joyBase.id = 'wJoyBase'; joyKnob.id = 'wJoyKnob';
  joyBase.style.display = 'none';
  joyBase.appendChild(joyKnob);
  document.body.appendChild(joyBase);
  function joyShow(x, y) {
    joyBase.style.display = '';
    joyBase.style.left = (x - 52) + 'px';
    joyBase.style.top = (y - 52) + 'px';
    joyKnob.style.transform = 'translate(0px,0px)';
  }
  function joyMove(dx, dy) { joyKnob.style.transform = 'translate(' + dx + 'px,' + dy + 'px)'; }
  function joyHide() { joyBase.style.display = 'none'; }
  function dragEnd() {
    dragJoy.on = false;
    if (E.joy) { E.joy.active = false; E.joy.dx = 0; E.joy.dy = 0; }
    joyHide();
  }
  cvEl.addEventListener('pointerdown', function (e) {
    if (modalOpen) return;
    var bm = E.buildState();
    if (bm && bm.on) {
      painting = true;
      try { cvEl.setPointerCapture(e.pointerId); } catch (err) {}
      E.paintScreen(e.clientX, e.clientY);
      e.preventDefault();
      return;
    }
    /* 普通模式：按住画布拖动 = 虚拟摇杆移动 */
    dragJoy.on = true; dragJoy.id = e.pointerId;
    dragJoy.sx = e.clientX; dragJoy.sy = e.clientY;
    try { cvEl.setPointerCapture(e.pointerId); } catch (err) {}
    joyShow(e.clientX, e.clientY);
    e.preventDefault();
  });
  cvEl.addEventListener('pointermove', function (e) {
    var bm = E.buildState();
    if ((!bm || !bm.on) && dragJoy.on && e.pointerId === dragJoy.id) {
      var dx = e.clientX - dragJoy.sx, dy = e.clientY - dragJoy.sy;
      var len = Math.hypot(dx, dy);
      if (len > 8) {
        var R = 52, cl = Math.min(len, R);
        var nx = dx / len, ny = dy / len;
        E.joy.active = true; E.joy.dx = nx; E.joy.dy = ny;
        E.joy.mag = Math.max(0.35, cl / R);
        joyMove(nx * cl, ny * cl);
      }
      e.preventDefault();
      return;
    }
    if (!bm || !bm.on || modalOpen) { E.setBrushCursor(null); return; }
    E.setBrushCursor(e.clientX, e.clientY);
    if (painting) E.paintScreen(e.clientX, e.clientY);
  });
  ['pointerup', 'pointercancel'].forEach(function (ev) {
    cvEl.addEventListener(ev, function (e) {
      painting = false;
      if (dragJoy.on && (e.pointerId === dragJoy.id || ev === 'pointercancel')) dragEnd();
    });
  });
  cvEl.addEventListener('pointerleave', function () {
    painting = false;
    if (dragJoy.on) dragEnd();
    E.setBrushCursor(null);
  });

  /* 建造工具条 */
  $('wBuildBar').querySelectorAll('.wbs').forEach(function (b) {
    b.addEventListener('click', function () {
      var bm = E.buildState();
      E.setBuildMode(true, null, +b.dataset.wbs);
      b.blur();
    });
  });
  $('wbDone').addEventListener('click', function () { E.setBuildMode(false); });

  /* 2D/3D 视角切换 */
  $('wModeBtn').addEventListener('click', function () {
    var nm = E.getRenderMode() === '3d' ? '2d' : '3d';
    if (nm === '3d' && !(window.WORLD3D && window.WORLD3D.available())) {
      showToast('3D 模块未加载，请检查静态资源');
      return;
    }
    E.setRenderMode(nm);
    try { localStorage.setItem('world_render_mode', nm); } catch (e) {}
    applyModeUI(nm);
    showToast(nm === '3d'
      ? '🧊 已切换 3D 立体视角（滚轮缩放 · 右键拖拽或 Q/Z 旋转）'
      : '🗺️ 已切回平面视角');
  });
  $('wRotL').addEventListener('click', function () {
    if (window.WORLD3D) window.WORLD3D.rotateBy(-0.5);
  });
  $('wRotR').addEventListener('click', function () {
    if (window.WORLD3D) window.WORLD3D.rotateBy(0.5);
  });
  document.addEventListener('keydown', function (e) {
    if (!running()) return;
    if (e.target && (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA')) return;
    var k = e.key.toLowerCase();
    if (k === 'escape') { if (modalOpen) closeModal(true); return; }
    if (modalOpen) return;
    if (panelKeys[k]) { e.preventDefault(); togglePanel(panelKeys[k]); }
    if (k === 'm') { e.preventDefault(); togglePanel('map'); }
  });
  if (!dbgEl) {
    dbgEl = document.createElement('div');
    dbgEl.id = 'wDbg';
    dbgEl.style.cssText = 'position:absolute;left:6px;bottom:6px;z-index:99;font:10px/1.4 ui-monospace,monospace;color:#e5e7eb;background:rgba(0,0,0,.5);padding:4px 8px;border-radius:6px;white-space:pre;pointer-events:none;max-width:60%';
    dbgEl.textContent = 'world: building…';
    var appEl = $('app-world');
    if (appEl) appEl.appendChild(dbgEl);
  }
}
function running() { return document.body.classList.contains('app-open') && $('app-world') && $('app-world').querySelector('.app-view.open, .w-root'); }

/* ================= HUD ================= */
var _clkLast = { day: '', time: '', wx: '' };
function refreshClock() {
  /* 引擎 tick 每帧触发，但三个字段至多分钟级变化：脏检查后再写 DOM */
  var S = E.state();
  var wd = E.weatherDef();
  var d = '第 ' + S.day + ' 天', t = E.gameClock(), w = wd.icon + ' ' + wd.name;
  if (_clkLast.day !== d) { $('wDay').textContent = d; _clkLast.day = d; }
  if (_clkLast.time !== t) { $('wTime').textContent = t; _clkLast.time = t; }
  if (_clkLast.wx !== w) { $('wWeather').textContent = w; _clkLast.wx = w; }
}
function refreshHUD() {
  var S = E.state();
  if (!S) return;
  var st = E.calcStats();
  var p = S.player;
  $('wLv').textContent = 'Lv.' + p.lv + (p.skillPts > 0 ? ' ⬆' : '');
  $('wHpBar').style.width = Math.max(0, Math.min(100, p.hp / st.hpMax * 100)) + '%';
  $('wHpTxt').textContent = Math.ceil(p.hp) + '/' + st.hpMax;
  $('wSpBar').style.width = Math.max(0, Math.min(100, p.sp / st.spMax * 100)) + '%';
  $('wSpTxt').textContent = Math.ceil(p.sp) + '/' + st.spMax;
  $('wMoney').textContent = '¥' + p.money;
  $('wExplore').textContent = '探索 ' + E.explorePct() + '%';
  refreshClock();
  refreshSeason();
  refreshTrack();
}
/* ---- 任务追踪条 ---- */
function refreshTrack() {
  var el = $('wTrack');
  if (!el) return;
  var S = E.state();
  if (!S || !S.questTrack) { el.style.display = 'none'; return; }
  var g = E.trackedGuide();
  if (!g) { el.style.display = 'none'; return; }
  var name = S.questTrack === 'main' ? '主线' : sideTitle(S.questTrack);
  var dist = Math.round(Math.hypot(g.x - S.player.x, g.y - S.player.y) * 10);
  el.style.display = '';
  el.innerHTML = '<span class="w-track-name">🎯 ' + esc(name) + '</span>' +
    '<span class="w-track-tip">' + esc(g.tip) + '</span>' +
    '<span class="w-track-dist">' + dist + 'm</span>' +
    '<span class="w-track-x" id="wTrackX" title="取消追踪">✕</span>';
}

/* ================= Toast ================= */
function showToast(msg) {
  var box = $('wToasts');
  if (!box) return;
  var el = document.createElement('div');
  el.className = 'w-toast';
  el.textContent = msg;
  box.appendChild(el);
  while (box.children.length > 4) box.removeChild(box.firstChild);
  setTimeout(function () {
    el.classList.add('out');
    setTimeout(function () { el.remove(); }, 350);
  }, 2600);
}

/* ================= 模态框基础 ================= */
function openModal(html, kind, opts) {
  modalOpen = true; modalKind = kind || null;
  var m = $('wModal'), box = $('wModalBox');
  box.innerHTML = html;
  m.style.display = 'flex';
  box.classList.remove('in');
  void box.offsetWidth;
  box.classList.add('in');
  /* 拒绝误关 */
  box.dataset.lock = opts && opts.lock ? '1' : '';
}
function closeModal(soft) {
  if (modalKind === 'battle') return;              /* 战斗不可关闭 */
  if (modalKind === 'dialog' && dialogLock && soft) { showToast('（先选一个选项……）'); return; }
  if (modalKind === 'ending' && soft) return;      /* 结局不可点外关闭 */
  modalOpen = false; modalKind = null; dialogLock = false;
  $('wModal').style.display = 'none';
  $('wModalBox').innerHTML = '';
}

/* ================= 对话系统 ================= */
var dialogLock = false;
function openNpcDialog(def) {
  var G = E.makeG();
  var node;
  try { node = def.dialog(G); } catch (err) { node = { text: '……（他似乎在想别的事。）', options: [{ t: '（离开）', eff: function () {} }] }; }
  if (!node) node = { text: '……', options: [{ t: '（离开）', eff: function () {} }] };
  renderDialog(def, node, G);
}
function renderDialog(def, node, G) {
  if (!node) { closeModal(); return; }
  var aff = E.state().npcAff[def.id] || 0;
  var affTxt = D.affLevel(aff) + ' · ' + aff + '/100';
  var optsHtml = '';
  (node.options || []).forEach(function (o, i) {
    var ok = true;
    if (o.cond) { try { ok = !!o.cond(); } catch (e) { ok = false; } }
    if (!ok) return;
    optsHtml += '<button class="w-dlg-opt" data-i="' + i + '">' + esc(o.t) + '</button>';
  });
  if (!optsHtml) optsHtml = '<button class="w-dlg-opt" data-i="end">（结束对话）</button>';
  /* 建模扩展·v2：NPC 需求交付按钮 */
  var need = (E.getNpcNeed && def.id) ? E.getNpcNeed(def.id) : null;
  var needBtn = need ? '<button class="w-dlg-opt need" data-need="1" title="' + esc(need.hint) + '">📦 交付 ' +
    (D.ITEMS[need.want] ? (D.ITEMS[need.want].icon + ' ' + D.ITEMS[need.want].name) : need.want) + '</button>' : '';
  optsHtml = needBtn + optsHtml;
  openModal(
    '<div class="w-dlg">' +
      '<div class="w-dlg-head">' +
        '<span class="w-dlg-avatar" style="background:' + def.color + '22;border-color:' + def.color + '">' + (def.avatar ? '<img src="' + esc(def.avatar) + '" alt="' + esc(def.name) + '头像" />' : def.emoji) + '</span>' +
        '<div><div class="w-dlg-name" style="color:' + def.color + '">' + esc(def.name) + '</div>' +
        '<div class="w-dlg-aff">' + esc(affTxt) + '</div></div>' +
      '</div>' +
      '<div class="w-dlg-text">' + esc(node.text).replace(/\n/g, '<br>') + '</div>' +
      '<div class="w-dlg-opts">' + optsHtml + '</div>' +
    '</div>', 'dialog');
  $('wModalBox').querySelectorAll('.w-dlg-opt').forEach(function (btn) {
    btn.addEventListener('click', function () {
      if (dialogLock) return;
      dialogLock = true;
      /* 建模扩展·v2：需求交付按钮 */
      if (btn.dataset.need) {
        var ok = E.deliverNeed(def.id);
        dialogLock = false;
        if (ok) renderDialog(def, node, G);
        return;
      }
      var i = btn.dataset.i;
      var opt = i === 'end' ? null : (node.options || [])[+i];
      var nextNode = null;
      if (opt) {
        if (opt.eff) { try { opt.eff(); } catch (e) { console.error(e); } }
        if (opt.next) { try { nextNode = opt.next(); } catch (e) { nextNode = null; } }
      }
      dialogLock = false;
      if (nextNode) renderDialog(def, nextNode, G);
      else { closeModal(); E.save(); refreshHUD(); }
    });
  });
}

/* ================= 开场 ================= */
function showPrologueCards(onDone) {
  var idx = 0;
  function show() {
    if (idx >= D.PROLOGUE.length) { closeModal(); onDone(); return; }
    var c = D.PROLOGUE[idx];
    openModal(
      '<div class="w-pro">' +
        '<div class="w-pro-t">' + esc(c.t) + '</div>' +
        '<div class="w-pro-d">' + esc(c.d).replace(/\n/g, '<br>') + '</div>' +
        '<button class="w-btn-main" id="wProNext">' + (idx === D.PROLOGUE.length - 1 ? '开始探索' : '继续') + '</button>' +
      '</div>', 'prologue', { lock: true });
    $('wProNext').addEventListener('click', function () { idx++; show(); });
  }
  show();
}
function openCafePrologue() {
  var S = E.state();
  showSceneChain([
    { t: '街角咖啡店 · 早晨', d: '风铃轻响。靠窗的位置，一个穿白衬衫的男人正在读书，银框眼镜，指尖停在书页边缘。\n他抬起头——像是早就知道你会来。' },
    { t: '许墨', d: '「你来了。」他合上书，微笑示意对面的座位，「先坐。热美式，还是……你的记忆，大概比咖啡更苦一点。」\n「最近城里那些『遗忘』的传闻——不必怀疑，是真的。而你的名字，恰好出现在我很在意的一份名单上。」' },
    { t: '许墨', d: '「先从简单的开始：三枚『记忆碎片』散落在城里——旧图书馆外、梧桐公园、临海栈桥。」\n「找到它们，带给我。」他顿了顿，目光温和却不容拒绝，「这是我给你的第一个……请求。」' }
  ], function () {
    S.mainStage = 1;
    E.callAffinity('world_quest', '主线·第一章开启');
    showToast('📋 主线开始：收集 3 枚记忆碎片');
    E.save(); refreshHUD();
  });
}
/* 连续场景卡 */
function showSceneChain(cards, onDone) {
  var idx = 0;
  function show() {
    if (idx >= cards.length) { closeModal(); onDone(); return; }
    var c = cards[idx];
    openModal(
      '<div class="w-pro">' +
        '<div class="w-pro-t">' + esc(c.t) + '</div>' +
        '<div class="w-pro-d">' + esc(c.d).replace(/\n/g, '<br>') + '</div>' +
        '<button class="w-btn-main" id="wSceneNext">' + (idx === cards.length - 1 ? '（继续）' : '（继续）') + '</button>' +
      '</div>', 'scene', { lock: false });
    $('wSceneNext').addEventListener('click', function () { idx++; show(); });
  }
  show();
}

/* ================= 面板 ================= */
function togglePanel(name) {
  if (modalOpen && modalKind === 'panel-' + name) { closeModal(); return; }
  if (modalOpen) return;
  var html = '';
  if (name === 'quest') html = panelQuest();
  else if (name === 'bag') html = panelBag();
  else if (name === 'skill') html = panelSkill();
  else if (name === 'map') html = panelMap();
  else if (name === 'set') html = panelSet();
  else if (name === 'build') html = panelBuild();
  else if (name === 'pulse') html = panelPulse();
  else if (name === 'chron') html = panelChron();
  else if (name === 'transport') html = panelTransport();
  openModal(html, 'panel-' + name);
  wirePanel(name);
  if (name === 'map') drawBigMap();
  if (name === 'bag') wireBag();
  if (name === 'quest') wireQuest();
  if (name === 'skill') wireSkill();
  if (name === 'build') wireBuild();
  if (name === 'pulse') wirePulse();
  if (name === 'chron') wireChron();
  if (name === 'transport') wireTransport();
}

/* ================= 世界工坊（扩建与创造） ================= */
var buildSel = 'grass', buildSize = 1;
var NPC_EMOJIS = ['🙂', '👧', '🧑', '👵', '👴', '🧒', '👨‍🍳', '👩‍🎨', '🧑‍🔬', '🕵️', '🐱', '🐶', '🦋', '🎀'];
var NPC_COLORS = ['#8b5cf6', '#ec4899', '#f59e0b', '#10b981', '#0ea5e9', '#6366f1', '#ef4444', '#64748b'];
var npcDraft = null, npcPickMode = false;
/* 智能设计居民（LLM 草稿，挑选后入住） */
var smartDrafts = [], smartRemark = '', smartCount = 2, smartBusy = false;
/* AI 智能建设（地形+地点+建筑 一站式方案） */
var aiDraft = null, aiPickMode = false, aiBusy = false;

function smartCardsHtml() {
  if (!smartDrafts.length) return '';
  var cards = smartDrafts.map(function (d, i) {
    if (d.done) {
      return '<div class="w-smart-card done"><div class="w-sc-head"><span class="w-sc-emoji">' + d.emoji + '</span><b>' + esc(d.name) + '</b><span class="w-sub">已住进恋语市 ✓</span></div></div>';
    }
    var linesPrev = (d.lines || []).slice(0, 2).map(function (l) { return '「' + esc(l) + '」'; }).join(' ');
    return '<div class="w-smart-card" data-si="' + i + '">' +
      '<div class="w-sc-head"><span class="w-sc-emoji">' + d.emoji + '</span><b style="color:' + esc(d.color) + '">' + esc(d.name) + '</b>' +
        '<i class="w-sc-dot" style="background:' + esc(d.color) + '"></i></div>' +
      (d.desc ? '<div class="w-sc-desc">' + esc(d.desc) + '</div>' : '') +
      '<div class="w-sc-lines">' + linesPrev + '</div>' +
      '<div class="w-sc-acts"><button class="w-mini-btn" data-smart-in="' + i + '">🏡 迎进恋语市</button>' +
        '<button class="w-mini-btn ghost" data-smart-no="' + i + '">✖ 不要了</button></div>' +
    '</div>';
  }).join('');
  var head = smartRemark
    ? '<div class="w-smart-remark">许墨：「' + esc(smartRemark) + '」</div>'
    : '';
  return head + cards;
}

function renderSmartList() {
  var box = $('wnSmartList');
  if (box) box.innerHTML = smartCardsHtml();
  var n = 0;
  for (var i = 0; i < smartDrafts.length; i++) if (!smartDrafts[i].done && !smartDrafts[i].drop) n++;
  if (!n && box) box.innerHTML = '<div class="w-sub" style="text-align:center;padding:4px 0">这批都送走了，再让许墨设计一批？</div>';
}

function smartMoveIn(i) {
  var d = smartDrafts[i];
  if (!d || d.done || smartBusy) return;
  var S = E.state();
  var px = Math.floor(S.player.x) + Math.floor(Math.random() * 13) - 6;
  var py = Math.floor(S.player.y) + Math.floor(Math.random() * 13) - 6;
  try {
    var pos = E.findWalkableNear(px, py);
    if (pos) { px = pos.x; py = pos.y; }
  } catch (e) {}
  d.busy = true; renderSmartList();
  fetch('/api/world/npcs', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name: d.name, emoji: d.emoji, color: d.color, desc: d.desc, lines: d.lines, x: px, y: py })
  }).then(function (r) { return r.json(); }).then(function (res) {
    d.busy = false;
    if (res.error) { showToast(res.error); renderSmartList(); return; }
    d.done = true; d.id = res.npc.id;
    E.applyCustomNpc(res.npc);
    showToast('🧑 「' + d.name + '」住进了恋语市（' + px + ', ' + py + '）');
    if (res.affinity && res.affinity.delta) showToast('💗 心动 +' + res.affinity.delta);
    renderSmartList();
  }).catch(function () {
    d.busy = false; renderSmartList(); showToast('入住失败，稍后再试');
  });
}

function smartGenerate() {
  if (smartBusy) return;
  var idea = ($('wnSmartIdea') && $('wnSmartIdea').value || '').trim();
  smartBusy = true;
  var go = $('wnSmartGo');
  if (go) { go.disabled = true; go.textContent = '✨ 许墨正在构思……'; }
  var list = $('wnSmartList');
  if (list) list.innerHTML = '<div class="w-sub" style="text-align:center;padding:8px 0">🦋 许墨拿起笔，在想几位新朋友的样子……</div>';
  fetch('/api/world/npcs/smart', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ idea: idea, count: smartCount })
  }).then(function (r) { return r.json(); }).then(function (d) {
    smartBusy = false;
    if (go) { go.disabled = false; go.textContent = '✨ 让许墨设计'; }
    if (d.error) { showToast(d.error); renderSmartList(); return; }
    smartDrafts = (d.npcs || []).map(function (x) { x.done = false; x.busy = false; return x; });
    smartRemark = d.remark || '';
    renderSmartList();
  }).catch(function () {
    smartBusy = false;
    if (go) { go.disabled = false; go.textContent = '✨ 让许墨设计'; }
    showToast('生成失败，稍后再试'); renderSmartList();
  });
}

function wireSmartList() {
  var box = $('wModalBox');
  if (!box) return;
  var listBox = box.querySelector('#wnSmartList');
  if (!listBox) return;
  listBox.addEventListener('click', function (ev) {
    var t = ev.target.closest ? ev.target.closest('[data-smart-in],[data-smart-no]') : null;
    if (!t) return;
    var i = +(t.dataset.smartIn != null ? t.dataset.smartIn : t.dataset.smartNo);
    if (t.dataset.smartIn != null) { smartMoveIn(i); return; }
    /* 不要了：从草稿中送走 */
    if (smartDrafts[i]) {
      smartDrafts.splice(i, 1);
      renderSmartList();
    }
  });
}

/* ---- AI 智能建设：方案生成 / 预览 / 动工 ---- */
function aiPosTxt() {
  return aiDraft && aiDraft.x != null
    ? '已选 (' + aiDraft.x + ', ' + aiDraft.y + ')'
    : '未选（默认用脚下位置）';
}

function aiPlanHtml() {
  if (!aiDraft || !aiDraft.plan) return '';
  var p = aiDraft.plan;
  var chips = (p.places || []).map(function (q) {
    return '<span class="w-ai-chip">' + (q.icon || '📍') + ' ' + esc(q.name) +
      ' <i>(' + q.x + ',' + q.y + ' · ' + q.w + '×' + q.h + (q.kind === 'mark' ? ' 地标' : ' 建筑') + ')</i></span>';
  }).join('');
  return '<div class="w-ai-plan">' +
    '<div class="w-ai-t">🏗️ ' + esc(p.title || '建设方案') + '</div>' +
    (p.concept ? '<div class="w-smart-remark">许墨：「' + esc(p.concept) + '」</div>' : '') +
    (chips ? '<div class="w-ai-chips">' + chips + '</div>' : '') +
    '<div class="w-ai-meta">' + aiDraft.tile_count + ' 格地形 · ' + (p.places || []).length +
      ' 处地点/建筑 · 费用 ¥' + aiDraft.cost_money + ' + 体力 ' + aiDraft.cost_sp + '</div>' +
    '<div class="w-ai-acts"><button class="w-btn-main" id="waiBuild">🏗️ 动工</button>' +
      '<button class="w-mini-btn ghost" id="waiRedo">🔄 重新设计</button>' +
      '<button class="w-mini-btn ghost" id="waiDrop">✕ 放弃</button></div>' +
  '</div>';
}

function renderAiPlan() {
  var boxEl = $('waiPlan');
  if (!boxEl) return;
  boxEl.innerHTML = aiPlanHtml();
  var b = $('waiBuild'), r = $('waiRedo'), d2 = $('waiDrop');
  if (b) b.addEventListener('click', aiBuild);
  if (r) r.addEventListener('click', aiDesign);
  if (d2) d2.addEventListener('click', function () {
    aiDraft = null; renderAiPlan(); showToast('方案已放弃');
  });
}

function aiDesign() {
  if (aiBusy) { showToast('许墨还在构思上一份蓝图，稍等一下'); return; }
  var ideaEl = $('waiIdea');
  var idea = (ideaEl && ideaEl.value || '').trim();
  if (!idea) { showToast('先说说你想建什么'); return; }
  var S = E.state();
  if (!S || !S.player) { showToast('世界还在加载，请稍后再试'); return; }
  aiDraft = aiDraft || {};
  aiDraft.idea = idea;
  if (aiDraft.x == null || aiDraft.x !== aiDraft.x) { aiDraft.x = Math.floor(S.player.x); aiDraft.y = Math.floor(S.player.y); }
  var px = aiDraft.x, py = aiDraft.y;
  if (typeof px !== 'number' || !isFinite(px)) px = Math.floor(S.player.x);
  if (typeof py !== 'number' || !isFinite(py)) py = Math.floor(S.player.y);
  aiDraft.plan = null;
  aiBusy = true;
  var go = $('waiGo');
  if (go) { go.disabled = true; go.textContent = '✨ 许墨正在绘制蓝图……'; }
  var boxEl = $('waiPlan');
  if (boxEl) boxEl.innerHTML = '<div class="w-sub" style="text-align:center;padding:8px 0">🦋 许墨铺开图纸，正在计算光照与风向……</div>';
  fetch('/api/world/ai/design', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ idea: idea, x: px, y: py })
  }).then(function (r) {
    if (!r.ok) throw new Error('HTTP ' + r.status);
    return r.json();
  }).then(function (d) {
    aiBusy = false;
    if (go) { go.disabled = false; go.textContent = '✨ 让许墨规划'; }
    if (d.error) { showToast(d.error); renderAiPlan(); return; }
    if (!d.plan) { showToast('方案构思失败，请换个说法再试'); renderAiPlan(); return; }
    aiDraft.plan = d.plan || null;
    aiDraft.tile_count = d.tile_count || 0;
    aiDraft.cost_money = d.cost_money || 0;
    aiDraft.cost_sp = d.cost_sp || 0;
    renderAiPlan();
  }).catch(function (err) {
    aiBusy = false;
    if (go) { go.disabled = false; go.textContent = '✨ 让许墨规划'; }
    console.error('[world] aiDesign fetch failed:', err);
    showToast('构思失败：' + (err && err.message ? err.message : '网络异常') + '，稍后再试');
    renderAiPlan();
  });
}

function aiBuild() {
  if (!aiDraft || !aiDraft.plan || aiBusy) { showToast('请先生成一份建设方案'); return; }
  var S = E.state();
  if (!S || !S.player) { showToast('世界还在加载，请稍后再试'); return; }
  if (S.player.money < aiDraft.cost_money || S.player.sp < aiDraft.cost_sp) {
    showToast('💰 动工需 ¥' + aiDraft.cost_money + ' + 体力 ' + aiDraft.cost_sp + '（余额或体力不足，先休息或打工吧）');
    return;
  }
  aiBusy = true;
  var btn = $('waiBuild');
  if (btn) { btn.disabled = true; btn.textContent = '🏗️ 施工中……'; }
  fetch('/api/world/ai/build', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ plan: aiDraft.plan })
  }).then(function (r) {
    if (!r.ok) throw new Error('HTTP ' + r.status);
    return r.json();
  }).then(function (d) {
    aiBusy = false;
    if (d.error) {
      showToast(d.error);
      if (btn) { btn.disabled = false; btn.textContent = '🏗️ 动工'; }
      return;
    }
    aiDraft = null; aiPickMode = false;
    E.applyAiBuild(d);
    showToast('🏗️ 「' + d.title + '」落成！' + d.tile_count + ' 格地貌焕新');
    if (d.affinity && d.affinity.delta) showToast('💗 心动 +' + d.affinity.delta);
    closeModal(); togglePanel('build');
  }).catch(function (err) {
    aiBusy = false;
    if (btn) { btn.disabled = false; btn.textContent = '🏗️ 动工'; }
    console.error('[world] aiBuild fetch failed:', err);
    showToast('施工失败：' + (err && err.message ? err.message : '网络异常') + '，稍后再试');
  });
}

function updateBuildBar(bm, br) {
  var bar = $('wBuildBar');
  if (!bar) return;
  bar.style.display = (bm && bm.on) ? '' : 'none';
  if (!bm || !bm.on) return;
  br = br || E.BUILD_BRUSHES[bm.brush];
  $('wbIcon').textContent = br.icon;
  $('wbName').textContent = br.name;
  $('wbCount').textContent = '已涂 ' + bm.painted + ' 格' + (bm.brush === 'restore' ? ' · 免费复原' : ' · ¥5/格+体力2');
  bar.querySelectorAll('.wbs').forEach(function (b) {
    b.classList.toggle('on', +b.dataset.wbs === bm.size);
  });
}

function panelBuild() {
  var S = E.state();
  var brushes = E.BUILD_BRUSHES;
  var bHtml = Object.keys(brushes).map(function (k) {
    var b = brushes[k];
    return '<button class="w-brush' + (buildSel === k ? ' on' : '') + '" data-brush="' + k + '">' +
      '<i>' + b.icon + '</i><span>' + b.name + '</span></button>';
  }).join('');
  var sHtml = [1, 2, 3].map(function (s) {
    return '<button class="w-mini-btn wsz' + (buildSize === s ? ' on' : '') + '" data-wsz="' + s + '">' + s + '×' + s + '</button>';
  }).join('');
  var n = npcDraft || {};
  var posTxt = npcDraft && npcDraft.x != null
    ? '已选位置 (' + npcDraft.x + ', ' + npcDraft.y + ')'
    : (npcDraft && npcDraft.useFeet ? '📍 我的脚下' : '未选（可用地图选点）');
  var eHtml = NPC_EMOJIS.map(function (i) {
    return '<button class="w-emoji' + (i === (n.emoji || '🙂') ? ' on' : '') + '" data-nemoji="' + i + '">' + i + '</button>';
  }).join('');
  var cHtml = NPC_COLORS.map(function (c) {
    return '<button class="w-color-dot' + (c === (n.color || NPC_COLORS[0]) ? ' on' : '') + '" data-ncolor="' + c + '" style="background:' + c + '"></button>';
  }).join('');
  var cnpcs = D.NPCS.filter(function (d) { return d.custom; });
  var npcRows = cnpcs.map(function (d) {
    return '<div class="w-npc-row"><span>' + d.emoji + '</span><b>' + esc(d.name) + '</b>' +
      '<span class="w-sub">(' + Math.floor(d.anchor.x) + ',' + Math.floor(d.anchor.y - 1) + ') · ' + d.lines.length + ' 句台词</span>' +
      '<span class="w-place-x" data-delnpc="' + d.id + '" title="送别">✕</span></div>';
  }).join('');
  var editN = E.worldEditCount();
  return '<div class="w-panel w-panel-build">' +
    '<div class="w-panel-title">🛠️ 世界工坊 · 扩建与创造<div class="w-panel-x" data-close>✕</div></div>' +
    '<div class="w-scroll">' +

      '<div class="w-ws-title">🖌️ 地形笔刷 <small>亲手改造恋语市的每一寸土地</small></div>' +
      '<div class="w-brush-row">' + bHtml + '</div>' +
      '<div class="w-form-row"><label>笔刷大小</label><div>' + sHtml + '</div></div>' +
      '<div class="w-form-row"><label>费用</label><span class="w-sub">每格 ¥5 + 体力 2（🧽 复原免费）· 当前 ¥' + S.player.money + '</span></div>' +
      '<button class="w-btn-main" id="wbsStart">🖌️ 进入建造模式</button>' +

      '<div class="w-ws-sec"></div>' +
      '<div class="w-ws-title">🏗️ AI 智能建设 <small>一句话，让许墨规划一整片风景</small></div>' +
      '<div class="w-form-row"><label>想法</label><input class="w-input" id="waiIdea" maxlength="60" placeholder="例如：带湖心亭的夜樱庭院 / 街角露天剧场 / 滨海灯塔花园" value="' + esc((aiDraft && aiDraft.idea) || '') + '"/></div>' +
      '<div class="w-form-row"><label>位置</label><span class="w-place-pos" id="waiPos">' + esc(aiPosTxt()) + '</span>' +
        '<button class="w-tab" id="waiFeet">📍 我的脚下</button>' +
        '<button class="w-tab" id="waiPick">🗺️ 地图选点</button></div>' +
      '<button class="w-btn-main" id="waiGo">✨ 让许墨规划</button>' +
      '<div class="w-ai-wrap" id="waiPlan">' + aiPlanHtml() + '</div>' +

      '<div class="w-ws-sec"></div>' +
      '<div class="w-ws-title">✨ 智能设计居民 <small>把一个想法交给许墨，他来设计</small></div>' +
      '<div class="w-form-row"><label>想法</label><input class="w-input" id="wnSmartIdea" maxlength="60" placeholder="例如：雨夜书店的诗人 / 公园晨练团 / 会占星的面包师"/></div>' +
      '<div class="w-form-row"><label>人数</label><div id="wnSmartCounts">' +
        [1, 2, 3].map(function (c) {
          return '<button class="w-mini-btn wsn' + (smartCount === c ? ' on' : '') + '" data-wsn="' + c + '">' + c + ' 位</button>';
        }).join('') + '</div></div>' +
      '<button class="w-btn-main" id="wnSmartGo">✨ 让许墨设计</button>' +
      '<div class="w-smart-list" id="wnSmartList">' + smartCardsHtml() + '</div>' +

      '<div class="w-ws-sec"></div>' +
      '<div class="w-ws-title">🧑 新居民 <small>让 TA 住进恋语市，可以对话</small></div>' +
      '<div class="w-form-row"><label>名字</label><input class="w-input" id="wnName" maxlength="12" placeholder="例如：小鹿" value="' + esc(n.name || '') + '"/></div>' +
      '<div class="w-form-row"><label>头像</label><div class="w-emoji-row" id="wnEmojis">' + eHtml + '</div></div>' +
      '<div class="w-form-row"><label>衣色</label><div class="w-color-row" id="wnColors">' + cHtml + '</div></div>' +
      '<div class="w-form-row"><label>台词<small>（每行一句，最多 6 句，聊一次换一句）</small></label>' +
        '<textarea class="w-input" id="wnLines" rows="3" placeholder="今天的晚霞很好看。&#10;听说公园的猫又胖了。">' + esc((n.lines || []).join('\n')) + '</textarea></div>' +
      '<div class="w-form-row"><label>住处</label><span class="w-place-pos" id="wnPos">' + esc(posTxt) + '</span>' +
        '<button class="w-tab" id="wnFeet">📍 我的脚下</button>' +
        '<button class="w-tab" id="wnPick">🗺️ 地图选点</button></div>' +
      '<button class="w-btn-main" id="wnSubmit">🏡 迎进恋语市</button>' +
      (cnpcs.length ? '<div class="w-npc-list">' + npcRows + '</div>' : '') +

      '<div class="w-ws-sec"></div>' +
      '<div class="w-ws-title">📍 新地标 <small>许墨为它作画并点评</small></div>' +
      '<button class="w-btn-main ghost" id="wbsPlace">✨ 去创建自定义地点</button>' +

      '<div class="w-ws-sec"></div>' +
      '<div class="w-ws-title">📐 建筑模板 <small>一键放置预设建筑（在脚下生成）</small></div>' +
      '<div class="w-tpl-grid">' +
        Object.keys(D.BUILD_TEMPLATES).map(function (k) {
          var t = D.BUILD_TEMPLATES[k];
          return '<button class="w-tpl" data-tpl="' + k + '" title="' + esc(t.name + ' · ¥' + t.cost + ' · 体力 ' + t.sp) + '">' +
            '<i>' + t.icon + '</i><span>' + esc(t.name) + '</span><small>¥' + t.cost + '</small></button>';
        }).join('') +
      '</div>' +
      '<div class="w-form-row"><label>提示</label><span class="w-sub">在脚下生成，钱/体力不足会失败</span></div>' +

      '<div class="w-ws-sec"></div>' +
      '<div class="w-ws-title">🗃️ 世界档案</div>' +
      '<div class="w-form-row"><label>地形改造</label><span class="w-sub">' + editN + ' 格</span>' +
        (editN ? '<button class="w-btn-danger small" id="wbsResetEdits">恢复原生地貌</button>' : '') + '</div>' +
      '<div class="w-form-row"><label>自定义地点</label><span class="w-sub">' + D.POIS.filter(function (p) { return p.custom; }).length + ' 处（地图面板可管理）</span></div>' +
    '</div></div>';
}

/* ================= 建模扩展·v2：交通与采集面板 ================= */
function panelTransport() {
  var S = E.state();
  /* 自行车 */
  var onBike = S.vehicle === 'bike';
  /* 公交站点 */
  var stops = D.BUS_STOPS || [];
  var stopRows = stops.map(function (id) {
    var p = E.poiById(id);
    if (!p) return '';
    var dist = Math.round(Math.hypot(p.x - S.player.x, p.y - S.player.y) * 10);
    return '<button class="w-tp-row" data-busstop="' + id + '"><b>' + esc(p.name) + '</b><span>' + dist + 'm · ¥5</span></button>';
  }).join('');
  /* 渡轮码头 */
  var ports = D.FERRY_PORTS || [];
  var portRows = ports.map(function (p) {
    var dist = Math.round(Math.hypot(p.x - S.player.x, p.y - S.player.y) * 10);
    return '<button class="w-tp-row" data-ferry="' + p.id + '"><b>' + esc(p.name) + '</b><span>' + dist + 'm · ¥15</span></button>';
  }).join('');
  /* 采集工具栏 */
  var tools = ['tool_pick', 'tool_rod', 'tool_sickle', 'tool_net', 'tool_axe', 'tool_bucket'];
  var toolRows = tools.map(function (id) {
    var eq = D.EQUIPS[id] || D.NEW_EQUIPS[id];
    if (!eq) return '';
    var has = (S.player.equip.tool === id) || (S.player.bag || []).some(function (s) { return s.id === id; });
    var on = S.player.equip.tool === id;
    return '<button class="w-tpl' + (on ? ' on' : '') + '" data-tool="' + id + '" title="' + esc(eq.name + '：' + eq.desc) + '">' +
      '<i>' + eq.icon + '</i><span>' + esc(eq.name) + '</span><small>' + (has ? (on ? '使用中' : '点击装备') : '未拥有') + '</small></button>';
  }).join('');
  /* 季节信息 */
  var season = E.currentSeason ? E.currentSeason() : 'spring';
  var sDef = D.SEASONS ? D.SEASONS[season] : null;
  var seasonHtml = sDef ? '<div class="w-form-row"><label>季节</label><span class="w-sub">' + sDef.icon + ' ' + sDef.name +
    (season === 'winter' ? '（湖面结冰可走）' : '') +
    (season === 'autumn' ? '（草木转黄）' : '') +
    (season === 'spring' ? '（花开繁盛）' : '') +
    '</span></div>' : '';
  return '<div class="w-panel w-panel-transport">' +
    '<div class="w-panel-title">🚲 交通与采集<div class="w-panel-x" data-close>✕</div></div>' +
    '<div class="w-scroll">' +
      seasonHtml +
      '<div class="w-ws-title">🚲 自行车</div>' +
      '<div class="w-form-row"><label>状态</label><span class="w-sub">' + (onBike ? '骑行中（1.6 倍速，体力 -40%）' : '未骑行') + '</span>' +
      '<button class="w-btn-main" id="wBikeBtn">' + (onBike ? '下车' : '租车 ¥200') + '</button></div>' +
      '<div class="w-ws-sec"></div>' +
      '<div class="w-ws-title">🚌 公交 <small>¥5 / 站</small></div>' +
      '<div class="w-tpl-grid">' + stopRows + '</div>' +
      '<div class="w-ws-sec"></div>' +
      '<div class="w-ws-title">⛴️ 渡轮 <small>¥15 / 程</small></div>' +
      '<div class="w-tpl-grid">' + portRows + '</div>' +
      '<div class="w-ws-sec"></div>' +
      '<div class="w-ws-title">🛠️ 采集工具 <small>装备后采集对应资源</small></div>' +
      '<div class="w-tpl-grid">' + toolRows + '</div>' +
    '</div></div>';
}
function wireTransport() {
  var box = $('wModalBox');
  var S = E.state();
  var bike = box.querySelector('#wBikeBtn');
  if (bike) bike.addEventListener('click', function () {
    if (S.vehicle === 'bike') { E.dismountVehicle(); }
    else { E.rideVehicle('bike'); }
    refreshHUD();
    /* 刷新面板 */
    var old = modalOpen; closeModal();
    if (old) togglePanel('transport');
  });
  box.querySelectorAll('[data-busstop]').forEach(function (b) {
    b.addEventListener('click', function () {
      var toId = b.dataset.busstop;
      /* 找最近的当前站点作为起点 */
      var stops = D.BUS_STOPS || [];
      var best = null, bestD = 1e9;
      stops.forEach(function (id) {
        var p = E.poiById(id); if (!p) return;
        var d = Math.hypot(p.x - S.player.x, p.y - S.player.y);
        if (d < bestD) { bestD = d; best = id; }
      });
      if (best && best !== toId) {
        /* 用 world-engine 的 teleportByTransport（通过 applyAiBuild 间接不可达，改用直接操作） */
        if (S.player.money < 5) { showToast('需要 ¥5'); return; }
        var p = E.poiById(toId);
        if (!p) return;
        S.player.money -= 5;
        var w = E.findWalkableNear(p.x, p.y);
        if (w) { S.player.x = w.x + 0.5; S.player.y = w.y + 0.5; }
        E.save(); refreshHUD(); closeModal();
        showToast('乘坐公交到达 ' + p.name + '（¥-5）');
      }
    });
  });
  box.querySelectorAll('[data-ferry]').forEach(function (b) {
    b.addEventListener('click', function () {
      var toId = b.dataset.ferry;
      var ports = D.FERRY_PORTS || [];
      var best = null, bestD = 1e9;
      ports.forEach(function (p) {
        var d = Math.hypot(p.x - S.player.x, p.y - S.player.y);
        if (d < bestD) { bestD = d; best = p; }
      });
      var to = ports.filter(function (p) { return p.id === toId; })[0];
      if (best && to && best.id !== toId) {
        if (S.player.money < 15) { showToast('需要 ¥15'); return; }
        S.player.money -= 15;
        var w = E.findWalkableNear(Math.floor(to.x), Math.floor(to.y));
        if (w) { S.player.x = w.x + 0.5; S.player.y = w.y + 0.5; }
        E.save(); refreshHUD(); closeModal();
        showToast('乘坐渡轮到达 ' + to.name + '（¥-15）');
      }
    });
  });
  box.querySelectorAll('[data-tool]').forEach(function (b) {
    b.addEventListener('click', function () {
      var id = b.dataset.tool;
      var S = E.state();
      var has = (S.player.bag || []).some(function (s) { return s.id === id; });
      if (!has) { showToast('未拥有此工具，可在超市或工坊获得'); return; }
      S.player.equip.tool = (S.player.equip.tool === id) ? null : id;
      E.save(); refreshHUD();
      /* 刷新面板 */
      var old = modalOpen; closeModal();
      if (old) togglePanel('transport');
    });
  });
}
function refreshSeason() {
  var el = $('wSeason');
  if (!el) return;
  var s = E.currentSeason ? E.currentSeason() : 'spring';
  var def = D.SEASONS ? D.SEASONS[s] : null;
  if (!def) return;
  var txt = def.icon + ' ' + def.name;
  if (el.textContent !== txt) el.textContent = txt;
}

function wireBuild() {
  var box = $('wModalBox');
  /* 建模扩展·v2：建筑模板按钮 */
  box.querySelectorAll('[data-tpl]').forEach(function (b) {
    b.addEventListener('click', function () {
      var tpl = b.dataset.tpl;
      var S = E.state();
      var x = Math.floor(S.player.x), y = Math.floor(S.player.y);
      var r = E.buildTemplate(tpl, x, y);
      if (!r.ok) showToast(r.error || '建造失败');
      else { closeModal(); refreshHUD(); }
    });
  });
  var st = {
    emoji: (npcDraft && npcDraft.emoji) || '🙂',
    color: (npcDraft && npcDraft.color) || NPC_COLORS[0]
  };
  box.querySelectorAll('[data-brush]').forEach(function (b) {
    b.addEventListener('click', function () {
      buildSel = b.dataset.brush;
      box.querySelectorAll('[data-brush]').forEach(function (x2) { x2.classList.remove('on'); });
      b.classList.add('on');
    });
  });
  box.querySelectorAll('[data-wsz]').forEach(function (b) {
    b.addEventListener('click', function () {
      buildSize = +b.dataset.wsz;
      box.querySelectorAll('[data-wsz]').forEach(function (x2) { x2.classList.remove('on'); });
      b.classList.add('on');
    });
  });
  var start = box.querySelector('#wbsStart');
  if (start) start.addEventListener('click', function () {
    E.setBuildMode(true, buildSel, buildSize);
    closeModal();
    showToast('🖌️ 建造模式：点击/拖动画面涂抹 · WASD 移动 · ✅ 完成退出');
  });
  var goPlace = box.querySelector('#wbsPlace');
  if (goPlace) goPlace.addEventListener('click', function () { openPlaceForm(); });

  /* AI 智能建设 */
  var aiFeet = box.querySelector('#waiFeet');
  if (aiFeet) aiFeet.addEventListener('click', function () {
    var S = E.state();
    aiDraft = aiDraft || {};
    aiDraft.x = Math.floor(S.player.x); aiDraft.y = Math.floor(S.player.y);
    var posEl = box.querySelector('#waiPos');
    if (posEl) posEl.textContent = '📍 (' + aiDraft.x + ', ' + aiDraft.y + ')';
  });
  var aiPick = box.querySelector('#waiPick');
  if (aiPick) aiPick.addEventListener('click', function () {
    aiDraft = aiDraft || {};
    aiDraft.idea = box.querySelector('#waiIdea').value;
    aiDraft.x = null; aiDraft.y = null;
    aiPickMode = true;
    closeModal();
    togglePanel('map');
  });
  var aiGo = box.querySelector('#waiGo');
  if (aiGo) aiGo.addEventListener('click', aiDesign);
  renderAiPlan();

  /* 智能设计居民 */
  box.querySelectorAll('[data-wsn]').forEach(function (b) {
    b.addEventListener('click', function () {
      smartCount = +b.dataset.wsn;
      box.querySelectorAll('[data-wsn]').forEach(function (x2) { x2.classList.remove('on'); });
      b.classList.add('on');
    });
  });
  var smartGo = box.querySelector('#wnSmartGo');
  if (smartGo) smartGo.addEventListener('click', smartGenerate);
  wireSmartList();

  /* 新居民表单 */
  box.querySelector('#wnEmojis').querySelectorAll('[data-nemoji]').forEach(function (b) {
    b.addEventListener('click', function () {
      st.emoji = b.dataset.nemoji;
      box.querySelectorAll('#wnEmojis .w-emoji').forEach(function (x2) { x2.classList.remove('on'); });
      b.classList.add('on');
    });
  });
  box.querySelector('#wnColors').querySelectorAll('[data-ncolor]').forEach(function (b) {
    b.addEventListener('click', function () {
      st.color = b.dataset.ncolor;
      box.querySelectorAll('#wnColors .w-color-dot').forEach(function (x2) { x2.classList.remove('on'); });
      b.classList.add('on');
    });
  });
  box.querySelector('#wnFeet').addEventListener('click', function () {
    var S = E.state();
    npcDraft = npcDraft || {};
    npcDraft.x = Math.floor(S.player.x);
    npcDraft.y = Math.floor(S.player.y);
    npcDraft.useFeet = true;
    box.querySelector('#wnPos').textContent = '📍 我的脚下 (' + npcDraft.x + ', ' + npcDraft.y + ')';
  });
  box.querySelector('#wnPick').addEventListener('click', function () {
    npcDraft = npcDraft || {};
    npcDraft.name = box.querySelector('#wnName').value;
    npcDraft.lines = box.querySelector('#wnLines').value.split('\n');
    npcDraft.x = null; npcDraft.y = null;
    npcPickMode = true;
    closeModal();
    togglePanel('map');
  });
  var submit = box.querySelector('#wnSubmit');
  submit.addEventListener('click', function () {
    var name = box.querySelector('#wnName').value.trim();
    if (!name) { showToast('先给居民起个名字吧'); return; }
    var lines = box.querySelector('#wnLines').value.split('\n')
      .map(function (l) { return l.trim(); }).filter(function (l) { return l; });
    if (!lines.length) { showToast('至少写一句 TA 会说的话'); return; }
    var S = E.state();
    var px = (npcDraft && npcDraft.x != null) ? npcDraft.x : Math.floor(S.player.x);
    var py = (npcDraft && npcDraft.y != null) ? npcDraft.y : Math.floor(S.player.y);
    if (submit.disabled) return;
    submit.disabled = true; submit.textContent = '🏡 正在搬进恋语市……';
    fetch('/api/world/npcs', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name: name, emoji: st.emoji, color: st.color, lines: lines, x: px, y: py })
    }).then(function (r) { return r.json(); }).then(function (d) {
      if (d.error) { submit.disabled = false; submit.textContent = '🏡 迎进恋语市'; showToast(d.error); return; }
      npcDraft = null; npcPickMode = false;
      E.applyCustomNpc(d.npc);
      showToast('🧑 「' + d.npc.name + '」住进了恋语市（' + px + ', ' + py + '）');
      if (d.affinity && d.affinity.delta) showToast('💗 心动 +' + d.affinity.delta);
      closeModal(); togglePanel('build');
    }).catch(function () {
      submit.disabled = false; submit.textContent = '🏡 迎进恋语市';
      showToast('创建失败，请稍后重试');
    });
  });
  /* 送别居民 */
  box.querySelectorAll('[data-delnpc]').forEach(function (btn) {
    btn.addEventListener('click', function () {
      var id = btn.dataset.delnpc;
      if (!confirm('送别这位居民？TA 会离开恋语市。')) return;
      fetch('/api/world/npcs/' + id, { method: 'DELETE' })
        .then(function (r) { return r.json(); })
        .then(function (d) {
          if (d.ok) {
            E.removeCustomNpc(id);
            showToast('TA 挥挥手，消失在街角。');
            closeModal(); togglePanel('build');
          } else showToast(d.error || '操作失败');
        })
        .catch(function () { showToast('操作失败'); });
    });
  });
  /* 恢复原生地貌 */
  var rst = box.querySelector('#wbsResetEdits');
  if (rst) rst.addEventListener('click', function () {
    if (!confirm('清空全部地形改造，恢复恋语市原生地貌？')) return;
    fetch('/api/world/edits', { method: 'DELETE' })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        if (d.ok) {
          E.resetWorldEdits();
          showToast('已恢复原生地貌');
          closeModal(); togglePanel('build');
        }
      }).catch(function () { showToast('操作失败'); });
  });
}

/* ---- 任务面板（可领取 · 可追踪） ---- */
function sideTitle(id) {
  for (var i = 0; i < D.SIDE_QUESTS.length; i++) if (D.SIDE_QUESTS[i].id === id) return D.SIDE_QUESTS[i].title;
  return id;
}
function panelQuest() {
  var S = E.state();
  var track = S.questTrack || null;
  var st = S.mainStage;
  var main = D.MAIN_STAGES[Math.min(st, D.MAIN_STAGES.length - 1)];
  var shards = (S.counters.shard || 0);
  var objTxt = '';
  if (st === 1) objTxt = '<div class="w-q-obj">记忆碎片：' + Math.min(shards, 3) + ' / 3</div>';
  if (st === 4) {
    var parts = [];
    parts.push((S.worldFlags.gear_done ? '✔' : '✘') + ' 齿轮');
    parts.push((E.hasItem('lens') || S.worldFlags.lighthouse_lit ? '✔' : '✘') + ' 透镜');
    parts.push((E.hasItem('bulb') || S.worldFlags.lighthouse_lit ? '✔' : '✘') + ' 灯泡');
    objTxt = '<div class="w-q-obj">' + parts.join(' · ') + '</div>';
  }
  var mainDone = st >= 5;
  var mainBtn = mainDone ? '' :
    '<button class="w-q-btn' + (track === 'main' ? ' on' : '') + '" data-track="main">' +
    (track === 'main' ? '✓ 追踪中' : '🎯 追踪') + '</button>';
  var sideHtml = D.SIDE_QUESTS.map(function (q) {
    var s = S.sides[q.id] || { state: 0 };
    /* s1 完成态但未领谢礼 → 仍可进行 */
    var finished = s.state === 3 && !(q.id === 's1' && !S.flags.s1_done_talk);
    var stateTxt = finished ? '已完成' : s.state === 0 ? '未领取' : (s.state === 2 || (q.id === 's1' && s.state === 3)) ? '待交付' : '进行中';
    var cls = finished ? 'done' : s.state >= 1 ? 'active' : '';
    var prog = '';
    if (q.id === 's1' && s.state === 2) prog = '（带上猫粮去找墨鱼）';
    if (q.id === 's2' && s.state === 1) prog = '（' + (S.counters.page || 0) + '/3 页）';
    if (q.id === 's3' && s.state === 1) prog = '（' + (S.counters.lore || 0) + '/3 段）';
    if (q.id === 's4' && s.state === 1) prog = '（' + (S.counters.photo || 0) + '/3 张）';
    if (q.id === 's5' && s.state === 1) prog = '（' + (S.counters.dew || 0) + '/3 朵）';
    if (q.id === 's6' && s.state === 1) prog = '（' + (S.counters.iron || 0) + '/3 块）';
    var ops = '', tip = '';
    if (finished) ops = '<span class="w-q-done">✔ 已完成</span>';
    else if (s.state === 0) {
      var ok = !q.lock || q.lock(S);
      ops = ok
        ? '<button class="w-q-btn take" data-take="' + q.id + '">📱 电话领取</button>'
        : '<span class="w-q-lock">🔒 ' + esc(q.lockTxt) + '</span>';
    } else {
      ops = '<button class="w-q-btn' + (track === q.id ? ' on' : '') + '" data-track="' + q.id + '">' +
        (track === q.id ? '✓ 追踪中' : '🎯 追踪') + '</button>';
      var g = E.questGuide(q.id);
      if (g) tip = g.tip;
    }
    return '<div class="w-q-item ' + cls + (track === q.id ? ' tracking' : '') + '">' +
      '<div class="w-q-t">' + esc(q.title) + '<span class="w-q-st">' + stateTxt + '</span></div>' +
      '<div class="w-q-d">' + esc(q.giver) + ' · ' + esc(q.desc) + esc(prog) + '</div>' +
      (tip ? '<div class="w-q-tip">🎯 ' + esc(tip) + '</div>' : '') +
      (finished ? '' : '<div class="w-q-reward">🎁 ' + esc(q.reward || '') + '</div>') +
      '<div class="w-q-ops">' + ops + '</div></div>';
  }).join('');
  return '<div class="w-panel">' +
    '<div class="w-panel-title">📋 任务' +
    '<div class="w-panel-x" data-close>✕</div></div>' +
    '<div class="w-scroll">' +
      '<div class="w-q-main">' +
        '<div class="w-q-tag">主线 ' + Math.min(st + 1, 6) + '/6</div>' +
        '<div class="w-q-t big">' + esc(main.title) + '</div>' +
        '<div class="w-q-d">' + esc(main.hint) + '</div>' + objTxt +
        '<div class="w-q-ops">' + mainBtn + '</div>' +
      '</div>' +
      '<div class="w-q-sec">支线 <small class="w-q-note">未领取的委托可电话接单，无需跑腿</small></div>' + sideHtml +
    '</div></div>';
}
function wireQuest() {
  var box = $('wModalBox');
  box.querySelectorAll('[data-take]').forEach(function (b) {
    b.addEventListener('click', function () {
      var id = b.dataset.take;
      var G = E.makeG();
      G.startSide(id);
      if (id === 's4') G.give('camera', 1);
      E.logWorld('quest', '接下了委托「' + sideTitle(id) + '」');
      showToast('📱 电话接单：' + sideTitle(id) + '（已自动追踪）');
      E.setTrack(id);
      E.save();
      closeModal(); togglePanel('quest');
    });
  });
  box.querySelectorAll('[data-track]').forEach(function (b) {
    b.addEventListener('click', function () {
      var id = b.dataset.track;
      var same = (E.state().questTrack === id);
      E.setTrack(same ? null : id);
      showToast(same ? '已取消追踪' : '🎯 正在追踪：' + (id === 'main' ? '主线' : sideTitle(id)));
      closeModal(); togglePanel('quest');
    });
  });
}

/* ---- 背包面板 ---- */
var bagTab = 'all';
function panelBag() {
  var S = E.state();
  var p = S.player;
  var kinds = { all: '全部', mat: '材料', food: '食物', key: '关键', eq: '装备' };
  var tabs = '';
  for (var k in kinds) tabs += '<button class="w-tab' + (bagTab === k ? ' on' : '') + '" data-tab="' + k + '">' + kinds[k] + '</button>';
  var items = p.bag.filter(function (slot) {
    if (bagTab === 'all') return true;
    var it = D.ITEMS[slot.id] || D.EQUIPS[slot.id];
    if (!it) return false;
    if (bagTab === 'eq') return !!D.EQUIPS[slot.id];
    return it.kind === bagTab;
  });
  var list = items.map(function (slot) {
    var eq = D.EQUIPS[slot.id];
    var it = eq || D.ITEMS[slot.id];
    if (!it) return '';
    var qcolor = ['#9ca3af', '#9ca3af', '#22c55e', '#3b82f6', '#a855f7'][eq ? eq.q : 1];
    var right = '';
    if (eq) {
      var on = p.equip[eq.slot] === slot.id;
      right = '<button class="w-mini-btn" data-equip="' + slot.id + '"' + (on ? ' disabled' : '') + '>' + (on ? '已装备' : '装备') + '</button>';
    } else if (it.kind === 'food') {
      right = '<button class="w-mini-btn" data-use="' + slot.id + '">使用</button>';
    }
    var stat = eq ? [eq.atk ? '攻击+' + eq.atk : '', eq.spd ? '速度+' + eq.spd + '%' : '', eq.hp ? '生命+' + eq.hp : '', eq.aff ? '好感+' + eq.aff + '%' : ''].filter(Boolean).join(' ') : '';
    return '<div class="w-bag-item">' +
      '<div class="w-bag-icon">' + it.icon + '</div>' +
      '<div class="w-bag-info"><div style="color:' + qcolor + '">' + esc(it.name) + ' <span class="w-qty">×' + slot.qty + '</span></div>' +
      '<div class="w-sub">' + esc(stat || it.desc) + '</div></div>' + right + '</div>';
  }).join('') || '<div class="w-empty">空空如也</div>';
  var eqRow = '';
  ['weapon', 'shoes', 'charm'].forEach(function (slotK) {
    var id = p.equip[slotK], eq = id && D.EQUIPS[id];
    eqRow += '<div class="w-eq-slot">' + ({ weapon: '武器', shoes: '鞋子', charm: '护符' })[slotK] + '：' + (eq ? eq.icon + ' ' + esc(eq.name) : '—') + '</div>';
  });
  return '<div class="w-panel">' +
    '<div class="w-panel-title">🎒 背包<div class="w-panel-x" data-close>✕</div></div>' +
    '<div class="w-eq-bar">' + eqRow + '</div>' +
    '<div class="w-tabs">' + tabs + '</div>' +
    '<div class="w-scroll" id="wBagList">' + list + '</div></div>';
}
function wireBag() {
  var box = $('wModalBox');
  box.querySelectorAll('[data-tab]').forEach(function (b) {
    b.addEventListener('click', function () { bagTab = b.dataset.tab; togglePanel('bag'); });
  });
  box.querySelectorAll('[data-use]').forEach(function (b) {
    b.addEventListener('click', function () {
      var id = b.dataset.use;
      var it = D.ITEMS[id];
      var S = E.state(), st = E.calcStats();
      if (!it) return;
      S.player.hp = Math.min(st.hpMax, S.player.hp + (it.hp || 0));
      S.player.sp = Math.min(st.spMax, S.player.sp + (it.sp || 0));
      E.takeItem(id, 1);
      showToast('吃掉了 ' + it.icon + ' ' + it.name);
      refreshHUD();
      togglePanel('bag');
    });
  });
  box.querySelectorAll('[data-equip]').forEach(function (b) {
    b.addEventListener('click', function () {
      var id = b.dataset.equip;
      var eq = D.EQUIPS[id];
      E.state().player.equip[eq.slot] = id;
      showToast('装备了 ' + eq.icon + ' ' + eq.name);
      refreshHUD();
      togglePanel('bag');
    });
  });
}

/* ---- 技能面板 ---- */
function panelSkill() {
  var S = E.state();
  var lines = [
    { id: 'per', name: '感知', icon: '👁️', color: '#0ea5e9' },
    { id: 'min', name: '心灵 · Evol', icon: '🌀', color: '#a855f7' },
    { id: 'bod', name: '体术', icon: '💪', color: '#f97316' }
  ];
  var cols = lines.map(function (line) {
    var tiers = D.SKILLS.filter(function (s) { return s.line === line.id; }).sort(function (a, b) { return a.tier - b.tier; });
    var nodes = tiers.map(function (s) {
      var learned = E.hasSkill(s.id);
      var can = learned ? false : (!s.req || E.hasSkill(s.req)) && S.player.skillPts > 0;
      return '<div class="w-sk-node ' + (learned ? 'learned' : can ? 'can' : '') + '" data-skill="' + s.id + '">' +
        '<div class="w-sk-icon">' + s.icon + '</div>' +
        '<div class="w-sk-info"><b>' + esc(s.name) + '</b><span>' + esc(s.desc) + '</span></div>' +
        '<div class="w-sk-st">' + (learned ? '✔' : can ? '＋1点' : s.req && !E.hasSkill(s.req) ? '🔒' : '—') + '</div></div>';
    }).join('');
    return '<div class="w-sk-col"><div class="w-sk-line" style="border-color:' + line.color + '44">' + line.icon + ' ' + esc(line.name) + '</div>' + nodes + '</div>';
  }).join('');
  return '<div class="w-panel">' +
    '<div class="w-panel-title">🌟 技能 · 可用点数 <b class="w-sk-pts">' + S.player.skillPts + '</b><div class="w-panel-x" data-close>✕</div></div>' +
    '<div class="w-scroll"><div class="w-sk-grid">' + cols + '</div></div></div>';
}
function wireSkill() {
  $('wModalBox').querySelectorAll('[data-skill]').forEach(function (el) {
    el.addEventListener('click', function () {
      var id = el.dataset.skill;
      var S = E.state();
      var def = null;
      D.SKILLS.forEach(function (s) { if (s.id === id) def = s; });
      if (!def || E.hasSkill(id)) return;
      if (def.req && !E.hasSkill(def.req)) { showToast('需要先学会前置技能'); return; }
      if (S.player.skillPts < 1) { showToast('技能点不足'); return; }
      S.player.skillPts--;
      S.player.skills.push(id);
      E.gainExp(0);
      showToast('学会技能：' + def.icon + ' ' + def.name);
      refreshHUD();
      togglePanel('skill');
    });
  });
}

/* ---- 地图面板 ---- */
function panelMap() {
  var custom = D.POIS.filter(function (p) { return p.custom; });
  var listHtml = custom.map(function (p) {
    return '<div class="w-place-row"><span class="w-place-ic">' + p.icon + '</span>' +
      '<span class="w-place-nm">' + esc(p.name) + '</span>' +
      '<span class="w-place-co">(' + p.x + ',' + p.y + ')</span>' +
      '<span class="w-place-x" data-delplace="' + p.id + '" title="删除">✕</span></div>';
  }).join('');
  return '<div class="w-panel w-panel-map">' +
    '<div class="w-panel-title">🗺️ 恋语市 · 全域地图<div class="w-panel-x" data-close>✕</div></div>' +
    '<div class="w-map-wrap"><canvas id="wBigMap" width="576" height="576"></canvas>' +
    '<div class="w-map-legend" id="wMapLegend"></div></div>' +
    '<div class="w-place-bar"><button class="w-btn-main ghost w-place-add" id="wPlaceAdd">＋ 新建自定义地点</button>' +
      '<button class="w-btn-main ghost" id="wWorkshop">🛠️ 世界工坊</button></div>' +
    (custom.length ? '<div class="w-place-list">' + listHtml + '</div>' : '') +
    '</div>';
}
function drawBigMap() {
  var c = $('wBigMap');
  if (!c) return;
  var g = c.getContext('2d');
  var scale = 4;   // 144*4=576
  var S = E.state();
  g.fillStyle = '#f6f2fd';
  g.fillRect(0, 0, 576, 576);
  var step = 2;
  for (var y = 0; y < D.MAP_H; y += step)
    for (var x = 0; x < D.MAP_W; x += step) {
      var i = y * D.MAP_W + x;
      var st = D.BIOME_STYLE[worldBiome(x, y)];
      if (!st) continue;
      g.fillStyle = st.base;
      g.fillRect(x * scale, y * scale, step * scale, step * scale);
    }
  /* 迷雾：未探索区域遮盖（若无天眼/未探索） */
  var reveal = E.hasSkill('per5') || !!(S && S.revealMap);
  if (!reveal) {
    g.fillStyle = 'rgba(238,234,248,.9)';
    for (var y2 = 0; y2 < D.MAP_H; y2 += step)
      for (var x2 = 0; x2 < D.MAP_W; x2 += step)
        if (!exploredAt(x2, y2)) g.fillRect(x2 * scale, y2 * scale, step * scale, step * scale);
  }
  /* POI 标记 */
  var marks = [];
  D.POIS.forEach(function (p) {
    if (p.hidden && !S.worldFlags[p.id + '_found']) {
      var dd = Math.hypot(p.x - S.player.x, p.y - S.player.y);
      if (dd > 10) return;
    }
    marks.push('<span>' + p.icon + ' ' + esc(p.name) + '</span>');
    g.font = '14px "Segoe UI Emoji",sans-serif';
    g.textAlign = 'center'; g.textBaseline = 'middle';
    if (p.custom) {
      g.fillStyle = 'rgba(147,51,234,.3)';
      g.beginPath(); g.arc((p.x + (p.w || 1) / 2) * scale, (p.y + (p.h || 1) / 2) * scale, 11, 0, Math.PI * 2); g.fill();
    }
    if (p.pulseEv) {
      g.fillStyle = 'rgba(245,158,11,.38)';
      g.beginPath(); g.arc((p.x + 0.5) * scale, (p.y + 0.5) * scale, 10, 0, Math.PI * 2); g.fill();
      g.strokeStyle = '#f59e0b'; g.lineWidth = 1.5;
      g.beginPath(); g.arc((p.x + 0.5) * scale, (p.y + 0.5) * scale, 13, 0, Math.PI * 2); g.stroke();
    }
    g.fillText(p.icon, (p.x + (p.w || 1) / 2) * scale, (p.y + (p.h || 1) / 2) * scale);
  });
  /* 主线指引 */
  var guide = E.mainGuidePoint();
  if (guide) {
    g.fillStyle = '#ea580c';
    g.strokeStyle = '#fff'; g.lineWidth = 2;
    g.beginPath(); g.arc(guide.x * scale, guide.y * scale, 8, 0, Math.PI * 2); g.fill(); g.stroke();
  }
  /* 任务追踪目标（紫 🎯） */
  var trackTag = '';
  var tg = E.trackedGuide();
  if (tg) {
    var tp = 0.6 + Math.sin(performance.now() / 300) * 0.4;
    g.fillStyle = 'rgba(147,51,234,.22)';
    g.beginPath(); g.arc(tg.x * scale, tg.y * scale, 11 + tp * 4, 0, Math.PI * 2); g.fill();
    g.strokeStyle = '#7c3aed'; g.lineWidth = 2;
    g.setLineDash([5, 4]);
    g.beginPath(); g.arc(tg.x * scale, tg.y * scale, 11 + tp * 4, 0, Math.PI * 2); g.stroke();
    g.setLineDash([]);
    g.font = '14px "Segoe UI Emoji",sans-serif';
    g.textAlign = 'center'; g.textBaseline = 'middle';
    g.fillText('🎯', tg.x * scale, tg.y * scale - 15 - tp * 3);
    trackTag = ' · <b style="color:#7c3aed">🎯 追踪</b>';
  }
  /* 玩家 */
  g.fillStyle = '#ff2d78';
  g.strokeStyle = '#fff'; g.lineWidth = 2;
  g.beginPath(); g.arc(S.player.x * scale, S.player.y * scale, 6, 0, Math.PI * 2); g.fill(); g.stroke();
  /* 选点模式：已选位置准星 */
  var legend = '<b>📍 你</b> · <b style="color:#ea580c">⬤ 目标</b>' + trackTag + marks.join(' · ');
  if (npcPickMode) {
    legend = '<b style="color:#0ea5e9">🖱️ 点击地图，为新居民选择住处</b> · ' + legend;
    if (npcDraft && npcDraft.x != null) {
      g.strokeStyle = '#0ea5e9'; g.lineWidth = 2; g.setLineDash([4, 3]);
      g.beginPath(); g.arc(npcDraft.x * scale, npcDraft.y * scale, 10, 0, Math.PI * 2); g.stroke();
      g.setLineDash([]);
    }
  }
  if (placePickMode) {
    legend = '<b style="color:#9333ea">🖱️ 点击地图，为「' + esc((placeDraft && placeDraft.name) || '新地点') + '」选择位置</b> · ' + legend;
    if (placeDraft && placeDraft.x != null) {
      g.strokeStyle = '#9333ea'; g.lineWidth = 2; g.setLineDash([4, 3]);
      g.beginPath(); g.arc(placeDraft.x * scale, placeDraft.y * scale, 10, 0, Math.PI * 2); g.stroke();
      g.setLineDash([]);
      g.beginPath();
      g.moveTo(placeDraft.x * scale - 14, placeDraft.y * scale);
      g.lineTo(placeDraft.x * scale + 14, placeDraft.y * scale);
      g.moveTo(placeDraft.x * scale, placeDraft.y * scale - 14);
      g.lineTo(placeDraft.x * scale, placeDraft.y * scale + 14);
      g.stroke();
    }
  }
  $('wMapLegend').innerHTML = legend;
}
/* 引擎暴露的地图数据访问（只读渲染用） */
function worldBiome(x, y) { return E.mapSample ? E.mapSample(x, y) : 3; }
function exploredAt(x, y) { return E.exploredAt ? E.exploredAt(x, y) : false; }

/* ---- 自定义地点：新建表单 / 地点卡 / 地图选点 ---- */
var placeDraft = null, placePickMode = false, placeImg = null;
var PLACE_ICONS = ['📍', '🌸', '☕', '🎡', '🌉', '🕯️', '🎭', '🎠', '🏝️', '🎸', '🎂', '🛶'];
var PLACE_STYLES = [
  ['sunset', '🌇 黄昏暮色'], ['night', '🌃 城市夜色'], ['rain', '🌧️ 细雨朦胧'],
  ['spring', '🌸 春日花语'], ['snow', '❄️ 落雪时分'], ['dream', '🦋 蝶梦幻境'], ['free', '✨ 自由风格']
];

function openPlaceForm() {
  var p = placeDraft || {};
  var icon = p.icon || '📍', kind = p.kind || 'build', style = p.style || 'sunset', ratio = p.ratio || 'landscape';
  var posTxt = p.x != null ? '已选位置 (' + p.x + ', ' + p.y + ')' : '📍 我的脚下（当前角色位置）';
  var iconHtml = PLACE_ICONS.map(function (i) {
    return '<button class="w-emoji' + (i === icon ? ' on' : '') + '" data-emoji="' + i + '">' + i + '</button>';
  }).join('');
  var styleHtml = PLACE_STYLES.map(function (s) {
    return '<button class="w-tab' + (s[0] === style ? ' on' : '') + '" data-style="' + s[0] + '">' + s[1] + '</button>';
  }).join('');
  var ratioHtml = [['square', '方形'], ['portrait', '竖版'], ['landscape', '横版']].map(function (r) {
    return '<button class="w-tab' + (r[0] === ratio ? ' on' : '') + '" data-ratio="' + r[0] + '">' + r[1] + '</button>';
  }).join('');
  openModal(
    '<div class="w-panel w-place-form">' +
      '<div class="w-panel-title">✨ 新建自定义地点<div class="w-panel-x" data-close>✕</div></div>' +
      '<div class="w-scroll">' +
        '<div class="w-form-row"><label>名称</label><input class="w-input" id="wpName" maxlength="20" placeholder="例如：初遇的天文馆" value="' + esc(p.name || '') + '"/></div>' +
        '<div class="w-form-row"><label>描述<small>（选填）</small></label><textarea class="w-input" id="wpDesc" rows="2" placeholder="它是什么样子？发生过什么？">' + esc(p.desc || '') + '</textarea></div>' +
        '<div class="w-form-row"><label>图标</label><div class="w-emoji-row" id="wpIcons">' + iconHtml + '</div></div>' +
        '<div class="w-form-row"><label>类型</label><div id="wpKinds">' +
          '<button class="w-tab' + (kind === 'build' ? ' on' : '') + '" data-kind="build">🏠 建筑</button>' +
          '<button class="w-tab' + (kind === 'mark' ? ' on' : '') + '" data-kind="mark">🗿 地标</button></div></div>' +
        '<div class="w-form-row"><label>配图风格</label><div class="w-tab-row" id="wpStyles">' + styleHtml + '</div></div>' +
        '<div class="w-form-row"><label>画幅</label><div class="w-tab-row" id="wpRatios">' + ratioHtml + '</div></div>' +
        '<div class="w-form-row"><label>参考图<small>（选填，图生图）</small></label>' +
          '<div class="w-place-up" id="wpUp"><input type="file" id="wpFile" accept="image/*" style="display:none"/>' +
          '<img id="wpUpImg" style="display:none" alt="参考图"/><span id="wpUpTxt">📤 上传参考图（可选）</span></div></div>' +
        '<div class="w-form-row"><label>位置</label><span class="w-place-pos" id="wpPos">' + esc(posTxt) + '</span>' +
          '<button class="w-tab" id="wpPick">🗺️ 地图选点</button></div>' +
        '<button class="w-btn-main" id="wpSubmit">🎨 让许墨为它作画并落成</button>' +
      '</div></div>', 'place-form');

  var box = $('wModalBox');
  var st = { icon: icon, kind: kind, style: style, ratio: ratio };
  box.querySelector('#wpIcons').querySelectorAll('.w-emoji').forEach(function (b) {
    b.addEventListener('click', function () {
      st.icon = b.dataset.emoji;
      box.querySelectorAll('.w-emoji').forEach(function (x2) { x2.classList.remove('on'); });
      b.classList.add('on');
    });
  });
  box.querySelector('#wpKinds').querySelectorAll('[data-kind]').forEach(function (b) {
    b.addEventListener('click', function () {
      st.kind = b.dataset.kind;
      box.querySelectorAll('#wpKinds .w-tab').forEach(function (x2) { x2.classList.remove('on'); });
      b.classList.add('on');
    });
  });
  box.querySelector('#wpStyles').querySelectorAll('[data-style]').forEach(function (b) {
    b.addEventListener('click', function () {
      st.style = b.dataset.style;
      box.querySelectorAll('#wpStyles .w-tab').forEach(function (x2) { x2.classList.remove('on'); });
      b.classList.add('on');
    });
  });
  box.querySelector('#wpRatios').querySelectorAll('[data-ratio]').forEach(function (b) {
    b.addEventListener('click', function () {
      st.ratio = b.dataset.ratio;
      box.querySelectorAll('#wpRatios .w-tab').forEach(function (x2) { x2.classList.remove('on'); });
      b.classList.add('on');
    });
  });
  /* 参考图上传（压缩为 dataURL） */
  var upImg = box.querySelector('#wpUpImg'), upTxt = box.querySelector('#wpUpTxt');
  box.querySelector('#wpUp').addEventListener('click', function () { box.querySelector('#wpFile').click(); });
  box.querySelector('#wpFile').addEventListener('change', function (e) {
    var f = e.target.files[0];
    e.target.value = '';
    if (!f || f.type.indexOf('image/') !== 0) { showToast('请选择图片文件'); return; }
    if (f.size > 8 * 1024 * 1024) { showToast('图片不能超过 8MB'); return; }
    var objUrl = URL.createObjectURL(f);
    var img = new Image();
    img.onload = function () {
      var canvas = document.createElement('canvas');
      var max = 1120, w = img.width, h = img.height;
      if (w > max || h > max) { var r = Math.min(max / w, max / h); w = Math.round(w * r); h = Math.round(h * r); }
      canvas.width = w; canvas.height = h;
      canvas.getContext('2d').drawImage(img, 0, 0, w, h);
      placeImg = canvas.toDataURL('image/jpeg', 0.85);
      upImg.src = placeImg; upImg.style.display = 'block';
      upTxt.textContent = '✅ 已选参考图（点击可更换）';
      URL.revokeObjectURL(objUrl);
    };
    img.onerror = function () { showToast('图片读取失败'); URL.revokeObjectURL(objUrl); };
    img.src = objUrl;
  });
  /* 地图选点：暂存草稿 → 地图面板点击 */
  box.querySelector('#wpPick').addEventListener('click', function () {
    placeDraft = {
      name: box.querySelector('#wpName').value, desc: box.querySelector('#wpDesc').value,
      x: placeDraft && placeDraft.x, y: placeDraft && placeDraft.y
    };
    for (var k in st) placeDraft[k] = st[k];
    placePickMode = true;
    closeModal();
    togglePanel('map');
  });
  /* 提交 */
  var submit = box.querySelector('#wpSubmit');
  submit.addEventListener('click', function () {
    var name = box.querySelector('#wpName').value.trim();
    if (!name) { showToast('先给地点起个名字吧'); return; }
    var S = E.state();
    var px = (placeDraft && placeDraft.x != null) ? placeDraft.x : Math.floor(S.player.x);
    var py = (placeDraft && placeDraft.y != null) ? placeDraft.y : Math.floor(S.player.y);
    if (submit.disabled) return;
    submit.disabled = true; submit.textContent = '🎨 许墨正在看图构思……';
    fetch('/api/world/places', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        name: name, desc: box.querySelector('#wpDesc').value.trim(),
        icon: st.icon, kind: st.kind, style: st.style, ratio: st.ratio,
        x: px, y: py, image: placeImg || ''
      })
    }).then(function (r) { return r.json(); }).then(function (d) {
      if (d.error) { submit.disabled = false; submit.textContent = '🎨 让许墨为它作画并落成'; showToast(d.error); return; }
      placeDraft = null; placeImg = null; placePickMode = false;
      closeModal();
      E.applyCustomPlace(d.place);
      showToast('📍 「' + d.place.name + '」已落成恋语市');
      if (d.affinity && d.affinity.delta) showToast('💗 心动 +' + d.affinity.delta);
      /* 生成图自动存入相册 */
      if (window.addPhotoFromUrl && d.place.img) {
        window.addPhotoFromUrl(d.place.img, function (ok) { if (ok) showToast('📸 配图已存入相册'); });
      }
      openPlaceCard(d.place);
    }).catch(function () {
      submit.disabled = false; submit.textContent = '🎨 让许墨为它作画并落成';
      showToast('创建失败，请稍后重试');
    });
  });
}

function openPlaceCard(p) {
  /* 建筑入内路由：若该 POI 有室内场景配置，优先切换到室内视图 */
  if (p && p.id && window.WORLD_DATA && window.WORLD_DATA.INTERIORS && window.WORLD_DATA.INTERIORS[p.id]) {
    return openInterior(p);
  }
  openModal(
    '<div class="w-panel w-place-card">' +
      '<div class="w-panel-title">' + (p.icon || '📍') + ' ' + esc(p.name) + '<div class="w-panel-x" data-close>✕</div></div>' +
      '<div class="w-scroll">' +
        (p.img ? '<img class="w-place-img" src="' + p.img + '" alt="地点配图"/>' : '') +
        '<div class="w-place-desc">' + esc(p.desc || '').replace(/\n/g, '<br>') + '</div>' +
        (p.comment ? '<div class="w-place-cmt"><b>许墨：</b>' + esc(p.comment) + '</div>' : '') +
        (p.img ? '<button class="w-btn-main ghost" id="wpAlbum">📸 存入相册</button>' : '') +
        '<button class="w-btn-main" data-close>（离开）</button>' +
      '</div></div>', 'place-card');
  var box = $('wModalBox');
  box.querySelectorAll('[data-close]').forEach(function (x) { x.addEventListener('click', function () { closeModal(); }); });
  var alb = box.querySelector('#wpAlbum');
  if (alb) alb.addEventListener('click', function () {
    if (window.addPhotoFromUrl) window.addPhotoFromUrl(p.img, function (ok) { showToast(ok ? '📸 已存入相册' : '存入相册失败'); });
  });
}

/* ================= 建筑入内·室内场景（全屏 AI 插画 + 热点叠加） ================= */
function openInterior(p) {
  var D = window.WORLD_DATA || {};
  var cfg = D.INTERIORS && D.INTERIORS[p.id];
  if (!cfg) { return openPlaceCard(p); }   /* 无配置 → 回退普通卡片 */
  /* 加载中态：AI 生图可能耗时 10-30s */
  openModal('<div class="w-int-loading">正在进入「' + esc(p.name || cfg.name) + '」...<br><small style="opacity:.7">许墨正在为你描绘室内</small></div>', 'interior', { lock: true });
  fetch('/api/world/interiors/' + encodeURIComponent(p.id), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name: p.name || cfg.name, prompt_hint: cfg.prompt_hint || '' })
  }).then(function (r) { return r.json(); }).then(function (d) {
    if (d.error) { showToast(d.error); closeModal(); return; }
    renderInterior(p, cfg, d.interior || {});
  }).catch(function () { showToast('进入失败：网络异常'); closeModal(); });
}

function renderInterior(p, cfg, d) {
  var img = d.img || '';
  var desc = d.desc || cfg.prompt_hint || '';
  var cmt = d.comment || '';
  var html = '<div class="w-interior">' +
    '<div class="w-int-bg" style="background-image:url(\'' + esc(img) + '\')"></div>' +
    '<div class="w-int-top">' +
      '<button class="w-int-back" data-close>‹ 离开</button>' +
      '<div class="w-int-title">' + (cfg.icon || p.icon || '📍') + ' ' + esc(p.name || cfg.name) + '</div>' +
    '</div>' +
    (cmt ? '<div class="w-int-cmt">' + esc(cmt) + '</div>' : '') +
    '<div class="w-int-hotspots">' +
      cfg.hotspots.map(function (h) {
        return '<button class="w-int-hotspot type-' + h.type + '" style="left:' + h.x + '%;top:' + h.y + '%" ' +
          'data-hot="' + esc(h.id) + '" data-type="' + esc(h.type) + '" data-label="' + esc(h.label) + '" title="' + esc(h.label) + '">' +
          '<span class="w-hot-icon">' + h.icon + '</span><span class="w-hot-label">' + esc(h.label) + '</span></button>';
      }).join('') +
    '</div>' +
    '<div class="w-int-desc">' + esc(desc).replace(/\n/g, '<br>') + '</div>' +
    '</div>';
  openModal(html, 'interior');
  var box = $('wModalBox');
  box.querySelectorAll('[data-close]').forEach(function (b) { b.addEventListener('click', closeModal); });
  box.querySelectorAll('.w-int-hotspot').forEach(function (btn) {
    btn.addEventListener('click', function () {
      onInteriorHotspot(p, cfg, btn.dataset.hot, btn.dataset.type, btn.dataset.label);
    });
  });
}

function onInteriorHotspot(p, cfg, hotId, hotType, hotLabel) {
  var S = E.state();
  if (hotType === 'rest') {
    /* 室内休息热点 → 开完整休息面板（安睡/小憩） */
    try { E.logWorld('interior_rest', '在「' + (p.name || cfg.name) + '」' + hotLabel + '准备休息'); } catch (e) {}
    try { openRest(); } catch (e) { interiorToast('💤 休息功能暂不可用'); }
  } else if (hotType === 'shop') {
    /* 室内购物热点 → 开商店面板 */
    try { E.logWorld('interior_shop', '在「' + (p.name || cfg.name) + '」' + hotLabel + '购物'); } catch (e) {}
    try { openShop(); } catch (e) { interiorToast('🛒 商店功能暂不可用'); }
  } else if (hotType === 'work') {
    var expGain = 8 + Math.floor(Math.random() * 8);
    if (E.gainExp) { try { E.gainExp(expGain); } catch (e) {} }
    interiorToast('📚 在「' + hotLabel + '」用心一阵，经验 +' + expGain);
    try { E.logWorld('interior_work', '在「' + (p.name || cfg.name) + '」' + hotLabel + '学习'); } catch (e) {}
  } else if (hotType === 'view') {
    var views = [
      '光透过窗格洒落，岁月在此刻慢了下来。',
      '风从远处带来海盐气息，恍惚间像听见了谁的轻笑。',
      '这角落安静得能听见自己的心跳。',
      '许墨说过，凝视是另一种对话。',
      '影子斜斜地铺在地上，像谁留下的邀请。',
      '远处城市的轮廓柔和得像一幅未干的画。'
    ];
    interiorToast('🌐 ' + views[Math.floor(Math.random() * views.length)]);
  } else if (hotType === 'npc') {
    interiorToast('💜 许墨抬眼看你：「嗯？想说什么？」');
    try { E.logWorld('interior_npc', '在「' + (p.name || cfg.name) + '」与许墨共处'); } catch (e) {}
    if (window.fetch) {
      fetch('/api/affinity/add', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action: 'interior_xumo', detail: '室内·' + hotLabel })
      }).catch(function () {});
    }
  }
}

function interiorToast(msg) {
  var box = $('wModalBox');
  if (!box) { showToast(msg); return; }
  var old = box.querySelector('.w-int-toast');
  if (old) old.remove();
  var sc = box.querySelector('.w-interior');
  if (!sc) { showToast(msg); return; }
  var el = document.createElement('div');
  el.className = 'w-int-toast';
  el.textContent = msg;
  sc.appendChild(el);
  setTimeout(function () { if (el.parentNode) el.remove(); }, 3200);
}

function onBigMapClick(e) {
  if (!placePickMode && !npcPickMode && !aiPickMode) return;
  var rect = e.target.getBoundingClientRect();
  var tx = Math.round((e.clientX - rect.left) / rect.width * D.MAP_W);
  var ty = Math.round((e.clientY - rect.top) / rect.height * D.MAP_H);
  tx = Math.max(2, Math.min(D.MAP_W - 3, tx));
  ty = Math.max(2, Math.min(D.MAP_H - 3, ty));
  if (aiPickMode) {
    aiDraft = aiDraft || {};
    aiDraft.x = tx; aiDraft.y = ty;
    aiPickMode = false;
    closeModal();
    showToast('建设位置已选：(' + tx + ', ' + ty + ')');
    togglePanel('build');
    return;
  }
  if (npcPickMode) {
    npcDraft = npcDraft || {};
    npcDraft.x = tx; npcDraft.y = ty;
    npcPickMode = false;
    closeModal();
    showToast('住处已选：(' + tx + ', ' + ty + ')');
    togglePanel('build');
    return;
  }
  if (!placeDraft) placeDraft = {};
  placeDraft.x = tx; placeDraft.y = ty;
  placePickMode = false;
  closeModal();
  showToast('位置已选：(' + tx + ', ' + ty + ')');
  openPlaceForm();
}

/* ---- 城市脉搏：智能生成的动态世界 ---- */
var PULSE_TYPE_COLORS = {
  festival: '#ec4899', incident: '#f97316', mystery: '#8b5cf6', market: '#10b981',
  weather: '#0ea5e9', encounter: '#f43f5e', show: '#d946ef', exhibit: '#6366f1',
  hunt: '#ca8a04', goodwill: '#16a34a'
};
function pulseTypeColor(t) { return PULSE_TYPE_COLORS[t] || '#f59e0b'; }
function pulseRarityTag(ev) {
  var r = ev.rarity || 'common';
  if (r === 'common') return '';
  var cls = r === 'epic' ? 'epic' : 'rare';
  return ' <i class="w-pl-rar ' + cls + '">' + (r === 'epic' ? '★★★' : '★★') + '</i>';
}
function panelPulse() {
  var S = E.state();
  var pd = E.pulseData();
  var wd = E.weatherDef();
  var vit = pd.vitality || 0;
  var vitPct = Math.max(2, Math.min(100, vit));
  var wdName = wd ? (wd.icon + ' ' + wd.name) : '🌤️ 晴';
  var clock = E.gameClock ? E.gameClock() : '';
  var evHtml = pd.events.length ? pd.events.map(function (ev, i) {
    var left = Math.max(0, (ev.expire_day || S.day) - S.day);
    var tc = pulseTypeColor(ev.type);
    var barPct = Math.max(8, Math.min(100, left / 4 * 100));
    return '<div class="w-pl-ev" data-pev="' + i + '" style="border-left:3px solid ' + tc + '">' +
      '<span class="w-pl-ic">' + (ev.emoji || '✨') + '</span>' +
      '<div class="w-pl-bd"><div class="w-pl-t">' + esc(ev.title) + pulseRarityTag(ev) + '</div>' +
      '<div class="w-pl-d"><i class="w-pl-ty" style="background:' + tc + '1a;color:' + tc + ';border-color:' + tc + '55">' + esc(ev.type_name || '城市动态') + '</i>' +
      (left > 0 ? '还有 ' + left + ' 天' : '今日落幕') + '</div>' +
      '<div class="w-pl-days"><span style="width:' + barPct + '%"></span></div></div>' +
      '<span class="w-pl-loc" data-loc-ev="' + i + '" title="定位">🧭</span>' +
      '<span class="w-pl-go">›</span></div>';
  }).join('') : '<div class="w-pl-empty">城市此刻很安静。让许墨为你唤醒新的故事？</div>';
  var ruHtml = pd.rumors.length ? pd.rumors.slice(0, 12).map(function (r, i) {
    var unread = !S.flags['pulse_read_' + r.id];
    var vv = r.verify ? '<i class="w-pl-verdict v-' + r.verify.verdict + '">' + esc(r.verify.verdict_name) + '</i>' : '';
    return '<div class="w-pl-ru' + (unread ? ' unread' : '') + '" data-pru="' + i + '">' +
      '<span class="w-pl-ic">' + (r.emoji || '🗣️') + '</span>' +
      '<div class="w-pl-bd"><div class="w-pl-t">' + esc(r.title) + (unread ? ' <i class="w-pl-new">NEW</i>' : '') + ' ' + vv + '</div>' +
      '<div class="w-pl-d">' + esc((r.text || '').replace(/\s/g, '').slice(0, 36)) + '…</div></div></div>';
  }).join('') : '<div class="w-pl-empty">暂无传闻</div>';
  var viHtml = pd.visitors.map(function (d, i) {
    var vleft = Math.max(0, (d.expireDay || S.day) - S.day);
    return '<div class="w-pl-vi" data-vi="' + i + '">' + d.emoji + ' <b>' + esc(d.name) + '</b>' +
      '<span class="w-pl-d">' + (d.gifted ? '已互赠礼物 · ' : '') + (vleft > 0 ? '还留 ' + vleft + ' 天' : '今日启程') + '</span>' +
      '<span class="w-pl-loc" data-loc-vi="' + i + '" title="定位">🧭</span></div>';
  }).join('');
  return '<div class="w-panel w-panel-pulse">' +
    '<div class="w-panel-title">📡 城市脉搏<div class="w-panel-x" data-close>✕</div></div>' +
    '<div class="w-scroll">' +
      '<div class="w-pl-vit">' +
        '<div class="w-pl-vit-top"><span>🌆 城市活力</span><b>' + esc(pd.vitalityLevel || '苏醒之城') + '</b><i>' + vit + '/100</i></div>' +
        '<div class="w-pl-vit-bar"><span style="width:' + vitPct + '%"></span></div>' +
        '<div class="w-pl-vit-sub">第 ' + S.day + ' 天 · ' + esc(wdName) + (clock ? ' · ' + esc(clock) : '') +
          ' · 活力越高，越容易遇见 ★★ 稀有事件</div>' +
      '</div>' +
      '<div class="w-pl-gen">' +
        '<input class="w-input" id="wplSeed" maxlength="30" placeholder="灵感（选填）：流星雨 / 桂花集市 / 迷路的猫…"/>' +
        '<button class="w-btn-main" id="wplGen">✨ 让城市生长</button>' +
        '<label class="w-pl-chk"><input type="checkbox" id="wplPlace"/> 同时生成一处新地点（AI 配图，稍慢）</label>' +
      '</div>' +
      '<div class="w-q-sec">进行中的事件</div>' + evHtml +
      '<div class="w-q-sec">城市传闻</div>' + ruHtml +
      (viHtml ? '<div class="w-q-sec">来客</div>' + viHtml : '') +
      '<div class="w-pl-tip">城市会随时间自己生长——参与事件、求证传闻、给来客送礼都会点亮城市活力；走到地图上的光柱处即可参与事件，稀有事件有更高的光柱和星标。</div>' +
    '</div></div>';
}
function wirePulse() {
  var pd = E.pulseData();
  var gen = $('wplGen');
  if (gen) gen.addEventListener('click', function () {
    var seed = ($('wplSeed').value || '').trim();
    var wp = !!($('wplPlace') && $('wplPlace').checked);
    gen.disabled = true;
    gen.textContent = wp ? '🌆 城市与新的角落正在生长……' : '🌙 城市正在生长……';
    E.triggerPulseGen(seed, wp, function (news, retryAfter) {
      if (!news) {
        if (retryAfter && retryAfter > 0) {
          var left = retryAfter;
          var iv = setInterval(function () {
            if (modalKind !== 'panel-pulse' || !$('wplGen')) { clearInterval(iv); return; }
            left--;
            if (left <= 0) { clearInterval(iv); gen.disabled = false; gen.textContent = '✨ 让城市生长'; }
            else gen.textContent = '🌱 城市生长中（' + left + 's）';
          }, 1000);
          gen.textContent = '🌱 城市生长中（' + left + 's）';
          return;
        }
        gen.disabled = false;
        gen.textContent = '✨ 让城市生长';
      }
    });
  });
  var box = $('wModalBox');
  box.querySelectorAll('[data-pev]').forEach(function (el) {
    el.addEventListener('click', function () { openPulseEventCard(pd.events[+el.dataset.pev]); });
  });
  box.querySelectorAll('[data-loc-ev]').forEach(function (el) {
    el.addEventListener('click', function (e) {
      e.stopPropagation();
      var ev = pd.events[+el.dataset.locEv];
      if (ev) E.locatePulseTarget(ev.x, ev.y, ev.title);
    });
  });
  box.querySelectorAll('[data-pru]').forEach(function (el) {
    el.addEventListener('click', function () { openRumorCard(pd.rumors[+el.dataset.pru]); });
  });
  box.querySelectorAll('[data-loc-vi]').forEach(function (el) {
    el.addEventListener('click', function (e) {
      e.stopPropagation();
      var v = pd.visitors[+el.dataset.locVi];
      if (v) E.locatePulseTarget(v.x, v.y, v.name);
    });
  });
  box.querySelectorAll('[data-vi]').forEach(function (el) {
    el.addEventListener('click', function () {
      var v = pd.visitors[+el.dataset.vi];
      if (v) E.locatePulseTarget(v.x, v.y, v.name);
    });
  });
  /* 兜底：初始同步失败/未完成时面板为空，重新拉取并在数据到达后刷新 */
  if (!pd.events.length && !pd.rumors.length && !pd.visitors.length) {
    E.loadWorldPulse();
    var t0 = Date.now();
    var timer = setInterval(function () {
      if (modalKind !== 'panel-pulse') { clearInterval(timer); return; }
      var nd = E.pulseData();
      if (nd.events.length || nd.rumors.length || nd.visitors.length || Date.now() - t0 > 15000) {
        clearInterval(timer);
        if (nd.events.length || nd.rumors.length || nd.visitors.length) {
          openModal(panelPulse(), 'panel-pulse');
          wirePulse();
        }
      }
    }, 600);
  }
}
function openPulseEventCard(ev) {
  if (!ev) return;
  var rw = ev.reward || {};
  var rwTxt = [];
  if (rw.money) rwTxt.push('¥' + rw.money + ' 左右');
  if (rw.exp) rwTxt.push(rw.exp + ' 经验上下');
  if (rw.item && D.ITEMS[rw.item]) rwTxt.push(D.ITEMS[rw.item].name + '×' + (rw.qty || 1));
  var tc = pulseTypeColor(ev.type);
  var choices = (ev.choices && ev.choices.length) ? ev.choices : null;
  var chHtml = '';
  if (choices) {
    chHtml = '<div class="w-pl-chsec">你要如何走进这段故事？</div>' + choices.map(function (c, i) {
      var hint = [];
      if (c.money_delta > 0) hint.push('¥+' + c.money_delta);
      if (c.money_delta < 0) hint.push('¥' + c.money_delta);
      if (c.exp_delta > 0) hint.push('经验+' + c.exp_delta);
      if (c.exp_delta < 0) hint.push('经验' + c.exp_delta);
      return '<button class="w-pl-choice" data-ch="' + i + '">' +
        '<b>' + esc(c.label) + '</b>' +
        (hint.length ? '<span>' + hint.join(' · ') + '</span>' : '<span>命运自有安排</span>') +
        '</button>';
    }).join('');
  } else {
    chHtml = '<button class="w-btn-main" id="wplJoin">✨ 参与这段故事</button>';
  }
  openModal(
    '<div class="w-panel w-pl-card">' +
      '<div class="w-panel-title">' + (ev.emoji || '✨') + ' ' + esc(ev.title) + pulseRarityTag(ev) + '<div class="w-panel-x" data-close>✕</div></div>' +
      '<div class="w-scroll">' +
        '<div class="w-pl-tag" style="color:' + tc + ';background:' + tc + '1a;border-color:' + tc + '55">' + esc(ev.type_name || '城市动态') + '</div>' +
        '<div class="w-place-desc">' + esc(ev.desc || '').replace(/\n/g, '<br>') + '</div>' +
        (ev.story ? '<div class="w-pl-story">' + esc(ev.story).replace(/\n/g, '<br>') + '</div>' : '') +
        (ev.comment ? '<div class="w-place-cmt"><b>许墨：</b>' + esc(ev.comment) + '</div>' : '') +
        (rwTxt.length ? '<div class="w-pl-rw">🎁 参与可得：' + rwTxt.join(' · ') + '（不同选择略有浮动）</div>' : '') +
        chHtml +
        '<button class="w-btn-main ghost" data-close>（只是路过）</button>' +
      '</div></div>', 'pulse-event');
  var box = $('wModalBox');
  box.querySelectorAll('[data-close]').forEach(function (x) { x.addEventListener('click', function () { closeModal(); }); });
  box.querySelectorAll('[data-ch]').forEach(function (btn) {
    btn.addEventListener('click', function () { settlePulseEvent(ev, +btn.dataset.ch); });
  });
  var join = box.querySelector('#wplJoin');
  if (join) join.addEventListener('click', function () { settlePulseEvent(ev, 0); });
}
function settlePulseEvent(ev, idx) {
  var res = E.completePulseEvent(ev.id, idx);
  if (!res) { closeModal(); return; }
  var gotTxt = res.got.length ? res.got.join(' · ') : '一段值得收藏的回忆';
  openModal(
    '<div class="w-panel w-pl-card">' +
      '<div class="w-panel-title">' + (ev.emoji || '✨') + ' ' + esc(ev.title) + '<div class="w-panel-x" data-close>✕</div></div>' +
      '<div class="w-scroll">' +
        (res.label ? '<div class="w-pl-chpick">你的选择：「' + esc(res.label) + '」</div>' : '') +
        '<div class="w-pl-story">' + esc(res.outcome || '').replace(/\n/g, '<br>') + '</div>' +
        (res.comment ? '<div class="w-place-cmt"><b>许墨：</b>' + esc(res.comment) + '</div>' : '') +
        '<div class="w-pl-rw">🎁 获得：' + esc(gotTxt) + '</div>' +
        '<button class="w-btn-main ghost" data-close>（把回忆收好）</button>' +
      '</div></div>', 'pulse-settle');
  $('wModalBox').querySelectorAll('[data-close]').forEach(function (x) { x.addEventListener('click', function () { closeModal(); }); });
}
function openRumorCard(r) {
  if (!r) return;
  E.state().flags['pulse_read_' + r.id] = 1;
  var v = r.verify;
  var verifyHtml = v
    ? '<div class="w-pl-vfbox">' +
        '<div class="w-pl-vfhead">🔍 许墨的求证报告 <i class="w-pl-verdict v-' + v.verdict + '">' + esc(v.verdict_name) + '</i></div>' +
        '<div class="w-pl-vftext">' + esc(v.report || '').replace(/\n/g, '<br>') + '</div>' +
        (v.comment ? '<div class="w-place-cmt"><b>许墨：</b>' + esc(v.comment) + '</div>' : '') +
      '</div>'
    : '<button class="w-btn-main" id="wplVerify">🔍 请许墨帮忙求证</button>';
  openModal(
    '<div class="w-panel w-pl-card">' +
      '<div class="w-panel-title">' + (r.emoji || '🗣️') + ' ' + esc(r.title) + '<div class="w-panel-x" data-close>✕</div></div>' +
      '<div class="w-scroll">' +
        '<div class="w-pl-story">' + esc(r.text || '').replace(/\n/g, '<br>') + '</div>' +
        (r.comment ? '<div class="w-place-cmt"><b>许墨：</b>' + esc(r.comment) + '</div>' : '') +
        verifyHtml +
        '<button class="w-btn-main ghost" data-close>（合上传闻）</button>' +
      '</div></div>', 'pulse-rumor');
  var box = $('wModalBox');
  box.querySelectorAll('[data-close]').forEach(function (x) { x.addEventListener('click', function () { closeModal(); }); });
  var vf = box.querySelector('#wplVerify');
  if (vf) vf.addEventListener('click', function () {
    vf.disabled = true;
    vf.textContent = '🔍 许墨正在查证……';
    E.verifyPulseRumor(r.id, function (verify) {
      if (!verify) {
        vf.disabled = false;
        vf.textContent = '🔍 请许墨帮忙求证';
        return;
      }
      r.verify = verify;
      openRumorCard(r);   /* 重开刷新为报告态 */
    });
  });
}
function showPulseNews(news) {
  if (!news) return;
  var rows = [];
  if (news.event) rows.push('<div class="w-pl-news-row ev" data-kind="ev">' + (news.event.emoji || '✨') +
    ' <b>' + esc(news.event.title) + '</b>' + pulseRarityTag(news.event) +
    '<span>' + esc(news.event.desc || '') + '</span></div>');
  (news.rumors || []).forEach(function (r) {
    rows.push('<div class="w-pl-news-row ru">' + (r.emoji || '🗣️') + ' <b>' + esc(r.title) + '</b><span>新的传闻正在城里流传，可以请许墨求证</span></div>');
  });
  if (news.visitor) rows.push('<div class="w-pl-news-row vi">' + (news.visitor.emoji || '🧳') +
    ' <b>' + esc(news.visitor.name) + '</b><span>一位来客出现在城中，去和 TA 聊聊、送件小礼物吧</span></div>');
  if (news.place) rows.push('<div class="w-pl-news-row pl">' + (news.place.icon || '📍') +
    ' <b>' + esc(news.place.name) + '</b><span>新的地点落成了恋语市</span></div>');
  if (!rows.length) return;
  openModal(
    '<div class="w-panel w-pl-card">' +
      '<div class="w-panel-title">📰 城市快报<div class="w-panel-x" data-close>✕</div></div>' +
      '<div class="w-scroll">' +
        '<div class="w-pl-news-intro">恋语市又有了新的动静——</div>' + rows.join('') +
        '<button class="w-btn-main ghost" data-close>（出门看看）</button>' +
      '</div></div>', 'pulse-news');
  var box = $('wModalBox');
  box.querySelectorAll('[data-close]').forEach(function (x) { x.addEventListener('click', function () { closeModal(); }); });
  var evRow = box.querySelector('.w-pl-news-row.ev');
  if (evRow) evRow.addEventListener('click', function () { openPulseEventCard(news.event); });
}

/* ================= 世界编年史（记录 · 许墨的记忆） ================= */
var CHRON_META = {
  day: '🌅', weather: '🌤️', talk: '💬', gather: '🌿', chest: '📦', photo: '📷',
  shard: '💠', page: '📄', puzzle: '🧩', battle: '⚔️', quest: '📋', build: '🛠️',
  npc: '🧑', place: '📍', pulse: '✨', rumor: '🗣️', gift: '🎁', rest: '🛏️', other: '🗒️'
};
var CHRON_TYPE_LABEL = {
  day: '新日', weather: '天气', talk: '交谈', gather: '采集', chest: '宝箱',
  photo: '拍照', shard: '碎片', page: '讲义', puzzle: '解谜', battle: '战斗',
  quest: '任务', build: '建造', npc: '居民', place: '地点', pulse: '事件',
  rumor: '传闻', gift: '赠礼', rest: '休息', other: '其他'
};
var CHRON_FILTERS = [
  ['', '全部', '🗂️'], ['talk', '交谈', '💬'], ['quest', '任务', '📋'], ['pulse', '事件', '✨'],
  ['gather', '采集', '🌿'], ['battle', '战斗', '⚔️'], ['build', '建造', '🛠️'],
  ['npc', '居民', '🧑'], ['place', '地点', '📍'], ['weather', '天气', '🌤️']
];
var CHRON_TOD = [
  { key: 'dawn', icon: '🌅', label: '黎明', lo: 0, hi: 300 },
  { key: 'morning', icon: '🌄', label: '上午', lo: 300, hi: 720 },
  { key: 'noon', icon: '☀️', label: '正午', lo: 720, hi: 900 },
  { key: 'afternoon', icon: '🌇', label: '下午', lo: 900, hi: 1140 },
  { key: 'evening', icon: '🌆', label: '黄昏', lo: 1140, hi: 1320 },
  { key: 'night', icon: '🌙', label: '夜晚', lo: 1320, hi: 1440 }
];
var CHRON_MEM_STYLES = [
  { key: 'gentle', label: '温柔回顾' },
  { key: 'poetic', label: '诗意小品' },
  { key: 'narrative', label: '故事叙述' }
];
var CHRON_PAGE_SIZE = 50;

var chronData = null, chronType = '', chronDay = 0, chronQ = '', chronOrder = 'desc';
var chronStarOnly = 0, chronMilestoneOnly = 0, chronPage = 1, chronHasMore = false;
var chronMem = null, chronMemBusy = false, chronMemStyle = 'gentle', chronMemBusyStyle = '';
var chronBusy = false, chronSearchTimer = null;

function chronBuildUrl() {
  var p = '/api/world/log?page=' + chronPage + '&page_size=' + CHRON_PAGE_SIZE + '&order=' + chronOrder;
  if (chronType) p += '&type=' + encodeURIComponent(chronType);
  if (chronDay) p += '&day=' + chronDay;
  if (chronStarOnly) p += '&star=1';
  if (chronMilestoneOnly) p += '&milestone=1';
  if (chronQ) p += '&q=' + encodeURIComponent(chronQ);
  return p;
}
function chronFetch() {
  chronBusy = true;
  if (modalKind === 'panel-chron') {
    var live = $('wModalBox');
    if (live) {
      var spin = live.querySelector('.w-ch-stats');
      if (spin) spin.innerHTML = '正在翻开编年史……';
      var lst = live.querySelector('.w-ch-list');
      if (lst && chronPage === 1) lst.innerHTML = '<div class="w-ch-skel"><span></span><span></span><span></span></div>';
    }
  }
  fetch(chronBuildUrl())
    .then(function (r) { return r.json(); })
    .then(function (d) {
      chronBusy = false;
      chronHasMore = !!d.has_more;
      /* 翻页累加；切条件时重置 */
      if (chronPage === 1 || !chronData || !chronData.entries) {
        chronData = d;
      } else {
        chronData.entries = chronData.entries.concat(d.entries || []);
        chronData.count = d.count;
        chronData.has_more = d.has_more;
      }
      if (modalKind === 'panel-chron') { chronRedraw({ keepScroll: chronPage > 1 }); }
    })
    .catch(function () { chronBusy = false; showToast('编年史加载失败'); });
}
function chronMemFetch(refresh) {
  chronMemBusy = true;
  chronMemBusyStyle = chronMemStyle;
  if (modalKind === 'panel-chron') {
    var live = $('wModalBox');
    if (live) {
      var txt = live.querySelector('.w-ch-mem-txt');
      if (txt) txt.textContent = '许墨正倚着窗边回忆这段时间……';
      var btn = live.querySelector('#wchMem');
      if (btn) { btn.disabled = true; btn.textContent = '🔄 回忆中…'; }
    }
  }
  fetch('/api/world/memory?style=' + chronMemStyle + (refresh ? '&refresh=1' : ''))
    .then(function (r) { return r.json(); })
    .then(function (d) {
      chronMemBusy = false;
      chronMem = (d && d.text) ? d : { text: '' };
      if (modalKind === 'panel-chron') { chronRedraw(); }
    })
    .catch(function () { chronMemBusy = false; showToast('记忆唤醒失败，稍后再试'); });
}
function chronTimeFmt(t) {
  var h = Math.floor((t || 0) / 60), m = (t || 0) % 60;
  return (h < 10 ? '0' : '') + h + ':' + (m < 10 ? '0' : '') + m;
}
function chronTodKey(t) {
  for (var i = 0; i < CHRON_TOD.length; i++) {
    var r = CHRON_TOD[i];
    if (t >= r.lo && t < r.hi) return r.key;
  }
  return 'night';
}
/* 统计卡：类型分布条形图 + 活跃度 */
function panelChronStats(d) {
  if (!d || !d.total_all) return '';
  var types = d.types || {};
  var maxT = 1;
  for (var k in types) if (types[k] > maxT) maxT = types[k];
  var typeRows = Object.keys(types).sort(function (a, b) { return types[b] - types[a]; }).slice(0, 6).map(function (k) {
    var pct = Math.round((types[k] / maxT) * 100);
    return '<div class="w-ch-stat-row">' +
      '<span class="w-ch-stat-ic">' + (CHRON_META[k] || '🗒️') + '</span>' +
      '<span class="w-ch-stat-label">' + esc(CHRON_TYPE_LABEL[k] || k) + '</span>' +
      '<span class="w-ch-stat-bar"><i style="width:' + pct + '%"></i></span>' +
      '<span class="w-ch-stat-n">' + types[k] + '</span></div>';
  }).join('');
  /* 最活跃时段 */
  var tod = d.tod || {}, todMax = 0, todMaxKey = '';
  for (var kk in tod) if (tod[kk] > todMax) { todMax = tod[kk]; todMaxKey = kk; }
  var todLabel = '—';
  for (var i = 0; i < CHRON_TOD.length; i++) if (CHRON_TOD[i].key === todMaxKey) todLabel = CHRON_TOD[i].icon + ' ' + CHRON_TOD[i].label;
  /* 最近 7 天活跃度 */
  var activity = d.activity || {};
  var aDays = Object.keys(activity).map(Number).sort(function (a, b) { return a - b; });
  var aMax = 1;
  aDays.forEach(function (dd) { if (activity[dd] > aMax) aMax = activity[dd]; });
  var actBars = aDays.map(function (dd) {
    var pct = Math.round((activity[dd] / aMax) * 100);
    return '<div class="w-ch-act-bar" title="第 ' + dd + ' 天：' + activity[dd] + ' 条"><i style="height:' + Math.max(4, pct) + '%"></i><span>D' + dd + '</span></div>';
  }).join('');
  return '<details class="w-ch-stats-card" open>' +
    '<summary>📊 编年史概览</summary>' +
    '<div class="w-ch-stats-grid">' +
      '<div class="w-ch-stat-cell"><b>' + (d.total_all || 0) + '</b><span>总记录</span></div>' +
      '<div class="w-ch-stat-cell"><b>' + ((d.days || []).length || 1) + '</b><span>跨越天数</span></div>' +
      '<div class="w-ch-stat-cell"><b>' + (d.milestone_count || 0) + '</b><span>里程碑</span></div>' +
      '<div class="w-ch-stat-cell"><b>' + (d.star_count || 0) + '</b><span>已收藏</span></div>' +
    '</div>' +
    '<div class="w-ch-stat-sub">最活跃时段：<b>' + todLabel + '</b></div>' +
    (aDays.length ? '<div class="w-ch-act">' + actBars + '</div>' : '') +
    (typeRows ? '<div class="w-ch-stat-types">' + typeRows + '</div>' : '') +
  '</details>';
}
/* 记忆卡（支持风格切换） */
function panelChronMem() {
  var memTxt = chronMemBusy
    ? '许墨正倚着窗边回忆这段时间……'
    : (chronMem && chronMem.text)
      ? chronMem.text
      : '记录还太少。多去世界里走走，再让许墨为你回忆这段时光。';
  var memSub = (chronMem && chronMem.time && !chronMemBusy)
    ? '回忆于 ' + new Date(chronMem.time * 1000).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' }) +
      (chronMem.cached ? '（缓存）' : '') +
      (chronMem.milestone_count != null ? ' · 锚点 ' + chronMem.milestone_count + ' 个' : '')
    : '';
  var styleChips = CHRON_MEM_STYLES.map(function (s) {
    return '<button class="w-ch-style' + (chronMemStyle === s.key ? ' on' : '') + '" data-mstyle="' + s.key + '"' +
      (chronMemBusy ? ' disabled' : '') + '>' + s.label + '</button>';
  }).join('');
  return '<div class="w-ch-mem">' +
    '<div class="w-ch-mem-top"><span>💭 许墨的记忆</span>' +
    '<button class="w-mini-btn" id="wchMem" ' + (chronMemBusy ? 'disabled' : '') + '>🔄 ' + (chronMemBusy ? '回忆中…' : '重新唤醒') + '</button></div>' +
    '<div class="w-ch-mem-styles">' + styleChips + '</div>' +
    '<div class="w-ch-mem-txt">' + esc(memTxt) + '</div>' +
    (memSub ? '<div class="w-ch-mem-sub">' + esc(memSub) + '</div>' : '') +
  '</div>';
}
function panelChron() {
  var d = chronData;
  var stats = (!d)
    ? '<div class="w-ch-stats">正在翻开编年史……</div>'
    : '<div class="w-ch-stats">共 <b>' + (d.count || 0) + '</b> 条记录' +
      (d.total_all != null && d.total_all !== d.count ? '（总 ' + d.total_all + '）' : '') +
      ' · 跨 <b>' + ((d.days || []).length || 1) + '</b> 天' +
      (chronBusy ? ' · 刷新中…' : '') + '</div>';
  /* 类型 chip */
  var chips = '<div class="w-ch-chips">' + CHRON_FILTERS.map(function (f) {
    var n = d && d.types ? (d.types[f[0]] || 0) : 0;
    return '<button class="w-ch-chip' + (chronType === f[0] ? ' on' : '') + '" data-ct="' + f[0] + '">' +
      (f[2] || '') + ' ' + f[1] + (f[0] && n ? '<i>' + n + '</i>' : '') + '</button>';
  }).join('') + '</div>';
  /* 搜索框 */
  var search = '<div class="w-ch-search">' +
    '<input type="text" id="wchSearch" placeholder="搜索编年史里的故事……" value="' + esc(chronQ) + '">' +
    (chronQ ? '<button class="w-ch-search-x" id="wchSearchX">✕</button>' : '') +
  '</div>';
  /* 工具条：日期筛选 / 排序 / 仅收藏 / 仅里程碑 / 导出 */
  var dayOpts = (d && d.days ? d.days : []).map(function (dd) {
    return '<option value="' + dd + '"' + (chronDay === dd ? ' selected' : '') + '>第 ' + dd + ' 天</option>';
  }).join('');
  var tools = '<div class="w-ch-tools">' +
    '<select id="wchDay" class="w-ch-select">' +
      '<option value="0"' + (!chronDay ? ' selected' : '') + '>全部日期</option>' + dayOpts +
    '</select>' +
    '<button class="w-ch-tool' + (chronOrder === 'asc' ? ' on' : '') + '" id="wchOrder" title="切换新旧顺序">' +
      (chronOrder === 'asc' ? '⬆ 旧→新' : '⬇ 新→旧') + '</button>' +
    '<button class="w-ch-tool' + (chronStarOnly ? ' on' : '') + '" id="wchStar" title="只看收藏">★</button>' +
    '<button class="w-ch-tool' + (chronMilestoneOnly ? ' on' : '') + '" id="wchMs" title="只看里程碑">⭐</button>' +
    '<button class="w-ch-tool" id="wchExport" title="导出编年史">⬇</button>' +
  '</div>';
  /* 列表：按天分组 → 天内按时段分组 */
  var rows = [];
  if (d && d.entries && d.entries.length) {
    /* 排序保证天顺序与 order 一致 */
    var sorted = d.entries.slice().sort(function (a, b) {
      var da = (a.day || 0) * 1440 + (a.time || 0);
      var db = (b.day || 0) * 1440 + (b.time || 0);
      return chronOrder === 'asc' ? da - db : db - da;
    });
    var lastDay = null, lastTod = null;
    sorted.forEach(function (e) {
      if (e.day !== lastDay) {
        lastDay = e.day;
        lastTod = null;
        rows.push('<div class="w-ch-day">第 ' + e.day + ' 天</div>');
      }
      var tk = chronTodKey(e.time || 0);
      if (tk !== lastTod) {
        lastTod = tk;
        var tr = null;
        for (var i = 0; i < CHRON_TOD.length; i++) if (CHRON_TOD[i].key === tk) { tr = CHRON_TOD[i]; break; }
        if (tr) rows.push('<div class="w-ch-tod"><span>' + tr.icon + ' ' + tr.label + '</span></div>');
      }
      var ms = e.milestone ? '<i class="w-ch-ms">⭐</i>' : '';
      var star = e.star ? '<i class="w-ch-star on">★</i>' : '<i class="w-ch-star">☆</i>';
      var del = '<i class="w-ch-del" title="删除">✕</i>';
      rows.push('<div class="w-ch-row' + (e.milestone ? ' ms' : '') + (e.star ? ' starred' : '') + '" data-id="' + esc(e.id || '') + '">' +
        '<i class="w-ch-t">' + chronTimeFmt(e.time) + '</i>' +
        '<em>' + (CHRON_META[e.type] || '🗒️') + '</em>' +
        '<span>' + esc(e.text) + '</span>' +
        ms + star + del +
      '</div>');
    });
    /* 加载更多 */
    if (chronHasMore) {
      rows.push('<button class="w-ch-more" id="wchMore">' + (chronBusy ? '加载中…' : '加载更早的记录 ↓') + '</button>');
    } else {
      rows.push('<div class="w-ch-end">—— 已经到底了 ——</div>');
    }
  } else if (!d) {
    rows.push('<div class="w-ch-skel"><span></span><span></span><span></span></div>');
  } else {
    rows.push('<div class="w-ch-empty">' +
      (chronQ || chronDay || chronStarOnly || chronMilestoneOnly || chronType
        ? '没有符合条件的记录。换个筛选条件试试？'
        : '这个世界还没有留下记录。去走走、和人说说话——一切都会被记下。') +
    '</div>');
  }
  return '<div class="w-panel w-panel-chron">' +
    '<div class="w-panel-title">📜 世界编年史<div class="w-panel-x" data-close>✕</div></div>' +
    '<div class="w-scroll">' +
      stats +
      panelChronMem(d) +
      panelChronStats(d) +
      search + chips + tools +
      '<div class="w-ch-list">' + rows.join('') + '</div>' +
      '<div class="w-ch-foot">' +
        '<span>世界里的每一步都会写进编年史，许墨会记得这一切。</span>' +
        '<button class="w-mini-btn ghost" id="wchClear">🗑 清空</button>' +
      '</div>' +
    '</div></div>';
}
/* 单条记录：收藏 / 取消收藏 / 删除 */
function chronToggleStar(id, btn) {
  var entry = chronData && chronData.entries ? chronData.entries.find(function (e) { return e.id === id; }) : null;
  if (!entry) return;
  var newStar = entry.star ? 0 : 1;
  fetch('/api/world/log/' + encodeURIComponent(id), {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ star: newStar })
  })
    .then(function (r) { return r.json(); })
    .then(function (d) {
      if (d.ok) {
        entry.star = newStar;
        if (d.entry && typeof d.entry.text !== 'undefined') entry.text = d.entry.text;
        if (chronData && chronData.star_count != null) {
          chronData.star_count += (newStar ? 1 : -1);
        }
        chronRedraw();
        showToast(newStar ? '已收藏 ★' : '取消收藏');
      } else showToast(d.error || '操作失败');
    })
    .catch(function () { showToast('操作失败'); });
}
function chronDeleteEntry(id, btn) {
  if (!confirm('删除这一条记录？')) return;
  fetch('/api/world/log/' + encodeURIComponent(id), { method: 'DELETE' })
    .then(function (r) { return r.json(); })
    .then(function (d) {
      if (d.ok) {
        if (chronData && chronData.entries) {
          chronData.entries = chronData.entries.filter(function (e) { return e.id !== id; });
          chronData.count = Math.max(0, (chronData.count || 0) - 1);
          if (chronData.total_all != null) chronData.total_all = Math.max(0, chronData.total_all - 1);
        }
        chronRedraw();
        showToast('已删除');
      } else showToast(d.error || '删除失败');
    })
    .catch(function () { showToast('删除失败'); });
}
function chronResetConditions() {
  chronPage = 1;
  chronData = null;
}
/* 焦点/滚动保持的重渲染：避免搜索时输入框失焦 */
function chronRedraw(opts) {
  opts = opts || {};
  var box = $('wModalBox');
  var focusId = null, selStart = 0, selEnd = 0, scrollTop = 0;
  if (box) {
    var sc = box.querySelector('.w-scroll');
    if (sc) scrollTop = sc.scrollTop;
    if (document.activeElement && box.contains(document.activeElement) && document.activeElement.id) {
      focusId = document.activeElement.id;
      try {
        selStart = document.activeElement.selectionStart || 0;
        selEnd = document.activeElement.selectionEnd || 0;
      } catch (e) {}
    }
  }
  openModal(panelChron(), 'panel-chron');
  wireChron(false);
  if (focusId) {
    var el = document.getElementById(focusId);
    if (el) {
      el.focus();
      try { el.setSelectionRange(selStart, selEnd); } catch (e) {}
    }
  }
  if (!opts.keepScroll) {
    var sc2 = box ? box.querySelector('.w-scroll') : null;
    if (sc2) sc2.scrollTop = scrollTop;
  }
}
function wireChron(firstOpen) {
  var box = $('wModalBox');
  if (firstOpen !== false && !chronData) chronFetch();
  if (firstOpen !== false && !chronMem) chronMemFetch(false);
  /* 类型筛选 */
  box.querySelectorAll('[data-ct]').forEach(function (b) {
    b.addEventListener('click', function () {
      chronType = b.dataset.ct;
      chronResetConditions();
      chronRedraw();
      chronFetch();
    });
  });
  /* 搜索：防抖 350ms */
  var search = $('wchSearch');
  if (search) {
    search.addEventListener('input', function () {
      clearTimeout(chronSearchTimer);
      var v = search.value;
      chronSearchTimer = setTimeout(function () {
        chronQ = (v || '').trim();
        chronResetConditions();
        chronRedraw();
        chronFetch();
      }, 350);
    });
    search.addEventListener('keydown', function (e) {
      if (e.key === 'Enter') { clearTimeout(chronSearchTimer); }
    });
  }
  var searchX = $('wchSearchX');
  if (searchX) searchX.addEventListener('click', function () {
    chronQ = ''; chronResetConditions();
    chronRedraw(); chronFetch();
  });
  /* 日期筛选 */
  var daySel = $('wchDay');
  if (daySel) daySel.addEventListener('change', function () {
    chronDay = parseInt(daySel.value, 10) || 0;
    chronResetConditions();
    chronRedraw(); chronFetch();
  });
  /* 排序切换 */
  var orderBtn = $('wchOrder');
  if (orderBtn) orderBtn.addEventListener('click', function () {
    chronOrder = (chronOrder === 'asc') ? 'desc' : 'asc';
    chronResetConditions();
    chronRedraw(); chronFetch();
  });
  /* 仅收藏 */
  var starBtn = $('wchStar');
  if (starBtn) starBtn.addEventListener('click', function () {
    chronStarOnly = chronStarOnly ? 0 : 1;
    chronResetConditions();
    chronRedraw(); chronFetch();
  });
  /* 仅里程碑 */
  var msBtn = $('wchMs');
  if (msBtn) msBtn.addEventListener('click', function () {
    chronMilestoneOnly = chronMilestoneOnly ? 0 : 1;
    chronResetConditions();
    chronRedraw(); chronFetch();
  });
  /* 导出 */
  var expBtn = $('wchExport');
  if (expBtn) expBtn.addEventListener('click', function () {
    var fmt = confirm('确定导出为 txt（确定）还是 json（取消）？') ? 'txt' : 'json';
    window.open('/api/world/log/export?format=' + fmt, '_blank');
  });
  /* 加载更多 */
  var more = $('wchMore');
  if (more) more.addEventListener('click', function () {
    if (chronBusy) return;
    chronPage += 1;
    chronFetch();
  });
  /* 记忆卡：重新唤醒 */
  var mem = $('wchMem');
  if (mem) mem.addEventListener('click', function () { chronMemFetch(true); });
  /* 记忆风格切换 */
  box.querySelectorAll('[data-mstyle]').forEach(function (b) {
    b.addEventListener('click', function () {
      if (chronMemBusy) return;
      var s = b.dataset.mstyle;
      if (s === chronMemStyle) return;
      chronMemStyle = s;
      chronMem = null;  /* 强制重新拉取 */
      chronRedraw();
      chronMemFetch(false);
    });
  });
  /* 行操作：收藏 / 删除（事件委托） */
  var list = box.querySelector('.w-ch-list');
  if (list) {
    list.addEventListener('click', function (ev) {
      var t = ev.target;
      if (!t) return;
      var row = t.closest('.w-ch-row');
      if (!row) return;
      var id = row.dataset.id;
      if (!id) return;
      if (t.classList.contains('w-ch-star')) { chronToggleStar(id, t); }
      else if (t.classList.contains('w-ch-del')) { chronDeleteEntry(id, t); }
    });
  }
  /* 清空 */
  var clr = $('wchClear');
  if (clr) clr.addEventListener('click', function () {
    if (!confirm('清空全部世界记录？许墨对这段世界的记忆也会一并抹去。')) return;
    fetch('/api/world/log', { method: 'DELETE' })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        if (d.ok) {
          chronData = { entries: [], count: 0, days: [], types: {}, tod: {}, activity: {},
                        milestone_count: 0, star_count: 0, total_all: 0, has_more: false };
          chronMem = null;
          chronPage = 1;
          showToast('编年史已清空');
          chronRedraw();
        }
      })
      .catch(function () { showToast('清空失败'); });
  });
}

/* ---- 设置面板 ---- */
/* ---- 3D 形象（上传 GLB / GLTF 模型）：「我」与「许墨」双槽位独立 ---- */
var M3 = { state: null };

function m3Size(n) {
  n = n || 0;
  return n >= 1048576 ? (n / 1048576).toFixed(1) + ' MB' : Math.max(1, Math.round(n / 1024)) + ' KB';
}

function m3Refresh() {
  fetch('/api/model/state').then(function (r) { return r.json(); }).then(function (d) {
    M3.state = d || { active_id: 'default', xumo_id: 'default', items: [] };
    m3RenderList();
  }).catch(function () {});
}

function m3Name(st, id) {
  var items = st.items || [];
  for (var i = 0; i < items.length; i++) if (items[i].id === id) return items[i].name;
  return id;
}

function m3RenderList() {
  if (!$('wM3List')) return;
  var st = M3.state || { active_id: 'default', xumo_id: 'default', items: [] };
  var h = '', i, it, items = st.items || [];
  for (i = 0; i < items.length; i++) {
    it = items[i];
    var isMe = it.id === st.active_id;
    var isXu = !!st.xumo_id && it.id === st.xumo_id;
    h += '<div class="w-m3-item' + ((isMe || isXu) ? ' on' : '') + '">' +
      '<span class="w-m3-name">' + (isMe ? '✅我 ' : '') + (isXu ? '💜许墨 ' : '') + esc(it.name) + '</span>' +
      '<span class="w-m3-meta">' + m3Size(it.size) + ' · ' + esc(it.time) + '</span>' +
      (isMe ? '' : '<button class="w-m3-btn" data-m3use="' + esc(it.id) + '">设为我</button>') +
      (isXu ? '' : '<button class="w-m3-btn" data-m3xu="' + esc(it.id) + '">设为许墨</button>') +
      '<button class="w-m3-btn w-m3-del" data-m3del="' + esc(it.id) + '">删除</button>' +
    '</div>';
  }
  if (!h) h = '<div class="w-m3-empty">还没有上传过模型</div>';
  $('wM3List').innerHTML = h;
  if ($('wM3Cur')) $('wM3Cur').textContent = (st.active_id === 'default') ? '当前：默认小人' : ('当前：' + m3Name(st, st.active_id));
  if ($('wM3XuCur')) $('wM3XuCur').textContent = (!st.xumo_id || st.xumo_id === 'default') ? '当前：默认许墨' : ('当前：' + m3Name(st, st.xumo_id));
  $('wM3List').querySelectorAll('[data-m3use]').forEach(function (b) {
    b.addEventListener('click', function () { m3Select(b.dataset.m3use, 'player'); });
  });
  $('wM3List').querySelectorAll('[data-m3xu]').forEach(function (b) {
    b.addEventListener('click', function () { m3Select(b.dataset.m3xu, 'xumo'); });
  });
  $('wM3List').querySelectorAll('[data-m3del]').forEach(function (b) {
    b.addEventListener('click', function () {
      if (!confirm('删除这个模型？（若正被使用将恢复对应默认形象）')) return;
      fetch('/api/model/' + b.dataset.m3del, { method: 'DELETE' })
        .then(function (r) { return r.json(); })
        .then(function (d) {
          if (!d.ok) { showToast(d.error || '删除失败'); return; }
          M3.state = d;
          m3RenderList();
          m3Apply(d.active_id, d.xumo_id);
          showToast('模型已删除');
        }).catch(function () { showToast('网络错误'); });
    });
  });
}

/* 通知 3D 渲染层即时换装（2D 模式只存服务端）：玩家 / 许墨 双槽位独立 */
function m3Apply(playerId, xumoId) {
  var st = M3.state || {};
  var items = st.items || [];
  var pit = null, xit = null;
  for (var i = 0; i < items.length; i++) {
    if (items[i].id === playerId) pit = items[i];
    if (items[i].id === xumoId) xit = items[i];
  }
  try {
    if (window.WORLD3D && window.WORLD3D.ext && window.WORLD3D.ext.setAvatar3D) {
      window.WORLD3D.ext.setAvatar3D(pit ? pit.url : null, xit ? xit.url : null);
    }
  } catch (e) {}
}

function m3Select(id, role) {
  fetch('/api/model/select', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ active_id: id, role: role || 'player' })
  }).then(function (r) { return r.json(); }).then(function (d) {
    if (!d.ok) { showToast(d.error || '切换失败'); return; }
    M3.state = d;
    m3RenderList();
    m3Apply(d.active_id, d.xumo_id);
    var isXu = role === 'xumo';
    showToast(id === 'default'
      ? (isXu ? '许墨已恢复默认形象' : '已恢复默认小人')
      : (isXu ? '许墨的 3D 形象已更新 💜' : '你的 3D 形象已更新 ✨'));
  }).catch(function () { showToast('网络错误'); });
}

function panelSet() {
  var S = E.state();
  return '<div class="w-panel w-panel-set">' +
    '<div class="w-panel-title">⚙️ 设置<div class="w-panel-x" data-close>✕</div></div>' +
    '<div class="w-scroll">' +
      '<div class="w-set-row"><span>时间流速</span><div>🕘 与现实同步（游戏时钟 = 现实时钟，每 24 小时度过一整天）</div></div>' +
      '<div class="w-set-row"><span>显示完整地貌</span><div class="w-set-doc"><label style="display:flex;align-items:center;gap:6px;cursor:pointer;color:#7c3aed"><input type="checkbox" id="wRevealMap" style="accent-color:#7c3aed"/> 关闭迷雾遮盖，直接看全图地貌<br><span style="color:#8a7fa8">（仅影响显示，探索度统计照常累计）</span></label></div></div>' +
      '<div class="w-set-row"><span>操作说明</span><div class="w-set-doc">WASD / 方向键 移动 · Shift 奔跑 · E 交互<br>Q/Z 旋转 · R/F 俯仰 · 右键拖拽 360° 环视 · 滚轮缩放<br>J 任务 · B 背包 · K 技能 · M 地图 · P 城市脉搏 · Esc 关闭</div></div>' +
      '<div class="w-set-row"><span>我的 3D 形象</span><div class="w-m3-box">' +
        '<div class="w-m3-cur" id="wM3Cur">当前：默认小人</div>' +
        '<label class="w-m3-up">📤 <span id="wM3UpTxt">上传我的模型</span><input type="file" id="wM3Up" accept=".glb,.gltf" style="display:none"></label>' +
        '<button class="w-m3-btn" id="wM3Reset">恢复默认小人</button>' +
      '</div></div>' +
      '<div class="w-set-row"><span>许墨的 3D 形象</span><div class="w-m3-box">' +
        '<div class="w-m3-cur" id="wM3XuCur">当前：默认许墨</div>' +
        '<label class="w-m3-up">📤 <span id="wM3XuUpTxt">上传许墨的模型</span><input type="file" id="wM3XuUp" accept=".glb,.gltf" style="display:none"></label>' +
        '<button class="w-m3-btn" id="wM3XuReset">恢复默认许墨</button>' +
      '</div></div>' +
      '<div class="w-set-row"><span>模型库</span><div class="w-m3-box">' +
        '<div class="w-m3-tip">支持 .glb（推荐）或全内嵌 .gltf，≤40MB；VRM 请先转 GLB。已上传的模型可分别「设为我」或「设为许墨」，两个形象完全独立。</div>' +
        '<div class="w-m3-list" id="wM3List"></div>' +
      '</div></div>' +
      '<div class="w-set-row"><span>游戏进度会自动保存在本机。<br>更换设备或清除浏览器数据将丢失存档。</span></div>' +
      '<div class="w-set-danger"><button class="w-btn-danger" id="wResetSave">重置世界（删除存档）</button></div>' +
    '</div></div>';
}
function wireSet() {
  $('wResetSave').addEventListener('click', function () {
    if (!confirm('确定要重置整个世界吗？所有进度将永久丢失。')) return;
    if (!confirm('再次确认：真的要重来吗？')) return;
    E.resetSave();
    closeModal();
    showToast('世界已重置。新的恋语市，新的开始。');
  });
  /* 显示完整地貌开关：关闭/开启迷雾遮盖（2D 主画面+小地图+大地图面板+3D 云雾盖） */
  var rm = $('wRevealMap');
  if (rm) {
    var st = E.state();
    rm.checked = !!(st && st.revealMap);
    rm.addEventListener('change', function () {
      var s2 = E.state();
      if (s2) { s2.revealMap = rm.checked; E.save(); }
      /* 3D 模式下立即重建云雾盖实例 */
      if (typeof rebuildFogMesh === 'function') { try { rebuildFogMesh(); } catch (_) {} }
      showToast(rm.checked ? '🌍 已显示完整地貌（迷雾已关闭）' : '🌫️ 已恢复迷雾探索');
    });
  }
  /* 3D 形象：列表 + 「我 / 许墨」双上传入口 */
  m3RenderList();
  m3Refresh();
  var m3Upload = function (upId, txtId, role) {
    var up = $(upId);
    if (!up) return;
    up.addEventListener('change', function () {
      var f = up.files && up.files[0];
      if (!f) return;
      if (f.size > 40 * 1024 * 1024) { showToast('模型不能超过 40MB'); up.value = ''; return; }
      var name = (f.name || '').replace(/\.(glb|gltf)$/i, '') || (role === 'xumo' ? '许墨模型' : '自传模型');
      var txt = $(txtId), idle = txt ? txt.textContent : '';
      up.disabled = true;
      /* 用 multipart/form-data 流式上传，避免 base64 膨胀与整文件内存驻留，
         显著提升外网/大文件场景的稳定性。XHR 支持 upload progress 反馈。 */
      var fd = new FormData();
      fd.append('file', f, f.name || 'model.glb');
      fd.append('name', name);
      fd.append('role', role);
      var xhr = new XMLHttpRequest();
      xhr.open('POST', '/api/model/upload', true);
      xhr.timeout = 300000; /* 5 分钟超时，适配大文件慢速上传 */
      if (txt) txt.textContent = '上传中… 0%';
      xhr.upload.onprogress = function (e) {
        if (e.lengthComputable && txt) {
          var pct = Math.round(e.loaded / e.total * 100);
          txt.textContent = '上传中… ' + pct + '%';
        }
      };
      xhr.onload = function () {
        up.disabled = false; up.value = '';
        if (txt) txt.textContent = idle;
        var d = null;
        try { d = JSON.parse(xhr.responseText); } catch (_) {}
        if (xhr.status >= 200 && xhr.status < 300 && d && d.ok) {
          M3.state = d;
          m3RenderList();
          m3Apply(d.active_id, d.xumo_id);
          showToast(role === 'xumo' ? '模型已应用为许墨的世界形象 💜' : '模型已应用为你的世界形象 ✨');
        } else {
          showToast((d && (d.error || d.detail)) || ('上传失败（HTTP ' + xhr.status + '）'));
        }
      };
      xhr.onerror = function () {
        up.disabled = false; up.value = '';
        if (txt) txt.textContent = idle;
        showToast('网络错误，请检查网络后重试');
      };
      xhr.ontimeout = function () {
        up.disabled = false; up.value = '';
        if (txt) txt.textContent = idle;
        showToast('上传超时，请压缩模型或检查网络后重试');
      };
      xhr.send(fd);
    });
  };
  m3Upload('wM3Up', 'wM3UpTxt', 'player');
  m3Upload('wM3XuUp', 'wM3XuUpTxt', 'xumo');
  var rst = $('wM3Reset');
  if (rst) rst.addEventListener('click', function () { m3Select('default', 'player'); });
  var xrst = $('wM3XuReset');
  if (xrst) xrst.addEventListener('click', function () { m3Select('default', 'xumo'); });
}

function wirePanel(name) {
  var box = $('wModalBox');
  box.querySelectorAll('[data-close]').forEach(function (x) {
    x.addEventListener('click', function () { closeModal(); });
  });
  if (name === 'set') wireSet();
  if (name === 'map') {
    var add = $('wPlaceAdd');
    if (add) add.addEventListener('click', function () { openPlaceForm(); });
    var ws = $('wWorkshop');
    if (ws) ws.addEventListener('click', function () { closeModal(); togglePanel('build'); });
    box.querySelectorAll('[data-delplace]').forEach(function (btn) {
      btn.addEventListener('click', function () {
        var id = btn.dataset.delplace;
        if (!confirm('删除这个自定义地点？配图也会一并删除。')) return;
        fetch('/api/world/places/' + id, { method: 'DELETE' })
          .then(function (r) { return r.json(); })
          .then(function (d) {
            if (d.ok) {
              E.removeCustomPlace(id);
              showToast('地点已删除');
              closeModal();
              togglePanel('map');
            } else showToast(d.error || '删除失败');
          })
          .catch(function () { showToast('删除失败'); });
      });
    });
    var bigCv = $('wBigMap');
    if (bigCv) bigCv.addEventListener('click', onBigMapClick);
  }
}

/* ================= 商店 ================= */
var SHOP_GOODS = [
  { id: 'bread', price: 15 },
  { id: 'bento', price: 28 },
  { id: 'coffee', price: 12 },
  { id: 'catfood', price: 20 },
  { id: 'bulb', price: 50, cond: function (S) { return S.mainStage >= 4; } }
];
function openShop() {
  var S = E.state();
  var rows = SHOP_GOODS.filter(function (g) { return !g.cond || g.cond(S); }).map(function (g) {
    var it = D.ITEMS[g.id];
    return '<div class="w-shop-row">' +
      '<span class="w-bag-icon">' + it.icon + '</span>' +
      '<div class="w-bag-info"><div>' + esc(it.name) + '</div><div class="w-sub">' + esc(it.desc) + '</div></div>' +
      '<button class="w-mini-btn" data-buy="' + g.id + '" data-price="' + g.price + '">¥' + g.price + '</button></div>';
  }).join('');
  openModal('<div class="w-panel"><div class="w-panel-title">🛒 日夜超市<div class="w-panel-x" data-close>✕</div></div>' +
    '<div class="w-shop-money">余额 ¥' + S.player.money + '</div>' +
    '<div class="w-scroll">' + rows + '</div></div>', 'shop');
  $('wModalBox').querySelectorAll('[data-buy]').forEach(function (b) {
    b.addEventListener('click', function () {
      var price = +b.dataset.price, id = b.dataset.buy;
      var S2 = E.state();
      if (S2.player.money < price) { showToast('钱不够呢……'); return; }
      S2.player.money -= price;
      E.giveItem(id, 1);
      showToast('买下了 ' + D.ITEMS[id].icon + ' ' + D.ITEMS[id].name);
      refreshHUD();
      openShop();
    });
  });
  $('wModalBox').querySelectorAll('[data-close]').forEach(function (x) {
    x.addEventListener('click', function () { closeModal(); });
  });
}

/* ================= 休息 ================= */
function openRest() {
  var S = E.state();
  var night = E.isNight();
  openModal('<div class="w-panel w-panel-rest">' +
    '<div class="w-panel-title">🏠 你的公寓<div class="w-panel-x" data-close>✕</div></div>' +
    '<div class="w-rest-body">' +
      '<p>小小的单人间，窗台上的绿萝长势正好。' + (night ? '夜色很深了。' : '') + '</p>' +
      '<p class="w-rest-tip">🕘 恋语市的时间与现实同步流转，休息不会让时间快进。</p>' +
      '<button class="w-btn-main" id="wRestNight">安睡一觉（恢复全部状态）</button>' +
      '<button class="w-btn-main ghost" id="wRestNap">小憩片刻（恢复 50% 体力生命）</button>' +
    '</div></div>', 'rest');
  $('wRestNight').addEventListener('click', function () {
    var S2 = E.state(), st = E.calcStats();
    S2.player.hp = st.hpMax; S2.player.sp = st.spMax;
    E.save(); refreshHUD();
    closeModal();
    showToast('一觉醒来，神清气爽。');
  });
  $('wRestNap').addEventListener('click', function () {
    var S2 = E.state(), st = E.calcStats();
    S2.player.hp = Math.min(st.hpMax, S2.player.hp + st.hpMax * 0.5);
    S2.player.sp = Math.min(st.spMax, S2.player.sp + st.spMax * 0.5);
    E.save(); refreshHUD();
    closeModal();
    showToast('眯了一会儿，舒服多了。');
  });
  $('wModalBox').querySelectorAll('[data-close]').forEach(function (x) {
    x.addEventListener('click', function () { closeModal(); });
  });
}

/* ================= 谜题 ================= */
var puzzleState = null;
function openPuzzle(pid) {
  var pz = D.PUZZLES[pid];
  if (!pz) return;
  var body = '';
  if (pz.type === 'code') {
    body = '<div class="w-pz-code"><input id="wPzInput" maxlength="' + pz.len + '" inputmode="numeric" placeholder="' + pz.len + ' 位数字" autocomplete="off">' +
      '<button class="w-btn-main" id="wPzOk">确认</button></div>';
  } else if (pz.type === 'lever') {
    puzzleState = { levers: [0, 0, 0] };
    body = '<div class="w-pz-levers">' +
      [0, 1, 2].map(function (i) {
        return '<button class="w-pz-lever" data-i="' + i + '"><span class="w-pz-arm"></span><span class="w-pz-base">杆 ' + (i + 1) + '</span></button>';
      }).join('') +
      '</div><button class="w-btn-main" id="wPzOk">拉动总闸</button>';
  } else if (pz.type === 'stele') {
    puzzleState = { seq: [] };
    body = '<div class="w-pz-steles">' +
      ['Ⅰ·冬', 'Ⅱ·春', 'Ⅲ·夏', 'Ⅳ·秋'].map(function (t, i) {
        return '<button class="w-pz-stele" data-i="' + (i + 1) + '"><span class="w-pz-star">🗿</span>' + t + '</button>';
      }).join('') +
      '</div><div class="w-pz-seq" id="wPzSeq">点击顺序：—</div>' +
      '<button class="w-btn-main" id="wPzOk">运转石阵</button>';
  }
  openModal('<div class="w-panel w-panel-pz">' +
    '<div class="w-panel-title">🧩 ' + esc(pz.name) + '<div class="w-panel-x" data-close>✕</div></div>' +
    '<div class="w-pz-hint">💡 ' + esc(pz.hint) + '</div>' +
    '<div class="w-pz-body">' + body + '</div>' +
    '</div>', 'puzzle');
  var box = $('wModalBox');
  box.querySelectorAll('[data-close]').forEach(function (x) { x.addEventListener('click', function () { closeModal(); }); });
  if (pz.type === 'code') {
    var inp = $('wPzInput');
    setTimeout(function () { inp.focus(); }, 60);
    inp.addEventListener('keydown', function (e) { if (e.key === 'Enter') tryCode(); });
    $('wPzOk').addEventListener('click', tryCode);
    function tryCode() {
      if (inp.value.trim() === pz.answer) pzDone(pid);
      else { showToast('不对……再想想线索。'); inp.value = ''; }
    }
  } else if (pz.type === 'lever') {
    box.querySelectorAll('.w-pz-lever').forEach(function (b) {
      b.addEventListener('click', function () {
        var i = +b.dataset.i;
        puzzleState.levers[i] = puzzleState.levers[i] ? 0 : 1;
        b.classList.toggle('up', !!puzzleState.levers[i]);
      });
    });
    $('wPzOk').addEventListener('click', function () {
      var ok = puzzleState.levers[0] === pz.answer[0] && puzzleState.levers[1] === pz.answer[1] && puzzleState.levers[2] === pz.answer[2];
      if (ok) pzDone(pid);
      else showToast('机关纹丝不动。顺序不对。');
    });
  } else if (pz.type === 'stele') {
    box.querySelectorAll('.w-pz-stele').forEach(function (b) {
      b.addEventListener('click', function () {
        var i = +b.dataset.i;
        if (puzzleState.seq.length >= 4) puzzleState.seq = [];
        puzzleState.seq.push(i);
        box.querySelectorAll('.w-pz-stele').forEach(function (bb) { bb.classList.remove('sel'); });
        puzzleState.seq.forEach(function (si, k) {
          var el = box.querySelector('[data-i="' + si + '"]');
          el.classList.add('sel');
          el.querySelector('.w-pz-star').textContent = (k + 1);
        });
        $('wPzSeq').textContent = '点击顺序：' + puzzleState.seq.join(' → ');
      });
    });
    $('wPzOk').addEventListener('click', function () {
      if (puzzleState.seq.length !== 4) { showToast('需要按顺序点亮四座石碑。'); return; }
      var ok = puzzleState.seq.every(function (v, k) { return v === pz.answer[k]; });
      if (ok) pzDone(pid);
      else { showToast('石碑暗了下去……次序不对。'); puzzleState.seq = []; box.querySelectorAll('.w-pz-stele').forEach(function (bb) { bb.classList.remove('sel'); bb.querySelector('.w-pz-star').textContent = '🗿'; }); $('wPzSeq').textContent = '点击顺序：—'; }
    });
  }
}
function pzDone(pid) {
  closeModal();
  E.onPuzzleSolved(pid);
  E.save();
}

/* ================= 战斗 ================= */
var battleSt = null;
function openBattle(shadow) {
  battleSt = { shadow: shadow, over: false };
  renderBattle();
}
function renderBattle(msg) {
  var s = battleSt.shadow;
  var S = E.state();
  var st = E.calcStats();
  var eDef = s.def || null;
  var eIcon = eDef && eDef.icon ? eDef.icon : '👁';
  var eName = eDef && eDef.name ? eDef.name : '记忆残影';
  var eEl = eDef && eDef.el ? eDef.el : 'normal';
  var elMeta = D.PLAYER_ELEMENTS ? (D.PLAYER_ELEMENTS[eEl] || D.PLAYER_ELEMENTS.normal) : { icon: '⚔️', name: '普通' };
  var myEl = E.playerElement ? E.playerElement() : 'normal';
  var myElMeta = (D.PLAYER_ELEMENTS && D.PLAYER_ELEMENTS[myEl]) ? D.PLAYER_ELEMENTS[myEl] : { icon: '⚔️', name: '普通' };
  var mul = (D.ELEMENT_CHART && D.ELEMENT_CHART[myEl]) ? (D.ELEMENT_CHART[myEl][eEl] || 1) : 1;
  var mulTxt = mul > 1.2 ? '<span class="w-bt-weak">克制 ×' + mul + '</span>' : (mul < 0.9 ? '<span class="w-bt-resist">抵抗 ×' + mul + '</span>' : '');
  openModal('<div class="w-panel w-panel-battle">' +
    '<div class="w-bt-title">⚔️ ' + esc(eName) + '</div>' +
    '<div class="w-bt-enemy">' +
      '<div class="w-bt-eicon">' + eIcon + '<span class="w-bt-el">' + elMeta.icon + '</span></div>' +
      '<div class="w-bt-emeta">' + esc(elMeta.name) + ' 系 ' + mulTxt + '</div>' +
      '<div class="w-bar w-hp big"><i style="width:' + Math.max(0, s.hp / s.hpMax * 100) + '%"></i><span>' + Math.max(0, Math.ceil(s.hp)) + '/' + s.hpMax + '</span></div>' +
    '</div>' +
    '<div class="w-bt-you">你 · HP ' + Math.ceil(S.player.hp) + '/' + st.hpMax + ' · 体力 ' + Math.ceil(S.player.sp) + '</div>' +
    (msg ? '<div class="w-bt-msg">' + esc(msg) + '</div>' : '') +
    '<div class="w-bt-acts">' +
      '<button class="w-btn-main" data-act="atk">攻击</button>' +
      '<button class="w-btn-main evol" data-act="skill">Evol 冲击（15体力）</button>' +
      '<button class="w-btn-main ghost" data-act="flee">逃跑</button>' +
    '</div></div>', 'battle', { lock: true });
  $('wModalBox').querySelectorAll('[data-act]').forEach(function (b) {
    b.addEventListener('click', function () { battleAct(b.dataset.act); });
  });
}
function battleAct(act) {
  if (!battleSt || battleSt.over) return;
  var S = E.state(), st = E.calcStats();
  var s = battleSt.shadow;
  var msg = '';
  if (act === 'atk') {
    var dmg = Math.round(st.atk * (0.8 + Math.random() * 0.4));
    s.hp -= dmg;
    msg += '你挥出武器，造成 ' + dmg + ' 点伤害。';
  } else if (act === 'skill') {
    if (S.player.sp < 15) { renderBattle('体力不足，Evol 无法凝聚……'); return; }
    S.player.sp -= 15;
    var dmg2 = Math.round(st.atk * 1.8 * (0.85 + Math.random() * 0.3));
    s.hp -= dmg2;
    msg += '淡紫色的波纹震荡开——造成 ' + dmg2 + ' 点伤害！';
  } else if (act === 'flee') {
    var ok = Math.random() < 0.62;
    if (ok) { battleSt.over = true; closeModal(); E.battleEnd(false, true); return; }
    msg += '你转身就跑——却被无形的东西缠住了脚踝。';
  }
  if (s.hp <= 0) {
    battleSt.over = true;
    closeModal();
    E.battleEnd(true, false);
    return;
  }
  /* 敌方反击 */
  var edmg = Math.round(s.atk * (0.8 + Math.random() * 0.4));
  S.player.hp -= edmg;
  msg += ' 残影发出刺耳的低语，你受到 ' + edmg + ' 点伤害。';
  if (S.player.hp <= 0) {
    battleSt.over = true;
    closeModal();
    E.battleEnd(false, false);
    return;
  }
  renderBattle(msg);
}

/* ================= 结局 ================= */
function showEnding(eid) {
  var e = D.ENDINGS[eid];
  var S = E.state();
  openModal('<div class="w-ending">' +
    '<div class="w-ending-icon">' + e.icon + '</div>' +
    '<div class="w-ending-name">' + esc(e.name) + '</div>' +
    '<div class="w-ending-tag">—— 结局 ' + e.id + ' · 主线完成 ——</div>' +
    '<div class="w-ending-text">' + esc(e.text).replace(/\n/g, '<br>') + '</div>' +
    '<div class="w-ending-stats">探索度 ' + E.explorePct() + '% · 第 ' + S.day + ' 天 · 许墨好感 ' + (S.npcAff.xumo || 0) + '</div>' +
    '<button class="w-btn-main" id="wEndGo">之后的日子（继续自由探索）</button>' +
    '<button class="w-btn-main ghost" id="wEndRe">重开这段旅程</button>' +
  '</div>', 'ending', { lock: true });
  $('wEndGo').addEventListener('click', function () { closeModal(); showToast('尾声：城市恢复了平静。大家都在等你去看他们。'); });
  $('wEndRe').addEventListener('click', function () {
    if (confirm('重新开始整个世界？当前进度将被清除。')) {
      E.resetSave();
      closeModal();
      showToast('新的旅程开始了。');
    }
  });
}

/* ================= 生命周期 ================= */
var startedOnce = false;
function applyModeUI(m) {
  if (!root) return;
  root.classList.toggle('mode-3d', m === '3d');
  var mb = $('wModeBtn');
  if (mb) { mb.textContent = m === '3d' ? '🗺️' : '🧊'; mb.title = m === '3d' ? '切回 2D 平面视角' : '切换 3D 立体视角'; }
  var rb = $('wRotBox');
  if (rb) rb.style.display = m === '3d' ? '' : 'none';
}
function boot() {
  if (!built || !$('wCanvas')) { build(); built = true; }
  E.bindCanvas($('wCanvas'), $('wMini'));
  /* 3D 体素渲染层（可选，失败自动留在 2D） */
  var mode3dReady = false;
  try {
    if (window.WORLD3D && window.WORLD3D.available()) {
      window.WORLD3D.init($('wCanvas3d'), $('wCanvas'));
      E.register3D(window.WORLD3D.ext);
      mode3dReady = true;
    }
  } catch (e) { console.error('[world] 3D init:', e); mode3dReady = false; }
  var savedMode = '2d';
  try { savedMode = localStorage.getItem('world_render_mode') || '2d'; } catch (e) {}
  /* 默认 2D 启动：避免 3D 场景异常时黑屏/空白；用户可在界面点 🗺️/🧊 按钮切到 3D */
  E.setRenderMode('2d');
  window.__worldMode3dReady = mode3dReady;
  window.__worldSavedMode = savedMode;
  applyModeUI(E.getRenderMode());
  E.start();
  refreshHUD();
  try {
    if (dbgEl) {
      dbgEl.textContent = 'world: booted ok\nmode=' + E.getRenderMode() + ' WG=' + (window.WorldGame ? 'y' : 'n') + ' 3D=' + (window.WORLD3D && window.WORLD3D.available() ? 'y' : 'n');
      var _dbgN = 0;
      setInterval(function () {
        try {
          var cv = $('wCanvas'), cv3 = $('wCanvas3d'), S = E.state();
          _dbgN++;
          dbgEl.textContent = 'mode=' + E.getRenderMode() + ' f=' + _dbgN
            + '\ncanvas=' + (cv ? cv.width + 'x' + cv.height : '?')
            + (cv3 ? (' 3d=' + cv3.width + 'x' + cv3.height) : '')
            + '\nstate=' + (S ? 'ok' : 'null') + ' WG=' + (window.WorldGame ? 'y' : 'n');
        } catch (e) { if (dbgEl) dbgEl.textContent = 'dbg err: ' + e; }
      }, 400);
    }
  } catch (e) {}
  /* 全局心动等级联动（技能·联结） */
  try {
    fetch('/api/affinity').then(function (r) { return r.json(); }).then(function (d) {
      if (d && typeof d.level_index === 'number') E.setLucienLevel(d.level_index + 1);
    }).catch(function () {});
  } catch (e) {}
  /* 去掉每次进入世界都要走的「开始探索」开场白环节 */
  var S = E.state();
  if (!S.seenPrologue) {
    S.seenPrologue = true;
    E.save();
  }
}
window.WorldGame = {
  start: function () {
    try { boot(); }
    catch (e) {
      console.error('[world] start:', e);
      var app = document.getElementById('app-world');
      if (app) {
        app.innerHTML = '<div style="position:absolute;inset:0;display:flex;align-items:center;justify-content:center;padding:24px;color:#b91c1c;font:14px/1.6 system-ui;white-space:pre-wrap;overflow:auto">世界启动失败：\n' + (e && e.stack ? e.stack : e) + '</div>';
      }
    }
  },
  pause: function () { try { if (modalOpen) closeModal(); E.pause(); } catch (e) { console.error('[world] pause:', e); } }
};

})();
