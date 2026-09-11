// Occupancy & Takeover Component
class OccupancyCardComponent {
  constructor(options = {}) {
    this.container = options.container || null;
    this.onResume = options.onResume || null;
    this.onHandoff = options.onHandoff || null;
    this.onForceResume = options.onForceResume || null;
    this.onRefresh = options.onRefresh || null;
  }

  render() {
    if (!this.container) return;
    this.container.innerHTML = `
      <div class="dt-occ-card dt-scope">
        <div class="dt-occ-header">
          <div style="display:flex; align-items:center; gap:8px;">
            <span style="font-size:13px; font-weight:600; color:var(--dt-text-primary);">独热占有与状态仲裁</span>
            <span class="dt-badge" id="dt-occ-state-badge">检测中</span>
          </div>
          <button type="button" class="dt-btn dt-btn-ghost dt-btn-sm" id="dt-occ-refresh-btn">🔄 刷新预检</button>
        </div>

        <div class="dt-occ-grid">
          <div class="dt-occ-stat">
            <span class="dt-occ-stat-label">持有者 (Holder)</span>
            <span class="dt-occ-stat-val" id="dt-occ-holder">—</span>
          </div>
          <div class="dt-occ-stat">
            <span class="dt-occ-stat-label">世代纪元 (Gen)</span>
            <span class="dt-occ-stat-val" id="dt-occ-gen">—</span>
          </div>
          <div class="dt-occ-stat">
            <span class="dt-occ-stat-label">归属判断 (Mine)</span>
            <span class="dt-occ-stat-val" id="dt-occ-mine">—</span>
          </div>
          <div class="dt-occ-stat">
            <span class="dt-occ-stat-label">仲裁动作 (Action)</span>
            <span class="dt-occ-stat-val" id="dt-occ-action">—</span>
          </div>
        </div>

        <div class="dt-occ-hint" id="dt-occ-reason">等待后台占用证据刷新...</div>

        <div class="dt-occ-actions">
          <button type="button" class="dt-btn dt-btn-primary dt-btn-sm" id="dt-occ-btn-resume" disabled>安全 Resume 接管</button>
          <button type="button" class="dt-btn dt-btn-ghost dt-btn-sm" id="dt-occ-btn-handoff" disabled>发起 Handoff 交接</button>
          <button type="button" class="dt-btn dt-btn-danger dt-btn-sm" id="dt-occ-btn-force" disabled>高风险 Force Resume</button>
        </div>
      </div>
    `;

    this.bindEvents();
  }

  bindEvents() {
    const refreshBtn = this.container.querySelector('#dt-occ-refresh-btn');
    const resumeBtn = this.container.querySelector('#dt-occ-btn-resume');
    const handoffBtn = this.container.querySelector('#dt-occ-btn-handoff');
    const forceBtn = this.container.querySelector('#dt-occ-btn-force');

    if (refreshBtn) refreshBtn.addEventListener('click', () => this.onRefresh && this.onRefresh());
    if (resumeBtn) resumeBtn.addEventListener('click', () => this.onResume && this.onResume());
    if (handoffBtn) handoffBtn.addEventListener('click', () => this.onHandoff && this.onHandoff());
    if (forceBtn) forceBtn.addEventListener('click', () => this.onForceResume && this.onForceResume());
  }

  update(plan) {
    if (!this.container) return;
    const badge = this.container.querySelector('#dt-occ-state-badge');
    const holder = this.container.querySelector('#dt-occ-holder');
    const gen = this.container.querySelector('#dt-occ-gen');
    const mine = this.container.querySelector('#dt-occ-mine');
    const action = this.container.querySelector('#dt-occ-action');
    const reason = this.container.querySelector('#dt-occ-reason');

    const resumeBtn = this.container.querySelector('#dt-occ-btn-resume');
    const handoffBtn = this.container.querySelector('#dt-occ-btn-handoff');
    const forceBtn = this.container.querySelector('#dt-occ-btn-force');

    const safe = !!plan.safe;
    const occ = (plan.ownership && (plan.ownership.occupancy || plan.ownership.lease)) || {};

    if (badge) {
      badge.className = 'dt-badge ' + (safe ? 'dt-badge-dst' : 'dt-badge-draft');
      badge.textContent = safe ? '可安全操作' : '接管受限';
    }

    if (holder) holder.textContent = occ.holder || '无人占用';
    if (gen) gen.textContent = occ.generation != null ? String(occ.generation) : '—';
    if (mine) mine.textContent = occ.mine ? '当前客户端 (本机)' : '远端客户端';
    if (action) action.textContent = plan.action || 'stop';

    const reasonDict = {
      already_owned: '当前机已持有独热所有权，可安全恢复会话。',
      free: '当前无人占用，可安全进行独热声明。',
      occupancy_steal: '其他客户端持有独热占用，执行 Resume 将声明本机接管，旧端自动清退。',
      not_a_frozen_dst: '当前隧道尚未通过 dt freeze 固化为 DST，跨机接管已阻断。',
      ownership_cache_missing: '占用缓存缺失，请确认后台 daemon 正常运行。'
    };

    if (reason) {
      reason.textContent = reasonDict[plan.reason] || plan.reason || '就绪';
    }

    if (resumeBtn) resumeBtn.disabled = !safe;
    if (handoffBtn) handoffBtn.disabled = !(safe && (plan.action === 'claim' || plan.action === 'resume'));
    if (forceBtn) forceBtn.disabled = !(safe && plan.action === 'claim');
  }
}

window.OccupancyCardComponent = OccupancyCardComponent;

