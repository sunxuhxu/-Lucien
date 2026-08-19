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

    var observer = new MutationObserver(function (records) {
      records.forEach(function (record) {
        if (record.type === 'attributes' && record.target.matches && record.target.matches('button')) {
          if (record.target.disabled) record.target.setAttribute('aria-busy', 'true');
          else record.target.removeAttribute('aria-busy');
        }
        record.addedNodes.forEach(function (node) {
          if (node.nodeType === 1) improveSemantics(node);
        });
      });
    });
    observer.observe(document.body, { childList: true, subtree: true, attributes: true, attributeFilter: ['disabled'] });
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init, { once: true });
  else init();
})();
