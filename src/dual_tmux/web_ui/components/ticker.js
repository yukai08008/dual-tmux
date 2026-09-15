/* === progress-ticker.js === */
(function(global) {
  'use strict';

  class ProgressTickerComponent {
    /**
     * @param {Object} options
     * @param {HTMLElement} options.container
     * @param {Function} [options.onInterrupt]
     * @param {Function} [options.onProbeNow]
     */
    constructor(options) {
      this.container = options.container;
      this.onInterrupt = options.onInterrupt || null;
      this.onProbeNow = options.onProbeNow || null;

      this.state = {
        status: 'idle', // idle | dispatching | working | polling | quiet | done | interrupted
        statusText: '就绪 / 等待任务',
        round: 0,
        elapsed: 0,
        quietRounds: 0,
        maxQuietRounds: 8,
        nextCheckSeconds: 0,
        target: 'bullet', // trigger | bullet
        summary: '当前无活跃轮询任务，等待派活或恢复',
        tokens: '',
        tokensDelta: '',
      };

      this.timer = null;
      this.countdownTimer = null;
      this.el = null;
    }

    render() {
      if (!this.container) return;

      const root = document.createElement('div');
      root.className = 'dt-ticker-container status-idle';
      root.id = 'dt-progress-ticker';

      root.innerHTML = `
        <!-- 状态胶囊 -->
        <div class="dt-ticker-badge" id="ticker-badge">
          <span class="dt-ticker-dot"></span>
          <span id="ticker-status-text">就绪 / 等待任务</span>
        </div>

        <!-- 跑马灯滚动区 -->
        <div class="dt-ticker-track" id="ticker-track" title="悬停暂停滚动">
          <div class="dt-ticker-content" id="ticker-content">
            <span class="dt-ticker-segment">
              <span class="dt-ticker-target tag-bullet" id="ticker-target-tag">BULLET</span>
              <span id="ticker-summary-text">当前无活跃轮询任务，等待派活或恢复</span>
              <span class="dt-ticker-metric" id="ticker-metrics"></span>
            </span>
          </div>
        </div>

        <!-- 静默轮次标尺 (Quiet Round Cap: 8格) -->
        <div class="dt-ticker-quiet-meter" id="ticker-quiet-meter" title="连续静默轮次（达到8轮触发停滞熔断）">
          <span class="dt-ticker-quiet-label">静默</span>
          <div class="dt-ticker-quiet-pip" data-index="1"></div>
          <div class="dt-ticker-quiet-pip" data-index="2"></div>
          <div class="dt-ticker-quiet-pip" data-index="3"></div>
          <div class="dt-ticker-quiet-pip" data-index="4"></div>
          <div class="dt-ticker-quiet-pip" data-index="5"></div>
          <div class="dt-ticker-quiet-pip" data-index="6"></div>
          <div class="dt-ticker-quiet-pip" data-index="7"></div>
          <div class="dt-ticker-quiet-pip" data-index="8"></div>
        </div>

        <!-- 下次检查倒计时 -->
        <div class="dt-ticker-countdown" id="ticker-countdown">
          <span>下次探针:</span>
          <strong id="ticker-countdown-sec">--s</strong>
        </div>

        <!-- 动作快捷组 -->
        <div class="dt-ticker-actions">
          <button type="button" class="dt-ticker-btn" id="ticker-btn-probe" title="立即执行一次采样探针">⚡ 探针</button>
          <button type="button" class="dt-ticker-btn btn-interrupt" id="ticker-btn-interrupt" title="打断当前轮询 (Ctrl+C)">🛑 打断</button>
        </div>
      `;

      this.container.appendChild(root);
      this.el = root;

      // 绑定事件
      const btnProbe = root.querySelector('#ticker-btn-probe');
      if (btnProbe) {
        btnProbe.addEventListener('click', () => {
          if (typeof this.onProbeNow === 'function') this.onProbeNow();
        });
      }

      const btnInterrupt = root.querySelector('#ticker-btn-interrupt');
      if (btnInterrupt) {
        btnInterrupt.addEventListener('click', () => {
          if (typeof this.onInterrupt === 'function') this.onInterrupt();
        });
      }

      this.updateView();
    }

    /**
     * 更新状态与进度
     */
    update(patch) {
      Object.assign(this.state, patch);
      this.updateView();
    }

    /**
     * 设置倒计时
     */
    setCountdown(seconds) {
      if (this.countdownTimer) clearInterval(this.countdownTimer);
      let rem = Math.max(0, Math.floor(seconds));
      this.state.nextCheckSeconds = rem;
      this.updateCountdownDisplay();

      if (rem > 0) {
        this.countdownTimer = setInterval(() => {
          rem--;
          this.state.nextCheckSeconds = rem;
          this.updateCountdownDisplay();
          if (rem <= 0) {
            clearInterval(this.countdownTimer);
            this.countdownTimer = null;
          }
        }, 1000);
      }
    }

    updateCountdownDisplay() {
      if (!this.el) return;
      const secEl = this.el.querySelector('#ticker-countdown-sec');
      if (secEl) {
        secEl.textContent = this.state.nextCheckSeconds > 0 ? `${this.state.nextCheckSeconds}s` : '--';
      }
    }

    updateView() {
      if (!this.el) return;
      const s = this.state;

      // 1. 容器样式与状态 Badge
      this.el.className = `dt-ticker-container status-${s.status}`;
      const badgeText = this.el.querySelector('#ticker-status-text');
      if (badgeText) {
        badgeText.textContent = s.statusText || this.defaultStatusLabel(s.status, s.round, s.elapsed);
      }

      // 2. 跑马灯内容
      const targetTag = this.el.querySelector('#ticker-target-tag');
      if (targetTag) {
        targetTag.className = `dt-ticker-target tag-${s.target === 'trigger' ? 'trigger' : 'bullet'}`;
        targetTag.textContent = (s.target || 'BULLET').toUpperCase();
      }

      const summaryText = this.el.querySelector('#ticker-summary-text');
      if (summaryText) {
        summaryText.textContent = s.summary || '无有效进展摘要';
      }

      const metrics = this.el.querySelector('#ticker-metrics');
      if (metrics) {
        const parts = [];
        if (s.tokens) parts.push(`tokens ${s.tokens}`);
        if (s.tokensDelta) parts.push(`(${s.tokensDelta})`);
        if (s.elapsed > 0) parts.push(`已等待 ${this.formatSeconds(s.elapsed)}`);
        metrics.textContent = parts.length ? `· ${parts.join(' ')}` : '';
      }

      // 重启跑马灯动画以适应新文本宽度
      const trackContent = this.el.querySelector('#ticker-content');
      if (trackContent) {
        trackContent.style.animation = 'none';
        trackContent.offsetHeight; // trigger reflow
        trackContent.style.animation = '';
      }

      // 3. 静默轮次指示标尺
      const pips = this.el.querySelectorAll('.dt-ticker-quiet-pip');
      pips.forEach((pip, idx) => {
        const pipIndex = idx + 1;
        pip.className = 'dt-ticker-quiet-pip';
        if (pipIndex <= s.quietRounds) {
          if (pipIndex <= 3) pip.classList.add('active-green');
          else if (pipIndex <= 6) pip.classList.add('active-yellow');
          else pip.classList.add('active-red');
        }
      });

      this.updateCountdownDisplay();
    }

    defaultStatusLabel(status, round, elapsed) {
      switch (status) {
        case 'idle':
          return '就绪 / 等待任务';
        case 'dispatching':
          return '🚀 任务派发中...';
        case 'working':
          return `🔵 轮询第 ${round} 轮 · ${this.formatSeconds(elapsed)}`;
        case 'polling':
          return `⚡ 正在探针采样 (第 ${round} 轮)`;
        case 'quiet':
          return `⚠️ 停滞警示 (${this.state.quietRounds}/8 轮)`;
        case 'done':
          return `🟢 本轮完成 · 总耗时 ${this.formatSeconds(elapsed)}`;
        case 'interrupted':
          return '🛑 任务已打断';
        default:
          return status;
      }
    }

    formatSeconds(sec) {
      if (!sec || sec < 0) return '0s';
      const m = Math.floor(sec / 60);
      const s = Math.floor(sec % 60);
      return m > 0 ? `${m}m ${s}s` : `${s}s`;
    }

    destroy() {
      if (this.countdownTimer) clearInterval(this.countdownTimer);
      if (this.el && this.el.parentNode) {
        this.el.parentNode.removeChild(this.el);
      }
    }
  }

  global.ProgressTickerComponent = ProgressTickerComponent;
})(typeof window !== 'undefined' ? window : this);

