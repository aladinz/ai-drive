/* ============================================================
  Aladdin AI — app.js
  Clean, modern, stable WebUI logic
  Endpoint: OpenAI-compatible local API
============================================================ */

const API_URL = "/v1/chat/completions";
const MAX_REQUEST_MESSAGES = 6;
const MAX_REQUEST_CHARS = 2800;
const DEFAULT_MAX_TOKENS = 2048;
const DEFAULT_TEMPERATURE = 0.7;
const MAX_REQUEST_EST_TOKENS = 900;
const CONTEXT_RETRY_RESERVE_TOKENS = 700;
const MODELS_URL = "/v1/models";
let activeModelId = "local-model";

const MODEL_NAME_BY_ID = {
  "qwen2.5-coder-7b-instruct-q4_k_m.gguf": "Qwen 2.5 Coder 7B",
  "Llama-3.1-8B-Lexi-Uncensored-V2-Q6_K.gguf": "Llama 3.1 8B Lexi",
  "DarkIdol-Llama-3.1-8B-Instruct-1.2-Uncensored.Q4_K_M.gguf": "DarkIdol Llama 3.1 8B",
  "L3.1-RP-Hero-BigTalker-8B-D_AU-Q4_k_m.gguf": "L3.1-RP-Hero-BigTalker 8B",
  "L3.1-RP-Hero-Dirty_Harry-8B-D_AU-Q4_k_m.gguf": "L3.1-RP-Hero-Dirty_Harry 8B",
  "Llama-3.1-128k-Dark-Planet-Uncensored-8B-Q4_k_m.gguf": "Dark Planet 8B"
};

let chats = JSON.parse(localStorage.getItem("aladdin_chats") || "{}");
let currentChatId = null;
let abortController = null;
let showPassOnly = false;

/* ============================================================
   DOM Elements
============================================================ */
const chatList = document.getElementById("chat-list");
const chatLog = document.getElementById("chat-log");
const chatInput = document.getElementById("chat-input");
const sendButton = document.getElementById("send-button");
const stopButton = document.getElementById("stop-button");
const sidebarToggle = document.getElementById("sidebar-toggle");
const newChatButton = document.getElementById("new-chat-button");
const clearChatButton = document.getElementById("clear-chat-button");
const voiceInputButton = document.getElementById("voice-input-button");
const ttsToggleButton = document.getElementById("tts-toggle-button");
const voiceSelect = document.getElementById("voice-select");
const VOICE_STORAGE_KEY = "aladdin_voice";

if (voiceSelect) {
  const savedVoice = localStorage.getItem(VOICE_STORAGE_KEY);
  if (savedVoice && [...voiceSelect.options].some(option => option.value === savedVoice)) {
    voiceSelect.value = savedVoice;
  }
  voiceSelect.addEventListener("change", () => {
    localStorage.setItem(VOICE_STORAGE_KEY, voiceSelect.value);
  });
}
const statusDot = document.getElementById("status-dot");
const statusText = document.getElementById("status-text");
const modelName = document.getElementById("model-name");
const passFilterButton = document.getElementById("pass-filter-button");

if (passFilterButton) {
  passFilterButton.addEventListener("click", () => {
    showPassOnly = !showPassOnly;
    passFilterButton.classList.toggle("active", showPassOnly);
    passFilterButton.textContent = showPassOnly ? "Show all" : "Show PASS only";
    if (currentChatId) renderMessages();
    renderScanTable();
  });
}

/* ============================================================
   Multi-ticker scan
============================================================ */
const tickerInput = document.getElementById("tickerInput");
const scanButton = document.getElementById("scan-button");
let scanResults = [];
let scanFilter = "all";
let scanTotal = 0;
const scanExpanded = new Set();
const scanLoading = new Set();

function parseTickers(input) {
  const seen = new Set();
  return input.toUpperCase()
    .split(/[,\s\n]+/)
    .map(s => s.trim())
    .filter(s => s.length > 0 && s.length <= 5 && !seen.has(s) && seen.add(s));
}

function scanSort(a, b) {
  return (b.qualified - a.qualified) || (b.passed - a.passed);
}

function scanRowHtml(r) {
  const ok = r.status === "PASS";
  const err = r.status === "ERROR";
  const badge = err
    ? `<span class="qual FAIL">! ERROR</span>`
    : `<span class="qual ${ok ? "PASS" : "FAIL"}">${ok ? "✓" : "✗"} ${escapeHtml(r.score)}</span>`;
  const pct = typeof r.stop_pct === "number" ? `${r.stop_pct.toFixed(2)}%` : "n/a";
  const rr = typeof r.rr_t1 === "number" ? `${r.rr_t1.toFixed(2)}R` : "n/a";
  const time = typeof r.elapsed === "number" ? `${r.elapsed.toFixed(1)}s` : "—";
  const expandable = ok && r.trade_setup;
  const open = expandable && scanExpanded.has(r.ticker);
  const row = `<tr class="${ok ? "scan-pass" : "scan-fail"}${expandable ? " scan-clickable" : ""}" data-ticker="${escapeHtml(r.ticker)}">
    <td><strong>${expandable ? (open ? "▾ " : "▸ ") : ""}${escapeHtml(r.ticker)}</strong></td>
    <td>${badge}</td>
    <td>${escapeHtml(r.score)}</td>
    <td>${pct}</td>
    <td>${rr}</td>
    <td>${r.reason ? escapeHtml(r.reason) : "-"}</td>
    <td>${time}</td>
  </tr>`;
  return open ? row + `<tr class="scan-detail"><td colspan="7">${tradeCardHtml(r)}</td></tr>` : row;
}

function money(v) {
  return typeof v === "number" ? `$${v.toFixed(2)}` : "n/a";
}

function tradeCardHtml(r) {
  const t = r.trade_setup;
  const account = parseFloat(document.getElementById("scan-account")?.value) || 0;
  const riskPct = parseFloat(document.getElementById("scan-risk")?.value) || 1;
  const perShare = t.entry - t.stop;
  const shares = account > 0 && perShare > 0 ? Math.floor((account * riskPct / 100) / perShare) : 0;
  const taken = loadTrades().some(x => x.ticker === r.ticker && x.date === todayKey());
  const chart = `https://s.tradingview.com/widgetembed/?symbol=${encodeURIComponent(r.ticker)}&interval=D&theme=dark&hidesidetoolbar=1&style=1`;
  const rr = v => (typeof v === "number" ? `${v.toFixed(2)}R` : "n/a");
  const gain = v => (typeof v === "number" ? `${((v / t.entry - 1) * 100).toFixed(1)}%` : "");
  const warn = (t.warnings || []).map(w => `<div class="trade-warn">⚠ ${escapeHtml(w)}</div>`).join("");
  const loading = scanLoading.has(r.ticker) ? "loading…" : "n/a";
  const conf = typeof t.confidence === "number" ? `${t.confidence}%` : loading;
  const checks = (r.checks || []).map(c =>
    `<span class="trade-check ${c.pass ? "ok" : "bad"}" title="${escapeHtml(c.reason)}">${c.pass ? "✓" : "✗"} ${escapeHtml(c.name)}</span>`
  ).join("");
  return `<div class="trade-card">
    <div class="trade-levels">
      <span>Entry <b>${money(t.entry)}</b></span>
      <span>Stop <b>${money(t.stop)}</b> (-${t.stop_pct.toFixed(2)}%)</span>
      <span>Target 1 <b>${money(t.target1)}</b> (+${gain(t.target1)}, ${rr(t.rr_t1)})</span>
      <span>Target 2 <b>${money(t.target2)}</b> (+${gain(t.target2)}, ${rr(t.rr_t2)})</span>
    </div>
    <div>Setup: <b>${escapeHtml(t.setup_type)}</b> | Confidence: ${conf} | Timeframe: ${escapeHtml(t.timeframe || loading)}</div>
    <div>Rationale: ${escapeHtml(t.rationale || loading)}</div>
    <div>Invalidation: ${escapeHtml(t.invalidation || `Close below ${money(t.stop)}`)}</div>
    <div>Risk Calculator: Account $${account.toLocaleString()} x ${riskPct}% = $${(account * riskPct / 100).toFixed(0)} risk => <b>${shares}</b> shares ($${(shares * t.entry).toLocaleString(undefined, { maximumFractionDigits: 0 })})</div>
    <label class="trade-taken"><input type="checkbox" data-taken="${escapeHtml(r.ticker)}" ${taken ? "checked" : ""}> Taken (save to journal)</label>
    <div class="trade-checks">${checks}</div>
    ${warn}
    <iframe class="trade-chart" src="${chart}" loading="lazy" title="${escapeHtml(r.ticker)} chart"></iframe>
  </div>`;
}

const TRADES_KEY = "trades.json";
function todayKey() { return new Date().toISOString().slice(0, 10); }
function loadTrades() {
  try { return JSON.parse(localStorage.getItem(TRADES_KEY)) || []; } catch (e) { return []; }
}
function setTaken(ticker, on) {
  const row = scanResults.find(r => r.ticker === ticker);
  let trades = loadTrades().filter(x => !(x.ticker === ticker && x.date === todayKey()));
  if (on && row && row.trade_setup) {
    const t = row.trade_setup;
    const account = parseFloat(document.getElementById("scan-account")?.value) || 0;
    const riskPct = parseFloat(document.getElementById("scan-risk")?.value) || 1;
    const shares = t.entry > t.stop ? Math.floor((account * riskPct / 100) / (t.entry - t.stop)) : 0;
    trades.push({
      date: todayKey(), ticker, score: row.score, setup_type: t.setup_type,
      entry: t.entry, stop: t.stop, target1: t.target1, target2: t.target2,
      rr_t1: t.rr_t1, shares, account, risk_pct: riskPct
    });
  }
  localStorage.setItem(TRADES_KEY, JSON.stringify(trades));
}

function downloadFile(name, text, type) {
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([text], { type }));
  a.download = name;
  a.click();
  URL.revokeObjectURL(a.href);
}

function exportWatchlistCsv() {
  const q = scanResults.filter(r => r.status === "PASS" && r.trade_setup);
  const rows = [["Ticker", "Score", "Setup", "Entry", "Stop", "Stop%", "Target1", "Target2", "R/R T1", "Warnings"]];
  q.forEach(r => {
    const t = r.trade_setup;
    rows.push([r.ticker, r.score, t.setup_type, t.entry.toFixed(2), t.stop.toFixed(2), t.stop_pct.toFixed(2),
      t.target1.toFixed(2), t.target2.toFixed(2), t.rr_t1.toFixed(2), (t.warnings || []).join(" | ")]);
  });
  const csv = rows.map(r => r.map(c => `"${String(c).replace(/"/g, '""')}"`).join(",")).join("\n");
  downloadFile(`watchlist-${todayKey()}.csv`, csv, "text/csv");
}

function scanSummaryText() {
  if (!scanResults.length) return "";
  const n = scanResults.length;
  const by = s => scanResults.filter(r => r.score === s && r.status === "PASS").length;
  const parts = [];
  const perfect = by("8/8"), seven = by("7/8"), six = by("6/8");
  const fail = scanResults.filter(r => r.status !== "PASS").length;
  if (perfect) parts.push(`${perfect} Perfect 8/8`);
  if (seven) parts.push(`${seven} 7/8`);
  if (six) parts.push(`${six} 6/8`);
  if (fail) parts.push(`${fail} FAIL`);
  const total = scanResults.reduce((s, r) => s + (r.elapsed || 0), 0);
  return `Scanned ${n}/${scanTotal || n} - ${parts.join(", ")} - ${total.toFixed(1)}s total`;
}

async function loadSetupNotes(ticker) {
  const row = scanResults.find(r => r.ticker === ticker);
  if (!row || !row.trade_setup || row.trade_setup.rationale || scanLoading.has(ticker)) return;
  scanLoading.add(ticker);
  renderScanTable();
  try {
    const res = await fetch("/api/setup", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ticker })
    });
    const data = await res.json();
    if (res.ok && data.trade_setup) row.trade_setup = data.trade_setup;
  } catch (err) { /* keep the code-computed setup */ }
  scanLoading.delete(ticker);
  renderScanTable();
}

function renderScanTable() {
  const table = document.getElementById("scan-table");
  const body = document.getElementById("scan-body");
  if (!table || !body) return;
  const rows = scanResults.filter(r =>
    !(showPassOnly && r.status !== "PASS") &&
    !(scanFilter === "qual" && r.status !== "PASS") &&
    !(scanFilter === "perfect" && r.score !== "8/8"));
  table.style.display = scanResults.length ? "" : "none";
  body.innerHTML = rows.map(scanRowHtml).join("");
  const summary = document.getElementById("scan-summary");
  if (summary) summary.textContent = scanSummaryText();
}

const scanFilters = document.getElementById("scan-filters");
if (scanFilters) {
  scanFilters.addEventListener("click", e => {
    const btn = e.target.closest("button");
    if (!btn) return;
    if (btn.dataset.filter) {
      scanFilter = btn.dataset.filter;
      scanFilters.querySelectorAll("[data-filter]").forEach(b => b.classList.toggle("active", b === btn));
      renderScanTable();
    } else if (btn.id === "scan-export") {
      exportWatchlistCsv();
    } else if (btn.id === "scan-journal-export") {
      downloadFile("trades.json", JSON.stringify(loadTrades(), null, 2), "application/json");
    }
  });
}

const scanRisk = document.getElementById("scan-risk");
if (scanRisk) scanRisk.addEventListener("input", renderScanTable);

const scanBodyEl = document.getElementById("scan-body");
if (scanBodyEl) {
  scanBodyEl.addEventListener("change", e => {
    const box = e.target.closest("input[data-taken]");
    if (box) setTaken(box.dataset.taken, box.checked);
  });
}

const scanBody = document.getElementById("scan-body");
if (scanBody) {
  scanBody.addEventListener("click", e => {
    const tr = e.target.closest("tr.scan-clickable");
    if (!tr) return;
    const ticker = tr.dataset.ticker;
    if (scanExpanded.has(ticker)) scanExpanded.delete(ticker);
    else { scanExpanded.add(ticker); loadSetupNotes(ticker); }
    renderScanTable();
  });
}

const scanAccount = document.getElementById("scan-account");
if (scanAccount) {
  scanAccount.value = localStorage.getItem("scanAccount") || scanAccount.value;
  scanAccount.addEventListener("input", () => {
    localStorage.setItem("scanAccount", scanAccount.value);
    renderScanTable();
  });
}

function setScanProgress(done, total, active) {
  const box = document.getElementById("scan-progress");
  box.style.display = "";
  document.getElementById("scan-progress-fill").style.width = `${total ? (done / total) * 100 : 0}%`;
  document.getElementById("scan-progress-text").textContent =
    active ? `Scanning ${Math.min(done + 1, total)}/${total}...` : `Scanned ${done}/${total}`;
}

const setMode = document.getElementById("set-mode");
const setFixed = document.getElementById("set-fixed");
const setAtr = document.getElementById("set-atr");

function syncSettingsUi() {
  document.getElementById("set-fixed-val").textContent = Number(setFixed.value).toFixed(1);
  document.getElementById("set-atr-val").textContent = Number(setAtr.value).toFixed(1);
  document.getElementById("set-fixed-wrap").style.display = setMode.value === "fixed" ? "" : "none";
  document.getElementById("set-atr-wrap").style.display = setMode.value === "atr" ? "" : "none";
}

let settingsTimer = null;
function saveScanSettings() {
  syncSettingsUi();
  clearTimeout(settingsTimer);
  settingsTimer = setTimeout(async () => {
    try {
      await fetch("/api/settings", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          stop_mode: setMode.value,
          stop_fixed_pct: parseFloat(setFixed.value),
          atr_mult: parseFloat(setAtr.value)
        })
      });
      if (scanResults.length && !scanButton.disabled) runScan(scanResults.map(r => r.ticker));
    } catch (err) { /* ignore */ }
  }, 500);
}

if (setMode && setFixed && setAtr) {
  fetch("/api/settings").then(r => r.json()).then(s => {
    setMode.value = s.stop_mode;
    setFixed.value = s.stop_fixed_pct;
    setAtr.value = s.atr_mult;
    syncSettingsUi();
  }).catch(syncSettingsUi);
  [setMode, setFixed, setAtr].forEach(el => el.addEventListener("input", saveScanSettings));
}

async function runScan(tickerList) {
  const tickers = Array.isArray(tickerList) ? tickerList : parseTickers(tickerInput.value);
  if (!tickers.length || scanButton.disabled) return;
  scanButton.disabled = true;
  scanTotal = tickers.length;
  scanResults = [];
  renderScanTable();
  for (let i = 0; i < tickers.length; i++) {
    setScanProgress(i, tickers.length, true);
    let row;
    try {
      const res = await fetch("/api/check", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ticker: tickers[i] })
      });
      row = await res.json();
      if (!res.ok) row = { ticker: tickers[i], status: "ERROR", score: "0/8", passed: 0, qualified: false, reason: row.error || `HTTP ${res.status}` };
    } catch (err) {
      row = { ticker: tickers[i], status: "ERROR", score: "0/8", passed: 0, qualified: false, reason: String(err) };
    }
    scanResults.push(row);
    renderScanTable();
  }
  scanResults.sort(scanSort);
  renderScanTable();
  setScanProgress(tickers.length, tickers.length, false);
  scanButton.disabled = false;
}

if (scanButton && tickerInput) {
  scanButton.addEventListener("click", () => runScan());
  tickerInput.addEventListener("keydown", e => {
    if (e.key === "Enter") { e.preventDefault(); runScan(); }
  });
}

const MAX_RECORDING_MS = 6000;
let mediaRecorder = null;
let mediaStream = null;
let mediaChunks = [];
let isListening = false;
let ttsEnabled = localStorage.getItem("aladdin_tts_enabled") !== "0";
let recordingTimeout = null;
let currentTtsAudio = null;
let currentTtsUrl = null;

/* ============================================================
   Utility
============================================================ */
function setMicStatus(msg, type) {
  const bar = document.getElementById("mic-status-bar");
  if (!bar) return;
  if (!msg) { bar.style.display = "none"; bar.textContent = ""; return; }
  bar.style.display = "block";
  bar.textContent = msg;
  bar.style.color = type === "error" ? "#ff4b6a" : type === "ok" ? "#3dd68c" : "#f5c84b";
  if (type !== "error") {
    setTimeout(() => { if (bar.textContent === msg) { bar.style.display = "none"; } }, 4000);
  }
}

function uuid() {
  return Math.random().toString(36).substring(2, 10);
}

function saveChats() {
  localStorage.setItem("aladdin_chats", JSON.stringify(chats));
}

function scrollToBottom() {
  chatLog.scrollTop = chatLog.scrollHeight;
}

function setStatus(state) {
  if (state === "thinking") {
    statusDot.style.background = "#f5c84b";
    statusText.textContent = "Thinking";
  } else if (state === "streaming") {
    statusDot.style.background = "#3dd68c";
    statusText.textContent = "Responding";
  } else {
    statusDot.style.background = "#3dd68c";
    statusText.textContent = "Idle";
  }
}

function updateVoiceButtons() {
  if (voiceInputButton) {
    voiceInputButton.classList.toggle("active", isListening);
    voiceInputButton.title = isListening ? "Recording... click to stop" : "Voice input";
  }

  if (ttsToggleButton) {
    ttsToggleButton.classList.toggle("active", ttsEnabled);
    ttsToggleButton.textContent = ttsEnabled ? "🔊" : "🔈";
    ttsToggleButton.title = ttsEnabled ? "Voice replies: On" : "Voice replies: Off";
  }
}

function normalizeSpeechText(text) {
  return (text || "")
    .replace(/```[\s\S]*?```/g, " ")
    .replace(/`([^`]*)`/g, "$1")
    .replace(/!?\[([^\]]*)\]\([^)]*\)/g, "$1")
    .replace(/https?:\/\/\S+/g, " ")
    .replace(/^\s{0,3}(#{1,6}|>|[-*+]|\d+[.)])\s+/gm, "")
    .replace(/^\s*\|?[\s:|-]{3,}\|?\s*$/gm, " ")
    .replace(/\|/g, ", ")
    .replace(/[*_~#]+/g, "")
    .replace(/[\u{1F000}-\u{1FAFF}\u{2600}-\u{27BF}\uFE0F\u200D]/gu, "")
    .replace(/\s+/g, " ")
    .trim();
}

let audioWakeContext = null;

function warmupAudioPipeline() {
  if (!ttsEnabled) return;
  try {
    if (!audioWakeContext) {
      const AudioCtx = window.AudioContext || window.webkitAudioContext;
      if (AudioCtx) {
        audioWakeContext = new AudioCtx();
      }
    }
    if (audioWakeContext && audioWakeContext.state === "suspended") {
      audioWakeContext.resume().catch(() => {});
    }
    if (audioWakeContext && audioWakeContext.state === "running") {
      const buf = audioWakeContext.createBuffer(1, Math.round(audioWakeContext.sampleRate * 0.1), audioWakeContext.sampleRate);
      const src = audioWakeContext.createBufferSource();
      src.buffer = buf;
      src.connect(audioWakeContext.destination);
      src.start();
    }
  } catch {
    // Non-fatal audio warm-up
  }
}

function stopTtsPlayback() {
  if (currentTtsAudio) {
    currentTtsAudio.pause();
    currentTtsAudio = null;
  }
  if (currentTtsUrl) {
    URL.revokeObjectURL(currentTtsUrl);
    currentTtsUrl = null;
  }
}

async function speakReply(text) {
  if (!ttsEnabled || !text) return;

  const spokenText = normalizeSpeechText(text);
  if (!spokenText) return;

  warmupAudioPipeline();

  try {
    const audioBlob = await window.VoiceBox.speakText(spokenText, voiceSelect?.value);
    if (!ttsEnabled) return;
    warmupAudioPipeline();
    stopTtsPlayback();
    currentTtsUrl = URL.createObjectURL(audioBlob);
    currentTtsAudio = new Audio(currentTtsUrl);
    currentTtsAudio.addEventListener("ended", stopTtsPlayback, { once: true });
    await currentTtsAudio.play();
  } catch (error) {
    setMicStatus(`Voice reply failed: ${error.message || "VoiceBox request failed"}`, "error");
  }
}

function setupVoiceInput() {
  if (!voiceInputButton) return;

  if (!window.MediaRecorder || !navigator.mediaDevices?.getUserMedia) {
    voiceInputButton.disabled = true;
    voiceInputButton.title = "Voice input is unavailable in this browser.";
    return;
  }

  voiceInputButton.onclick = async () => {
    try {
      if (isListening) {
        stopVoiceRecording();
      } else {
        await startVoiceRecording();
      }
    } catch (error) {
      isListening = false;
      setStatus("idle");
      mediaStream?.getTracks().forEach(track => track.stop());
      mediaStream = null;
      mediaRecorder = null;
      updateVoiceButtons();
      setMicStatus(`Microphone unavailable: ${error.message || "Could not start recording."}`, "error");
    }
  };
}

async function startVoiceRecording() {
  mediaStream = await navigator.mediaDevices.getUserMedia({ audio: true });
  mediaChunks = [];
  mediaRecorder = new MediaRecorder(mediaStream);

  mediaRecorder.ondataavailable = event => {
    if (event.data?.size > 0) mediaChunks.push(event.data);
  };
  mediaRecorder.onerror = event => {
    setMicStatus(`Recording failed: ${event.error?.message || "Unknown recorder error."}`, "error");
    stopVoiceRecording();
  };
  mediaRecorder.onstop = async () => {
    isListening = false;
    setStatus("idle");
    updateVoiceButtons();
    if (recordingTimeout) {
      clearTimeout(recordingTimeout);
      recordingTimeout = null;
    }
    mediaStream?.getTracks().forEach(track => track.stop());
    mediaStream = null;

    if (!mediaChunks.length) {
      setMicStatus("No audio was captured.", "error");
      return;
    }

    try {
      const blob = new Blob(mediaChunks, { type: mediaChunks[0].type || "audio/webm" });
      const transcript = await window.VoiceBox.transcribeAudio(blob);
      setMicStatus(`Heard: "${transcript}"`, "ok");
      chatInput.value = transcript;
      await sendMessage();
    } catch (error) {
      setMicStatus(`Transcription failed: ${error.message || "VoiceBox request failed"}`, "error");
    }
  };

  mediaRecorder.start();
  isListening = true;
  setStatus("thinking");
  setMicStatus("Recording... click the microphone to stop.", "warn");
  updateVoiceButtons();
  recordingTimeout = setTimeout(stopVoiceRecording, MAX_RECORDING_MS);
}

function stopVoiceRecording() {
  if (recordingTimeout) {
    clearTimeout(recordingTimeout);
    recordingTimeout = null;
  }
  if (mediaRecorder && mediaRecorder.state !== "inactive") {
    mediaRecorder.stop();
  }
}

/* ============================================================
   Chat Rendering
============================================================ */
function renderChatList() {
  chatList.innerHTML = "";

  Object.entries(chats).forEach(([id, chat]) => {
    const li = document.createElement("li");
    li.className = "chat-item";
    if (id === currentChatId) li.classList.add("active");

    li.innerHTML = `
      <div class="chat-item-main">
        <div class="chat-item-title">${chat.title || "New Chat"}</div>
        <div class="chat-item-preview">${chat.messages[chat.messages.length - 1]?.content || ""}</div>
      </div>
      <div class="chat-item-actions">
        <button class="chat-action-btn" title="Rename chat">✏️</button>
        <button class="chat-action-btn" title="Delete chat">🗑</button>
      </div>
    `;

    li.onclick = () => loadChat(id);

    const renameBtn = li.querySelector('.chat-action-btn:nth-child(1)');
    const deleteBtn = li.querySelector('.chat-action-btn:nth-child(2)');

    renameBtn.onclick = (e) => {
      e.stopPropagation();
      renameChat(id);
    };

    deleteBtn.onclick = (e) => {
      e.stopPropagation();
      deleteChat(id);
    };

    chatList.appendChild(li);
  });
}

function escapeHtml(text) {
  return String(text)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

function renderInline(text) {
  return escapeHtml(text)
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
    .replace(/(^|[^*])\*([^*\s][^*]*)\*/g, "$1<em>$2</em>");
}

// Minimal, HTML-safe Markdown: headings, bullet lists, quotes, rules, paragraphs.
function renderMarkdown(text) {
  const out = [];
  let listOpen = false;
  let para = [];
  const closeList = () => { if (listOpen) { out.push("</ul>"); listOpen = false; } };
  const flushPara = () => {
    if (para.length) { out.push(`<p>${para.map(renderInline).join("<br>")}</p>`); para = []; }
  };

  String(text).replace(/\r\n?/g, "\n").split("\n").forEach(line => {
    let m;
    if (!line.trim()) { flushPara(); closeList(); }
    else if ((m = line.match(/^(#{1,5})\s+(.*)$/))) {
      flushPara(); closeList();
      const level = Math.max(2, m[1].length);
      out.push(`<h${level}>${renderInline(m[2])}</h${level}>`);
    } else if ((m = line.match(/^\s*[-*]\s+(.*)$/))) {
      flushPara();
      if (!listOpen) { out.push("<ul>"); listOpen = true; }
      out.push(`<li>${renderInline(m[1])}</li>`);
    } else if ((m = line.match(/^>\s?(.*)$/))) {
      flushPara(); closeList();
      out.push(`<blockquote>${renderInline(m[1])}</blockquote>`);
    } else if (/^\s*---+\s*$/.test(line)) {
      flushPara(); closeList(); out.push("<hr>");
    } else {
      closeList(); para.push(line);
    }
  });
  flushPara(); closeList();
  return out.join("");
}

function qualificationHtml(q) {
  const pass = q.status === "PASS";
  const badge = pass
    ? `<span class="qual PASS">✓ QUALIFIED ${escapeHtml(q.score)}</span>`
    : `<span class="qual FAIL">✗ UNQUALIFIED ${escapeHtml(q.score)}</span>`;
  const rows = (q.checks || []).map(c => `
    <tr>
      <td class="qual-mark ${c.pass ? "ok" : "bad"}">${c.pass ? "✓" : "✗"}</td>
      <td>${escapeHtml(c.name)}</td>
      <td>${escapeHtml(c.value ?? "—")}</td>
      <td>${escapeHtml(c.reason)}</td>
    </tr>`).join("");
  return `<div class="qual-card">${badge}
    <details class="qual-details">
      <summary>Checklist</summary>
      <table class="qual-table"><tbody>${rows}</tbody></table>
    </details></div>`;
}

function renderMessages() {
  chatLog.innerHTML = "";

  const messages = chats[currentChatId].messages;

  messages.forEach((msg, index) => {
    const next = messages[index + 1];
    const failed = msg.qualification?.status === "FAIL"
      || (msg.role === "user" && next?.qualification?.status === "FAIL");

    const row = document.createElement("div");
    row.className = `message-row ${msg.role === "user" ? "row-user" : "row-assistant"}`;
    if (showPassOnly && failed) row.style.display = "none";

    const bubble = document.createElement("div");
    bubble.className = `message ${msg.role}`;
    if (msg.role === "assistant") {
      const qual = msg.qualification ? qualificationHtml(msg.qualification) : "";
      bubble.innerHTML = msg.content
        ? `${qual}<div class="message-content">${renderMarkdown(msg.content)}</div>`
        : `<div class="message-content thinking">Thinking..</div>`;
    } else {
      bubble.innerHTML = `<div class="message-content">${escapeHtml(msg.content)}</div>`;
    }

    row.appendChild(bubble);
    chatLog.appendChild(row);
  });

  scrollToBottom();
}

/* ============================================================
   Chat Management
============================================================ */
function newChat() {
  const id = uuid();
  chats[id] = {
    title: "New Chat",
    messages: []
  };
  currentChatId = id;
  saveChats();
  renderChatList();
  renderMessages();
}

function loadChat(id) {
  currentChatId = id;
  renderChatList();
  renderMessages();
}

function renameChat(id) {
  const chat = chats[id];
  if (!chat) return;

  const newTitle = prompt("Rename chat:", chat.title || "New Chat");
  if (newTitle && newTitle.trim()) {
    chat.title = newTitle.trim();
    saveChats();
    renderChatList();
  }
}

function deleteChat(id) {
  if (!confirm("Delete this chat? This cannot be undone.")) {
    return;
  }

  delete chats[id];
  saveChats();

  if (currentChatId === id) {
    const ids = Object.keys(chats);
    currentChatId = ids.length > 0 ? ids[0] : null;
    if (currentChatId) {
      renderMessages();
    } else {
      newChat();
    }
  }

  renderChatList();
}

/* ============================================================
   Sending Messages
============================================================ */
async function sendMessage() {
  const text = chatInput.value.trim();
  if (!text) return;

  chatInput.value = "";
  setStatus("thinking");
  warmupAudioPipeline();

  const chat = chats[currentChatId];
  chat.messages.push({ role: "user", content: text });
  chat.title = chat.title === "New Chat" ? text.slice(0, 40) : chat.title;

  const requestMessages = buildRequestMessages(chat.messages);

  saveChats();
  renderMessages();

  abortController = new AbortController();

  const assistantMsg = { role: "assistant", content: "" };
  chat.messages.push(assistantMsg);
  renderMessages();

  try {
    let response = await fetch(API_URL, {
      method: "POST",
      signal: abortController.signal,
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        model: activeModelId,
        messages: requestMessages,
        max_tokens: DEFAULT_MAX_TOKENS,
        temperature: DEFAULT_TEMPERATURE,
        stream: false
      })
    });

    setStatus("streaming");

    if (!response.ok) {
      let errText = await response.text();

      // If the server reports context overflow, retry once with a tighter budget.
      const overflowMeta = parseContextOverflow(errText || "");
      if (overflowMeta) {
        const contextSize = overflowMeta.contextSize;
        const retryBudget = Math.max(256, contextSize - CONTEXT_RETRY_RESERVE_TOKENS);
        let retryMessages = buildRequestMessagesWithTokenBudget(chat.messages, retryBudget);

        if (!retryMessages.length || estimateMessageListTokens(retryMessages) > retryBudget) {
          retryMessages = buildEmergencyMessages(chat.messages, retryBudget);
        }

        response = await fetch(API_URL, {
          method: "POST",
          signal: abortController.signal,
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            model: activeModelId,
            messages: retryMessages,
            max_tokens: DEFAULT_MAX_TOKENS,
            temperature: DEFAULT_TEMPERATURE,
            stream: false
          })
        });

        if (!response.ok) {
          errText = await response.text();
          throw new Error(errText || `HTTP ${response.status}`);
        }
      } else {
        throw new Error(errText || `HTTP ${response.status}`);
      }
    }

    const data = await response.json();
    const reply = data?.choices?.[0]?.message?.content || "";
    assistantMsg.content = reply || "[No response text returned]";
    if (data?.qualification) assistantMsg.qualification = data.qualification;
    renderMessages();
    speakReply(reply);

  } catch (err) {
    assistantMsg.content += `\n\n[Error: ${err.message || "Request failed"}]`;
  }

  setStatus("idle");
  saveChats();
  renderMessages();
}

function buildRequestMessages(messages) {
  return buildRequestMessagesWithTokenBudget(messages, MAX_REQUEST_EST_TOKENS);
}

function buildRequestMessagesWithTokenBudget(messages, tokenBudget) {
  const safeTokenBudget = Math.max(256, Number(tokenBudget) || MAX_REQUEST_EST_TOKENS);

  const systemMessages = messages
    .filter(msg => msg.role === "system")
    .map(msg => ({ role: msg.role, content: String(msg.content || "") }));

  const systemTokenCost = systemMessages.reduce((sum, msg) => {
    return sum + estimateTokens(msg.content);
  }, 0);

  const usableBudget = Math.max(128, safeTokenBudget - systemTokenCost);

  const recentMessages = [];
  let charCount = 0;
  let tokenCount = 0;

  for (let i = messages.length - 1; i >= 0; i--) {
    const msg = messages[i];
    if (msg.role === "system") continue;

    let content = String(msg.content || "");
    let msgChars = content.length;
    let msgTokens = estimateTokens(content);

    if (recentMessages.length >= MAX_REQUEST_MESSAGES) break;
    if (recentMessages.length > 0 && charCount + msgChars > MAX_REQUEST_CHARS) break;
    if (recentMessages.length > 0 && tokenCount + msgTokens > usableBudget) break;

    if (recentMessages.length === 0 && msgTokens > usableBudget) {
      content = truncateToTokenBudget(content, usableBudget);
      msgChars = content.length;
      msgTokens = estimateTokens(content);
    }

    recentMessages.push({ role: msg.role, content });
    charCount += msgChars;
    tokenCount += msgTokens;
  }

  return sanitizeRoleOrder([...systemMessages, ...recentMessages.reverse()]);
}

function sanitizeRoleOrder(messages) {
  const isFailed = msg =>
    msg.role === "assistant" &&
    (!msg.content.trim() || /^\[(Error|No response)/.test(msg.content.trim()) || /\n\n\[Error:/.test(msg.content));

  const system = messages.filter(msg => msg.role === "system");
  const result = [];
  for (const msg of messages) {
    if (msg.role === "system" || isFailed(msg)) continue;
    const last = result[result.length - 1];
    if (last && last.role === msg.role) {
      last.content += "\n\n" + msg.content;
    } else {
      result.push({ ...msg });
    }
  }
  while (result.length && result[0].role !== "user") result.shift();
  while (result.length && result[result.length - 1].role !== "user") result.pop();
  return [...system, ...result];
}

function estimateTokens(text) {
  // Deliberately conservative approximation to avoid server-side overflow.
  return Math.ceil(String(text || "").length / 2.5);
}

function truncateToTokenBudget(text, tokenBudget) {
  const maxChars = Math.max(200, Math.floor(tokenBudget * 3.6));
  const value = String(text || "");
  if (value.length <= maxChars) {
    return value;
  }

  return value.slice(value.length - maxChars);
}

function parseContextOverflow(errorText) {
  const text = String(errorText || "");

  const availableMatch = /available context size \((\d+) tokens\)/i.exec(text);
  if (availableMatch) {
    return { contextSize: Number(availableMatch[1]) };
  }

  const exceedsMatch = /request \((\d+) tokens\) exceeds the available context size \((\d+) tokens\)/i.exec(text);
  if (exceedsMatch) {
    return { contextSize: Number(exceedsMatch[2]) };
  }

  const contextLineMatch = /Context size:\s*([\d,]+)/i.exec(text);
  if (contextLineMatch) {
    return { contextSize: Number(contextLineMatch[1].replace(/,/g, "")) };
  }

  return null;
}

function estimateMessageListTokens(messages) {
  return (messages || []).reduce((sum, msg) => {
    return sum + estimateTokens(msg?.content || "") + 8;
  }, 0);
}

function buildEmergencyMessages(messages, tokenBudget) {
  const safeTokenBudget = Math.max(256, Number(tokenBudget) || MAX_REQUEST_EST_TOKENS);
  const result = [];

  const system = messages.find(msg => msg.role === "system" && String(msg.content || "").trim());
  if (system) {
    result.push({ role: "system", content: String(system.content || "") });
  }

  const nonSystem = messages.filter(msg => msg.role !== "system");
  const lastUser = [...nonSystem].reverse().find(msg => msg.role === "user");
  const lastAssistant = [...nonSystem].reverse().find(msg => msg.role === "assistant");

  if (lastAssistant && String(lastAssistant.content || "").trim()) {
    const trimmed = truncateToTokenBudget(String(lastAssistant.content || ""), Math.floor(safeTokenBudget * 0.35));
    result.push({ role: "assistant", content: trimmed });
  }

  if (lastUser && String(lastUser.content || "").trim()) {
    const trimmed = truncateToTokenBudget(String(lastUser.content || ""), Math.floor(safeTokenBudget * 0.45));
    result.push({ role: "user", content: trimmed });
  }

  return sanitizeRoleOrder(result);
}

/* ============================================================
   Stop Button
============================================================ */
function stopGeneration() {
  if (abortController) abortController.abort();
  setStatus("idle");
}

/* ============================================================
   Event Listeners
============================================================ */
sendButton.onclick = sendMessage;
stopButton.onclick = stopGeneration;
ttsToggleButton.onclick = () => {
  ttsEnabled = !ttsEnabled;
  localStorage.setItem("aladdin_tts_enabled", ttsEnabled ? "1" : "0");
  if (!ttsEnabled) stopTtsPlayback();
  updateVoiceButtons();
};

newChatButton.onclick = newChat;
clearChatButton.onclick = () => {
  chats[currentChatId].messages = [];
  saveChats();
  renderMessages();
};

sidebarToggle.onclick = () => {
  document.getElementById("sidebar").classList.toggle("collapsed");
};

chatInput.addEventListener("keydown", e => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    sendMessage();
  }
});

async function loadModel() {
  const normalizeModelId = (id) => (id || "").trim().replace(/\\/g, "/").split("/").pop();
  const toDisplayName = (id) => {
    const base = normalizeModelId(id);
    return MODEL_NAME_BY_ID[id] || MODEL_NAME_BY_ID[base] || base || id;
  };
  const params = new URLSearchParams(window.location.search || "");
  const hashRaw = (window.location.hash || "").replace(/^#/, "");
  const hashParams = new URLSearchParams(hashRaw);
  const modelFromUrl = (
    params.get("model") ||
    params.get("model_id") ||
    hashParams.get("model") ||
    hashParams.get("model_id") ||
    ""
  ).trim();
  const readTextFirst = async (paths) => {
    for (const path of paths) {
      try {
        const resp = await fetch(path, { cache: "no-store" });
        if (!resp.ok) continue;
        const text = (await resp.text()).trim();
        if (text) return text;
      } catch (_) {
        // Try next candidate path.
      }
    }
    return "";
  };

  let preferredModelId = modelFromUrl || await readTextFirst([
    "./current_model_id.txt",
    "/current_model_id.txt",
    "../current_model_id.txt",
    "/WebUI/current_model_id.txt",
    "/miniweb/htdocs/current_model_id.txt"
  ]);

  // Backward-compatible fallback for older launchers that only write model label.
  let preferredModelLabel = "";
  if (!preferredModelId) {
    preferredModelLabel = await readTextFirst([
      "./current_model.txt",
      "/current_model.txt",
      "../current_model.txt",
      "/WebUI/current_model.txt",
      "/miniweb/htdocs/current_model.txt"
    ]);
  }

  // In local file mode, use launcher-provided model directly.
  if (window.location.protocol === "file:" && preferredModelId) {
    activeModelId = preferredModelId;
    localStorage.setItem("aladdin_last_model_id", preferredModelId);
    modelName.textContent = `Model: ${toDisplayName(preferredModelId)} (launcher)`;
    return;
  }

  try {
    const response = await fetch(MODELS_URL, { method: "GET" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const payload = await response.json();
    const candidates = [];

    if (Array.isArray(payload?.data)) {
      payload.data.forEach(item => {
        if (item?.id) candidates.push(item.id);
      });
    }

    if (Array.isArray(payload?.models)) {
      payload.models.forEach(item => {
        if (item?.model) candidates.push(item.model);
        else if (item?.name) candidates.push(item.name);
      });
    }

    const preferredBase = normalizeModelId(preferredModelId);
    const preferredCandidate = preferredModelId
      ? candidates.find(item => item === preferredModelId || normalizeModelId(item) === preferredBase)
      : "";

    const model = preferredCandidate || candidates[0] || "";

    if (model) {
      activeModelId = model;
      localStorage.setItem("aladdin_last_model_id", model);
      const friendly = toDisplayName(model);
      if (preferredModelId && preferredModelId !== model) {
        modelName.textContent = `Model: ${friendly} (server)`;
      } else {
        modelName.textContent = `Model: ${friendly}`;
      }
      return;
    }
  } catch (_) {
    // Ignore and keep fallback model label.
  }

  if (preferredModelId) {
    activeModelId = preferredModelId;
    localStorage.setItem("aladdin_last_model_id", preferredModelId);
    modelName.textContent = `Model: ${toDisplayName(preferredModelId)} (launcher)`;
    return;
  }

  if (preferredModelLabel) {
    modelName.textContent = `Model: ${preferredModelLabel} (launcher)`;
    return;
  }

  const lastModelId = (localStorage.getItem("aladdin_last_model_id") || "").trim();
  if (lastModelId) {
    activeModelId = lastModelId;
    modelName.textContent = `Model: ${toDisplayName(lastModelId)} (cached)`;
    return;
  }

  modelName.textContent = "Model: Local (unresolved)";
}

/* ============================================================
   Initialization
============================================================ */
(function init() {
  if (Object.keys(chats).length === 0) {
    newChat();
  } else {
    // Auto-load last chat
    const ids = Object.keys(chats);
    currentChatId = ids[ids.length - 1];
    renderChatList();
    renderMessages();
  }

  setStatus("idle");
  updateVoiceButtons();
  setupVoiceInput();
  loadModel();
})();
