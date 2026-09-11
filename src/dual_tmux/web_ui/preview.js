// Component Preview Harness
(function() {
  const params = new URLSearchParams(window.location.search);
  const currentComponent = params.get('c') || 'terminal';
  const stage = document.getElementById('dt-component-stage');
  const controls = document.getElementById('dt-tester-controls');

  if (!stage || !controls) return;

  if (currentComponent === 'terminal') {
    initTerminalSandbox();
  } else if (currentComponent === 'sender') {
    initSenderSandbox();
  } else if (currentComponent === 'picker') {
    initPickerSandbox();
  } else if (currentComponent === 'occupancy') {
    initOccupancySandbox();
  } else if (currentComponent === 'toast') {
    initToastSandbox();
  } else if (currentComponent === 'thread') {
    initThreadSandbox();
  } else if (currentComponent === 'lifecycle') {
    initLifecycleSandbox();
  }

  // === 1. Terminal Sandbox ===
  function initTerminalSandbox() {
    controls.innerHTML = `
      <div class="dt-control-title">🎮 交互控制台（验证智能吸底与操作）</div>
      <div class="dt-control-actions">
        <button type="button" class="dt-btn dt-btn-primary dt-btn-sm" id="btn-mock-log">📝 追加一条输出</button>
        <button type="button" class="dt-btn dt-btn-ghost dt-btn-sm" id="btn-mock-stream">⚡ 开启连续日志流 (5条/秒)</button>
        <button type="button" class="dt-btn dt-btn-ghost dt-btn-sm" id="btn-toggle-live">🟢 切换在线/离线状态</button>
        <button type="button" class="dt-btn dt-btn-ghost dt-btn-sm" id="btn-clear-term">🧹 清空屏幕</button>
      </div>
      <div style="font-size:11.5px; color:var(--dt-text-muted); margin-top:4px;">
        💡 <b>测试指引</b>：在下方终端滚动条处于底部时，日志会自动跟随；用鼠标向上滚动翻看历史，吸底将自动暂停，并弹出“👇 滚动锁定”提示，再点提示立即回到底部。
      </div>
    `;

    const term = new DualTerminalComponent({ container: stage });
    term.render();

    let opText = "=== [op_demo] Trigger session initialized ===\nReady for task prompt.\n";
    let runText = "=== [run_demo] Bullet remote bash ready ===\nroot@sandbox:~# uname -a\nLinux sandbox 5.15.0 #1 SMP x86_64\n";
    let count = 0;
    let streamTimer = null;
    let isLive = true;

    term.updatePane('op', { text: opText, name: 'op_demo', cmd: 'opencode@1.18.30', live: true });
    term.updatePane('run', { text: runText, name: 'run_demo', cmd: 'ssh -> tom7r', live: true });

    const addLog = () => {
      count++;
      const time = new Date().toLocaleTimeString();
      opText += "[" + time + "] Step #" + count + ": Agent running AST scan on repository files...\n";
      runText += "[" + time + "] #" + count + " executing rsync --checksum remote worker status OK\n";
      term.updatePane('op', { text: opText, live: isLive });
      term.updatePane('run', { text: runText, live: isLive });
    };

    document.getElementById('btn-mock-log').addEventListener('click', addLog);

    const streamBtn = document.getElementById('btn-mock-stream');
    streamBtn.addEventListener('click', () => {
      if (streamTimer) {
        clearInterval(streamTimer);
        streamTimer = null;
        streamBtn.textContent = '⚡ 开启连续日志流 (5条/秒)';
        streamBtn.className = 'dt-btn dt-btn-ghost dt-btn-sm';
      } else {
        streamTimer = setInterval(addLog, 200);
        streamBtn.textContent = '⏸️ 暂停连续日志流';
        streamBtn.className = 'dt-btn dt-btn-primary dt-btn-sm';
      }
    });

    document.getElementById('btn-toggle-live').addEventListener('click', () => {
      isLive = !isLive;
      term.updatePane('op', { text: opText, live: isLive });
      term.updatePane('run', { text: runText, live: isLive });
      if (window.DualToast) DualToast.info(isLive ? '终端已上线 (Live)' : '终端已离线 (Down)');
    });

    document.getElementById('btn-clear-term').addEventListener('click', () => {
      opText = 'Screen cleared.\n';
      runText = 'Screen cleared.\n';
      term.updatePane('op', { text: opText, live: isLive });
      term.updatePane('run', { text: runText, live: isLive });
      if (window.DualToast) DualToast.info('已重置屏幕文本');
    });
  }

  // === 2. Sender Sandbox ===
  function initSenderSandbox() {
    controls.innerHTML = `
      <div class="dt-control-title">🎮 发送器测试台</div>
      <div style="font-size:12px; color:var(--dt-text-muted);">
        在下方输入框中测试输入与换行，按 <b>Cmd+Enter</b> 或 <b>Ctrl+Enter</b> 测试快捷发送。
      </div>
    `;

    const sender = new CommandSenderComponent({
      container: stage,
      onSend: async (payload) => {
        await new Promise(r => setTimeout(r, 400));
        console.log('Mock sent to', payload.target, payload.text);
      }
    });
    sender.render();
    sender.updateLamps({ opLive: true, runLive: true });
  }

  // === 3. Picker Sandbox ===
  function initPickerSandbox() {
    controls.innerHTML = `
      <div class="dt-control-title">🎮 隧道选择与 Tabs 测试台</div>
      <div class="dt-control-actions">
        <button type="button" class="dt-btn dt-btn-primary dt-btn-sm" id="btn-mock-add-tab">➕ 触发“打开新会话”</button>
        <button type="button" class="dt-btn dt-btn-ghost dt-btn-sm" id="btn-mock-switch-1">👉 切到 dt-company_intro_v2</button>
        <button type="button" class="dt-btn dt-btn-ghost dt-btn-sm" id="btn-mock-switch-2">👉 切到 dt-alex-serp</button>
        <button type="button" class="dt-btn dt-btn-ghost dt-btn-sm" id="btn-mock-switch-3">👉 切到 dt-new-event-v2</button>
      </div>
      <div style="font-size:11.5px; color:var(--dt-text-muted); margin-top:4px;">
        💡 <b>焦点验证指引</b>：
        1. 观察上方 Tab 激活状态（鲜艳蓝顶条 + 发光阴影 + 白色加粗字体）；
        2. 观察 Tab 下方的 <b>📍 当前编辑与监视会话看板</b>，无论切到哪个 Tab，当前编辑对象一目了然；
        3. 点击 “+ 新增会话” 体验新建流程（出现高亮暂态 Tab，搜索框自动清空并弹出候选池，回车或点选立即载入）。
      </div>
    `;

    const picker = new TunnelPickerComponent({
      container: stage,
      onSelect: (name) => {
        if (window.DualToast) DualToast.info('已选定隧道: ' + name);
      }
    });
    picker.render();
    picker.setTunnels([
      { name: 'dt-company_intro_v2', op: 'op_company_intro_v2', run: 'run_company_intro_v2', dst: true, op_live: true, run_live: true },
      { name: 'dt-alex-serp', op: 'op_alex_serp', run: 'run_alex_serp', dst: true, op_live: true, run_live: false },
      { name: 'dt-autotest', op: 'op_autotest', run: 'run_autotest', dst: false, op_live: false, run_live: false },
      { name: 'dt-new-event-v2', op: 'op_new_event_v2', run: 'run_new_event_v2', dst: true, op_live: true, run_live: true },
    ]);
    picker.selectTunnel('dt-company_intro_v2');

    document.getElementById('btn-mock-add-tab').addEventListener('click', () => {
      picker.openNewTabPrompt();
    });
    document.getElementById('btn-mock-switch-1').addEventListener('click', () => {
      picker.selectTunnel('dt-company_intro_v2');
    });
    document.getElementById('btn-mock-switch-2').addEventListener('click', () => {
      picker.selectTunnel('dt-alex-serp');
    });
    document.getElementById('btn-mock-switch-3').addEventListener('click', () => {
      picker.selectTunnel('dt-new-event-v2');
    });
  }

  // === 4. Occupancy Sandbox ===
  function initOccupancySandbox() {
    controls.innerHTML = `
      <div class="dt-control-title">🎮 独热仲裁模拟器</div>
      <div class="dt-control-actions">
        <button type="button" class="dt-btn dt-btn-ghost dt-btn-sm" id="btn-sim-owned">🟢 模拟本机持有 (Already Owned)</button>
        <button type="button" class="dt-btn dt-btn-ghost dt-btn-sm" id="btn-sim-foreign">🟡 模拟远端占用可接管 (Claimable)</button>
        <button type="button" class="dt-btn dt-btn-ghost dt-btn-sm" id="btn-sim-blocked">🔴 模拟未冻结草稿阻断 (Draft Blocked)</button>
      </div>
    `;

    const occ = new OccupancyCardComponent({
      container: stage,
      onResume: () => window.DualToast && DualToast.success('触发执行安全 Resume 流程！'),
      onHandoff: () => window.DualToast && DualToast.info('发起优雅 Handoff 协商'),
      onForceResume: () => window.DualToast && DualToast.warn('警告：已触发强制接管')
    });
    occ.render();

    const applyOwned = () => {
      occ.update({
        safe: true,
        action: 'resume',
        reason: 'already_owned',
        ownership: {
          occupancy: { holder: 'tm_laptop (本机)', generation: 42, mine: true }
        }
      });
    };

    const applyForeign = () => {
      occ.update({
        safe: true,
        action: 'claim',
        reason: 'occupancy_steal',
        ownership: {
          occupancy: { holder: 'tm_office (远程Mac)', generation: 41, mine: false }
        }
      });
    };

    const applyBlocked = () => {
      occ.update({
        safe: false,
        action: 'stop',
        reason: 'not_a_frozen_dst',
        ownership: {
          occupancy: { holder: 'none', generation: 0, mine: true }
        }
      });
    };

    document.getElementById('btn-sim-owned').addEventListener('click', applyOwned);
    document.getElementById('btn-sim-foreign').addEventListener('click', applyForeign);
    document.getElementById('btn-sim-blocked').addEventListener('click', applyBlocked);

    applyOwned();
  }

  // === 5. Toast Sandbox ===
  function initToastSandbox() {
    controls.innerHTML = `
      <div class="dt-control-title">🎮 Toast 通知触发器</div>
      <div class="dt-control-actions">
        <button type="button" class="dt-btn dt-btn-primary dt-btn-sm" onclick="DualToast.success('操作成功：已完成会话固化 Freeze')">✅ 成功提示</button>
        <button type="button" class="dt-btn dt-btn-danger dt-btn-sm" onclick="DualToast.error('操作失败：远端客户端无响应')">❌ 错误提示</button>
        <button type="button" class="dt-btn dt-btn-ghost dt-btn-sm" onclick="DualToast.warn('警告：当前隧道尚未冻结')">⚠️ 警告提示</button>
        <button type="button" class="dt-btn dt-btn-ghost dt-btn-sm" onclick="DualToast.info('信息：后台正在同步快照...')">ℹ️ 信息提示</button>
      </div>
    `;
    stage.innerHTML = '<div class="dt-card" style="text-align:center; padding:40px; color:var(--dt-text-muted);">点击上方按钮测试全局 Toast 弹出效果</div>';
  }

  // === 6. Thread Sandbox ===
  function initThreadSandbox() {
    controls.innerHTML = `
      <div class="dt-control-title">🎮 问答对话流模拟器</div>
      <div class="dt-control-actions">
        <button type="button" class="dt-btn dt-btn-primary dt-btn-sm" id="btn-add-ask">🙋 追加用户提问</button>
        <button type="button" class="dt-btn dt-btn-ghost dt-btn-sm" id="btn-add-ans">🤖 追加 Agent 回复</button>
        <button type="button" class="dt-btn dt-btn-danger dt-btn-sm" id="btn-add-fail">⚠️ 追加执行失败</button>
        <button type="button" class="dt-btn dt-btn-ghost dt-btn-sm" id="btn-clear-chat">🧹 清空对话</button>
      </div>
    `;

    const thread = new TurnThreadComponent({ container: stage });
    thread.render();

    thread.addMessage('ask', '请帮我重构 dual-tmux 的 Web 模块，实现组件化设计。', { ts: new Date().toISOString() });
    thread.addMessage('ans', '已拆分为 7 大独立组件，并设计了统一的主题样式规范。', {
      model: 'xs-cp-gate/gpt-5.6-sol',
      elapsed: '3.4s',
      ts: new Date().toISOString()
    });

    document.getElementById('btn-add-ask').addEventListener('click', () => {
      thread.addMessage('ask', '模拟提问：检查当前隧道是否处于独热状态？', { ts: new Date().toISOString() });
    });
    document.getElementById('btn-add-ans').addEventListener('click', () => {
      thread.addMessage('ans', '模拟回复：已完成仲裁校验，当前由 tm_laptop 独热持有。', {
        model: 'xs-cp-gate/gpt-5.6-sol',
        elapsed: '1.8s',
        ts: new Date().toISOString()
      });
    });
    document.getElementById('btn-add-fail').addEventListener('click', () => {
      thread.addMessage('fail', '模拟错误：无法连接到 tom7r 宿主机，连接超时。', { ts: new Date().toISOString() });
    });
    document.getElementById('btn-clear-chat').addEventListener('click', () => {
      thread.clear();
    });
  }

  // === 7. Lifecycle Sandbox ===
  function initLifecycleSandbox() {
    controls.innerHTML = `
      <div class="dt-control-title">🎮 运维折叠卡片测试台</div>
      <div style="font-size:12px; color:var(--dt-text-muted);">
        测试点击右上角“展开/收起”，点击各个运维操作按钮，观察交互与 Toast 联动。
      </div>
    `;

    const ops = new LifecycleToolbarComponent({
      container: stage,
      onFreeze: (side) => window.DualToast && DualToast.success('触发 Freeze 固化: ' + side),
      onReconnect: () => window.DualToast && DualToast.info('触发重新连接入口'),
      onDrop: () => window.DualToast && DualToast.warn('触发 Drop 清退隧道'),
      onModelChange: (side, model) => window.DualToast && DualToast.info('模型设置 [' + side + ']: ' + (model || '默认'))
    });
    ops.render();
    ops.setModels({ triggerModel: 'xs-cp-gate/gpt-5.6-sol', bulletModel: 'xs-cli-pro/deepseek-v4-pro' });
  }
})();
