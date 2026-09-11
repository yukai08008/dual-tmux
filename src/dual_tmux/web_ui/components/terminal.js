// Dual Terminal View Component
class DualTerminalComponent {
  constructor(options = {}) {
    this.container = options.container || null;
    this.layout = localStorage.getItem('dt:term:layout') || 'split'; // split | op | run
    this.states = {
      op: { isAtBottom: true, lastContent: '' },
      run: { isAtBottom: true, lastContent: '' }
    };
    this.onLayoutChange = options.onLayoutChange || null;
  }

  render() {
    if (!this.container) return;
    this.container.innerHTML = `
      <div class="dt-term-container dt-scope">
        <div class="dt-term-toolbar">
          <div class="dt-term-layouts">
            <span style="font-size:12px; color:var(--dt-text-secondary); margin-right:4px;">视窗布局:</span>
            <button type="button" class="dt-term-layout-btn ${this.layout === 'split' ? 'active' : ''}" data-layout="split">并排双屏 (Split)</button>
            <button type="button" class="dt-term-layout-btn ${this.layout === 'op' ? 'active' : ''}" data-layout="op">Trigger 独占</button>
            <button type="button" class="dt-term-layout-btn ${this.layout === 'run' ? 'active' : ''}" data-layout="run">Bullet 独占</button>
          </div>
          <div style="font-size:11.5px; color:var(--dt-text-muted);">
            智能吸底已开启 · 向上滚动自动锁定位置
          </div>
        </div>

        <div class="dt-term-panes layout-${this.layout}" id="dt-term-panes">
          <!-- Trigger Pane -->
          <div class="dt-pane-card pane-op" id="pane-card-op">
            <div class="dt-pane-header">
              <div class="dt-pane-title-group">
                <span class="dt-lamp dt-lamp-gray" id="dt-lamp-op"></span>
                <span class="dt-pane-role-badge">Trigger</span>
                <span class="dt-pane-name" id="dt-title-op">op_*</span>
                <span class="dt-pane-cmd" id="dt-cmd-op"></span>
              </div>
              <div class="dt-pane-actions">
                <button type="button" class="dt-pane-btn" id="dt-copy-op" title="复制屏幕文本">📋 复制</button>
              </div>
            </div>
            <div class="dt-pane-viewport">
              <pre class="dt-pane-screen" id="dt-screen-op">选定隧道后显示 Trigger 会话...</pre>
              <div class="dt-scroll-lock-banner" id="dt-lock-op" style="display:none">
                👇 滚动锁定中 · 点击回到底部
              </div>
            </div>
          </div>

          <!-- Bullet Pane -->
          <div class="dt-pane-card pane-run" id="pane-card-run">
            <div class="dt-pane-header">
              <div class="dt-pane-title-group">
                <span class="dt-lamp dt-lamp-gray" id="dt-lamp-run"></span>
                <span class="dt-pane-role-badge">Bullet</span>
                <span class="dt-pane-name" id="dt-title-run">run_*</span>
                <span class="dt-pane-cmd" id="dt-cmd-run"></span>
              </div>
              <div class="dt-pane-actions">
                <button type="button" class="dt-pane-btn" id="dt-copy-run" title="复制屏幕文本">📋 复制</button>
              </div>
            </div>
            <div class="dt-pane-viewport">
              <pre class="dt-pane-screen" id="dt-screen-run">选定隧道后显示 Bullet 会话...</pre>
              <div class="dt-scroll-lock-banner" id="dt-lock-run" style="display:none">
                👇 滚动锁定中 · 点击回到底部
              </div>
            </div>
          </div>
        </div>
      </div>
    `;

    this.bindEvents();
  }

  bindEvents() {
    const panes = this.container.querySelector('#dt-term-panes');
    const layoutBtns = this.container.querySelectorAll('.dt-term-layout-btn');

    layoutBtns.forEach(btn => {
      btn.addEventListener('click', () => {
        const target = btn.dataset.layout;
        this.setLayout(target);
      });
    });

    ['op', 'run'].forEach(side => {
      const screen = this.container.querySelector('#dt-screen-' + side);
      const lockBanner = this.container.querySelector('#dt-lock-' + side);
      const copyBtn = this.container.querySelector('#dt-copy-' + side);

      // Smart auto-scroll detection
      screen.addEventListener('scroll', () => {
        const threshold = 25;
        const isAtBottom = screen.scrollHeight - screen.scrollTop - screen.clientHeight <= threshold;
        this.states[side].isAtBottom = isAtBottom;
        lockBanner.style.display = isAtBottom ? 'none' : 'flex';
      });

      lockBanner.addEventListener('click', () => {
        screen.scrollTop = screen.scrollHeight;
        this.states[side].isAtBottom = true;
        lockBanner.style.display = 'none';
      });

      copyBtn.addEventListener('click', async () => {
        const text = screen.textContent || '';
        try {
          await navigator.clipboard.writeText(text);
          if (window.DualToast) DualToast.success(side.toUpperCase() + ' 屏幕内容已复制到剪贴板');
        } catch (e) {
          if (window.DualToast) DualToast.error('复制失败');
        }
      });
    });
  }

  setLayout(layout) {
    this.layout = layout;
    localStorage.setItem('dt:term:layout', layout);
    const panes = this.container.querySelector('#dt-term-panes');
    panes.className = 'dt-term-panes layout-' + layout;

    this.container.querySelectorAll('.dt-term-layout-btn').forEach(b => {
      b.classList.toggle('active', b.dataset.layout === layout);
    });

    if (this.onLayoutChange) this.onLayoutChange(layout);
  }

  updatePane(side, { text = '', name = '', cmd = '', live = false }) {
    if (!this.container) return;
    const titleEl = this.container.querySelector('#dt-title-' + side);
    const cmdEl = this.container.querySelector('#dt-cmd-' + side);
    const lampEl = this.container.querySelector('#dt-lamp-' + side);
    const screenEl = this.container.querySelector('#dt-screen-' + side);

    if (titleEl && name) titleEl.textContent = name;
    if (cmdEl) cmdEl.textContent = cmd ? '(' + cmd + ')' : '';
    if (lampEl) {
      lampEl.className = 'dt-lamp ' + (live ? 'dt-lamp-green' : 'dt-lamp-gray');
    }

    if (screenEl && text !== this.states[side].lastContent) {
      this.states[side].lastContent = text;
      screenEl.textContent = text;
      // Only auto-scroll if user was already at the bottom
      if (this.states[side].isAtBottom) {
        screenEl.scrollTop = screenEl.scrollHeight;
      }
    }
  }
}

window.DualTerminalComponent = DualTerminalComponent;

