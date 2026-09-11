// Tunnel Picker & Tabs Component
class TunnelPickerComponent {
  constructor(options = {}) {
    this.container = options.container || null;
    this.tunnels = [];
    this.tabs = [];
    this.activeTunnel = '';
    this.onSelect = options.onSelect || null;
  }

  render() {
    if (!this.container) return;
    this.container.innerHTML = `
      <div class="dt-picker-container dt-scope">
        <!-- Session Tabs -->
        <div class="dt-tabs-bar" id="dt-tabs-bar"></div>

        <!-- Search Bar -->
        <div class="dt-picker-search-row">
          <div class="dt-picker-input-wrap">
            <input type="search" class="dt-input" style="width:100%" id="dt-picker-search" placeholder="🔍 输入隧道名称模糊搜索（dt ls）..." autocomplete="off">
            <div class="dt-picker-hits" id="dt-picker-hits"></div>
          </div>
        </div>

        <!-- DST / Draft Banner -->
        <div class="dt-picker-banner" id="dt-picker-banner" style="display:none"></div>
      </div>
    `;

    this.bindEvents();
  }

  bindEvents() {
    const searchInput = this.container.querySelector('#dt-picker-search');
    const hitsEl = this.container.querySelector('#dt-picker-hits');

    const renderHits = () => {
      const q = (searchInput.value || '').trim().toLowerCase();
      const filtered = this.tunnels.filter(t => {
        if (!q) return true;
        const blob = [t.name, t.op, t.run].join(' ').toLowerCase();
        return q.split(/\s+/).every(p => blob.includes(p));
      }).slice(0, 15);

      if (!filtered.length) {
        hitsEl.innerHTML = '<div style="padding:10px; font-size:12px; color:var(--dt-text-muted);">无匹配隧道</div>';
      } else {
        hitsEl.innerHTML = filtered.map(t => `
          <div class="dt-picker-hit-item" data-name="${t.name}">
            <div style="display:flex; align-items:center; gap:8px;">
              <span class="dt-lamp ${t.op_live || t.run_live ? 'dt-lamp-green' : 'dt-lamp-gray'}"></span>
              <span style="font-weight:600; font-size:13px;">${t.name}</span>
              <span class="dt-badge ${t.dst ? 'dt-badge-dst' : 'dt-badge-draft'}">${t.dst ? 'DST' : '草稿'}</span>
            </div>
            <div style="font-size:11px; color:var(--dt-text-muted); font-family:var(--dt-font-mono);">
              ${t.op} / ${t.run}
            </div>
          </div>
        `).join('');
      }
      hitsEl.style.display = 'block';
    };

    searchInput.addEventListener('focus', renderHits);
    searchInput.addEventListener('input', renderHits);

    hitsEl.addEventListener('click', (e) => {
      const item = e.target.closest('.dt-picker-hit-item');
      if (!item) return;
      const name = item.dataset.name;
      hitsEl.style.display = 'none';
      this.selectTunnel(name);
    });

    document.addEventListener('click', (e) => {
      if (!this.container.contains(e.target)) {
        hitsEl.style.display = 'none';
      }
    });
  }

  setTunnels(tunnels) {
    this.tunnels = tunnels || [];
    this.renderTabs();
  }

  renderTabs() {
    const tabsBar = this.container.querySelector('#dt-tabs-bar');
    if (!tabsBar) return;

    tabsBar.innerHTML = this.tabs.map(t => {
      const active = t.name === this.activeTunnel ? 'active' : '';
      return `
        <div class="dt-tab-item ${active}" data-tab="${t.name}">
          <span class="dt-lamp ${t.live ? 'dt-lamp-green' : 'dt-lamp-gray'}"></span>
          <span>${t.name}</span>
          <button type="button" class="dt-tab-close" data-close="${t.name}">×</button>
        </div>
      `;
    }).join('') + '<button type="button" class="dt-tab-add" id="dt-tab-add-btn">+ 新增会话</button>';

    tabsBar.querySelectorAll('.dt-tab-item').forEach(item => {
      item.addEventListener('click', (e) => {
        if (e.target.classList.contains('dt-tab-close')) return;
        this.selectTunnel(item.dataset.tab);
      });
    });

    tabsBar.querySelectorAll('.dt-tab-close').forEach(btn => {
      btn.addEventListener('click', (e) => {
        e.stopPropagation();
        this.closeTab(btn.dataset.close);
      });
    });

    const addBtn = tabsBar.querySelector('#dt-tab-add-btn');
    if (addBtn) {
      addBtn.addEventListener('click', () => {
        const searchInput = this.container.querySelector('#dt-picker-search');
        searchInput.focus();
      });
    }
  }

  selectTunnel(name) {
    this.activeTunnel = name;
    if (!this.tabs.some(t => t.name === name)) {
      const row = this.tunnels.find(r => r.name === name);
      this.tabs.push({ name, live: row ? (row.op_live || row.run_live) : false });
    }
    this.renderTabs();

    const searchInput = this.container.querySelector('#dt-picker-search');
    if (searchInput) searchInput.value = name;

    this.updateBanner(name);
    if (this.onSelect) this.onSelect(name);
  }

  closeTab(name) {
    this.tabs = this.tabs.filter(t => t.name !== name);
    if (this.activeTunnel === name) {
      this.activeTunnel = this.tabs.length ? this.tabs[this.tabs.length - 1].name : '';
      if (this.activeTunnel) this.selectTunnel(this.activeTunnel);
    }
    this.renderTabs();
  }

  updateBanner(name) {
    const banner = this.container.querySelector('#dt-picker-banner');
    if (!banner) return;
    const row = this.tunnels.find(t => t.name === name);
    if (!row) {
      banner.style.display = 'none';
      return;
    }

    banner.style.display = 'flex';
    if (row.dst) {
      banner.className = 'dt-picker-banner banner-dst';
      banner.innerHTML = '<span>✅ <b>已固化 DST 隧道</b> · 支持独热占有与跨机安全接管</span>';
    } else {
      banner.className = 'dt-picker-banner banner-draft';
      banner.innerHTML = '<span>💡 <b>未冻结草稿隧道</b> · 尚未通过 <code>dt freeze</code> 固化为 DST。请先在终端使用 <code>dt work</code> 验证后执行 <code>dt freeze</code>。未冻结禁止跨机接管。</span>';
    }
  }
}

window.TunnelPickerComponent = TunnelPickerComponent;

