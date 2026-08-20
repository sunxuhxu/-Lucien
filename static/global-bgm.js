(function () {
  'use strict';
  if (window.__xumoGlobalBgm) return;
  window.__xumoGlobalBgm = true;

  var SAVE_INTERVAL = 15000;
  var preferredTitle = '一幕情深';
  var root = document.createElement('aside');
  root.id = 'xumo-global-bgm';
  root.className = 'bgm-loading';
  root.setAttribute('aria-label', '全局背景音乐');
  root.innerHTML =
    '<button class="bgm-play" type="button" aria-label="播放背景音乐" title="播放 / 暂停"></button>' +
    '<span class="bgm-copy"><strong class="bgm-title">正在准备 BGM…</strong><small class="bgm-artist">V.K克</small></span>' +
    '<span class="bgm-volume"><button class="bgm-mute" type="button" aria-label="静音" title="静音"></button>' +
    '<input type="range" min="0" max="1" step="0.01" value="0.35" aria-label="BGM 音量"></span>';
  document.body.appendChild(root);

  var audio = new Audio();
  var playButton = root.querySelector('.bgm-play');
  var muteButton = root.querySelector('.bgm-mute');
  var volumeInput = root.querySelector('input');
  var titleNode = root.querySelector('.bgm-title');
  var artistNode = root.querySelector('.bgm-artist');
  var state = { enabled: true, current_id: '', position: 0, volume: .35, muted: false, mode: 'single', queue: [] };
  var current = null;
  var library = [];
  var restorePosition = 0;
  var initialized = false;

  audio.preload = 'metadata';
  audio.loop = true;

  function clamp(value, min, max) { return Math.min(max, Math.max(min, value)); }

  function icon(name) {
    if (name === 'pause') return '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M8 5v14M16 5v14"/></svg>';
    if (name === 'mute') return '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M11 5 6 9H3v6h3l5 4V5Z"/><path d="m17 9 4 6m0-6-4 6"/></svg>';
    if (name === 'volume-low') return '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M11 5 6 9H3v6h3l5 4V5Z"/><path d="M15 9.5a4 4 0 0 1 0 5"/></svg>';
    if (name === 'volume') return '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M11 5 6 9H3v6h3l5 4V5Z"/><path d="M15 9.5a4 4 0 0 1 0 5M18 7a7 7 0 0 1 0 10"/></svg>';
    return '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="m9 6 9 6-9 6V6Z"/></svg>';
  }

  playButton.innerHTML = icon('play');
  muteButton.innerHTML = icon('volume-low');

  function request(url, options) {
    return fetch(url, Object.assign({ credentials: 'same-origin' }, options || {})).then(function (response) {
      if (!response.ok) throw new Error('BGM request failed: ' + response.status);
      return response.json();
    });
  }

  function snapshot() {
    return {
      enabled: state.enabled,
      current_id: state.current_id,
      position: Number.isFinite(audio.currentTime) ? audio.currentTime : state.position,
      volume: audio.volume,
      muted: audio.muted,
      mode: 'single',
      queue: state.queue || []
    };
  }

  function save(keepalive) {
    if (!initialized) return;
    state = Object.assign(state, snapshot());
    fetch('/api/bgm/state', {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(state),
      keepalive: !!keepalive
    }).catch(function () {});
  }

  function syncUi() {
    var playing = !audio.paused && !audio.ended;
    root.classList.toggle('bgm-playing', playing);
    playButton.innerHTML = icon(playing ? 'pause' : 'play');
    playButton.setAttribute('aria-label', playing ? '暂停背景音乐' : '播放背景音乐');
    muteButton.innerHTML = icon(audio.muted || audio.volume === 0 ? 'mute' : (audio.volume < .5 ? 'volume-low' : 'volume'));
    muteButton.setAttribute('aria-label', audio.muted ? '恢复声音' : '静音');
    volumeInput.value = String(audio.volume);
  }

  function startPlayback() {
    state.enabled = true;
    var attempt = audio.play();
    if (attempt && typeof attempt.catch === 'function') {
      attempt.catch(function () {
        titleNode.textContent = (current && current.title) || preferredTitle;
        artistNode.textContent = '点击播放 · ' + ((current && current.artist) || 'V.K克');
        syncUi();
      });
    }
  }

  function pickSong(data) {
    var match = library.find(function (song) { return song.title === preferredTitle || song.title.indexOf(preferredTitle) >= 0; });
    if (!match && data.current) return data.current;
    if (!match && library.length) match = library[0];
    if (!match) return null;
    return {
      id: match.id,
      title: match.title,
      artist: match.artist,
      duration: match.duration,
      src: '/api/music/file/' + encodeURIComponent(match.id)
    };
  }

  function mountSong(song) {
    current = song;
    state.current_id = song.id;
    titleNode.textContent = song.title || preferredTitle;
    artistNode.textContent = song.artist || 'V.K克';
    restorePosition = Math.max(0, Number(state.position) || 0);
    audio.src = song.src;
    audio.load();
  }

  playButton.addEventListener('click', function () {
    if (audio.paused) startPlayback();
    else { audio.pause(); state.enabled = false; save(false); }
  });

  muteButton.addEventListener('click', function () {
    audio.muted = !audio.muted;
    state.muted = audio.muted;
    syncUi();
    save(false);
  });

  volumeInput.addEventListener('input', function () {
    audio.volume = clamp(Number(volumeInput.value) || 0, 0, 1);
    if (audio.volume > 0 && audio.muted) audio.muted = false;
    state.volume = audio.volume;
    state.muted = audio.muted;
    syncUi();
  });
  volumeInput.addEventListener('change', function () { save(false); });

  audio.addEventListener('loadedmetadata', function () {
    if (restorePosition > 0 && Number.isFinite(audio.duration)) {
      audio.currentTime = Math.min(restorePosition, Math.max(0, audio.duration - .5));
      restorePosition = 0;
    }
    if (state.enabled) startPlayback();
  });
  audio.addEventListener('play', function () { state.enabled = true; syncUi(); save(false); });
  audio.addEventListener('pause', syncUi);
  audio.addEventListener('volumechange', syncUi);
  audio.addEventListener('error', function () {
    titleNode.textContent = 'BGM 加载失败';
    artistNode.textContent = '请刷新页面重试';
    root.classList.remove('bgm-loading');
  });

  request('/api/bgm/state').then(function (data) {
    library = Array.isArray(data.library) ? data.library : [];
    state = Object.assign(state, data.state || {});
    state.mode = 'single';
    var savedVolume = Number(state.volume);
    audio.volume = clamp(Number.isFinite(savedVolume) ? savedVolume : .35, 0, 1);
    audio.muted = !!state.muted;
    var song = pickSong(data);
    if (!song) throw new Error('No BGM track available');
    initialized = true;
    mountSong(song);
    root.classList.remove('bgm-loading');
    syncUi();
    save(false);
  }).catch(function () {
    root.classList.remove('bgm-loading');
    titleNode.textContent = 'BGM 暂时不可用';
    artistNode.textContent = '请刷新后重试';
  });

  var unlock = function () {
    if (state.enabled && audio.paused && audio.src) startPlayback();
    document.removeEventListener('pointerdown', unlock, true);
    document.removeEventListener('keydown', unlock, true);
  };
  document.addEventListener('pointerdown', unlock, true);
  document.addEventListener('keydown', unlock, true);
  document.addEventListener('visibilitychange', function () { if (document.hidden) save(true); });
  window.addEventListener('pagehide', function () { save(true); });
  window.setInterval(function () { if (!audio.paused) save(false); }, SAVE_INTERVAL);
})();
