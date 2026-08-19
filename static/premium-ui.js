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
      pulse: '<path d="M3 12h4l2-5 4 10 2-5h6"/>',
      note: '<path d="M5 3h11l3 3v15H5V3Z"/><path d="M15 3v4h4M8 11h8M8 15h8"/>',
      todo: '<rect x="3" y="3" width="18" height="18" rx="3"/><path d="m7 9 2 2 4-4M7 16h10"/>',
      curve: '<path d="M3 5c3 1 3.5 8 7 10s6 1 11 4"/><path d="M3 20h18M4 4v16"/>',
      word: '<path d="M4 5.5A2.5 2.5 0 0 1 6.5 3H11a3 3 0 0 1 3 3v15a3 3 0 0 0-3-3H4V5.5Z"/><path d="M20 5.5A2.5 2.5 0 0 0 17.5 3H14v18a3 3 0 0 1 3-3h3V5.5Z"/>',
      book: '<path d="M4 4h12a3 3 0 0 1 3 3v13H7a3 3 0 0 1-3-3V4Z"/><path d="M7 17h12M8 8h7M8 12h5"/>',
      music: '<path d="M9 18V6l10-2v12"/><circle cx="6" cy="18" r="3"/><circle cx="16" cy="16" r="3"/>',
      anime: '<rect x="3" y="5" width="18" height="15" rx="3"/><path d="m9 9 6 3-6 3V9ZM8 2l4 3 4-3"/>',
      calendar: '<rect x="3" y="5" width="18" height="16" rx="3"/><path d="M8 3v4M16 3v4M3 10h18M8 14h.01M12 14h.01M16 14h.01M8 18h.01M12 18h.01"/>',
      rings: '<circle cx="9" cy="12" r="6"/><circle cx="15" cy="12" r="6"/><path d="m10 5 2-3 2 3"/>',
      home: '<path d="m3 11 9-8 9 8"/><path d="M5 10v11h14V10M9 21v-7h6v7"/>',
      user: '<circle cx="12" cy="8" r="4"/><path d="M4 21a8 8 0 0 1 16 0"/>'
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
      ['[data-act="bgcar"]', 'layers', '背景轮播'],
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

  function renderImmersiveMetrics(context) {
    var progress = Math.max(0, Math.min(100, safeNumber(context.progress, 0)));
    var week = Array.isArray(context.week) ? context.week.slice(-7) : [];
    var weekValues = week.map(function (item) { return safeNumber(item.minutes, 0); });
    var weekTotal = weekValues.reduce(function (sum, value) { return sum + value; }, 0);
    var weekMax = Math.max.apply(Math, weekValues.concat([1]));
    var promises = context.promises || [];
    var promiseDone = promises.filter(function (item) { return !!item.done; }).length;
    var promiseRate = promises.length ? Math.round(promiseDone / promises.length * 100) : 0;
    var memories = context.memories || [];
    var now = Date.now();
    var recentMemories = memories.filter(function (item) {
      var raw = item.ts || item.created_at || item.time;
      var stamp = raw ? new Date(String(raw).replace(' ', 'T')).getTime() : NaN;
      return Number.isFinite(stamp) && now - stamp <= 7 * 86400000;
    });
    var memoryDays = Array.from({ length: 7 }, function (_, index) {
      var start = new Date();
      start.setHours(0, 0, 0, 0);
      start.setDate(start.getDate() - (6 - index));
      var end = start.getTime() + 86400000;
      return memories.filter(function (item) {
        var raw = item.ts || item.created_at || item.time;
        var stamp = raw ? new Date(String(raw).replace(' ', 'T')).getTime() : NaN;
        return Number.isFinite(stamp) && stamp >= start.getTime() && stamp < end;
      }).length;
    });
    var totalWords = safeNumber(context.study.total_words, 0);
    var mastered = safeNumber(context.study.mastered, 0);
    var masteryRate = totalWords ? Math.round(mastered / totalWords * 100) : 0;

    setImmersiveText('uiImmMomentumValue', progress + '%');
    setImmersiveText('uiImmFocusValue', weekTotal + 'm');
    setImmersiveText('uiImmPromiseRate', promiseRate + '%');
    setImmersiveText('uiImmRecentMemory', String(recentMemories.length));
    setImmersiveText('uiImmMasteryValue', masteryRate + '%');
    var momentum = document.getElementById('uiImmMomentumBar');
    if (momentum) momentum.style.width = progress + '%';
    var promiseRing = document.getElementById('uiImmPromiseRing');
    if (promiseRing) promiseRing.style.setProperty('--metric-value', promiseRate);
    var mastery = document.getElementById('uiImmMasteryBar');
    if (mastery) mastery.style.width = masteryRate + '%';
    var focusMini = document.getElementById('uiImmFocusMini');
    if (focusMini) focusMini.innerHTML = weekValues.concat(Array(7 - weekValues.length).fill(0)).slice(0, 7).map(function (value) {
      return '<i style="height:' + (value ? Math.max(18, Math.round(value / weekMax * 100)) : 10) + '%"></i>';
    }).join('');
    var memoryHeat = document.getElementById('uiImmMemoryHeat');
    if (memoryHeat) memoryHeat.innerHTML = memoryDays.map(function (value) {
      return '<i class="' + (value > 1 ? 'is-high' : value ? 'is-on' : '') + '" title="' + value + ' 条新记忆"></i>';
    }).join('');

    var metricGrid = document.getElementById('uiImmMetricGrid');
    if (metricGrid) metricGrid.setAttribute('aria-label', '五项关系数据：阶段进度 ' + progress + '%，本周专注 ' + weekTotal + ' 分钟，承诺履约 ' + promiseRate + '%，七日新增记忆 ' + recentMemories.length + ' 条，词汇掌握 ' + masteryRate + '%');
  }

  var immersiveDeskState = {
    words: [], wordIndex: 0, wordRevealed: false,
    songs: [], songIndex: 0, audio: null,
    life: null, auth: null
  };

  function immersiveEscape(value) {
    return String(value == null ? '' : value).replace(/[&<>"']/g, function (char) {
      return ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[char];
    });
  }

  function immersiveNotice(message) {
    if (window.showToast) window.showToast(message);
    var live = document.querySelector('.ui-live-region');
    if (live) live.textContent = message;
  }

  function immersiveToday() {
    var now = new Date();
    return now.getFullYear() + '-' + String(now.getMonth() + 1).padStart(2, '0') + '-' + String(now.getDate()).padStart(2, '0');
  }

  function postImmersiveLife(path, body) {
    return fetch(path, {
      method: 'POST', credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body || {})
    }).then(function (response) {
      return response.json().catch(function () { return {}; }).then(function (data) {
        if (!response.ok || data.error) throw new Error(data.error || data.detail || '操作失败');
        immersiveDeskState.life = data;
        renderImmersiveLife(data);
        return data;
      });
    }).catch(function (error) { immersiveNotice(error.message || '操作失败'); return null; });
  }

  function immersiveDeskRead(key, fallback) {
    try {
      var value = JSON.parse(localStorage.getItem(key));
      return value == null ? fallback : value;
    } catch (error) { return fallback; }
  }

  function immersiveDeskWrite(key, value) {
    try { localStorage.setItem(key, JSON.stringify(value)); } catch (error) { /* storage is optional */ }
  }

  function setImmersiveDeskOpen(open, remember) {
    var desk = document.getElementById('uiImmersiveDesk');
    var toggle = document.getElementById('uiImmDeskToggle');
    if (!desk || !toggle) return;
    document.body.classList.toggle('imm-desk-open', open);
    desk.classList.toggle('is-open', open);
    desk.setAttribute('aria-hidden', open ? 'false' : 'true');
    toggle.setAttribute('aria-expanded', open ? 'true' : 'false');
    if (remember !== false) immersiveDeskWrite('xumo_immersive_desk_open_v1', !!open);
    if (open) refreshImmersiveDesk();
  }

  function renderImmersiveTodos() {
    var list = document.getElementById('uiImmTodoList');
    if (!list) return;
    var todos = immersiveDeskRead('xumo_immersive_todos_v1', []);
    list.innerHTML = todos.length ? todos.slice(0, 8).map(function (todo) {
      return '<li class="' + (todo.done ? 'is-done' : '') + '" data-id="' + String(todo.id) + '">' +
        '<button type="button" class="ui-imm-todo-check" aria-label="' + (todo.done ? '标记为未完成' : '标记为完成') + '" aria-pressed="' + (todo.done ? 'true' : 'false') + '"><span></span></button>' +
        '<span>' + String(todo.text || '').replace(/[&<>"']/g, function (char) { return ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[char]; }) + '</span>' +
        '<button type="button" class="ui-imm-todo-delete" aria-label="删除待办">×</button></li>';
    }).join('') : '<li class="ui-imm-desk-empty">写下今天想完成的一件事</li>';
    setImmersiveText('uiImmTodoCount', todos.filter(function (todo) { return !todo.done; }).length + ' 项待办');
  }

  function addImmersiveTodo() {
    var input = document.getElementById('uiImmTodoInput');
    if (!input) return;
    var text = input.value.trim();
    if (!text) return;
    var todos = immersiveDeskRead('xumo_immersive_todos_v1', []);
    todos.unshift({ id: Date.now(), text: text.slice(0, 80), done: false });
    immersiveDeskWrite('xumo_immersive_todos_v1', todos.slice(0, 30));
    input.value = '';
    renderImmersiveTodos();
  }

  function renderImmersiveCurve(cardsData) {
    var cards = cardsData && (cardsData.items || cardsData.cards) || [];
    var due = safeNumber(cardsData && cardsData.due, cards.filter(function (card) { return (card.due || '') <= new Date().toISOString().slice(0, 10); }).length);
    var reviewed = cards.filter(function (card) { return safeNumber(card.reps, 0) > 0; });
    var strength = reviewed.length ? reviewed.reduce(function (sum, card) { return sum + Math.max(1, safeNumber(card.interval, 1)); }, 0) / reviewed.length : 2.4;
    var days = [0, 1, 3, 7, 14];
    var points = days.map(function (day, index) {
      var retention = Math.max(12, Math.round(100 * Math.exp(-day / Math.max(2.8, strength * 1.8))));
      return (8 + index * 46) + ',' + (68 - retention * .52);
    }).join(' ');
    var line = document.getElementById('uiImmCurveLine');
    if (line) line.setAttribute('points', points);
    setImmersiveText('uiImmCurveDue', due ? '今天 ' + due + ' 张待复习' : (cards.length ? '今日记忆状态良好' : '创建卡片后生成预测'));
  }

  function renderImmersiveWord() {
    var words = immersiveDeskState.words;
    var word = words[immersiveDeskState.wordIndex] || null;
    setImmersiveText('uiImmWordMain', word ? word.word : '暂无单词');
    setImmersiveText('uiImmWordPhonetic', word && word.phonetic ? word.phonetic : (word ? '点击查看释义' : '去词库添加内容'));
    var meaning = document.getElementById('uiImmWordMeaning');
    if (meaning) {
      meaning.textContent = word ? (word.meaning || '暂无释义') : '打开背单词应用开始学习';
      meaning.classList.toggle('is-revealed', !!immersiveDeskState.wordRevealed || !word);
    }
    var reveal = document.getElementById('uiImmWordReveal');
    if (reveal) reveal.textContent = immersiveDeskState.wordRevealed ? '隐藏释义' : '查看释义';
  }

  function renderImmersiveReading(booksData) {
    var books = booksData && booksData.books || [];
    var book = books[0];
    var pct = book ? safeNumber(book.progress, 0) : 0;
    if (pct > 0 && pct <= 1) pct *= 100;
    pct = Math.max(0, Math.min(100, Math.round(pct)));
    setImmersiveText('uiImmReadingTitle', book ? book.title : '书架还没有阅读记录');
    setImmersiveText('uiImmReadingMeta', book ? '第 ' + (safeNumber(book.current_chapter, 0) + 1) + ' / ' + safeNumber(book.chapters, 0) + ' 章 · ' + pct + '%' : '放入一本书，和他开始共读');
    var bar = document.getElementById('uiImmReadingBar');
    if (bar) bar.style.width = pct + '%';
  }

  function formatImmersiveTime(seconds) {
    seconds = Math.max(0, Math.floor(safeNumber(seconds, 0)));
    return Math.floor(seconds / 60) + ':' + String(seconds % 60).padStart(2, '0');
  }

  function setImmersiveRangeProgress(slider, value) {
    if (!slider) return;
    var pct = Math.max(0, Math.min(100, safeNumber(value, 0)));
    slider.value = String(pct);
    slider.style.setProperty('--ui-range-pct', pct + '%');
  }

  function selectImmersiveSong(index, autoplay) {
    var songs = immersiveDeskState.songs;
    if (!songs.length) return;
    immersiveDeskState.songIndex = (index + songs.length) % songs.length;
    var song = songs[immersiveDeskState.songIndex];
    var audio = immersiveDeskState.audio;
    if (!audio) {
      audio = new Audio();
      audio.preload = 'metadata';
      immersiveDeskState.audio = audio;
      audio.addEventListener('timeupdate', function () {
        var slider = document.getElementById('uiImmMusicProgress');
        if (slider && audio.duration) setImmersiveRangeProgress(slider, audio.currentTime / audio.duration * 100);
        setImmersiveText('uiImmMusicTime', formatImmersiveTime(audio.currentTime) + ' / ' + formatImmersiveTime(audio.duration));
      });
      audio.addEventListener('play', function () { document.getElementById('uiImmMusicPlay').innerHTML = immersiveIcon('pause'); });
      audio.addEventListener('pause', function () { document.getElementById('uiImmMusicPlay').innerHTML = immersiveIcon('play'); });
      audio.addEventListener('ended', function () { selectImmersiveSong(immersiveDeskState.songIndex + 1, true); });
    }
    audio.src = '/api/music/file/' + encodeURIComponent(song.id);
    setImmersiveText('uiImmMusicTitle', song.title || '未命名音乐');
    setImmersiveText('uiImmMusicArtist', song.artist || (song.source === 'singing' ? '唱给许墨' : '本地音乐'));
    setImmersiveText('uiImmMusicTime', '0:00 / ' + formatImmersiveTime(song.duration));
    var progress = document.getElementById('uiImmMusicProgress');
    setImmersiveRangeProgress(progress, 0);
    if (autoplay) audio.play().catch(function () { /* browser may require a second gesture */ });
  }

  function renderImmersiveMusic(songsData) {
    var incoming = songsData && songsData.songs || [];
    immersiveDeskState.songs = incoming;
    if (!incoming.length) {
      setImmersiveText('uiImmMusicTitle', '歌单还是空的');
      setImmersiveText('uiImmMusicArtist', '去「一起听」上传一首歌');
      document.getElementById('uiImmMusicPlay').disabled = true;
      return;
    }
    document.getElementById('uiImmMusicPlay').disabled = false;
    if (!immersiveDeskState.audio || !immersiveDeskState.audio.src) selectImmersiveSong(0, false);
  }

  function renderImmersiveAnime(items) {
    var list = document.getElementById('uiImmAnimeList');
    if (!list) return;
    items = Array.isArray(items) ? items : [];
    setImmersiveText('uiImmAnimeCount', items.length + ' 部');
    list.innerHTML = items.length ? items.slice(0, 4).map(function (item) {
      var current = safeNumber(item.current, 0);
      var total = safeNumber(item.total, 0);
      return '<li data-id="' + immersiveEscape(item.id) + '" class="' + (item.status === 'done' ? 'is-done' : '') + '">' +
        '<span title="' + immersiveEscape(item.title) + '">' + immersiveEscape(item.title) + '</span>' +
        '<button type="button" data-anime-delta="-1" aria-label="上一集">−</button>' +
        '<b>' + current + (total ? '/' + total : '') + '</b>' +
        '<button type="button" data-anime-delta="1" aria-label="下一集">＋</button>' +
        '<button type="button" data-anime-delete aria-label="删除追番记录">×</button></li>';
    }).join('') : '<li class="ui-imm-desk-empty">添加一部想和他一起追的番</li>';
  }

  function renderImmersiveCalendar(items) {
    var list = document.getElementById('uiImmCalendarList');
    if (!list) return;
    items = Array.isArray(items) ? items : [];
    var today = immersiveToday();
    var dayStrip = document.getElementById('uiImmCalendarDays');
    if (dayStrip) {
      dayStrip.innerHTML = Array.from({ length: 7 }).map(function (_, index) {
        var date = new Date();
        date.setHours(12, 0, 0, 0);
        date.setDate(date.getDate() + index);
        var dateKey = date.getFullYear() + '-' + String(date.getMonth() + 1).padStart(2, '0') + '-' + String(date.getDate()).padStart(2, '0');
        var count = items.filter(function (item) { return item.date === dateKey; }).length;
        return '<button type="button" class="' + (index === 0 ? 'is-selected' : '') + '" data-calendar-date="' + dateKey + '" aria-label="选择' + (date.getMonth() + 1) + '月' + date.getDate() + '日"><span>' + '日一二三四五六'[date.getDay()] + '</span><b>' + date.getDate() + '</b>' + (count ? '<i>' + count + '</i>' : '') + '</button>';
      }).join('');
    }
    var upcoming = items.filter(function (item) { return (item.date || '') >= today; }).slice(0, 4);
    setImmersiveText('uiImmCalendarMonth', (new Date().getMonth() + 1) + '月 · ' + items.length + ' 项');
    list.innerHTML = upcoming.length ? upcoming.map(function (item) {
      return '<li data-id="' + immersiveEscape(item.id) + '"><time datetime="' + immersiveEscape(item.date) + '">' + immersiveEscape((item.date || '').slice(5).replace('-', '/')) + '</time><span>' + immersiveEscape(item.title) + '</span><button type="button" data-calendar-delete aria-label="删除日程">×</button></li>';
    }).join('') : '<li class="ui-imm-desk-empty">暂时没有未来日程</li>';
  }

  function renderImmersiveMarriage(marriage) {
    marriage = marriage || {};
    var married = marriage.status === 'married';
    var card = document.querySelector('.ui-imm-marriage');
    if (card) card.classList.toggle('is-married', married);
    setImmersiveText('uiImmMarriageStatus', married ? '已缔结婚约' : '等待你们写下共同约定');
    setImmersiveText('uiImmMarriageDays', married ? '相伴第 ' + safeNumber(marriage.days, 1) + ' 天' : '选择纪念日与誓言');
    var date = document.getElementById('uiImmMarriageDate');
    var vow = document.getElementById('uiImmMarriageVow');
    var button = document.getElementById('uiImmMarriageSave');
    if (date && marriage.anniversary) date.value = marriage.anniversary;
    if (vow && document.activeElement !== vow) vow.value = marriage.vow || '';
    if (button) button.textContent = married ? '保存纪念' : '缔结婚约';
  }

  function renderImmersiveHome(home) {
    home = home || {};
    setImmersiveText('uiImmHomeLevel', 'Lv.' + safeNumber(home.level, 1));
    setImmersiveText('uiImmHomeWarmth', safeNumber(home.warmth, 0) + ' 温暖值');
    setImmersiveText('uiImmHomeLast', home.last_action || '家里正等你们回来。');
    var rooms = document.getElementById('uiImmHomeRooms');
    if (rooms) rooms.innerHTML = (home.rooms || ['客厅']).map(function (room) { return '<span>' + immersiveEscape(room) + '</span>'; }).join('');
  }

  function renderImmersiveAccount(auth) {
    auth = auth || {};
    immersiveDeskState.auth = auth;
    var authenticated = !!auth.authenticated;
    var name = authenticated ? (auth.username || (auth.scope === 'owner' ? '本地主人' : '已登录用户')) : '尚未登录';
    setImmersiveText('uiImmAccountName', name);
    setImmersiveText('uiImmAccountMeta', authenticated ? '数据已按当前身份隔离保存' : '登录后同步你的专属数据');
    var login = document.getElementById('uiImmAccountLogin');
    var logout = document.getElementById('uiImmAccountLogout');
    if (login) login.hidden = authenticated;
    if (logout) logout.hidden = !authenticated;
  }

  function renderImmersiveLife(data) {
    data = data || {};
    renderImmersiveAnime(data.anime || []);
    renderImmersiveCalendar(data.calendar || []);
    renderImmersiveMarriage(data.marriage || {});
    renderImmersiveHome(data.home || {});
  }

  function refreshImmersiveDesk() {
    Promise.all([
      getJson('/api/coach/cards'),
      getJson('/api/words'),
      getJson('/api/books'),
      getJson('/api/music/list'),
      getJson('/api/immersive/life'),
      getJson('/api/auth/me')
    ]).then(function (data) {
      renderImmersiveCurve(data[0] || {});
      immersiveDeskState.words = data[1] && data[1].words || [];
      immersiveDeskState.wordIndex = Math.min(immersiveDeskState.wordIndex, Math.max(0, immersiveDeskState.words.length - 1));
      renderImmersiveWord();
      renderImmersiveReading(data[2] || {});
      renderImmersiveMusic(data[3] || {});
      immersiveDeskState.life = data[4] || {};
      renderImmersiveLife(immersiveDeskState.life);
      renderImmersiveAccount(data[5] || {});
    });
  }

  function buildImmersiveDesk(home) {
    if (!home || document.getElementById('uiImmersiveDesk')) return;
    var desk = document.createElement('section');
    desk.id = 'uiImmersiveDesk';
    desk.className = 'ui-imm-desk';
    desk.setAttribute('aria-label', '沉浸书桌');
    desk.setAttribute('aria-hidden', 'true');
    desk.innerHTML =
      '<header class="ui-imm-desk-head"><div><span>FOCUS DESK</span><h2>沉浸书桌</h2></div><button type="button" id="uiImmDeskClose" aria-label="收起沉浸书桌">' + immersiveIcon('previous') + '</button></header>' +
      '<div class="ui-imm-desk-grid">' +
        '<article class="ui-imm-desk-card ui-imm-note"><header><span>' + immersiveIcon('note') + '便签</span><button type="button" data-desk-app="notes">全部</button></header><label class="ui-visually-hidden" for="uiImmNote">沉浸便签内容</label><textarea id="uiImmNote" maxlength="360" placeholder="随手记下此刻的想法…"></textarea><small id="uiImmNoteStatus">自动保存</small></article>' +
        '<article class="ui-imm-desk-card ui-imm-todo"><header><span>' + immersiveIcon('todo') + 'TODOLIST</span><small id="uiImmTodoCount">0 项待办</small></header><div class="ui-imm-todo-add"><label class="ui-visually-hidden" for="uiImmTodoInput">新增待办</label><input id="uiImmTodoInput" maxlength="80" placeholder="添加一件事"><button type="button" id="uiImmTodoAdd" aria-label="添加待办">＋</button></div><ul id="uiImmTodoList"></ul></article>' +
        '<article class="ui-imm-desk-card ui-imm-curve"><header><span>' + immersiveIcon('curve') + '遗忘曲线</span><button type="button" data-desk-app="coach">复习</button></header><svg viewBox="0 0 200 82" role="img" aria-label="未来十四天记忆保持预测"><path d="M8 16V68H194" class="ui-imm-curve-axis"/><polyline id="uiImmCurveLine" points="8,16 54,28 100,43 146,55 192,63"/><g><text x="7" y="79">现在</text><text x="50" y="79">1天</text><text x="96" y="79">3天</text><text x="141" y="79">7天</text><text x="181" y="79">14天</text></g></svg><small id="uiImmCurveDue">正在读取复习计划</small></article>' +
        '<article class="ui-imm-desk-card ui-imm-word"><header><span>' + immersiveIcon('word') + '单词卡</span><button type="button" data-desk-app="words">词库</button></header><div class="ui-imm-word-main"><strong id="uiImmWordMain">正在抽卡</strong><small id="uiImmWordPhonetic">—</small><p id="uiImmWordMeaning">—</p></div><div class="ui-imm-word-actions"><button type="button" id="uiImmWordReveal">查看释义</button><button type="button" id="uiImmWordNext" aria-label="下一个单词">' + immersiveIcon('next') + '</button></div></article>' +
        '<article class="ui-imm-desk-card ui-imm-reading"><header><span>' + immersiveIcon('book') + '阅读记录</span><button type="button" data-desk-app="reading">继续</button></header><strong id="uiImmReadingTitle">正在同步书架</strong><p id="uiImmReadingMeta">—</p><div class="ui-imm-reading-track"><i id="uiImmReadingBar"></i></div></article>' +
        '<article class="ui-imm-desk-card ui-imm-music"><header><span>' + immersiveIcon('music') + '听歌播放器</span><button type="button" data-desk-app="listen">歌单</button></header><div class="ui-imm-music-copy"><strong id="uiImmMusicTitle">正在同步歌单</strong><small id="uiImmMusicArtist">—</small></div><input id="uiImmMusicProgress" type="range" min="0" max="100" value="0" aria-label="播放进度"><div class="ui-imm-music-controls"><button type="button" id="uiImmMusicPrev" aria-label="上一首">' + immersiveIcon('previous') + '</button><button type="button" id="uiImmMusicPlay" aria-label="播放或暂停">' + immersiveIcon('play') + '</button><button type="button" id="uiImmMusicNext" aria-label="下一首">' + immersiveIcon('next') + '</button><span id="uiImmMusicTime">0:00 / 0:00</span></div></article>' +
        '<article class="ui-imm-desk-card ui-imm-account"><header><span>' + immersiveIcon('user') + '用户账号</span><small>ACCOUNT</small></header><strong id="uiImmAccountName">正在读取身份</strong><p id="uiImmAccountMeta">—</p><div class="ui-imm-account-actions"><a href="/account.html">账号管理</a><a href="/" id="uiImmAccountLogin" hidden>登录</a><a href="/register.html">注册</a><button type="button" id="uiImmAccountLogout" hidden>退出</button></div></article>' +
        '<article class="ui-imm-desk-card ui-imm-anime ui-imm-desk-wide"><header><span>' + immersiveIcon('anime') + '追番表</span><small id="uiImmAnimeCount">0 部</small></header><div class="ui-imm-life-add"><label class="ui-visually-hidden" for="uiImmAnimeTitle">番剧名称</label><input id="uiImmAnimeTitle" maxlength="80" placeholder="想一起追的番"><label class="ui-visually-hidden" for="uiImmAnimeTotal">总集数</label><input id="uiImmAnimeTotal" type="number" min="0" max="9999" inputmode="numeric" placeholder="集"><button type="button" id="uiImmAnimeAdd" aria-label="加入追番表">＋</button></div><ul id="uiImmAnimeList"></ul></article>' +
        '<article class="ui-imm-desk-card ui-imm-calendar ui-imm-desk-wide"><header><span>' + immersiveIcon('calendar') + '共同日历</span><small id="uiImmCalendarMonth">本月</small></header><div class="ui-imm-calendar-days" id="uiImmCalendarDays" aria-label="未来七天"></div><div class="ui-imm-life-add ui-imm-calendar-add"><label class="ui-visually-hidden" for="uiImmCalendarDate">日程日期</label><input id="uiImmCalendarDate" type="date"><label class="ui-visually-hidden" for="uiImmCalendarTitle">日程内容</label><input id="uiImmCalendarTitle" maxlength="100" placeholder="约会、追番或纪念日"><button type="button" id="uiImmCalendarAdd" aria-label="添加日程">＋</button></div><ul id="uiImmCalendarList"></ul></article>' +
        '<article class="ui-imm-desk-card ui-imm-marriage"><header><span>' + immersiveIcon('rings') + '结婚系统</span><small id="uiImmMarriageDays">—</small></header><strong id="uiImmMarriageStatus">读取关系状态</strong><label class="ui-visually-hidden" for="uiImmMarriageDate">结婚纪念日</label><input id="uiImmMarriageDate" type="date"><label class="ui-visually-hidden" for="uiImmMarriageVow">共同誓言</label><input id="uiImmMarriageVow" maxlength="300" placeholder="写下一句共同誓言"><button type="button" id="uiImmMarriageSave">缔结婚约</button></article>' +
        '<article class="ui-imm-desk-card ui-imm-home ui-imm-desk-wide"><header><span>' + immersiveIcon('home') + '我和许墨的家</span><div><small id="uiImmHomeLevel">Lv.1</small><b id="uiImmHomeWarmth">0 温暖值</b></div></header><div class="ui-imm-home-scene"><div class="ui-imm-home-house">' + immersiveIcon('home') + '</div><div><div id="uiImmHomeRooms"></div><p id="uiImmHomeLast">家里正等你们回来。</p></div></div><div class="ui-imm-home-actions"><button type="button" data-home-action="cook">一起做饭</button><button type="button" data-home-action="read">共读</button><button type="button" data-home-action="rest">休息</button><button type="button" data-home-action="decorate">布置家</button><button type="button" data-desk-app="world">回家看看</button></div></article>' +
      '</div>';
    home.appendChild(desk);

    document.getElementById('uiImmCalendarDate').value = immersiveToday();
    document.getElementById('uiImmMarriageDate').value = immersiveToday();

    var note = document.getElementById('uiImmNote');
    note.value = immersiveDeskRead('xumo_immersive_note_v1', '');
    var noteTimer = 0;
    note.addEventListener('input', function () {
      setImmersiveText('uiImmNoteStatus', '保存中…');
      clearTimeout(noteTimer);
      noteTimer = setTimeout(function () {
        immersiveDeskWrite('xumo_immersive_note_v1', note.value);
        setImmersiveText('uiImmNoteStatus', '已自动保存');
      }, 320);
    });
    document.getElementById('uiImmTodoAdd').addEventListener('click', addImmersiveTodo);
    document.getElementById('uiImmTodoInput').addEventListener('keydown', function (event) { if (event.key === 'Enter') { event.preventDefault(); addImmersiveTodo(); } });
    document.getElementById('uiImmTodoList').addEventListener('click', function (event) {
      var item = event.target.closest('li[data-id]');
      if (!item) return;
      var todos = immersiveDeskRead('xumo_immersive_todos_v1', []);
      var id = item.getAttribute('data-id');
      if (event.target.closest('.ui-imm-todo-delete')) todos = todos.filter(function (todo) { return String(todo.id) !== id; });
      else if (event.target.closest('.ui-imm-todo-check')) todos.forEach(function (todo) { if (String(todo.id) === id) todo.done = !todo.done; });
      immersiveDeskWrite('xumo_immersive_todos_v1', todos);
      renderImmersiveTodos();
    });
    document.getElementById('uiImmWordReveal').addEventListener('click', function () { immersiveDeskState.wordRevealed = !immersiveDeskState.wordRevealed; renderImmersiveWord(); });
    document.getElementById('uiImmWordNext').addEventListener('click', function () { if (!immersiveDeskState.words.length) return; immersiveDeskState.wordIndex = (immersiveDeskState.wordIndex + 1) % immersiveDeskState.words.length; immersiveDeskState.wordRevealed = false; renderImmersiveWord(); });
    document.getElementById('uiImmMusicPlay').addEventListener('click', function () { var audio = immersiveDeskState.audio; if (!audio) { selectImmersiveSong(0, true); return; } if (audio.paused) audio.play().catch(function () {}); else audio.pause(); });
    document.getElementById('uiImmMusicPrev').addEventListener('click', function () { selectImmersiveSong(immersiveDeskState.songIndex - 1, true); });
    document.getElementById('uiImmMusicNext').addEventListener('click', function () { selectImmersiveSong(immersiveDeskState.songIndex + 1, true); });
    document.getElementById('uiImmMusicProgress').addEventListener('input', function () { setImmersiveRangeProgress(this, this.value); var audio = immersiveDeskState.audio; if (audio && audio.duration) audio.currentTime = safeNumber(this.value, 0) / 100 * audio.duration; });
    document.getElementById('uiImmAnimeAdd').addEventListener('click', function () {
      var title = document.getElementById('uiImmAnimeTitle');
      var total = document.getElementById('uiImmAnimeTotal');
      if (!title.value.trim()) { immersiveNotice('请填写番剧名称'); title.focus(); return; }
      postImmersiveLife('/api/immersive/anime', { action: 'add', title: title.value.trim(), total: safeNumber(total.value, 0) }).then(function (data) {
        if (!data) return;
        title.value = ''; total.value = ''; immersiveNotice('已加入追番表');
      });
    });
    document.getElementById('uiImmAnimeTitle').addEventListener('keydown', function (event) { if (event.key === 'Enter') { event.preventDefault(); document.getElementById('uiImmAnimeAdd').click(); } });
    document.getElementById('uiImmAnimeList').addEventListener('click', function (event) {
      var item = event.target.closest('li[data-id]');
      if (!item) return;
      if (event.target.closest('[data-anime-delete]')) postImmersiveLife('/api/immersive/anime', { action: 'delete', id: item.getAttribute('data-id') });
      else {
        var deltaButton = event.target.closest('[data-anime-delta]');
        if (deltaButton) postImmersiveLife('/api/immersive/anime', { action: 'progress', id: item.getAttribute('data-id'), delta: safeNumber(deltaButton.getAttribute('data-anime-delta'), 1) });
      }
    });
    document.getElementById('uiImmCalendarAdd').addEventListener('click', function () {
      var title = document.getElementById('uiImmCalendarTitle');
      var date = document.getElementById('uiImmCalendarDate');
      if (!title.value.trim()) { immersiveNotice('请填写日程内容'); title.focus(); return; }
      postImmersiveLife('/api/immersive/calendar', { action: 'add', title: title.value.trim(), date: date.value }).then(function (data) {
        if (!data) return;
        title.value = ''; immersiveNotice('日程已加入共同日历');
      });
    });
    document.getElementById('uiImmCalendarTitle').addEventListener('keydown', function (event) { if (event.key === 'Enter') { event.preventDefault(); document.getElementById('uiImmCalendarAdd').click(); } });
    document.getElementById('uiImmCalendarDays').addEventListener('click', function (event) {
      var button = event.target.closest('[data-calendar-date]');
      if (!button) return;
      document.getElementById('uiImmCalendarDate').value = button.getAttribute('data-calendar-date');
      this.querySelectorAll('button').forEach(function (item) { item.classList.toggle('is-selected', item === button); });
    });
    document.getElementById('uiImmCalendarList').addEventListener('click', function (event) {
      var button = event.target.closest('[data-calendar-delete]');
      var item = event.target.closest('li[data-id]');
      if (button && item) postImmersiveLife('/api/immersive/calendar', { action: 'delete', id: item.getAttribute('data-id') });
    });
    document.getElementById('uiImmMarriageSave').addEventListener('click', function () {
      var date = document.getElementById('uiImmMarriageDate').value;
      var vow = document.getElementById('uiImmMarriageVow').value.trim();
      if (!date) { immersiveNotice('请先选择纪念日'); return; }
      postImmersiveLife('/api/immersive/marriage', { anniversary: date, vow: vow }).then(function (data) { if (data) immersiveNotice('你们的共同纪念已经保存'); });
    });
    document.querySelector('.ui-imm-home-actions').addEventListener('click', function (event) {
      var button = event.target.closest('[data-home-action]');
      if (button) postImmersiveLife('/api/immersive/home', { action: button.getAttribute('data-home-action') }).then(function (data) { if (data) immersiveNotice('家的温暖值增加了'); });
    });
    document.getElementById('uiImmAccountLogout').addEventListener('click', function () {
      fetch('/api/auth/logout', { method: 'POST', credentials: 'include' }).then(function () { window.location.href = '/'; });
    });
    desk.addEventListener('click', function (event) { var button = event.target.closest('[data-desk-app]'); if (button && window.openApp) window.openApp(button.getAttribute('data-desk-app')); });
    document.getElementById('uiImmDeskClose').addEventListener('click', function () { setImmersiveDeskOpen(false); });
    renderImmersiveTodos();
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
      renderImmersiveMetrics({ progress: progress, week: focus.week || [], promises: promises, memories: memories, study: study });
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
      '<header class="ui-imm-head"><div><span class="ui-imm-kicker"><i></i> LUCID CONNECTION</span><h2>共生仪表</h2></div><div class="ui-imm-head-actions"><div class="ui-imm-clock"><b id="uiImmTime">--:--</b><span id="uiImmDate">—</span></div><button type="button" id="uiImmDeskToggle" aria-expanded="false" aria-controls="uiImmersiveDesk">' + immersiveIcon('note') + '<span>书桌</span></button></div></header>' +
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
      '<section class="ui-imm-data-grid" id="uiImmMetricGrid" aria-label="关系数据概览">' +
        '<article class="ui-imm-metric"><div><span>关系动能</span><strong id="uiImmMomentumValue">0%</strong></div><div class="ui-imm-bullet"><i id="uiImmMomentumBar"></i><b aria-hidden="true"></b></div><small>下一阶段目标 74%</small></article>' +
        '<article class="ui-imm-metric"><div><span>本周专注</span><strong id="uiImmFocusValue">0m</strong></div><div class="ui-imm-spark" id="uiImmFocusMini" aria-hidden="true"></div><small>近七日共同节律</small></article>' +
        '<article class="ui-imm-metric ui-imm-promise"><div><span>承诺履约</span><strong id="uiImmPromiseRate">0%</strong></div><div class="ui-imm-mini-ring" id="uiImmPromiseRing" aria-hidden="true"></div><small>已完成 / 全部承诺</small></article>' +
        '<article class="ui-imm-metric"><div><span>新增记忆</span><strong id="uiImmRecentMemory">0</strong></div><div class="ui-imm-heat" id="uiImmMemoryHeat" aria-hidden="true"></div><small>最近七天沉淀</small></article>' +
        '<article class="ui-imm-metric"><div><span>词汇掌握</span><strong id="uiImmMasteryValue">0%</strong></div><div class="ui-imm-mastery-bar"><i id="uiImmMasteryBar"></i></div><small>复习进度</small></article>' +
      '</section>' +
      '<section class="ui-imm-insight"><span>' + immersiveIcon('pulse') + '</span><div><small>此刻 · <b id="uiImmWeather">环境数据待同步</b></small><strong id="uiImmStatus">正在感知他的状态</strong><p id="uiImmInsight">新的共同记忆会在这里浮现</p></div></section>' +
      '<nav class="ui-imm-quick" aria-label="沉浸页快捷入口"><button type="button" data-app="affinity">' + immersiveIcon('heart') + '<span>关系详情</span></button><button type="button" data-app="memory">' + immersiveIcon('memory') + '<span>记忆手账</span></button><button type="button" data-ui-mode="chat">' + immersiveIcon('chat') + '<span>进入对话</span></button></nav>';
    home.appendChild(panel);
    buildImmersiveDesk(home);

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
    document.getElementById('uiImmDeskToggle').addEventListener('click', function () {
      setImmersiveDeskOpen(!document.getElementById('uiImmersiveDesk').classList.contains('is-open'));
    });
    document.addEventListener('keydown', function (event) { if (event.key === 'Escape' && document.getElementById('uiImmersiveDesk').classList.contains('is-open')) setImmersiveDeskOpen(false); });

    updateImmersiveClock();
    renderImmersiveWeek([]);
    renderImmersiveMetrics({ progress: 0, week: [], promises: [], memories: [], study: {} });
    var deskPreference = immersiveDeskRead('xumo_immersive_desk_open_v1', null);
    setImmersiveDeskOpen(deskPreference == null ? false : !!deskPreference, false);
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
