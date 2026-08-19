/* =========================================================
 * chat-window-kit.js — 聊天窗口拖拽 / 缩放套件
 * 让指定的聊天窗口支持：按住顶部 ⠿ 拖动漂浮移动、拉右下角手柄放大缩小。
 * 双击 ⠿ 或点 ⟲ 还原回原布局；Esc 一键还原所有漂浮窗口。
 * 仅在桌面宽度（≥768px）启用，移动端自动隐藏手柄不影响原布局。
 * 用法：ChatWinKit.attachAll(['.chat-panel', '#smsPage', ...])
 * ========================================================= */
(function () {
  'use strict';
  if (window.__chatWinKitLoaded) return;
  window.__chatWinKitLoaded = true;

  var Z_FLOAT = 1200;
  var FLOATING = []; /* 当前处于漂浮状态的实例 */

  /* ---------- 注入样式 ---------- */
  var css = [
    '.cw-grip{position:absolute;top:0;left:50%;transform:translateX(-50%);z-index:40;display:flex;align-items:center;gap:5px;padding:1px 10px 4px;border-radius:0 0 9px 9px;background:rgba(124,58,237,.14);color:rgba(124,58,237,.6);font-size:10px;line-height:1;letter-spacing:2px;cursor:grab;touch-action:none;-webkit-user-select:none;user-select:none;transition:background .15s,color .15s}',
    '.cw-grip:hover{background:rgba(124,58,237,.9);color:#fff}',
    'body.cw-dragging{cursor:grabbing}',
    'body.cw-dragging,body.cw-dragging *{-webkit-user-select:none!important;user-select:none!important}',
    '.cw-restore{display:none;border:none;background:rgba(255,255,255,.28);color:inherit;font-size:11px;line-height:1;padding:2px 5px;border-radius:5px;cursor:pointer;letter-spacing:0;font-family:inherit}',
    '.cw-restore:hover{background:rgba(255,255,255,.5)}',
    '.cw-floating .cw-restore{display:inline-block}',
    '.cw-rz{position:absolute;right:2px;bottom:2px;width:16px;height:16px;z-index:40;cursor:nwse-resize;touch-action:none;opacity:.5;background:linear-gradient(135deg,transparent 46%,rgba(124,58,237,.55) 46%);border-radius:0 0 8px 0;transition:opacity .15s}',
    '.cw-rz:hover{opacity:1}',
    '.cw-floating{box-shadow:0 20px 55px rgba(43,33,64,.38)!important}',
    '.cw-wrap{position:relative;display:flex;flex-direction:column;flex:1 1 auto;min-height:0;min-width:0}',
    '.cw-placeholder{pointer-events:none;opacity:0}',
    '@media (max-width:767px){.cw-grip,.cw-rz{display:none!important}}'
  ].join('\n');
  var st = document.createElement('style');
  st.id = 'cw-kit-style';
  st.textContent = css;
  (document.head || document.documentElement).appendChild(st);

  function desktopOk() { return window.innerWidth >= 768; }
  function px(n) { return Math.round(n) + 'px'; }

  /* 漂浮时的活动范围：手机 App 内限制在其 app-view 里，其余为整个视口 */
  function containerRect(el) {
    var av = el.closest ? el.closest('.app-view') : null;
    if (av) {
      var r = av.getBoundingClientRect();
      if (r.width > 60 && r.height > 60) return r;
    }
    return { left: 0, top: 0, width: window.innerWidth, height: window.innerHeight, right: window.innerWidth, bottom: window.innerHeight };
  }

  function modeStr() {
    var out = [];
    document.body.classList.forEach(function (c) { if (c.indexOf('mode-') === 0) out.push(c); });
    return out.join(' ');
  }

  /* ---------- 漂浮 / 还原 ---------- */
  function doFloat(inst) {
    var t = inst.target;
    var rect = t.getBoundingClientRect();
    inst.savedStyle = t.getAttribute('style') || '';

    /* 占位元素：保持原布局不塌陷（原本就脱离文档流的则不需要） */
    var ph = document.createElement('div');
    ph.className = 'cw-placeholder';
    var pcs = getComputedStyle(t);
    if (pcs.position === 'absolute' || pcs.position === 'fixed') {
      ph.style.display = 'none';
    } else {
      ph.style.cssText = 'flex-grow:' + pcs.flexGrow + ';flex-shrink:' + pcs.flexShrink +
        ';flex-basis:' + pcs.flexBasis + ';align-self:' + pcs.alignSelf +
        ';min-width:0;min-height:0;max-width:' + pcs.maxWidth +
        ';width:' + px(rect.width) + ';height:' + px(rect.height) + ';';
    }
    t.parentNode.insertBefore(ph, t);
    inst.ph = ph;

    var s = t.style;
    s.position = 'fixed';
    s.left = px(rect.left); s.top = px(rect.top);
    s.width = px(rect.width); s.height = px(rect.height);
    s.margin = '0';
    s.flex = 'none';
    s.maxWidth = 'none'; s.maxHeight = 'none';
    s.transform = 'none';
    s.transition = 'none';
    s.zIndex = String(Z_FLOAT);
    t.classList.add('cw-floating');
    inst.floating = true;
    if (FLOATING.indexOf(inst) < 0) FLOATING.push(inst);
  }

  function restore(inst) {
    if (!inst || !inst.floating) return;
    var t = inst.target;
    t.classList.remove('cw-floating');
    if (inst.savedStyle) t.setAttribute('style', inst.savedStyle);
    else t.removeAttribute('style');
    if (inst.ph) { inst.ph.remove(); inst.ph = null; }
    inst.floating = false;
    var i = FLOATING.indexOf(inst);
    if (i >= 0) FLOATING.splice(i, 1);
  }

  function restoreAll() { FLOATING.slice().forEach(restore); }

  /* ---------- 拖拽 / 缩放 ---------- */
  function beginDrag(e, inst, mode) {
    if (!desktopOk()) return;
    if (e.button !== undefined && e.button !== 0) return;
    e.preventDefault(); e.stopPropagation();
    if (!inst.floating) doFloat(inst);

    var t = inst.target;
    var startX = e.clientX, startY = e.clientY;
    var r = t.getBoundingClientRect();
    var oL = r.left, oT = r.top, oW = r.width, oH = r.height;
    var minW = inst.inPhone ? 150 : 260;
    var minH = inst.inPhone ? 110 : 180;
    document.body.classList.add('cw-dragging');

    function onMove(ev) {
      var dx = ev.clientX - startX, dy = ev.clientY - startY;
      var c = containerRect(inst.el);
      if (mode === 'move') {
        var x = Math.max(c.left - oW + 60, Math.min(oL + dx, c.right - 60));
        var y = Math.max(c.top - 12, Math.min(oT + dy, c.bottom - 44));
        t.style.left = px(x); t.style.top = px(y);
      } else {
        var w = Math.max(minW, Math.min(oW + dx, c.right - oL));
        var h = Math.max(minH, Math.min(oH + dy, c.bottom - oT));
        t.style.width = px(w); t.style.height = px(h);
      }
    }
    function onUp() {
      document.body.classList.remove('cw-dragging');
      window.removeEventListener('pointermove', onMove);
      window.removeEventListener('pointerup', onUp);
      window.removeEventListener('pointercancel', onUp);
    }
    window.addEventListener('pointermove', onMove);
    window.addEventListener('pointerup', onUp);
    window.addEventListener('pointercancel', onUp);
  }

  /* ---------- 挂载 ---------- */
  function attach(el) {
    if (!el || el.__cwBound) return null;
    el.__cwBound = true;

    /* 聊天区自身是滚动容器时，在外面包一层，手柄才不会随内容滚走 */
    var target = el;
    if (/auto|scroll/.test(getComputedStyle(el).overflowY)) {
      var wrap = document.createElement('div');
      wrap.className = 'cw-wrap';
      el.parentNode.insertBefore(wrap, el);
      wrap.appendChild(el);
      target = wrap;
    }
    if (getComputedStyle(target).position === 'static') target.style.position = 'relative';

    var grip = document.createElement('div');
    grip.className = 'cw-grip';
    grip.title = '按住拖动窗口 · 双击还原';
    grip.innerHTML = '\u28FF<button type="button" class="cw-restore" title="还原窗口位置与大小">\u27F2</button>';

    var rz = document.createElement('div');
    rz.className = 'cw-rz';
    rz.title = '按住拖动以放大 / 缩小';

    target.appendChild(grip);
    target.appendChild(rz);

    var inst = {
      el: el, target: target, grip: grip, rz: rz,
      floating: false, savedStyle: '', ph: null,
      inPhone: !!(target.closest && target.closest('.app-view'))
    };

    grip.querySelector('.cw-restore').addEventListener('click', function (e) {
      e.stopPropagation(); restore(inst);
    });
    grip.addEventListener('dblclick', function () { restore(inst); });
    grip.addEventListener('pointerdown', function (e) {
      if (e.target.closest && e.target.closest('.cw-restore')) return;
      beginDrag(e, inst, 'move');
    });
    rz.addEventListener('pointerdown', function (e) { beginDrag(e, inst, 'resize'); });

    /* 所属 App 关闭时自动还原，避免残留漂浮窗口 */
    var av = target.closest ? target.closest('.app-view') : null;
    if (av && window.MutationObserver) {
      new MutationObserver(function () {
        if (inst.floating && !av.classList.contains('open')) restore(inst);
      }).observe(av, { attributes: true, attributeFilter: ['class'] });
    }

    /* 包裹场景：原聊天区被隐藏时同步隐藏手柄 */
    if (target !== el && window.MutationObserver) {
      var syncVis = function () {
        var hidden = el.style.display === 'none' || getComputedStyle(el).display === 'none';
        grip.style.visibility = hidden ? 'hidden' : '';
        rz.style.visibility = hidden ? 'hidden' : '';
      };
      new MutationObserver(syncVis).observe(el, { attributes: true, attributeFilter: ['style', 'class'] });
      syncVis();
    }
    return inst;
  }

  function attachAll(selectors) {
    function run() {
      (selectors || []).forEach(function (sel) {
        var els = document.querySelectorAll(sel);
        for (var i = 0; i < els.length; i++) attach(els[i]);
      });
    }
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', run);
    else run();
  }

  /* ---------- 全局兜底 ---------- */
  /* Esc 还原所有漂浮窗口 */
  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape' && FLOATING.length) restoreAll();
  });

  /* 页面布局模式（mode-*）切换时全部还原，避免和内联样式打架 */
  if (window.MutationObserver) {
    var lastModes = modeStr();
    new MutationObserver(function () {
      var now = modeStr();
      if (now !== lastModes) { lastModes = now; restoreAll(); }
    }).observe(document.body, { attributes: true, attributeFilter: ['class'] });
  }

  /* 视口尺寸变化时，把漂浮窗口夹回可见范围 */
  window.addEventListener('resize', function () {
    FLOATING.forEach(function (inst) {
      var t = inst.target;
      var r = t.getBoundingClientRect();
      var c = containerRect(inst.el);
      var x = Math.max(c.left - r.width + 60, Math.min(r.left, c.right - 60));
      var y = Math.max(c.top - 12, Math.min(r.top, c.bottom - 44));
      t.style.left = px(x); t.style.top = px(y);
      t.style.width = px(Math.max(120, Math.min(r.width, c.right - x)));
      t.style.height = px(Math.max(90, Math.min(r.height, c.bottom - y)));
    });
  });

  window.ChatWinKit = { attach: attach, attachAll: attachAll, restoreAll: restoreAll };
})();
