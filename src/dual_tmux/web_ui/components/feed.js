import sys

feed_js = r"""/* === progress-feed.js === */
(function(global) {
  'use strict';

  class ProgressFeedComponent {
    /**
     * @param {Object} options
     * @param {HTMLElement} options.container
     * @param {number} [options.maxItems=100]
     * @param {Function} [options.onFilterChange]
     */
    constructor(options = {}) {
      this.container = options.container || null;
      this.maxItems = options.maxItems || 100;
      this.messages = [];
      this.activeFilter = 'all'; // all | evidence | quiet | alert
      this.isFocused = false; // 用户聚焦/查看状态，为 true 时暂停自动吸底跟随
      this.unreadWhileFocused = 0; // 聚焦查看期间积攒的新消息数
      this.el = null;
    }

    render() {
      if (!this.container) return;

      const root = document.createElement('div');
      root.className = 'dt-feed-container dt-scope';
      root.id = 'dt-progress-feed';
      root.setAttribute('tabindex', '0');

      root.innerHTML = [
        '<div class="dt-feed-header">',
        '  <div class="dt-feed-title-wrap">',
        '    <div class="dt-feed-title">',
        '      <span>📋 轮询进展消息流 (Progress Feed)</span>',
        '      <span class="dt-feed-count-badge" id="dt-feed-count">0 条</span>',
        '      <span class="dt-feed-focus-badge" id="dt-feed-focus-badge" style="display:none;">🔍 聚焦查看中 (暂停跟随)</span>',
        '    </div>',
        '    <div class="dt-feed-filters">',
        '      <button type="button" class="dt-feed-filter-btn active" data-filter="all">全部</button>',
        '      <button type="button" class="dt-feed-filter-btn" data-filter="evidence">✨ 仅有效增长</button>',
        '      <button type="button" class="dt-feed-filter-btn" data-filter="quiet">⏳ 静默/无变化</button>',
        '      <button type="button" class="dt-feed-filter-btn" data-filter="alert">⚠️ 停滞告警</button>',
        '    </div>',
        '  </div>',
        '  <div class="dt-feed-actions">',
        '    <button type="button" class="dt-feed-btn" id="dt-feed-btn-status" title="当前滚动跟随状态">跟随: 实时</button>',
        '    <button type="button" class="dt-feed-btn" id="dt-feed-btn-clear" title="清空消息流">清空</button>',
        '  </div>',
        '</div>',
        '<div class="dt-feed-viewport">',
        '  <div class="dt-feed-list" id="dt-feed-list">',
        '    <div class="dt-feed-empty" id="dt-feed-empty">',
        '      <span>暂无轮询消息记录</span>',
        '      <span style="font-size:11px; color:#475569;">Trigger 派活或执行探针后，纵向消息将在此处实时追加</span>',
        '    </div>',
        '  </div>',
        '  <div class="dt-feed-unread-bar" id="dt-feed-unread-bar" style="display:none;">',
        '    <span>👇 查看中收到 <strong id="dt-feed-unread-count">0</strong> 条新进展 · 点击回到底部</span>',
        '  </div>',
        '</div>'
      ].join('');

      this.container.appendChild(root);
      this.el = root;

      // 绑定过滤点击
      const filterBtns = root.querySelectorAll('.dt-feed-filter-btn');
      filterBtns.forEach(btn => {
        btn.addEventListener('click', (e) => {
          e.stopPropagation();
          filterBtns.forEach(b => b.classList.remove('active'));
          btn.classList.add('active');
          this.activeFilter = btn.dataset.filter;
          this.applyFilter();
        });
      });

      // 绑定清空
      const clearBtn = root.querySelector('#dt-feed-btn-clear');
      if (clearBtn) {
        clearBtn.addEventListener('click', (e) => {
          e.stopPropagation();
          this.clear();
        });
      }

      // 未读提示横幅点击：立即回到底部并恢复跟随
      const unreadBar = root.querySelector('#dt-feed-unread-bar');
      if (unreadBar) {
        unreadBar.addEventListener('click', (e) => {
          e.stopPropagation();
          this.scrollToBottom();
          this.unreadWhileFocused = 0;
          this.updateUnreadBar();
        });
      }

      // 状态按钮点击手动回到底部
      const statusBtn = root.querySelector('#dt-feed-btn-status');
      if (statusBtn) {
        statusBtn.addEventListener('click', (e) => {
          e.stopPropagation();
          this.scrollToBottom();
        });
      }

      // 聚焦（查看）与失焦（恢复跟随）生命周期管理
      this.bindFocusBehavior(root);
    }

    bindFocusBehavior(root) {
      // 1. 点击组件区域内部：进入查看模式（保持当前滚动位置，暂停自动吸底）
      root.addEventListener('click', () => {
        if (!this.isFocused) {
          this.setFocused(true);
        }
      });

      // 原生 focusin 事件（包含内部元素获得键盘焦点）
      root.addEventListener('focusin', () => {
        if (!this.isFocused) {
          this.setFocused(true);
        }
      });

      // 2. 点击组件外部：失去焦点，自动恢复跟随最新消息并平滑滚到底部
      document.addEventListener('click', (e) => {
        if (this.isFocused && !root.contains(e.target)) {
          this.setFocused(false);
        }
      });

      // 原生 focusout 事件（焦点转移到外部元素）
      root.addEventListener('focusout', (e) => {
        if (this.isFocused && (!e.relatedTarget || !root.contains(e.relatedTarget))) {
          this.setFocused(false);
        }
      });

      // 3. 用户在列表内滚动到达底部时若有未读计数则清零
      const listEl = root.querySelector('#dt-feed-list');
      if (listEl) {
        listEl.addEventListener('scroll', () => {
          const atBottom = listEl.scrollHeight - listEl.scrollTop - listEl.clientHeight <= 20;
          if (atBottom && this.unreadWhileFocused > 0) {
            this.unreadWhileFocused = 0;
            this.updateUnreadBar();
          }
        });
      }
    }

    setFocused(focused) {
      this.isFocused = focused;
      if (!this.el) return;

      const badge = this.el.querySelector('#dt-feed-focus-badge');
      const statusBtn = this.el.querySelector('#dt-feed-btn-status');

      if (focused) {
        this.el.classList.add('dt-feed-focused');
        if (badge) badge.style.display = 'inline-flex';
        if (statusBtn) {
          statusBtn.textContent = '跟随: 查看暂停';
          statusBtn.style.color = '#f59e0b';
        }
      } else {
        this.el.classList.remove('dt-feed-focused');
        if (badge) badge.style.display = 'none';
        if (statusBtn) {
          statusBtn.textContent = '跟随: 实时';
          statusBtn.style.color = '#38bdf8';
        }
        // 恢复跟随：清零未读数并自动吸底
        this.unreadWhileFocused = 0;
        this.updateUnreadBar();
        this.scrollToBottom();
      }
    }

    addMessage(item) {
      if (!this.el) return;

      const record = {
        id: 'msg-' + Date.now() + '-' + Math.random().toString(36).slice(2, 6),
        ts: new Date().toLocaleTimeString(),
        kind: item.kind || 'evidence',
        round: item.round || 1,
        target: item.target || 'bullet',
        summary: item.summary || '无有效描述',
        elapsed: item.elapsed || 0,
        roundElapsed: item.roundElapsed || 0,
        tokens: item.tokens || '',
        tokensDelta: item.tokensDelta || '',
        quietCount: item.quietCount || 0,
        nextCheck: item.nextCheck || '',
      };

      this.messages.push(record);
      if (this.messages.length > this.maxItems) {
        this.messages.shift();
      }

      this.renderCard(record);
      this.updateBadge();

      // 当组件处于聚焦查看中时：不必跟随最新消息，增加未读计数提示
      if (this.isFocused) {
        this.unreadWhileFocused++;
        this.updateUnreadBar();
      } else {
        // 未聚焦（默认模式）：实时吸底跟随
        this.scrollToBottom();
      }
    }

    renderCard(record) {
      const listEl = this.el.querySelector('#dt-feed-list');
      const emptyEl = this.el.querySelector('#dt-feed-empty');
      if (emptyEl && emptyEl.style.display !== 'none') {
        emptyEl.style.display = 'none';
      }

      const card = document.createElement('div');
      card.className = 'dt-feed-card kind-' + record.kind;
      card.dataset.id = record.id;
      card.dataset.kind = record.kind;

      if (!this.matchesFilter(record.kind)) {
        card.style.display = 'none';
      }

      const kindLabels = {
        dispatch: '🚀 任务派发',
        evidence: '✨ 进展增长',
        quiet: '⏳ 状态平滞',
        alert: '⚠️ 停滞预警',
        done: '✅ 本轮达成',
        interrupt: '🛑 收到打断',
      };

      const metaParts = [];
      if (record.elapsed > 0) metaParts.push('<span>⏱️ 累计: <strong>' + this.formatSeconds(record.elapsed) + '</strong></span>');
      if (record.tokens) metaParts.push('<span>📊 Tokens: <strong>' + this.escapeHtml(record.tokens) + '</strong> ' + (record.tokensDelta ? '(' + this.escapeHtml(record.tokensDelta) + ')' : '') + '</span>');
      if (record.quietCount > 0) metaParts.push('<span>⚠️ 连续无变化: <strong>' + record.quietCount + '/8</strong> 轮</span>');
      if (record.nextCheck) metaParts.push('<span>⏱️ 下次: <strong>' + this.escapeHtml(record.nextCheck) + '</strong></span>');

      card.innerHTML = [
        '<div class="dt-feed-card-header">',
        '  <div class="dt-feed-card-left">',
        '    <span class="dt-feed-round-pill">#' + record.round + ' 轮</span>',
        '    <span class="dt-feed-target-tag tag-' + record.target + '">' + record.target.toUpperCase() + '</span>',
        '    <span class="dt-feed-kind-label">' + (kindLabels[record.kind] || record.kind) + '</span>',
        '  </div>',
        '  <div class="dt-feed-card-right">',
        '    <span>' + record.ts + '</span>',
        '  </div>',
        '</div>',
        '<div class="dt-feed-card-body">' + this.escapeHtml(record.summary) + '</div>',
        '<div class="dt-feed-card-meta">' + metaParts.join('') + '</div>'
      ].join('');

      listEl.appendChild(card);
    }

    applyFilter() {
      if (!this.el) return;
      const cards = this.el.querySelectorAll('.dt-feed-card');
      cards.forEach(card => {
        const kind = card.dataset.kind;
        card.style.display = this.matchesFilter(kind) ? 'flex' : 'none';
      });
      if (!this.isFocused) {
        this.scrollToBottom();
      }
    }

    matchesFilter(kind) {
      if (this.activeFilter === 'all') return true;
      if (this.activeFilter === 'evidence') return kind === 'evidence' || kind === 'done';
      if (this.activeFilter === 'quiet') return kind === 'quiet';
      if (this.activeFilter === 'alert') return kind === 'alert' || kind === 'interrupt';
      return true;
    }

    updateBadge() {
      if (!this.el) return;
      const countEl = this.el.querySelector('#dt-feed-count');
      if (countEl) {
        countEl.textContent = this.messages.length + ' 条';
      }
    }

    updateUnreadBar() {
      if (!this.el) return;
      const bar = this.el.querySelector('#dt-feed-unread-bar');
      const countEl = this.el.querySelector('#dt-feed-unread-count');
      if (!bar || !countEl) return;

      if (this.unreadWhileFocused > 0) {
        countEl.textContent = this.unreadWhileFocused;
        bar.style.display = 'flex';
      } else {
        bar.style.display = 'none';
      }
    }

    scrollToBottom() {
      if (!this.el) return;
      const listEl = this.el.querySelector('#dt-feed-list');
      if (listEl) {
        listEl.scrollTop = listEl.scrollHeight;
      }
    }

    clear() {
      this.messages = [];
      this.unreadWhileFocused = 0;
      if (!this.el) return;
      const listEl = this.el.querySelector('#dt-feed-list');
      if (listEl) {
        listEl.innerHTML = [
          '<div class="dt-feed-empty" id="dt-feed-empty">',
          '  <span>暂无轮询消息记录</span>',
          '  <span style="font-size:11px; color:#475569;">Trigger 派活或执行探针后，纵向消息将在此处实时追加</span>',
          '</div>'
        ].join('');
      }
      this.updateBadge();
      this.updateUnreadBar();
    }

    formatSeconds(sec) {
      if (!sec || sec < 0) return '0s';
      const m = Math.floor(sec / 60);
      const s = Math.floor(sec % 60);
      return m > 0 ? m + 'm ' + s + 's' : s + 's';
    }

    escapeHtml(str) {
      return String(str || '').replace(/[&<>"']/g, function(c) {
        return {'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c];
      });
    }
  }

  global.ProgressFeedComponent = ProgressFeedComponent;
})(typeof window !== 'undefined' ? window : this);
