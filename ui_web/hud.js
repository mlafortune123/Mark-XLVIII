(() => {
  'use strict';

  const $ = (sel) => document.querySelector(sel);

  const els = {
    clock: $('#clock'), date: $('#date'),
    head: $('#head'), statusLine: $('#statusLine'),
    headZone: $('#headZone'),
    rightColumn: $('#rightColumn'), chevronTab: $('#chevronTab'),
    statsList: $('#statsList'),
    kvUptime: $('#kvUptime'), kvProc: $('#kvProc'), kvOs: $('#kvOs'),
    logList: $('#logList'),
    draftInput: $('#draftInput'), sendBtn: $('#sendBtn'),
    muteBtn: $('#muteBtn'), interruptBtn: $('#interruptBtn'), remoteBtn: $('#remoteBtn'),
    attachBtn: $('#attachBtn'), prefsBtn: $('#prefsBtn'),
    micLabel: $('#micLabel'), dropHint: $('#dropHint'),
  };

  const state = {
    muted: false,
    rightOpen: true,
    activity: 'idle',
    log: [],
  };

  const STAT_META = {
    CPU: { color: '#4fd8ff' },
    MEM: { color: '#4fd8ff', warnColor: '#ffb454' },
    NET: { color: '#4fd8ff' },
    GPU: { color: '#4fd8ff' },
    TMP: { color: '#4fd8ff' },
  };

  const WHO_CLASS = { SYS: 'who-sys', YOU: 'who-you', JARVIS: 'who-jarvis' };

  // ---- clock ----
  function tickClock() {
    const now = new Date();
    const p2 = (n) => String(n).padStart(2, '0');
    els.clock.textContent = `${p2(now.getHours())}:${p2(now.getMinutes())}:${p2(now.getSeconds())}`;
    els.date.textContent = now.toDateString().toUpperCase();
  }
  tickClock();
  setInterval(tickClock, 1000);

  // ---- log ----
  function appendLog(who, text) {
    const entry = document.createElement('div');
    entry.className = 'log-entry';
    const whoEl = document.createElement('span');
    whoEl.className = `log-who mono ${WHO_CLASS[who] || 'who-you'}`;
    whoEl.textContent = who;
    const textEl = document.createElement('span');
    textEl.className = 'log-text';
    textEl.textContent = text;
    entry.appendChild(whoEl);
    entry.appendChild(textEl);
    els.logList.appendChild(entry);
    els.logList.scrollTop = els.logList.scrollHeight;
    // cap history so the DOM doesn't grow unbounded over a long session
    while (els.logList.children.length > 300) {
      els.logList.removeChild(els.logList.firstChild);
    }
  }

  // ---- state / activity ----
  function applyState(rawState) {
    const s = (rawState || '').toUpperCase();
    let activity = 'idle';
    if (s === 'SPEAKING') activity = 'speaking';
    else if (s === 'LISTENING' || s === 'THINKING') activity = 'listening';
    else activity = 'idle';
    state.activity = activity;
    renderActivity();
  }

  function renderActivity() {
    els.head.setAttribute('activity', state.activity);
    let statusLine;
    if (state.muted) statusLine = 'STANDBY — MIC MUTED';
    else if (state.activity === 'speaking') statusLine = 'RESPONDING';
    else if (state.activity === 'listening') statusLine = 'LISTENING';
    else statusLine = 'STANDBY';
    els.statusLine.textContent = statusLine;
  }

  function applyMuted(muted) {
    state.muted = muted;
    els.muteBtn.classList.toggle('muted', muted);
    els.micLabel.textContent = muted ? 'MIC MUTED' : 'MIC LIVE';
    renderActivity();
  }

  // ---- stats ----
  function renderStats(stats) {
    els.statsList.innerHTML = '';
    (stats || []).filter((s) => !s.na).forEach((s) => {
      const meta = STAT_META[s.label] || {};
      const color = s.warn ? (meta.warnColor || '#ffb454') : meta.color;
      const row = document.createElement('div');
      row.className = 'stat-row';
      row.innerHTML = `
        <div class="stat-head">
          <span class="stat-label mono">${s.label}</span>
          <span class="stat-val mono" style="color:${color}">${s.value}</span>
        </div>
        <div class="stat-bar-track">
          <div class="stat-bar-fill" style="width:${s.pct || 0}%;background:${color};box-shadow:0 0 8px ${color}"></div>
        </div>`;
      els.statsList.appendChild(row);
    });
  }

  function applyMetrics(m) {
    if (!m) return;
    if (typeof m === 'string') {
      try { m = JSON.parse(m); } catch (e) { return; }
    }
    renderStats(m.stats || []);
    if (m.uptime != null) els.kvUptime.textContent = m.uptime;
    if (m.proc != null) els.kvProc.textContent = m.proc;
    if (m.os != null) els.kvOs.textContent = m.os;
  }

  // ---- right column collapse ----
  function toggleRight() {
    state.rightOpen = !state.rightOpen;
    els.rightColumn.classList.toggle('collapsed', !state.rightOpen);
    els.headZone.classList.toggle('right-collapsed', !state.rightOpen);
    els.chevronTab.textContent = state.rightOpen ? '›' : '‹';
  }
  els.chevronTab.addEventListener('click', toggleRight);

  // ---- bridge wiring ----
  let bridge = null;

  function send() {
    const text = els.draftInput.value.trim();
    if (!text) return;
    els.draftInput.value = '';
    if (bridge) bridge.sendText(text);
    else appendLog('YOU', text); // browser-preview fallback, no Python backing
  }
  els.sendBtn.addEventListener('click', send);
  els.draftInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') send();
  });

  els.muteBtn.addEventListener('click', () => {
    if (bridge) bridge.toggleMute();
    else applyMuted(!state.muted);
  });
  els.interruptBtn.addEventListener('click', () => { if (bridge) bridge.clickInterrupt(); });
  els.remoteBtn.addEventListener('click', () => { if (bridge) bridge.clickRemote(); });
  els.attachBtn.addEventListener('click', () => { if (bridge) bridge.requestFileDialog(); });
  els.prefsBtn.addEventListener('click', () => { if (bridge) bridge.openPreferences(); });

  // native drag-over visual cue (the native _DropOverlay handles the actual drop;
  // this is just an in-page tint so the page doesn't look dead during a drag)
  ['dragenter', 'dragover'].forEach((evt) => {
    window.addEventListener(evt, (e) => { e.preventDefault(); els.dropHint.classList.add('active'); });
  });
  ['dragleave', 'drop'].forEach((evt) => {
    window.addEventListener(evt, (e) => { e.preventDefault(); els.dropHint.classList.remove('active'); });
  });

  function connectBridge() {
    if (typeof QWebChannel === 'undefined' || typeof qt === 'undefined' || !qt.webChannelTransport) {
      console.warn('QWebChannel unavailable — running in standalone preview mode with dummy data.');
      runPreviewMode();
      return;
    }
    new QWebChannel(qt.webChannelTransport, (channel) => {
      bridge = channel.objects.bridge;
      bridge.logAppended.connect(appendLog);
      bridge.stateChanged.connect(applyState);
      bridge.mutedChanged.connect(applyMuted);
      bridge.statsUpdated.connect(applyMetrics);
      bridge.remoteConnected.connect(() => els.remoteBtn.classList.add('connected'));
      bridge.requestSync();
    });
  }

  // ---- keyboard shortcuts ----
  // QShortcut on the native MainWindow is unreliable once a QWebEngineView
  // owns keyboard focus (a known Chromium-embedding quirk), so these are
  // handled here instead and forwarded to the bridge.
  window.addEventListener('keydown', (e) => {
    if (!bridge) return;
    if (e.key === 'F4') { e.preventDefault(); bridge.toggleMute(); }
    else if (e.key === 'F11') { e.preventDefault(); bridge.toggleFullscreen(); }
    else if (e.key === 'Escape') { e.preventDefault(); bridge.clickInterrupt(); }
    else if (e.ctrlKey && e.shiftKey && (e.key === 'F' || e.key === 'f')) { e.preventDefault(); bridge.showFontDebug(); }
  });

  // ---- standalone preview mode (opened directly in a browser, no Qt backing) ----
  function runPreviewMode() {
    applyMuted(false);
    applyState('LISTENING');
    appendLog('SYS', 'JARVIS online. All subsystems nominal.');
    appendLog('JARVIS', "Hello, sir. I'm here for whatever you need. What's on your mind?");
    let cpu = 28, mem = 79, net = 884, up = 0;
    setInterval(() => {
      up += 1;
      cpu = Math.max(4, Math.min(96, cpu + (Math.random() - 0.5) * 6));
      mem = Math.max(40, Math.min(92, mem + (Math.random() - 0.5) * 2));
      net = Math.max(20, Math.min(2000, net + (Math.random() - 0.5) * 180));
      const p2 = (n) => String(n).padStart(2, '0');
      applyMetrics({
        stats: [
          { label: 'CPU', value: Math.round(cpu) + '%', pct: cpu },
          { label: 'MEM', value: Math.round(mem) + '%', pct: mem, warn: mem > 75 },
          { label: 'NET', value: Math.round(net) + ' KB/s', pct: Math.min(100, net / 20) },
          { label: 'GPU', value: 'N/A', pct: 0, na: true },
          { label: 'TMP', value: 'N/A', pct: 0, na: true },
        ],
        uptime: `${p2((up / 60) | 0)}:${p2(up % 60)}`,
        proc: '587',
        os: 'macOS',
      });
    }, 1000);
  }

  connectBridge();
})();
