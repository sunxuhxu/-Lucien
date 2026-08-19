(function () {
  'use strict';

  var icons = {
    voice: '<svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M11 5 6.5 9H3v6h3.5L11 19V5Z" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"/><path d="M15 9a4 4 0 0 1 0 6M17.8 6.5a7.5 7.5 0 0 1 0 11" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg>',
    screen: '<svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><rect x="3" y="4" width="18" height="13" rx="2" stroke="currentColor" stroke-width="1.8"/><path d="M8 21h8M12 17v4" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg>',
    call: '<svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><rect x="9" y="3" width="6" height="11" rx="3" stroke="currentColor" stroke-width="1.8"/><path d="M5.5 11.5a6.5 6.5 0 0 0 13 0M12 18v3M9 21h6" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg>',
    history: '<svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M4 8V4m0 0h4M4.5 4.5A9 9 0 1 1 3 14" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/><path d="M12 7v5l3 2" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg>',
    reset: '<svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M4 8V4m0 0h4M4.5 4.5A9 9 0 1 1 3 14" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>',
    help: '<svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><circle cx="12" cy="12" r="9" stroke="currentColor" stroke-width="1.8"/><path d="M9.8 9a2.35 2.35 0 1 1 3.6 2c-.9.55-1.4 1.1-1.4 2M12 17h.01" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg>'
  };

  function enhanceButton(id, icon, label) {
    var button = document.getElementById(id);
    if (!button || button.dataset.premiumReady) return;
    button.dataset.premiumReady = 'true';
    button.setAttribute('aria-label', label);
    if (!button.title) button.title = label;
    button.innerHTML = icons[icon] + '<span class="ui-btn-label">' + label + '</span>';
  }

  function improveSemantics(root) {
    (root || document).querySelectorAll('.app-icon[data-app]').forEach(function (button) {
      if (!button.hasAttribute('aria-label')) {
        var label = button.querySelector('.label');
        var fallback = { phone: '电话', sms: '短信', moments: '朋友圈', affinity: '心动', settings: '设置' };
        button.setAttribute('aria-label', label && label.textContent.trim() || fallback[button.dataset.app] || '打开应用');
      }
    });
    (root || document).querySelectorAll('.glyph img:not([width])').forEach(function (image) {
      image.setAttribute('width', '52');
      image.setAttribute('height', '52');
      image.setAttribute('decoding', 'async');
    });
    (root || document).querySelectorAll('button:disabled').forEach(function (button) {
      button.setAttribute('aria-busy', 'true');
    });
  }

  function immersiveIcon(name) {
    var paths = {
      chat: '<path d="M7 17.2 3.5 20v-5.2A8 8 0 1 1 7 17.2Z"/><path d="M8 10h.01M12 10h.01M16 10h.01"/>',
      world: '<circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3a14 14 0 0 1 0 18M12 3a14 14 0 0 0 0 18"/>',
      listen: '<path d="M4 13v-1a8 8 0 0 1 16 0v1"/><path d="M4 13h2a2 2 0 0 1 2 2v3a2 2 0 0 1-2 2H5a1 1 0 0 1-1-1v-6ZM20 13h-2a2 2 0 0 0-2 2v3a2 2 0 0 0 2 2h1a1 1 0 0 0 1-1v-6Z"/>',
      photos: '<rect x="3" y="5" width="18" height="14" rx="2"/><circle cx="9" cy="10" r="2"/><path d="m21 15-4.5-4.5L8 19"/>',
      search: '<circle cx="11" cy="11" r="7"/><path d="m20 20-4-4"/>',
      layers: '<path d="m12 3 9 5-9 5-9-5 9-5Z"/><path d="m3 12 9 5 9-5M3 16l9 5 9-5"/>',
      edit: '<path d="M13.5 6.5 17.5 10.5M4 20l4.4-1 10.8-10.8a2.8 2.8 0 0 0-4-4L4.4 15 4 20Z"/>',
      previous: '<path d="m14.5 7-5 5 5 5"/>',
      next: '<path d="m9.5 7 5 5-5 5"/>',
      play: '<path d="m9 7 8 5-8 5V7Z"/>',
      pause: '<path d="M9 7v10M15 7v10"/>',
      heart: '<path d="M20.8 5.9a5.4 5.4 0 0 0-7.7 0L12 7l-1.1-1.1a5.4 5.4 0 0 0-7.7 7.7L12 22l8.8-8.4a5.4 5.4 0 0 0 0-7.7Z"/>',
      memory: '<path d="M9 4a3 3 0 0 0-3 3v.2A3.5 3.5 0 0 0 4 13a3.5 3.5 0 0 0 2 5.8V19a3 3 0 0 0 6 0V7a3 3 0 0 0-3-3Z"/><path d="M15 4a3 3 0 0 1 3 3v.2a3.5 3.5 0 0 1 2 5.8 3.5 3.5 0 0 1-2 5.8V19a3 3 0 0 1-6 0V7a3 3 0 0 1 3-3Z"/><path d="M8 9h1M15 9h1M8 15h1M15 15h1"/>',
      promise: '<path d="M8 3h8M9 3v3M15 3v3"/><rect x="4" y="6" width="16" height="15" rx="2"/><path d="m8 14 2.4 2.4L16.5 10"/>',
      pulse: '<path d="M3 12h4l2-5 4 10 2-5h6"/>'
    };
    return '<svg viewBox="0 0 24 24" fill="none" aria-hidden="true" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">' + (paths[name] || paths.pulse) + '</svg>';
  }

  function upgradeImmersiveActions(home) {
    var map = [
      ['[data-act="chat"]', 'chat', '对话'],
      ['[data-app="world"]', 'world', '世界'],
      ['[data-app="listen"]', 'listen', '一起听'],
      ['[data-app="photos"]', 'photos', '相册'],
      ['[data-act="cmd"]', 'search', '搜索'],
      ['[data-act="bgcar"]', 'layers', '场景'],
      ['[data-act="edit"]', 'edit', '编辑布局']
    ];
    map.forEach(function (item) {
      var button = home.querySelector('.xa-actions ' + item[0]);
      if (!button) return;
      button.innerHTML = immersiveIcon(item[1]) + '<span>' + item[2] + '</span>';
      button.setAttribute('aria-label', item[2]);
    });
  }

  function upgradeSceneBar(home) {
    var bar = home.querySelector('#xabBar');
    if (!bar || bar.dataset.premiumReady) return;
    bar.dataset.premiumReady = 'true';
    function render(button) {
      var action = button && button.dataset.xab;
      if (!action || action === 'speed') return;
      var name = action === 'prev' ? 'previous' : action;
      if (action === 'play') {
        if (button.textContent.indexOf('▶') > -1) name = 'play';
        else if (button.textContent.indexOf('⏸') > -1) name = 'pause';
        else return;
      }
      if (button.dataset.sceneIcon === name) return;
      button.dataset.sceneIcon = name;
      button.innerHTML = immersiveIcon(name);
      button.setAttribute('aria-label', button.title || ({ previous: '上一张', next: '下一张', play: '播放', pause: '暂停' }[name]));
    }
    bar.querySelectorAll('button').forEach(render);
    var playButton = bar.querySelector('[data-xab="play"]');
    if (playButton) new MutationObserver(function () { render(playButton); }).observe(playButton, { childList: true, characterData: true, subtree: true });
  }

  function safeNumber(value, fallback) {
    var number = Number(value);
    return Number.isFinite(number) ? number : (fallback == null ? 0 : fallback);
  }

  function setImmersiveText(id, value) {
    var element = document.getElementById(id);
    if (element) element.textContent = value;
  }

  function getJson(url) {
    return fetch(url, { credentials: 'include' }).then(function (response) {
      return response.ok ? response.json() : null;
    }).catch(function () { return null; });
  }

  function updateImmersiveClock() {
    var now = new Date();
    var h = String(now.getHours()).padStart(2, '0');
    var m = String(now.getMinutes()).padStart(2, '0');
    setImmersiveText('uiImmTime', h + ':' + m);
    setImmersiveText('uiImmDate', (now.getMonth() + 1) + '月' + now.getDate() + '日 · 星期' + '日一二三四五六'[now.getDay()]);
  }

  function renderImmersiveWeek(week) {
    var chart = document.getElementById('uiImmChart');
    var total = document.getElementById('uiImmWeekTotal');
    if (!chart) return;
    var items = Array.isArray(week) ? week.slice(-7) : [];
    var minutes = items.map(function (item) { return safeNumber(item.minutes, 0); });
    var sum = minutes.reduce(function (a, b) { return a + b; }, 0);
    var max = Math.max.apply(Math, minutes.concat([1]));
    var weekNames = ['日', '一', '二', '三', '四', '五', '六'];
    if (total) total.textContent = sum ? sum + ' 分钟' : '等待记录';
    chart.innerHTML = Array.from({ length: 7 }).map(function (_, index) {
      var sourceIndex = index - (7 - items.length);
      var item = sourceIndex >= 0 ? items[sourceIndex] : null;
      var value = item ? safeNumber(item.minutes, 0) : 0;
      var height = value ? Math.max(14, Math.round(value / max * 100)) : 8;
      var label = item && item.date ? weekNames[new Date(item.date.replace(/-/g, '/')).getDay()] : '—';
      return '<div class="ui-imm-bar-cell" title="' + (value ? value + ' 分钟' : '暂无记录') + '">' +
        '<span class="ui-imm-bar-value">' + (value || '') + '</span>' +
        '<i style="height:' + height + '%"></i><small>' + label + '</small></div>';
    }).join('');
    chart.setAttribute('aria-label', sum ? '近七日专注共 ' + sum + ' 分钟' : '近七日暂无专注记录');
  }

  function refreshImmersiveDashboard() {
    var panel = document.getElementById('uiImmersivePanel');
    if (!panel || !document.body.classList.contains('mode-a')) return;
    panel.classList.add('is-syncing');
    Promise.all([
      getJson('/api/affinity'),
      getJson('/api/memory'),
      getJson('/api/promises'),
      getJson('/api/coach/focus/stats'),
      getJson('/api/status'),
      getJson('/api/quotes/daily'),
      getJson('/api/weather'),
      getJson('/api/study/stats')
    ]).then(function (data) {
      var affinity = data[0] || {};
      var memoryData = data[1] || {};
      var promiseData = data[2] || {};
      var focus = data[3] || {};
      var status = data[4] || {};
      var quote = data[5] || {};
      var weather = data[6] || {};
      var study = data[7] || {};

      var affinityValue = safeNumber(affinity.value != null ? affinity.value : affinity.affinity && affinity.affinity.value, 0);
      var progress = Math.max(0, Math.min(100, safeNumber(affinity.progress, affinityValue <= 100 ? affinityValue : affinityValue % 100)));
      var ring = document.getElementById('uiImmRing');
      if (ring) ring.style.strokeDashoffset = String(263.9 * (1 - progress / 100));
      setImmersiveText('uiImmAff', affinityValue ? String(affinityValue) : '—');
      setImmersiveText('uiImmLevel', affinity.level_name || affinity.level_code || '关系正在生长');
      setImmersiveText('uiImmProgress', affinityValue ? progress + '% 阶段进度' : '等待首次同步');

      var memories = memoryData.items || memoryData.memories || memoryData.list || (Array.isArray(memoryData) ? memoryData : []);
      var promises = promiseData.items || promiseData.list || promiseData.promises || [];
      var openPromises = promises.filter(function (item) { return !item.done; });
      setImmersiveText('uiImmMemoryCount', String(memories.length || 0));
      setImmersiveText('uiImmPromiseCount', String(openPromises.length || 0));
      setImmersiveText('uiImmStreak', safeNumber(study.streak_days, 0) + '天');

      var activity = status.activity || status.state && status.state.activity || '此刻很安静';
      var place = status.scene || status.state && status.state.place || '沉浸空间';
      setImmersiveText('uiImmStatus', activity);
      setImmersiveText('uiImmPlace', place);

      var recentMemory = memories[0];
      var memoryText = recentMemory && (recentMemory.content || recentMemory.text || recentMemory.summary);
      var daily = quote.daily && quote.daily.content;
      setImmersiveText('uiImmInsight', memoryText ? '他记得：' + memoryText.slice(0, 42) + (memoryText.length > 42 ? '…' : '') : (daily ? '今日签语：' + daily.slice(0, 42) : '新的共同记忆会在这里浮现'));

      var today = weather.today || {};
      var weatherText = [today.city, today.weather, today.temp != null ? today.temp + '°' : ''].filter(Boolean).join(' · ');
      setImmersiveText('uiImmWeather', weatherText || '环境数据待同步');
      setImmersiveText('uiImmTodayFocus', safeNumber(focus.today_minutes, 0) + 'm');
      renderImmersiveWeek(focus.week || []);
    }).finally(function () {
      panel.classList.remove('is-syncing');
    });
  }

  function buildImmersiveDashboard() {
    var home = document.getElementById('xumoHomeA');
    if (!home || document.getElementById('uiImmersivePanel')) return;
    upgradeImmersiveActions(home);
    upgradeSceneBar(home);
    var panel = document.createElement('aside');
    panel.id = 'uiImmersivePanel';
    panel.className = 'ui-immersive-panel';
    panel.setAttribute('aria-label', '共生关系仪表');
    panel.innerHTML =
      '<header class="ui-imm-head"><div><span class="ui-imm-kicker"><i></i> LUCID CONNECTION</span><h2>共生仪表</h2></div><div class="ui-imm-clock"><b id="uiImmTime">--:--</b><span id="uiImmDate">—</span></div></header>' +
      '<section class="ui-imm-relation" aria-labelledby="uiImmRelationTitle">' +
        '<div class="ui-imm-ring"><svg viewBox="0 0 100 100" role="img" aria-label="关系阶段进度"><circle class="ui-imm-ring-track" cx="50" cy="50" r="42"/><circle class="ui-imm-ring-value" id="uiImmRing" cx="50" cy="50" r="42"/></svg><div><strong id="uiImmAff">—</strong><small>心动</small></div></div>' +
        '<div class="ui-imm-relation-copy"><span id="uiImmRelationTitle">关系温度</span><strong id="uiImmLevel">正在同步</strong><small id="uiImmProgress">等待数据</small><div class="ui-imm-scene"><i></i><span id="uiImmPlace">沉浸空间</span></div></div>' +
      '</section>' +
      '<section class="ui-imm-stats" aria-label="关系摘要">' +
        '<button type="button" data-app="memory"><span>' + immersiveIcon('memory') + '共同记忆</span><strong id="uiImmMemoryCount">—</strong><small>件</small></button>' +
        '<button type="button" data-app="promises"><span>' + immersiveIcon('promise') + '待办承诺</span><strong id="uiImmPromiseCount">—</strong><small>件</small></button>' +
        '<button type="button" data-app="coach"><span>' + immersiveIcon('pulse') + '连续陪伴</span><strong id="uiImmStreak">—</strong><small>今日 <b id="uiImmTodayFocus">—</b></small></button>' +
      '</section>' +
      '<section class="ui-imm-chart-wrap"><div class="ui-imm-section-title"><span>七日节律</span><b id="uiImmWeekTotal">等待记录</b></div><div class="ui-imm-chart" id="uiImmChart" role="img" aria-label="近七日专注记录"></div></section>' +
      '<section class="ui-imm-insight"><span>' + immersiveIcon('pulse') + '</span><div><small>此刻 · <b id="uiImmWeather">环境数据待同步</b></small><strong id="uiImmStatus">正在感知他的状态</strong><p id="uiImmInsight">新的共同记忆会在这里浮现</p></div></section>' +
      '<nav class="ui-imm-quick" aria-label="沉浸页快捷入口"><button type="button" data-app="affinity">' + immersiveIcon('heart') + '<span>关系详情</span></button><button type="button" data-app="memory">' + immersiveIcon('memory') + '<span>记忆手账</span></button><button type="button" data-ui-mode="chat">' + immersiveIcon('chat') + '<span>进入对话</span></button></nav>';
    home.appendChild(panel);

    panel.addEventListener('click', function (event) {
      var appButton = event.target.closest('[data-app]');
      if (appButton && window.openApp) {
        window.openApp(appButton.getAttribute('data-app'));
        return;
      }
      if (event.target.closest('[data-ui-mode="chat"]')) {
        var chatMode = document.querySelector('#xumoModeSw button[data-mode="c"]');
        if (chatMode) chatMode.click();
      }
    });

    updateImmersiveClock();
    renderImmersiveWeek([]);
    refreshImmersiveDashboard();
    setInterval(updateImmersiveClock, 30000);
    setInterval(refreshImmersiveDashboard, 60000);

    var modeObserver = new MutationObserver(function () {
      if (document.body.classList.contains('mode-a')) {
        updateImmersiveClock();
        refreshImmersiveDashboard();
      }
    });
    modeObserver.observe(document.body, { attributes: true, attributeFilter: ['class'] });
  }

  function init() {
    document.documentElement.dataset.ui = 'premium-v2';

    if (!document.querySelector('.ui-skip-link')) {
      var skip = document.createElement('a');
      skip.className = 'ui-skip-link';
      skip.href = '#chat-main';
      skip.textContent = '跳到主要对话';
      document.body.insertBefore(skip, document.body.firstChild);
    }

    var chat = document.querySelector('.chat-panel');
    if (chat) {
      chat.id = chat.id || 'chat-main';
      chat.setAttribute('role', 'main');
      chat.setAttribute('tabindex', '-1');
    }

    enhanceButton('voiceBtn', 'voice', '语音');
    enhanceButton('screenBtn', 'screen', '屏幕');
    enhanceButton('callEntryBtn', 'call', '通话');
    enhanceButton('chatHistBtn', 'history', '记录');
    enhanceButton('clearBtn', 'reset', '重置');
    enhanceButton('guideBtn', 'help', '引导');

    if (!document.querySelector('.ui-live-region')) {
      var live = document.createElement('div');
      live.className = 'ui-live-region';
      live.setAttribute('role', 'status');
      live.setAttribute('aria-live', 'polite');
      live.setAttribute('aria-atomic', 'true');
      document.body.appendChild(live);
    }

    improveSemantics(document);
    buildImmersiveDashboard();

    var observer = new MutationObserver(function (records) {
      records.forEach(function (record) {
        if (record.type === 'attributes' && record.target.matches && record.target.matches('button')) {
          if (record.target.disabled) record.target.setAttribute('aria-busy', 'true');
          else record.target.removeAttribute('aria-busy');
        }
        record.addedNodes.forEach(function (node) {
          if (node.nodeType === 1) {
            improveSemantics(node);
            if (node.id === 'xabBar' || node.querySelector && node.querySelector('#xabBar')) {
              var immersiveHome = document.getElementById('xumoHomeA');
              if (immersiveHome) upgradeSceneBar(immersiveHome);
            }
          }
        });
      });
    });
    observer.observe(document.body, { childList: true, subtree: true, attributes: true, attributeFilter: ['disabled'] });
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init, { once: true });
  else init();
})();
