(function () {
  'use strict';
  if (window.__xumoMobileAdapt) return;
  window.__xumoMobileAdapt = true;

  var nativeShell = !!(
    (window.Capacitor && typeof window.Capacitor.isNativePlatform === 'function' && window.Capacitor.isNativePlatform()) ||
    /;\s*wv\)/i.test(navigator.userAgent)
  );
  var viewportMeta = document.querySelector('meta[name="viewport"]');
  if (!viewportMeta) {
    viewportMeta = document.createElement('meta');
    viewportMeta.name = 'viewport';
    document.head.appendChild(viewportMeta);
  }
  viewportMeta.content = 'width=device-width,initial-scale=1,viewport-fit=cover,interactive-widget=resizes-content';

  var shellMedia = window.matchMedia('(max-width: 820px), (max-width: 932px) and (max-height: 500px)');
  var shellReady = false;
  var currentRoute = 'chat';
  var returnRoute = 'apps';
  var activeModeKey = 'c';
  var raf = 0;
  var icons = {
    chat: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M7.2 18.2 3.5 20l1-3.6A8 8 0 1 1 7.2 18.2Z"/><path d="M8 10h8M8 14h5"/></svg>',
    apps: '<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="4" y="4" width="6" height="6" rx="1.5"/><rect x="14" y="4" width="6" height="6" rx="1.5"/><rect x="4" y="14" width="6" height="6" rx="1.5"/><rect x="14" y="14" width="6" height="6" rx="1.5"/></svg>',
    modes: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="m12 3 1.7 4.3L18 9l-4.3 1.7L12 15l-1.7-4.3L6 9l4.3-1.7L12 3Z"/><path d="m18.5 15 .8 2.2 2.2.8-2.2.8-.8 2.2-.8-2.2-2.2-.8 2.2-.8.8-2.2Z"/></svg>',
    world: '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="9"/><path d="M3.5 9h17M3.5 15h17M12 3c2.2 2.5 3.3 5.5 3.3 9S14.2 18.5 12 21c-2.2-2.5-3.3-5.5-3.3-9S9.8 5.5 12 3Z"/></svg>',
    me: '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="8" r="4"/><path d="M4.5 21c.7-4.2 3.2-6.5 7.5-6.5s6.8 2.3 7.5 6.5"/></svg>',
    back: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="m15 5-7 7 7 7"/></svg>',
    search: '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="11" cy="11" r="7"/><path d="m16.5 16.5 4 4"/></svg>',
    chevron: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="m9 5 7 7-7 7"/></svg>'
  };

  function mobileEnabled() { return nativeShell || shellMedia.matches; }

  function syncVisualViewport() {
    cancelAnimationFrame(raf);
    raf = requestAnimationFrame(function () {
      var vv = window.visualViewport;
      var height = vv ? vv.height : window.innerHeight;
      document.documentElement.style.setProperty('--mobile-visual-height', Math.round(height) + 'px');
      if (document.body) document.body.classList.toggle('keyboard-open', mobileEnabled() && height < window.innerHeight * .78);
    });
  }

  function revealFocusedControl(event) {
    if (!mobileEnabled()) return;
    var target = event.target;
    if (!target || !target.matches('input,textarea,select,[contenteditable="true"]')) return;
    window.setTimeout(function () {
      var vv = window.visualViewport;
      var bottom = vv ? vv.height : window.innerHeight;
      var rect = target.getBoundingClientRect();
      if (rect.bottom > bottom - 12 || rect.top < 8) target.scrollIntoView({ block: 'center', inline: 'nearest', behavior: 'smooth' });
    }, 180);
  }

  function cleanLabel(value) {
    return String(value || '').trim().replace(/^[^\u4e00-\u9fa5A-Za-z0-9]+/, '') || '应用';
  }

  function escapeHtml(value) {
    return String(value == null ? '' : value).replace(/[&<>"']/g, function (character) {
      return { '&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;' }[character];
    });
  }

  function appCatalog() {
    var seen = {};
    var result = [];
    document.querySelectorAll('#iconGrid .app-icon[data-app], .dock .app-icon[data-app]').forEach(function (item) {
      var key = item.getAttribute('data-app');
      if (!key || seen[key]) return;
      seen[key] = true;
      var label = item.querySelector('.label');
      var glyph = item.querySelector('.glyph');
      result.push({ key: key, label: cleanLabel(label ? label.textContent : (item.title || key)), glyph: glyph ? glyph.innerHTML : '' });
    });
    return result;
  }

  function buildShell() {
    if (shellReady || !document.body || !document.getElementById('iconGrid') || !document.querySelector('.chat-panel')) return;
    shellReady = true;
    var legacyTab = document.getElementById('xumoBottomTab');
    if (legacyTab && mobileEnabled()) legacyTab.remove();

    var pages = document.createElement('div');
    pages.id = 'mobileShellPages';
    pages.innerHTML =
      '<section class="mobile-shell-page" id="mobileAppsPage" data-route="apps" aria-label="全部应用">' +
        '<header class="mobile-shell-header"><div><small>功能中心</small><h1>全部应用</h1></div><span class="mobile-shell-count" id="mobileAppCount"></span></header>' +
        '<label class="mobile-shell-search">' + icons.search + '<span class="sr-only">搜索应用</span><input id="mobileAppSearch" type="search" inputmode="search" autocomplete="off" placeholder="搜索全部功能"></label>' +
        '<div class="mobile-app-grid" id="mobileAppGrid"></div>' +
      '</section>' +
      '<section class="mobile-shell-page" id="mobileModesPage" data-route="modes" aria-label="场景模式">' +
        '<header class="mobile-shell-header"><div><small>呈现方式</small><h1>场景模式</h1></div></header>' +
        '<p class="mobile-shell-lead">选择一种手机场景。聊天、应用与数据共用同一套功能。</p>' +
        '<div class="mobile-mode-list" id="mobileModeList"></div>' +
        '<button class="mobile-list-row" id="mobileModeManage" type="button"><span class="mobile-list-icon">' + icons.modes + '</span><span><b>管理模式</b><small>添加、隐藏或恢复模式</small></span>' + icons.chevron + '</button>' +
      '</section>' +
      '<section class="mobile-shell-page" id="mobileMePage" data-route="me" aria-label="我的">' +
        '<header class="mobile-profile-head"><span class="mobile-profile-avatar">X</span><div><small>个人中心</small><h1>我的</h1><p>账号、设置与使用帮助</p></div></header>' +
        '<div class="mobile-list-group">' +
          '<button class="mobile-list-row" type="button" data-me-action="account"><span><b>账号与数据</b><small>查看账户资料和数据状态</small></span>' + icons.chevron + '</button>' +
          '<button class="mobile-list-row" type="button" data-me-action="settings"><span><b>应用设置</b><small>偏好、模型与功能配置</small></span>' + icons.chevron + '</button>' +
          '<button class="mobile-list-row" type="button" data-me-action="guide"><span><b>使用引导</b><small>重新查看功能说明</small></span>' + icons.chevron + '</button>' +
        '</div>' +
      '</section>';

    var nav = document.createElement('nav');
    nav.id = 'mobilePrimaryNav';
    nav.setAttribute('aria-label', '手机主导航');
    nav.innerHTML = [['chat','聊天'],['apps','应用'],['modes','模式'],['world','世界'],['me','我的']].map(function (entry) {
      return '<button type="button" data-route="' + entry[0] + '" aria-label="' + entry[1] + '">' + icons[entry[0]] + '<span>' + entry[1] + '</span></button>';
    }).join('');

    var modeBackBar = document.createElement('header');
    modeBackBar.id = 'mobileModeBackBar';
    modeBackBar.innerHTML = '<button type="button" aria-label="返回应用中心">' + icons.back + '<span>全部应用</span></button><b>场景模式</b><i aria-hidden="true"></i>';

    document.body.appendChild(pages);
    document.body.appendChild(modeBackBar);
    document.body.appendChild(nav);
    renderApps();
    renderModes();
    pages.addEventListener('click', onPageClick);
    nav.addEventListener('click', function (event) {
      var button = event.target.closest('button[data-route]');
      if (button) showRoute(button.getAttribute('data-route'));
    });
    modeBackBar.querySelector('button').addEventListener('click', backToApps);
    document.getElementById('mobileAppSearch').addEventListener('input', renderApps);
    document.getElementById('mobileModeManage').addEventListener('click', function () {
      var trigger = document.getElementById('xumoModeManageBtn');
      if (trigger) trigger.click();
    });
    var modeSwitch = document.getElementById('xumoModeSw');
    if (modeSwitch) new MutationObserver(renderModes).observe(modeSwitch, { childList: true, subtree: true, attributes: true });

    var originalOpenApp = window.openApp;
    if (typeof originalOpenApp === 'function' && !originalOpenApp.__mobileShellWrapped) {
      var wrappedOpenApp = function (name) {
        if (mobileEnabled()) {
          returnRoute = currentRoute === 'mode'
            ? ((activeModeKey === 'g' || activeModeKey === 'h') ? 'modes' : 'mode')
            : (currentRoute === 'me' ? 'me' : (currentRoute === 'modes' ? 'modes' : 'apps'));
          closeShellPages();
          document.body.classList.remove('mobile-route-chat', 'mobile-route-mode');
          setNav(name === 'world' ? 'world' : 'apps');
        }
        return originalOpenApp.apply(this, arguments);
      };
      wrappedOpenApp.__mobileShellWrapped = true;
      window.openApp = wrappedOpenApp;
    }

    document.addEventListener('click', function (event) {
      if (!mobileEnabled() || !event.target.closest('.nav-back')) return;
      window.setTimeout(function () { if (!document.body.classList.contains('app-open')) showRoute(returnRoute); }, 380);
    }, true);
    document.addEventListener('click', function (event) {
      if (!mobileEnabled() || currentRoute !== 'mode' || !event.target.closest('[data-app]')) return;
      returnRoute = (activeModeKey === 'g' || activeModeKey === 'h') ? 'modes' : 'mode';
    }, true);
    new MutationObserver(function () {
      if (!mobileEnabled() || !document.body.classList.contains('app-open') || currentRoute !== 'mode') return;
      returnRoute = (activeModeKey === 'g' || activeModeKey === 'h') ? 'modes' : 'mode';
      document.body.classList.remove('mobile-route-mode');
    }).observe(document.body, { attributes: true, attributeFilter: ['class'] });
    applyShellState();
    showRoute('chat');
    installNativeBackHandler();
  }

  function backToApps() {
    if (!mobileEnabled() || !document.body) return false;
    if (document.body.classList.contains('app-open')) {
      try { if (typeof window.closeApp === 'function') window.closeApp(true); } catch (ignore) {}
    }
    showRoute('apps');
    return true;
  }

  function handleNativeBack() {
    if (!mobileEnabled() || !document.body) return false;
    if (document.body.classList.contains('app-open')) {
      try { if (typeof window.closeApp === 'function') window.closeApp(true); } catch (ignore) {}
      showRoute(returnRoute || 'apps');
      return true;
    }
    if (document.body.classList.contains('mobile-route-mode') || currentRoute === 'mode' || currentRoute === 'modes' || currentRoute === 'world' || currentRoute === 'me') {
      return backToApps();
    }
    if (currentRoute === 'apps') {
      showRoute('chat');
      return true;
    }
    return false;
  }

  function installNativeBackHandler() {
    if (window.__xumoNativeBackInstalled) return;
    var capacitorApp = window.Capacitor && window.Capacitor.Plugins && window.Capacitor.Plugins.App;
    if (!capacitorApp || typeof capacitorApp.addListener !== 'function') return;
    window.__xumoNativeBackInstalled = true;
    capacitorApp.addListener('backButton', function (event) {
      if (handleNativeBack()) return;
      if (event && event.canGoBack) window.history.back();
      else if (typeof capacitorApp.exitApp === 'function') capacitorApp.exitApp();
    });
  }

  function renderApps() {
    var grid = document.getElementById('mobileAppGrid');
    if (!grid) return;
    var search = document.getElementById('mobileAppSearch');
    var query = (search && search.value || '').trim().toLowerCase();
    var apps = appCatalog().filter(function (app) { return !query || app.label.toLowerCase().indexOf(query) > -1 || app.key.toLowerCase().indexOf(query) > -1; });
    grid.innerHTML = apps.map(function (app) {
      return '<button type="button" class="mobile-app-tile" data-app="' + escapeHtml(app.key) + '" aria-label="打开' + escapeHtml(app.label) + '"><span class="mobile-app-glyph">' + app.glyph + '</span><span>' + escapeHtml(app.label) + '</span></button>';
    }).join('') || '<p class="mobile-shell-empty">没有找到匹配的功能</p>';
    grid.querySelectorAll('img').forEach(function (image) { image.loading = 'lazy'; image.decoding = 'async'; });
    var count = document.getElementById('mobileAppCount');
    if (count) count.textContent = apps.length + ' 项';
  }

  function renderModes() {
    var list = document.getElementById('mobileModeList');
    var sw = document.getElementById('xumoModeSw');
    if (!list || !sw) return;
    var names = { a:'沉浸共生', b:'心象阁', c:'掌上终端', d:'记忆星图', e:'时光庭院', f:'深夜电台', g:'世界', h:'手谈', j:'心境潮汐', k:'纸上书房', l:'实验室' };
    var seen = {};
    var rows = [];
    sw.querySelectorAll('button[data-mode]').forEach(function (button) {
      var key = button.getAttribute('data-mode');
      if (!key || seen[key] || button.style.display === 'none') return;
      seen[key] = true;
      var title = cleanLabel(button.title || names[key] || button.textContent || key);
      if (/^[A-L]\s/i.test(title)) title = title.slice(2).trim();
      rows.push('<button class="mobile-mode-row" type="button" data-mode="' + escapeHtml(key) + '"><span class="mobile-mode-letter">' + escapeHtml(key.slice(0,2).toUpperCase()) + '</span><span><b>' + escapeHtml(title) + '</b><small>以全屏手机页面打开</small></span>' + icons.chevron + '</button>');
    });
    list.innerHTML = rows.join('');
  }

  function onPageClick(event) {
    var app = event.target.closest('[data-app]');
    if (app && typeof window.openApp === 'function') { window.openApp(app.getAttribute('data-app')); return; }
    var mode = event.target.closest('[data-mode]');
    if (mode) {
      var modeKey = mode.getAttribute('data-mode');
      activateMode(modeKey);
      return;
    }
    var action = event.target.closest('[data-me-action]');
    if (!action) return;
    var name = action.getAttribute('data-me-action');
    if (name === 'account') window.location.href = '/account.html';
    if (name === 'settings' && typeof window.openApp === 'function') window.openApp('settings');
    if (name === 'guide') { var guide = document.getElementById('guideBtn'); if (guide) guide.click(); }
  }

  function closeShellPages() {
    document.querySelectorAll('.mobile-shell-page.active').forEach(function (page) { page.classList.remove('active'); });
    if (document.body) document.body.classList.remove('mobile-shell-page-open');
  }

  function setNav(route) {
    var nav = document.getElementById('mobilePrimaryNav');
    if (!nav) return;
    nav.querySelectorAll('button[data-route]').forEach(function (button) {
      var selected = button.getAttribute('data-route') === route;
      button.classList.toggle('on', selected);
      button.setAttribute('aria-current', selected ? 'page' : 'false');
    });
  }

  function activateMode(modeKey) {
    if (!modeKey || !document.body) return;
    activeModeKey = modeKey;
    currentRoute = 'mode';
    closeShellPages();
    document.body.classList.remove('mobile-route-chat');
    document.body.classList.add('mobile-route-mode');
    setNav('modes');
    if (typeof window.xumoSetMode === 'function') {
      window.xumoSetMode(modeKey);
      return;
    }
    var modeButton = document.querySelector('#xumoModeSw button[data-mode="' + modeKey + '"]');
    if (modeButton) modeButton.click();
    if (/^[a-l]$/.test(modeKey) && !document.body.classList.contains('mode-' + modeKey)) {
      Array.prototype.slice.call(document.body.classList).forEach(function (name) {
        if (/^mode-[a-l]$/.test(name)) document.body.classList.remove(name);
      });
      document.body.classList.add('mode-' + modeKey);
    }
  }

  function showRoute(route) {
    if (!mobileEnabled() || !document.body) return;
    currentRoute = route;
    closeShellPages();
    document.body.classList.remove('mobile-route-chat', 'mobile-route-mode');
    if (route === 'mode') {
      activateMode(activeModeKey || 'c');
      return;
    }
    if (route === 'chat') {
      try { if (typeof window.closeApp === 'function') window.closeApp(true); } catch (ignore) {}
      document.body.classList.add('mobile-route-chat');
      setNav('chat');
      return;
    }
    if (route === 'world') {
      if (typeof window.openApp === 'function') window.openApp('world');
      setNav('world');
      return;
    }
    var page = document.querySelector('.mobile-shell-page[data-route="' + route + '"]');
    if (page) {
      try { if (typeof window.closeApp === 'function') window.closeApp(true); } catch (ignore2) {}
      page.classList.add('active');
      document.body.classList.add('mobile-shell-page-open');
      if (route === 'apps') renderApps();
      if (route === 'modes') renderModes();
    }
    setNav(route);
  }

  function applyShellState() {
    if (!document.body) return;
    var enabled = mobileEnabled();
    document.body.classList.toggle('mobile-shell-active', enabled && shellReady);
    document.body.classList.toggle('capacitor-shell', nativeShell);
    if (enabled) {
      document.body.classList.remove('device-desktop');
      document.body.classList.add('device-mobile');
      document.body.setAttribute('data-device', 'mobile');
    }
    if (!enabled) {
      closeShellPages();
      document.body.classList.remove('mobile-route-chat', 'mobile-route-mode');
    } else if (shellReady && !document.querySelector('.mobile-shell-page.active') && !document.body.classList.contains('app-open') && !document.body.classList.contains('mobile-route-mode')) {
      showRoute(currentRoute || 'chat');
    }
  }

  function boot() {
    buildShell();
    applyShellState();
    syncVisualViewport();
    window.setTimeout(function () { buildShell(); applyShellState(); renderApps(); renderModes(); installNativeBackHandler(); }, 700);
  }

  window.xumoMobileBackToApps = backToApps;

  document.addEventListener('DOMContentLoaded', boot);
  document.addEventListener('focusin', revealFocusedControl);
  window.addEventListener('resize', function () { syncVisualViewport(); applyShellState(); }, { passive: true });
  window.addEventListener('orientationchange', syncVisualViewport, { passive: true });
  if (shellMedia.addEventListener) shellMedia.addEventListener('change', applyShellState);
  if (window.visualViewport) {
    window.visualViewport.addEventListener('resize', syncVisualViewport, { passive: true });
    window.visualViewport.addEventListener('scroll', syncVisualViewport, { passive: true });
  }
  if (document.readyState !== 'loading') boot();
  syncVisualViewport();
})();
