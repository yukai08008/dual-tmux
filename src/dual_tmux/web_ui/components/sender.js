// Command / Prompt Sender Component
class CommandSenderComponent {
  constructor(options = {}) {
    this.container = options.container || null;
    this.target = 'op'; // 'op' | 'run'
    this.history = [];
    this.historyIndex = -1;
    this.sending = false;
    this.onSend = options.onSend || null; // async ({ target, text }) => {}
  }

  render() {
    if (!this.container) return;
    const isMac = navigator.platform.toUpperCase().indexOf('MAC') >= 0;
    const shortcutText = isMac ? '⌘ + Enter' : 'Ctrl + Enter';

    this.container.innerHTML = `
      <div class="dt-sender-card dt-scope">
        <div class="dt-sender-header">
          <div style="display:flex; align-items:center; gap:10px;">
            <span style="font-size:13px; font-weight:600; color:var(--dt-text-primary);">发送指令</span>
            <div class="dt-sender-target-switch">
              <button type="button" class="dt-sender-target-tab ${this.target === 'op' ? 'active' : ''}" data-target="op">
                <span class="dt-lamp dt-lamp-gray" id="dt-target-lamp-op"></span>
                <span>Trigger (op_*)</span>
              </button>
              <button type="button" class="dt-sender-target-tab ${this.target === 'run' ? 'active' : ''}" data-target="run">
                <span class="dt-lamp dt-lamp-gray" id="dt-target-lamp-run"></span>
                <span>Bullet (run_*)</span>
              </button>
            </div>
          </div>
          <div class="dt-sender-hints">
            <span>支持换行 · 按 <kbd class="dt-sender-kbd">${shortcutText}</kbd> 快捷发送</span>
          </div>
        </div>

        <textarea class="dt-sender-textarea" id="dt-sender-input" placeholder="输入命令或提示词，将通过 tmux send-keys 注入选定端点..."></textarea>

        <div class="dt-sender-footer">
          <label style="display:inline-flex; align-items:center; gap:6px; font-size:12px; color:var(--dt-text-secondary); cursor:pointer;">
            <input type="checkbox" id="dt-sender-clear-toggle" checked>
            <span>发送后清空输入框</span>
          </label>
          <button type="button" class="dt-btn dt-btn-primary dt-sender-submit" id="dt-sender-submit-btn">
            <span>提交</span>
          </button>
        </div>
      </div>
    `;

    this.bindEvents();
  }

  bindEvents() {
    const input = this.container.querySelector('#dt-sender-input');
    const submitBtn = this.container.querySelector('#dt-sender-submit-btn');
    const clearToggle = this.container.querySelector('#dt-sender-clear-toggle');
    const tabs = this.container.querySelectorAll('.dt-sender-target-tab');

    tabs.forEach(tab => {
      tab.addEventListener('click', () => {
        this.target = tab.dataset.target;
        tabs.forEach(t => t.classList.toggle('active', t.dataset.target === this.target));
      });
    });

    const doSubmit = async () => {
      if (this.sending) return;
      const text = input.value.trim();
      if (!text) {
        if (window.DualToast) DualToast.warn('输入内容不能为空');
        input.focus();
        return;
      }

      this.sending = true;
      submitBtn.disabled = true;
      submitBtn.innerHTML = '<span>发送中...</span>';

      try {
        if (this.onSend) {
          await this.onSend({ target: this.target, text });
        }
        this.history.unshift(text);
        if (this.history.length > 50) this.history.pop();
        this.historyIndex = -1;

        if (clearToggle.checked) {
          input.value = '';
        }
        if (window.DualToast) {
          DualToast.success(`已向 ${this.target.toUpperCase()} 注入指令`);
        }
      } catch (err) {
        if (window.DualToast) {
          DualToast.error('发送失败: ' + (err.message || err));
        }
      } finally {
        this.sending = false;
        submitBtn.disabled = false;
        submitBtn.innerHTML = '<span>提交</span>';
      }
    };

    submitBtn.addEventListener('click', doSubmit);

    // Keyboard shortcut: Cmd+Enter or Ctrl+Enter
    input.addEventListener('keydown', (e) => {
      if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') {
        e.preventDefault();
        doSubmit();
      }
    });
  }

  setDisabled(disabled) {
    if (!this.container) return;
    const input = this.container.querySelector('#dt-sender-input');
    const submitBtn = this.container.querySelector('#dt-sender-submit-btn');
    if (input) input.disabled = disabled;
    if (submitBtn) submitBtn.disabled = disabled;
  }

  updateLamps({ opLive, runLive }) {
    if (!this.container) return;
    const opLamp = this.container.querySelector('#dt-target-lamp-op');
    const runLamp = this.container.querySelector('#dt-target-lamp-run');
    if (opLamp) opLamp.className = 'dt-lamp ' + (opLive ? 'dt-lamp-green' : 'dt-lamp-gray');
    if (runLamp) runLamp.className = 'dt-lamp ' + (runLive ? 'dt-lamp-green' : 'dt-lamp-gray');
  }
}

window.CommandSenderComponent = CommandSenderComponent;

