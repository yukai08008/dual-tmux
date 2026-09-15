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
  } else if (currentComponent === 'ticker') {
    initTickerSandbox();
  } else if (currentComponent === 'feed') {
    initFeedSandbox();
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
      },
      onInterrupt: async (payload) => {
        await new Promise(r => setTimeout(r, 400));
        console.log('Mock interrupted', payload.target, payload.kind);
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

  // === 8. Progress Ticker Sandbox ===
  function initTickerSandbox() {
    controls.innerHTML = `
      <div class="dt-control-title">🎮 进展跑马灯原型控制台（模拟 Trigger 轮询 Bullet 进展生命周期）</div>
      <div class="dt-control-actions">
        <button type="button" class="dt-btn dt-btn-ghost dt-btn-sm" id="btn-state-idle">🟢 空闲就绪 (Idle)</button>
        <button type="button" class="dt-btn dt-btn-ghost dt-btn-sm" id="btn-state-dispatch">🚀 派发任务 (Dispatch)</button>
        <button type="button" class="dt-btn dt-btn-ghost dt-btn-sm" id="btn-state-working">🔵 Bullet 执行 (Working)</button>
        <button type="button" class="dt-btn dt-btn-primary dt-btn-sm" id="btn-state-poll">⚡ 执行探针采样 (Probe)</button>
        <button type="button" class="dt-btn dt-btn-ghost dt-btn-sm" id="btn-state-quiet">⚠️ 静默停滞警告 (Quiet 5/8)</button>
        <button type="button" class="dt-btn dt-btn-ghost dt-btn-sm" id="btn-state-done">✅ 本轮完成 (Done)</button>
        <button type="button" class="dt-btn dt-btn-danger dt-btn-sm" id="btn-state-interrupt">🛑 打断中断 (Ctrl+C)</button>
      </div>
      <div style="font-size:11.5px; color:var(--dt-text-muted); margin-top:4px;">
        💡 <b>测试指引</b>：点击上方不同阶段按钮，观察跑马灯横向平滑滚动、静默轮次熔断标尺（8格指示）、呼吸脉冲指示灯以及下次检查倒计时的实时变化。鼠标悬停在跑马灯上可暂停滚动。
      </div>
    `;

    const ticker = new ProgressTickerComponent({
      container: stage,
      onInterrupt: () => {
        if (typeof DualToast !== 'undefined') {
          DualToast.warn('已触发打断信号 (C-c)，正在通知后端中断目标端点...');
        }
        ticker.update({
          status: 'interrupted',
          statusText: '🛑 任务已打断',
          summary: '用户主动触发中断，前台进程已收到 Ctrl+C / SIGINT 信号',
          nextCheckSeconds: 0,
        });
      },
      onProbeNow: () => {
        if (typeof DualToast !== 'undefined') {
          DualToast.info('正在执行即时探针采样 (Capture Pane)...');
        }
        ticker.update({
          status: 'polling',
          statusText: '⚡ 正在探针比对...',
          summary: 'Trigger 正在截取 Bullet 最近 60 行输出并计算去 ANSI 语义指纹...',
        });
        setTimeout(() => {
          ticker.update({
            status: 'working',
            round: ticker.state.round + 1,
            elapsed: ticker.state.elapsed + 15,
            quietRounds: Math.max(0, ticker.state.quietRounds - 1),
            summary: '检测到有效增量：Bullet 正在运行 pytest tests/test_activity.py (通过 5/6 项)',
            tokens: '148.2K',
            tokensDelta: '+1.2K',
          });
          ticker.setCountdown(20);
        }, 1200);
      }
    });

    ticker.render();

    // 默认初始装载状态
    ticker.update({
      status: 'working',
      round: 3,
      elapsed: 48,
      quietRounds: 2,
      maxQuietRounds: 8,
      target: 'bullet',
      summary: 'Bullet 正在编译项目并生成测试报告: npm run build (stdout: 12 modules transformed)...',
      tokens: '142.6K',
      tokensDelta: '+850',
    });
    ticker.setCountdown(18);

    // 绑定交互按钮
    document.getElementById('btn-state-idle').addEventListener('click', () => {
      ticker.update({
        status: 'idle',
        statusText: '就绪 / 等待任务',
        round: 0,
        elapsed: 0,
        quietRounds: 0,
        target: 'bullet',
        summary: '当前会话空闲，等待在输入框下发新任务',
        tokens: '135.0K',
        tokensDelta: '',
      });
      ticker.setCountdown(0);
    });

    document.getElementById('btn-state-dispatch').addEventListener('click', () => {
      ticker.update({
        status: 'dispatching',
        statusText: '🚀 派发任务中...',
        round: 1,
        elapsed: 2,
        quietRounds: 0,
        target: 'trigger',
        summary: 'Trigger 已将需求整理为 Bullet 结构化任务，正在向 run_* 注入 send-keys...',
        tokens: '138.4K',
        tokensDelta: '+3.4K',
      });
      ticker.setCountdown(5);
    });

    document.getElementById('btn-state-working').addEventListener('click', () => {
      ticker.update({
        status: 'working',
        round: 2,
        elapsed: 32,
        quietRounds: 1,
        target: 'bullet',
        summary: 'Bullet 正在执行模型深度思考与工具调用：AST 分析文件依赖结构中...',
        tokens: '141.2K',
        tokensDelta: '+2.8K',
      });
      ticker.setCountdown(25);
    });

    document.getElementById('btn-state-poll').addEventListener('click', () => {
      ticker.onProbeNow();
    });

    document.getElementById('btn-state-quiet').addEventListener('click', () => {
      ticker.update({
        status: 'quiet',
        round: 6,
        elapsed: 155,
        quietRounds: 5,
        target: 'bullet',
        summary: '连续 5 轮无有效证据增长（Token 未变动，输出无新增行），可能进入死锁或长等待，请留意！',
        tokens: '148.2K',
        tokensDelta: '+0',
      });
      ticker.setCountdown(10);
    });

    document.getElementById('btn-state-done').addEventListener('click', () => {
      ticker.update({
        status: 'done',
        statusText: '🟢 本轮完成 · 总耗时 2m 15s',
        round: 7,
        elapsed: 135,
        quietRounds: 0,
        target: 'trigger',
        summary: 'Bullet 已生成最终成果，Trigger 确认交付物完整无误，会话已恢复空闲就绪',
        tokens: '152.0K',
        tokensDelta: '+3.8K',
      });
      ticker.setCountdown(0);
    });

    document.getElementById('btn-state-interrupt').addEventListener('click', () => {
      ticker.onInterrupt();
    });
  }


  // === 9. Progress Feed Sandbox ===
  function initFeedSandbox() {
    controls.innerHTML = `
      <div class="dt-control-title">🎮 轮询进展消息流控制台（模拟纵向追加各类轮询进展与状态事件）</div>
      <div class="dt-control-actions">
        <button type="button" class="dt-btn dt-btn-ghost dt-btn-sm" id="btn-feed-dispatch">🚀 派发任务</button>
        <button type="button" class="dt-btn dt-btn-primary dt-btn-sm" id="btn-feed-growth">✨ 追加有效增长 (#)</button>
        <button type="button" class="dt-btn dt-btn-ghost dt-btn-sm" id="btn-feed-quiet">⏳ 追加静默无变化</button>
        <button type="button" class="dt-btn dt-btn-ghost dt-btn-sm" id="btn-feed-alert">⚠️ 追加停滞告警 (5/8)</button>
        <button type="button" class="dt-btn dt-btn-ghost dt-btn-sm" id="btn-feed-done">✅ 追加本轮达成</button>
        <button type="button" class="dt-btn dt-btn-danger dt-btn-sm" id="btn-feed-interrupt">🛑 追加打断事件</button>
        <button type="button" class="dt-btn dt-btn-ghost dt-btn-sm" id="btn-feed-batch">⚡ 模拟完整 5 轮演进流</button>
      </div>
      <div style="font-size:11.5px; color:var(--dt-text-muted); margin-top:4px;">
        💡 <b>测试指引</b>：点击不同按钮向下方列表纵向追加带有时间戳、耗时、Token变化与结构化摘要的消息卡片；支持顶部分类筛选（有效增长、静默、告警）与自动吸底跟随控制。
      </div>
    `;

    const feed = new ProgressFeedComponent({
      container: stage,
      maxItems: 100
    });
    feed.render();

    let roundCounter = 1;
    let totalElapsed = 0;
    let quietCounter = 0;
    let tokenBase = 142000;

    // 默认初始装载几条真实数据
    feed.addMessage({
      kind: 'dispatch',
      round: 1,
      target: 'trigger',
      summary: 'Trigger 收到用户指令，整理为 Bullet 任务卡片并注入 run_* 窗格：npm run test:e2e',
      elapsed: 2,
      nextCheck: '15s 后',
    });

    feed.addMessage({
      kind: 'evidence',
      round: 2,
      target: 'bullet',
      summary: '检测到有效增长：Bullet 正在加载测试套件 (已发现 14 个测试文件，启动 Jest worker)',
      elapsed: 17,
      tokens: '143.5K',
      tokensDelta: '+1.5K',
      nextCheck: '20s 后',
    });

    feed.addMessage({
      kind: 'quiet',
      round: 3,
      target: 'bullet',
      summary: 'Token 与输出内容平滞：Jest worker 正在执行重型浏览器端对端渲染，无新控制台行输出',
      elapsed: 37,
      tokens: '143.5K',
      tokensDelta: '+0',
      quietCount: 1,
      nextCheck: '25s 后',
    });

    roundCounter = 4;
    totalElapsed = 37;

    document.getElementById('btn-feed-dispatch').addEventListener('click', () => {
      feed.addMessage({
        kind: 'dispatch',
        round: ++roundCounter,
        target: 'trigger',
        summary: 'Trigger 下发指令：重新运行失败项 pytest tests/test_activity.py',
        elapsed: (totalElapsed += 5),
        nextCheck: '15s 后',
      });
    });

    document.getElementById('btn-feed-growth').addEventListener('click', () => {
      quietCounter = 0;
      tokenBase += 1800;
      feed.addMessage({
        kind: 'evidence',
        round: ++roundCounter,
        target: 'bullet',
        summary: '检测到有效增长：pytest 执行完成 5 项通过，正在生成 coverage 报告 (stdout 增长 48 行)...',
        elapsed: (totalElapsed += 15),
        tokens: (tokenBase / 1000).toFixed(1) + 'K',
        tokensDelta: '+1.8K',
        nextCheck: '20s 后',
      });
    });

    document.getElementById('btn-feed-quiet').addEventListener('click', () => {
      quietCounter++;
      feed.addMessage({
        kind: 'quiet',
        round: ++roundCounter,
        target: 'bullet',
        summary: '指纹与输出无变化：Bullet 进程占用保持平稳，等待下一次采样比对...',
        elapsed: (totalElapsed += 20),
        tokens: (tokenBase / 1000).toFixed(1) + 'K',
        tokensDelta: '+0',
        quietCount: quietCounter,
        nextCheck: '20s 后',
      });
    });

    document.getElementById('btn-feed-alert').addEventListener('click', () => {
      quietCounter = 5;
      feed.addMessage({
        kind: 'alert',
        round: ++roundCounter,
        target: 'bullet',
        summary: '⚠️ 连续 5 轮未检测到有效证据增长！请注意 Bullet 可能遇到大模型 Cooldown、死锁或后台等待授权。',
        elapsed: (totalElapsed += 25),
        tokens: (tokenBase / 1000).toFixed(1) + 'K',
        tokensDelta: '+0',
        quietCount: 5,
        nextCheck: '10s 后 (加频探针)',
      });
    });

    document.getElementById('btn-feed-done').addEventListener('click', () => {
      feed.addMessage({
        kind: 'done',
        round: ++roundCounter,
        target: 'trigger',
        summary: '✅ 任务完成：Bullet 交付完整代码并由 Trigger 校验通过，退出轮询循环，恢复空闲。',
        elapsed: (totalElapsed += 12),
        tokens: ((tokenBase + 2400) / 1000).toFixed(1) + 'K',
        tokensDelta: '+2.4K',
        nextCheck: '已结束',
      });
    });

    document.getElementById('btn-feed-interrupt').addEventListener('click', () => {
      feed.addMessage({
        kind: 'interrupt',
        round: roundCounter,
        target: 'trigger',
        summary: '🛑 用户在 Web 发送中断信号 (Ctrl+C / Escape)，轮询流程已安全中止。',
        elapsed: totalElapsed,
        nextCheck: '已中止',
      });
    });

    document.getElementById('btn-feed-batch').addEventListener('click', () => {
      feed.clear();
      roundCounter = 1;
      totalElapsed = 0;
      tokenBase = 140000;
      const steps = [
        { kind: 'dispatch', text: 'Trigger 派发长任务：构建 wheel 包并运行端到端验收用例', delay: 300 },
        { kind: 'evidence', text: 'Bullet 开始构建 hatchling wheel (uv build)', delay: 1000 },
        { kind: 'quiet', text: '编译缓存命中，轮询比对指纹无新行 (1/8 轮)', delay: 1800 },
        { kind: 'evidence', text: '启动 pytest 测试套件，468 tests 全部通过 (通过 100%)', delay: 2600 },
        { kind: 'done', text: '全部产物生成并经过验证，Trigger 记录并结束本轮轮询', delay: 3400 }
      ];
      steps.forEach((s, idx) => {
        setTimeout(() => {
          tokenBase += (s.kind === 'evidence' ? 2200 : (s.kind === 'done' ? 1500 : 0));
          feed.addMessage({
            kind: s.kind,
            round: idx + 1,
            target: s.kind === 'dispatch' || s.kind === 'done' ? 'trigger' : 'bullet',
            summary: s.text,
            elapsed: (idx + 1) * 15,
            tokens: (tokenBase / 1000).toFixed(1) + 'K',
            tokensDelta: s.kind === 'evidence' ? '+2.2K' : '',
            quietCount: s.kind === 'quiet' ? 1 : 0,
            nextCheck: idx === steps.length - 1 ? '已结束' : '15s 后'
          });
        }, s.delay);
      });
    });
  }

})();
