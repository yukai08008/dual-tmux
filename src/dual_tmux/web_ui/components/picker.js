// Tunnel Picker & Tabs Component
class TunnelPickerComponent {
  constructor(options = {}) {
    this.container = options.container || null;
    this.tunnels = [];
    this.tabs = [];
    this.activeTunnel = '';
    this.isCreatingNewTab = false;
    this.onSelect = options.onSelect || null;
  }

  render() {
    if (!this.container) return;
    this.container.innerHTML = `
      <div class="dt-picker-container dt-scope">
        <!-- Session Tabs -->
        <div class="dt-tabs-bar" id="dt-tabs-bar"></div>

        <!-- Active Session Focus Card -->
        <div class="dt-focus-banner" id="dt-focus-banner"></div>

        <!-- Search & Fast Switcher Row -->
        <div class="dt-picker-search-row">
          <div class="dt-picker-input-wrap">
            <span class="dt-search-icon">🔍</span>
            <input type="search" class="dt-input dt-picker-search-input" id="dt-picker-search" placeholder="快速模糊搜索隧道或输入名称打开新 Tab (Enter 选定)..." autocomplete="off">
            <button type="button" class="dt-search-clear" id="dt-search-clear" title="清空输入" style="display:none">×</button>
            <div class="dt-picker-hits" id="dt-picker-hits"></div>
          </div>
        </div>
      </div>
    `;

    this.bindEvents();
    this.renderTabs();
    this.updateFocusBanner();
  }

  bindEvents() {
    const searchInput = this.container.querySelector('#dt-picker-search');
    const hitsEl = this.container.querySelector('#dt-picker-hits');
    const clearBtn = this.container.querySelector('#dt-search-clear');

    const renderHits = () => {
      const q = (searchInput.value || '').trim().toLowerCase();
      if (clearBtn) clearBtn.style.display = q ? 'block' : 'none';
      const openTabs = new Set(this.tabs.map(t => t.name));
      const filtered = this.tunnels.filter(t => {
        if (!q) return true;
        const blob = [t.name, t.op, t.run].join(' ').toLowerCase();
        return q.split(/\s+/).every(p => blob.includes(p));
      }).slice(0, 20);

      if (!filtered.length) {
        hitsEl.innerHTML = '<div style="padding:12px; font-size:12px; color:var(--dt-text-muted); text-align:center;">未找到匹配隧道（可按 Enter 直接选定）</div>';
      } else {
        hitsEl.innerHTML = filtered.map(t => {
          const isOpen = openTabs.has(t.name);
          const isCurrent = t.name === this.activeTunnel && !this.isCreatingNewTab;
          return `
            <div class="dt-picker-hit-item ${isCurrent ? 'current' : ''}" data-name="${t.name}">
              <div style="display:flex; align-items:center; gap:8px;">
                <span class="dt-lamp ${t.op_live || t.run_live ? 'dt-lamp-green' : 'dt-lamp-gray'}"></span>
                <span class="dt-hit-name">${t.name}</span>
                <span class="dt-badge ${t.dst ? 'dt-badge-dst' : 'dt-badge-draft'}">${t.dst ? 'DST' : '草稿'}</span>
                ${isCurrent ? '<span class="dt-badge" style="background:rgba(59,130,246,0.2); color:#60a5fa;">当前编辑</span>' : ''}
              </div>
              <div style="display:flex; align-items:center; gap:10px;">
                <span style="font-size:11px; color:var(--dt-text-muted); font-family:var(--dt-font-mono);">
                  ${t.op || 'op_*'} ⇄ ${t.run || 'run_*'}
                </span>
                <span class="dt-tab-tag ${isOpen ? 'is-open' : ''}">
                  ${isOpen ? '已在标签页' : '+ 载入'}
                </span>
              </div>
            </div>
          `;
        }).join('');
      }
      hitsEl.style.display = 'block';
    };

    searchInput.addEventListener('focus', renderHits);
    searchInput.addEventListener('input', renderHits);

    searchInput.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') {
        e.preventDefault();
        const q = (searchInput.value || '').trim();
        const firstItem = hitsEl.querySelector('.dt-picker-hit-item');
        if (firstItem) {
          const name = firstItem.dataset.name;
          hitsEl.style.display = 'none';
          this.selectTunnel(name);
        } else if (q) {
          hitsEl.style.display = 'none';
          this.selectTunnel(q);
        }
      } else if (e.key === 'Escape') {
        hitsEl.style.display = 'none';
        if (this.isCreatingNewTab) {
          this.isCreatingNewTab = false;
          this.renderTabs();
          this.updateFocusBanner();
        }
      }
    });

    if (clearBtn) {
      clearBtn.addEventListener('click', () => {
        searchInput.value = '';
        clearBtn.style.display = 'none';
        renderHits();
        searchInput.focus();
      });
    }

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
    this.tabs = this.tabs.map(tab => {
      const match = this.tunnels.find(t => t.name === tab.name);
      return match ? { ...tab, live: !!(match.op_live || match.run_live), dst: !!match.dst } : tab;
    });
    this.renderTabs();
    this.updateFocusBanner();
  }

  renderTabs() {
    const tabsBar = this.container.querySelector('#dt-tabs-bar');
    if (!tabsBar) return;

    const tabItemsHtml = this.tabs.map(t => {
      const isActive = t.name === this.activeTunnel && !this.isCreatingNewTab;
      return `
        <div class="dt-tab-item ${isActive ? 'active' : ''}" data-tab="${t.name}" title="${t.name} · 点击切回该会话">
          <span class="dt-lamp ${t.live ? 'dt-lamp-green' : 'dt-lamp-gray'}"></span>
          <span class="dt-tab-title">${t.name}</span>
          ${t.dst ? '<span class="dt-badge dt-badge-dst dt-tab-badge">DST</span>' : ''}
          <button type="button" class="dt-tab-close" data-close="${t.name}" title="关闭标签页">×</button>
        </div>
      `;
    }).join('');

    const newTabPromptHtml = this.isCreatingNewTab ? `
      <div class="dt-tab-item active is-new-tab" data-tab="__new__">
        <span class="dt-lamp dt-lamp-yellow"></span>
        <span class="dt-tab-title">➕ 选择新会话...</span>
        <button type="button" class="dt-tab-close" data-close="__new__" title="取消新建">×</button>
      </div>
    ` : '';

    tabsBar.innerHTML = tabItemsHtml + newTabPromptHtml + `
      <button type="button" class="dt-tab-add" id="dt-tab-add-btn" title="打开新隧道会话标签页">+ 新增会话</button>
    `;

    tabsBar.querySelectorAll('.dt-tab-item').forEach(item => {
      item.addEventListener('click', (e) => {
        if (e.target.classList.contains('dt-tab-close')) return;
        const tabName = item.dataset.tab;
        if (tabName === '__new__') return;
        this.isCreatingNewTab = false;
        this.selectTunnel(tabName);
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
        this.openNewTabPrompt();
      });
    }

    const activeEl = tabsBar.querySelector('.dt-tab-item.active');
    if (activeEl && typeof activeEl.scrollIntoView === 'function') {
      activeEl.scrollIntoView({ behavior: 'smooth', block: 'nearest', inline: 'nearest' });
    }
  }

  openNewTabPrompt() {
    this.isCreatingNewTab = true;
    this.renderTabs();
    this.updateFocusBanner();

    const searchInput = this.container.querySelector('#dt-picker-search');
    if (searchInput) {
      searchInput.value = '';
      searchInput.focus();
      searchInput.dispatchEvent(new Event('focus'));
    }
  }

  selectTunnel(name, triggerCallback = true) {
    if (!name) return;
    this.activeTunnel = name;
    this.isCreatingNewTab = false;

    const row = this.tunnels.find(r => r.name === name);
    if (!this.tabs.some(t => t.name === name)) {
      this.tabs.push({
        name,
        live: row ? !!(row.op_live || row.run_live) : false,
        dst: row ? !!row.dst : false
      });
    }

    this.renderTabs();
    this.updateFocusBanner();

    const searchInput = this.container.querySelector('#dt-picker-search');
    const clearBtn = this.container.querySelector('#dt-search-clear');
    if (searchInput) searchInput.value = '';
    if (clearBtn) clearBtn.style.display = 'none';

    if (triggerCallback && this.onSelect) {
      this.onSelect(name);
    }
  }

  closeTab(name) {
    if (name === '__new__') {
      this.isCreatingNewTab = false;
      this.renderTabs();
      this.updateFocusBanner();
      return;
    }

    this.tabs = this.tabs.filter(t => t.name !== name);
    if (this.activeTunnel === name) {
      if (this.tabs.length > 0) {
        const nextActive = this.tabs[this.tabs.length - 1].name;
        this.selectTunnel(nextActive);
      } else {
        this.activeTunnel = '';
        this.openNewTabPrompt();
      }
    } else {
      this.renderTabs();
    }

    if (this.onClose) this.onClose(name);
  }

  updateFocusBanner() {
    const banner = this.container.querySelector('#dt-focus-banner');
    if (!banner) return;

    if (this.isCreatingNewTab) {
      banner.innerHTML = `
        <div class="dt-focus-card is-creating">
          <div class="dt-focus-main">
            <div class="dt-focus-meta-tag">新建 / 载入会话标签</div>
            <div class="dt-focus-title-group">
              <span class="dt-focus-title" style="color:#c084fc;">➕ 正在打开新会话</span>
              <span class="dt-badge dt-badge-draft">选择中</span>
            </div>
            <div class="dt-focus-desc">
              请在下方搜索框输入隧道名或从下拉候选列表中选择。选定后将自动添加为活动 Tab。按 ESC 可取消。
            </div>
          </div>
        </div>
      `;
      return;
    }

    if (!this.activeTunnel) {
      banner.innerHTML = `
        <div class="dt-focus-card is-creating">
          <div class="dt-focus-main">
            <div class="dt-focus-meta-tag">尚未选定会话</div>
            <div class="dt-focus-title-group">
              <span class="dt-focus-title">点击上方 “+ 新增会话” 或在下方搜索选择隧道</span>
            </div>
          </div>
        </div>
      `;
      return;
    }

    const row = this.tunnels.find(t => t.name === this.activeTunnel);
    const isLive = row && (row.op_live || row.run_live);
    const isDst = row && row.dst;

    banner.innerHTML = `
      <div class="dt-focus-card ${isDst ? 'is-dst' : 'is-draft'}">
        <div class="dt-focus-main">
          <div class="dt-focus-meta-tag">
            <span class="dt-tag-dot"></span> 📍 当前编辑与监视会话 (ACTIVE SESSION)
          </div>
          <div class="dt-focus-title-group">
            <span class="dt-focus-title" id="dt-active-tunnel-name">${this.activeTunnel}</span>
            <button type="button" class="dt-focus-copy-btn" id="dt-focus-copy-btn" title="复制隧道名称">📋 复制</button>
            <span class="dt-badge ${isDst ? 'dt-badge-dst' : 'dt-badge-draft'}">
              ${isDst ? '🛡️ DST 固化' : '⚠️ 草稿未冻结'}
            </span>
            <span class="dt-badge ${isLive ? 'dt-badge-live' : 'dt-badge-down'}">
              ${isLive ? '🟢 活跃在线' : '⚪ 离线'}
            </span>
          </div>
          <div class="dt-focus-desc">
            ${isDst ?
              '已固化 DST 隧道 · 支持独热占有与跨机安全接管。' :
              '尚未通过 <code>dt freeze</code> 固化为 DST。建议先在终端执行 <code>dt work</code> 验证后再固化。'}
          </div>
        </div>

        <div class="dt-focus-endpoints">
          <div class="dt-focus-endpoint-item">
            <span class="dt-endpoint-label">Trigger</span>
            <span class="dt-endpoint-value">${row ? (row.op || 'op_*') : 'op_*'}</span>
            <span class="dt-lamp ${row && row.op_live ? 'dt-lamp-green' : 'dt-lamp-gray'}"></span>
          </div>
          <div class="dt-focus-endpoint-divider">⇄</div>
          <div class="dt-focus-endpoint-item">
            <span class="dt-endpoint-label">Bullet</span>
            <span class="dt-endpoint-value">${row ? (row.run || 'run_*') : 'run_*'}</span>
            <span class="dt-lamp ${row && row.run_live ? 'dt-lamp-green' : 'dt-lamp-gray'}"></span>
          </div>
        </div>
      </div>
    `;

    const copyBtn = banner.querySelector('#dt-focus-copy-btn');
    if (copyBtn) {
      copyBtn.addEventListener('click', async () => {
        try {
          await navigator.clipboard.writeText(this.activeTunnel);
          if (window.DualToast) DualToast.success('已复制会话名称: ' + this.activeTunnel);
        } catch (e) {
          if (window.DualToast) DualToast.error('复制失败');
        }
      });
    }
  }
}

window.TunnelPickerComponent = TunnelPickerComponent;
