// Global Toast Notification Manager
class ToastManager {
  constructor() {
    this.container = null;
  }

  ensureContainer() {
    if (!this.container) {
      this.container = document.querySelector('.dt-toast-container');
      if (!this.container) {
        this.container = document.createElement('div');
        this.container.className = 'dt-toast-container';
        document.body.appendChild(this.container);
      }
    }
    return this.container;
  }

  show(message, type = 'info', duration = 3000) {
    const container = this.ensureContainer();
    const toast = document.createElement('div');
    toast.className = 'dt-toast dt-toast-' + type;

    const icons = {
      success: '✅',
      error: '❌',
      warning: '⚠️',
      info: 'ℹ️'
    };

    toast.innerHTML = `
      <span class="dt-toast-icon">${icons[type] || icons.info}</span>
      <div class="dt-toast-content">${this.escapeHtml(message)}</div>
      <button type="button" class="dt-toast-close" aria-label="Close">×</button>
    `;

    const closeBtn = toast.querySelector('.dt-toast-close');
    const dismiss = () => {
      toast.classList.add('dt-toast-hiding');
      setTimeout(() => {
        if (toast.parentElement) toast.parentElement.removeChild(toast);
      }, 200);
    };

    closeBtn.addEventListener('click', dismiss);
    if (duration > 0) {
      setTimeout(dismiss, duration);
    }

    container.appendChild(toast);
  }

  success(msg, duration) { this.show(msg, 'success', duration); }
  error(msg, duration = 5000) { this.show(msg, 'error', duration); }
  warn(msg, duration) { this.show(msg, 'warning', duration); }
  info(msg, duration) { this.show(msg, 'info', duration); }

  escapeHtml(str) {
    return String(str || '').replace(/[&<>"']/g, c => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
    })[c]);
  }
}

window.DualToast = new ToastManager();

