// Lifecycle & Operations Component
class LifecycleToolbarComponent {
  constructor(options = {}) {
    this.container = options.container || null;
    this.collapsed = true;
    this.onFreeze = options.onFreeze || null;
    this.onReconnect = options.onReconnect || null;
    this.onDrop = options.onDrop || null;
    this.onModelChange = options.onModelChange || null;
  }

  render() {
    if (!this.container) return;
    this.container.innerHTML = `
      <div class="dt-ops-card dt-scope">
        <div class="dt-ops-toggle" id="dt-ops-toggle">
          <div style="display:flex; align-items:center; gap:8px;">
            <span style="font-size:13px; font-weight:600; color:var(--dt-text-primary);">⚙️ 运维工具与模型配置</span>
            <span style="font-size:11px; color:var(--dt-text-muted);">Freeze / 重连 / Drop / 模型切换</span>
          </div>
          <span style="font-size:12px; color:var(--dt-text-muted);" id="dt-ops-arrow">${this.collapsed ? '展开 ▼' : '收起 ▲'}</span>
        </div>

        <div class="dt-ops-body" id="dt-ops-body" style="display:${this.collapsed ? 'none' : 'flex'}">
          <div class="dt-ops-row">
            <div class="dt-ops-field">
              <span>Freeze 范围:</span>
              <select class="dt-select" id="dt-ops-freeze-side">
                <option value="both">trigger + bullet</option>
                <option value="trigger">仅 trigger</option>
                <option value="bullet">仅 bullet</option>
              </select>
            </div>
            <button type="button" class="dt-btn dt-btn-ghost dt-btn-sm" id="dt-ops-btn-freeze">❄️ 执行 Freeze 固化</button>
            <button type="button" class="dt-btn dt-btn-ghost dt-btn-sm" id="dt-ops-btn-reconnect">🔌 重新连接入口</button>
            <button type="button" class="dt-btn dt-btn-ghost dt-btn-sm" id="dt-ops-btn-drop">🧹 清退 (Drop)</button>
          </div>

          <div class="dt-ops-row">
            <div class="dt-ops-field">
              <span>Trigger 模型:</span>
              <input type="text" class="dt-input" style="width:160px" id="dt-ops-model-op" placeholder="provider/model">
              <button type="button" class="dt-btn dt-btn-ghost dt-btn-sm" id="dt-ops-btn-model-op">设置</button>
            </div>
            <div class="dt-ops-field">
              <span>Bullet 模型:</span>
              <input type="text" class="dt-input" style="width:160px" id="dt-ops-model-run" placeholder="provider/model">
              <button type="button" class="dt-btn dt-btn-ghost dt-btn-sm" id="dt-ops-btn-model-run">设置</button>
            </div>
          </div>
        </div>
      </div>
    `;

    this.bindEvents();
  }

  bindEvents() {
    const toggle = this.container.querySelector('#dt-ops-toggle');
    const body = this.container.querySelector('#dt-ops-body');
    const arrow = this.container.querySelector('#dt-ops-arrow');

    toggle.addEventListener('click', () => {
      this.collapsed = !this.collapsed;
      body.style.display = this.collapsed ? 'none' : 'flex';
      arrow.textContent = this.collapsed ? '展开 ▼' : '收起 ▲';
    });

    const freezeBtn = this.container.querySelector('#dt-ops-btn-freeze');
    const reconnectBtn = this.container.querySelector('#dt-ops-btn-reconnect');
    const dropBtn = this.container.querySelector('#dt-ops-btn-drop');

    if (freezeBtn) {
      freezeBtn.addEventListener('click', () => {
        const side = this.container.querySelector('#dt-ops-freeze-side').value;
        if (this.onFreeze) this.onFreeze(side);
      });
    }

    if (reconnectBtn && this.onReconnect) reconnectBtn.addEventListener('click', () => this.onReconnect());
    if (dropBtn && this.onDrop) dropBtn.addEventListener('click', () => this.onDrop());

    const modelOpBtn = this.container.querySelector('#dt-ops-btn-model-op');
    const modelRunBtn = this.container.querySelector('#dt-ops-btn-model-run');

    if (modelOpBtn) {
      modelOpBtn.addEventListener('click', () => {
        const m = this.container.querySelector('#dt-ops-model-op').value.trim();
        if (this.onModelChange) this.onModelChange('op', m);
      });
    }

    if (modelRunBtn) {
      modelRunBtn.addEventListener('click', () => {
        const m = this.container.querySelector('#dt-ops-model-run').value.trim();
        if (this.onModelChange) this.onModelChange('run', m);
      });
    }
  }

  setModels({ triggerModel = '', bulletModel = '' }) {
    if (!this.container) return;
    const opInput = this.container.querySelector('#dt-ops-model-op');
    const runInput = this.container.querySelector('#dt-ops-model-run');
    if (opInput && !opInput.matches(':focus')) opInput.value = triggerModel;
    if (runInput && !runInput.matches(':focus')) runInput.value = bulletModel;
  }
}

window.LifecycleToolbarComponent = LifecycleToolbarComponent;

