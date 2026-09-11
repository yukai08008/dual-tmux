// Turn Thread / Dialogue Flow Component
class TurnThreadComponent {
  constructor(options = {}) {
    this.container = options.container || null;
    this.messages = [];
  }

  render() {
    if (!this.container) return;
    this.container.innerHTML = `
      <div class="dt-thread-card dt-scope">
        <div style="display:flex; align-items:center; justify-content:space-between;">
          <span style="font-size:13px; font-weight:600; color:var(--dt-text-primary);">💬 Trigger 交互流</span>
          <span style="font-size:11px; color:var(--dt-text-muted);">提问与 Agent 回复历史</span>
        </div>
        <div class="dt-thread-stream" id="dt-thread-stream">
          <div style="color:var(--dt-text-muted); font-size:12px; padding:8px;">暂无交互记录</div>
        </div>
      </div>
    `;
  }

  addMessage(kind, text, extra = {}) {
    if (!this.container) return;
    const stream = this.container.querySelector('#dt-thread-stream');
    if (!stream) return;

    if (!this.messages.length) stream.innerHTML = '';
    this.messages.push({ kind, text, extra });
    if (this.messages.length > 50) this.messages.shift();

    const bubble = document.createElement('div');
    bubble.className = 'dt-bubble dt-bubble-' + kind;

    const kindLabels = { ask: '提问', ans: '回复', fail: '失败' };
    const ts = extra.ts ? new Date(extra.ts).toLocaleTimeString() : new Date().toLocaleTimeString();

    bubble.innerHTML = `
      <div class="dt-bubble-header">
        <span>${kindLabels[kind] || kind}</span>
        <span>${ts}</span>
      </div>
      <div class="dt-bubble-body">${this.escapeHtml(text)}</div>
      ${extra.model || extra.elapsed ? `
        <div class="dt-bubble-meta">
          ${extra.model ? `<span>${this.escapeHtml(extra.model)}</span>` : ''}
          ${extra.elapsed ? `<span>⏱️ ${this.escapeHtml(extra.elapsed)}</span>` : ''}
        </div>
      ` : ''}
    `;

    stream.appendChild(bubble);
    stream.scrollTop = stream.scrollHeight;
  }

  clear() {
    this.messages = [];
    if (!this.container) return;
    const stream = this.container.querySelector('#dt-thread-stream');
    if (stream) stream.innerHTML = '<div style="color:var(--dt-text-muted); font-size:12px; padding:8px;">暂无交互记录</div>';
  }

  escapeHtml(str) {
    return String(str || '').replace(/[&<>"']/g, c => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
    })[c]);
  }
}

window.TurnThreadComponent = TurnThreadComponent;

