import os
import asyncio
from pathlib import Path
from flask import Flask, request, jsonify, send_from_directory, render_template_string
from src.downloader import BatchDownloader, BotForwarder, parse_link, _fmt_size

DOWNLOADS_DIR = Path("downloads")
DOWNLOADS_DIR.mkdir(exist_ok=True)
PHONE_NUMBER = os.environ.get("PHONE_NUMBER", "")

# ── HTML ──────────────────────────────────────────────────────────────────────

INDEX_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1.0"/>
<title>TG Downloader</title>
<script src="https://cdn.tailwindcss.com"></script>
<style>
  :root {
    --bg:      #07090f;
    --surface: #0d1017;
    --card:    #111827;
    --border:  #1f2d45;
    --accent:  #00d4ff;
    --purple:  #7c3aed;
    --green:   #10b981;
    --red:     #ef4444;
    --amber:   #f59e0b;
    --text:    #e2e8f0;
    --muted:   #475569;
  }
  * { box-sizing: border-box; }
  body { background: var(--bg); color: var(--text); font-family: 'Inter', ui-sans-serif, system-ui, sans-serif; min-height: 100vh; }
  ::selection { background: #00d4ff30; }

  /* Scrollbar */
  ::-webkit-scrollbar { width: 4px; height: 4px; }
  ::-webkit-scrollbar-track { background: transparent; }
  ::-webkit-scrollbar-thumb { background: var(--border); border-radius: 4px; }

  /* Cards */
  .card {
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 12px;
  }
  .card-glow:hover { border-color: #1e3a5f; box-shadow: 0 0 20px #00d4ff0d; }

  /* Inputs */
  input[type=text], input[type=tel], input[type=number], input[type=password] {
    background: var(--surface);
    border: 1px solid var(--border);
    color: var(--text);
    border-radius: 8px;
    padding: 9px 12px;
    font-size: 0.875rem;
    width: 100%;
    transition: border-color .2s;
    outline: none;
  }
  input:focus { border-color: var(--accent); box-shadow: 0 0 0 2px #00d4ff15; }

  /* Buttons */
  .btn {
    border-radius: 8px;
    padding: 9px 18px;
    font-size: 0.8125rem;
    font-weight: 600;
    letter-spacing: .02em;
    cursor: pointer;
    transition: all .15s;
    border: none;
    white-space: nowrap;
    display: inline-flex;
    align-items: center;
    gap: 6px;
  }
  .btn-accent  { background: var(--accent);  color: #000; }
  .btn-accent:hover  { background: #00bce0; box-shadow: 0 0 12px #00d4ff40; }
  .btn-purple  { background: var(--purple); color: #fff; }
  .btn-purple:hover  { background: #6d28d9; box-shadow: 0 0 12px #7c3aed40; }
  .btn-green   { background: var(--green);  color: #fff; }
  .btn-green:hover   { background: #059669; }
  .btn-red     { background: var(--red);    color: #fff; }
  .btn-red:hover     { background: #dc2626; }
  .btn-amber   { background: var(--amber);  color: #000; }
  .btn-amber:hover   { background: #d97706; }
  .btn-ghost   { background: transparent; color: var(--muted); border: 1px solid var(--border); }
  .btn-ghost:hover   { border-color: #334155; color: var(--text); }
  .btn:disabled { opacity: .4; cursor: not-allowed; }

  /* Animated progress bar */
  #prog-track {
    height: 3px;
    background: var(--border);
    border-radius: 99px;
    overflow: visible;
    position: relative;
  }
  #prog-fill {
    height: 100%;
    border-radius: 99px;
    background: linear-gradient(90deg, var(--purple), var(--accent), var(--purple));
    background-size: 200% 100%;
    animation: shimmer 2s linear infinite;
    box-shadow: 0 0 8px var(--accent), 0 0 20px #00d4ff30;
    transition: width .4s ease;
    position: relative;
  }
  #prog-fill::after {
    content: '';
    position: absolute;
    right: -1px;
    top: 50%;
    transform: translateY(-50%);
    width: 8px; height: 8px;
    background: var(--accent);
    border-radius: 50%;
    box-shadow: 0 0 6px var(--accent);
  }
  @keyframes shimmer {
    0%   { background-position: 200% 0; }
    100% { background-position: -200% 0; }
  }
  #prog-fill.done { animation: none; background: var(--green); box-shadow: 0 0 8px #10b98180; }
  #prog-fill.done::after { background: var(--green); box-shadow: 0 0 6px var(--green); }

  /* Log */
  #log-box {
    height: 160px; overflow-y: auto;
    font-size: 0.7rem; font-family: 'JetBrains Mono', 'Courier New', monospace;
    color: var(--muted); line-height: 1.6;
    background: var(--surface);
    border-radius: 8px; padding: 12px;
  }
  #log-box .log-ok   { color: var(--green); }
  #log-box .log-err  { color: var(--red); }
  #log-box .log-info { color: var(--accent); }

  /* Thumbnail grid */
  #thumb-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(140px,1fr)); gap: 10px; }
  .thumb-card {
    background: var(--surface); border: 1px solid var(--border);
    border-radius: 10px; overflow: hidden; cursor: pointer;
    transition: border-color .15s, box-shadow .15s;
    position: relative; user-select: none;
  }
  .thumb-card.selected { border-color: var(--accent); box-shadow: 0 0 12px #00d4ff25; }
  .thumb-card .thumb-img {
    width: 100%; aspect-ratio: 16/9;
    object-fit: cover; display: block;
    background: #0d1017;
  }
  .thumb-card .thumb-placeholder {
    width: 100%; aspect-ratio: 16/9;
    background: var(--surface);
    display: flex; align-items: center; justify-content: center;
    font-size: 0.65rem; color: var(--muted);
  }
  .thumb-card .thumb-meta {
    padding: 6px 8px;
    font-size: 0.65rem; color: var(--muted);
  }
  .thumb-card .thumb-meta .msg-id { font-weight: 700; color: var(--text); font-size: 0.7rem; }
  .thumb-card .cb-overlay {
    position: absolute; top: 6px; left: 6px;
    width: 18px; height: 18px;
    border-radius: 4px; border: 2px solid var(--border);
    background: #07090fcc;
    display: flex; align-items: center; justify-content: center;
    transition: all .15s;
  }
  .thumb-card.selected .cb-overlay {
    background: var(--accent); border-color: var(--accent);
  }
  .thumb-card.selected .cb-overlay::after {
    content: ''; display: block;
    width: 5px; height: 8px;
    border: 2px solid #000;
    border-left: none; border-top: none;
    transform: rotate(45deg) translate(-1px,-1px);
  }
  .thumb-card .type-badge {
    position: absolute; top: 6px; right: 6px;
    font-size: 0.6rem; font-weight: 700; letter-spacing: .05em;
    padding: 2px 5px; border-radius: 4px;
    background: #00000099; color: var(--accent);
    text-transform: uppercase;
  }
  .thumb-card.no-media { opacity: .35; cursor: default; }

  /* File list */
  .file-row {
    display: flex; align-items: center; gap: 10px;
    background: var(--surface); border: 1px solid var(--border);
    border-radius: 8px; padding: 10px 12px;
    cursor: pointer; transition: border-color .15s;
  }
  .file-row.selected { border-color: var(--accent); background: #00d4ff08; }
  .file-row .fcb {
    width: 16px; height: 16px; flex-shrink: 0;
    accent-color: var(--accent); cursor: pointer;
  }
  .file-row:hover { border-color: #2d4060; }

  /* Section labels */
  .section-label {
    font-size: 0.7rem; font-weight: 700; letter-spacing: .12em;
    text-transform: uppercase; color: var(--muted);
    margin-bottom: 12px;
  }

  /* Divider */
  .divider { border-color: var(--border); }

  /* Scan spinner */
  .spinner {
    width: 16px; height: 16px; border-radius: 50%;
    border: 2px solid var(--border);
    border-top-color: var(--accent);
    animation: spin .7s linear infinite;
    display: inline-block;
  }
  @keyframes spin { to { transform: rotate(360deg); } }

  /* Status dot */
  .dot { width: 8px; height: 8px; border-radius: 50%; display: inline-block; }
  .dot-green { background: var(--green); box-shadow: 0 0 6px var(--green); }
  .dot-amber { background: var(--amber); box-shadow: 0 0 6px var(--amber); }
</style>
</head>
<body>

<!-- Top bar -->
<header style="background:var(--card);border-bottom:1px solid var(--border)" class="sticky top-0 z-50">
  <div class="max-w-2xl mx-auto px-4 h-14 flex items-center justify-between">
    <div class="flex items-center gap-3">
      <div style="width:28px;height:28px;background:linear-gradient(135deg,var(--purple),var(--accent));border-radius:7px"></div>
      <span style="font-size:.875rem;font-weight:700;letter-spacing:.04em;color:var(--text)">TG DOWNLOADER</span>
    </div>
    <div id="user-badge" class="flex items-center gap-2 text-xs" style="color:var(--muted)">
      <span class="dot dot-amber" id="status-dot"></span>
      <span id="status-label">Connecting…</span>
    </div>
  </div>
</header>

<main class="max-w-2xl mx-auto px-4 py-6 space-y-4">

  <!-- API credentials missing banner -->
  <div id="no-creds-banner" class="hidden" style="background:#7c2d12;border:1px solid #dc2626;border-radius:10px;padding:14px 16px;font-size:.85rem;line-height:1.5">
    ⚠️ <strong>API_ID และ API_HASH ยังไม่ได้ตั้งค่า</strong><br>
    ไปที่ <strong>Render Dashboard → Your Service → Environment</strong> แล้วเพิ่มตัวแปร:<br>
    <code style="background:#450a0a;padding:2px 6px;border-radius:4px">API_ID</code> และ
    <code style="background:#450a0a;padding:2px 6px;border-radius:4px">API_HASH</code><br>
    <span style="color:#fca5a5">รับค่าได้จาก <a href="https://my.telegram.org/auth" target="_blank" style="color:#f87171;text-decoration:underline">my.telegram.org/auth</a></span>
  </div>

  <!-- Auth card -->
  <div id="auth-card" class="card p-5 hidden">
    <p class="section-label">Authentication Required</p>
    <div class="space-y-3">
      <input id="auth-phone" type="tel" placeholder="Phone number  (+66812345678)" value="{{ phone }}"/>
      <div id="otp-row" class="hidden space-y-3">
        <input id="auth-otp" type="text" placeholder="OTP code from Telegram"/>
        <input id="auth-2fa" type="password" placeholder="2FA password (if enabled)"/>
      </div>
      <div class="flex gap-2 flex-wrap">
        <button class="btn btn-accent" id="btn-send" onclick="sendCode()">Send Code</button>
        <button class="btn btn-green hidden" id="btn-verify" onclick="verifyCode()">Verify</button>
      </div>
      <p id="auth-msg" class="text-xs hidden" style="color:var(--muted)"></p>
    </div>
  </div>

  <!-- Downloader card -->
  <div id="dl-card" class="card p-5 hidden card-glow">
    <p class="section-label">Batch Downloader</p>

    <!-- Mode toggle -->
    <div class="flex gap-1 p-1 mb-3" style="background:var(--surface);border-radius:8px;border:1px solid var(--border)">
      <button id="btn-mode-save" class="btn flex-1 btn-accent" onclick="setMode('save')" style="font-size:.75rem">💾 บันทึกลงเซิร์ฟเวอร์</button>
      <button id="btn-mode-fwd"  class="btn flex-1 btn-ghost"  onclick="setMode('forward')" style="font-size:.75rem">🤖 ส่งผ่านบอท</button>
    </div>

    <!-- Bot config (forward mode only) -->
    <div id="bot-config" class="hidden mb-3 p-3 space-y-2" style="background:var(--surface);border-radius:8px;border:1px solid var(--accent)30">
      <p class="text-xs font-bold" style="color:var(--accent);letter-spacing:.06em">⚙️ ตั้งค่าบอท</p>
      <input id="bot-token" type="password" placeholder="Bot Token (จาก @BotFather)"/>
      <input id="target-chat" type="text" placeholder="Target Chat ID  เช่น -1001234567890"/>
      <div class="flex items-center gap-2">
        <button class="btn btn-ghost" style="padding:5px 12px;font-size:.75rem" onclick="validateBot()">
          <span id="bot-spinner" class="spinner hidden"></span>
          ทดสอบบอท
        </button>
        <span id="bot-status" class="text-xs" style="color:var(--muted)"></span>
      </div>
    </div>

    <div class="space-y-3">
      <input id="dl-link" type="text" placeholder="https://t.me/c/1234567890/100"/>
      <div class="grid grid-cols-2 gap-3">
        <div>
          <p class="text-xs mb-1" style="color:var(--muted)">Message count</p>
          <input id="dl-count" type="number" value="10" min="1" max="500"/>
        </div>
        <div>
          <p class="text-xs mb-1" style="color:var(--muted)">Start offset</p>
          <input id="dl-offset" type="number" value="0"/>
        </div>
      </div>
      <div class="flex gap-2 flex-wrap">
        <button class="btn btn-accent" onclick="scanPreview()">
          <span id="scan-spinner" class="spinner hidden"></span>
          Scan &amp; Preview
        </button>
        <button id="btn-dl-range" class="btn btn-purple" onclick="startBatch()">Download Range</button>
        <button class="btn btn-ghost" onclick="stopDownload()">Stop</button>
      </div>
    </div>
  </div>

  <!-- Thumbnail preview card -->
  <div id="preview-card" class="card p-5 hidden">
    <div class="flex items-center justify-between mb-4">
      <p class="section-label" style="margin-bottom:0">Preview</p>
      <div class="flex items-center gap-2">
        <span id="thumb-sel-count" class="text-xs" style="color:var(--muted)">0 selected</span>
        <button class="btn btn-ghost" style="padding:5px 10px;font-size:.75rem" onclick="selectAllThumbs()">Select All</button>
        <button class="btn btn-accent" style="padding:5px 12px;font-size:.75rem" onclick="downloadScanned()">Download Selected</button>
      </div>
    </div>
    <div id="thumb-grid"></div>
  </div>

  <!-- Clone Topic card -->
  <div id="clone-card" class="card p-5 hidden card-glow" style="border-color:#7c3aed30">
    <p class="section-label" style="color:var(--purple)">🔁 Clone Topic</p>
    <p class="text-xs mb-3" style="color:var(--muted)">กรอก link ข้อความแรกของ Topic — ระบบดึงทุกอย่าง (วิดีโอ, รูป, ข้อความ) ส่งบอทให้ครบ แล้วลบทิ้งอัตโนมัติ</p>
    <div class="space-y-3">
      <input id="clone-link" type="text" placeholder="https://t.me/c/1234567890/100  (ข้อความแรกของ Topic)"/>
      <input id="clone-bot-token" type="password" placeholder="Bot Token (จาก @BotFather)"/>
      <input id="clone-target-chat" type="text" placeholder="Target Chat ID  เช่น -1001234567890"/>
      <div class="flex items-center gap-2">
        <button class="btn btn-ghost" style="padding:5px 12px;font-size:.75rem" onclick="validateCloneBot()">
          <span id="clone-bot-spinner" class="spinner hidden"></span>
          ทดสอบบอท
        </button>
        <span id="clone-bot-status" class="text-xs" style="color:var(--muted)"></span>
      </div>
      <div class="flex gap-2 flex-wrap">
        <button class="btn btn-purple" onclick="startClone()">🔁 Clone ทั้งหมด</button>
        <button class="btn btn-ghost" onclick="stopDownload()">Stop</button>
      </div>
    </div>
  </div>

  <!-- Progress card -->
  <div id="prog-card" class="card p-5 hidden">
    <div class="flex items-center justify-between mb-4">
      <p class="section-label" style="margin-bottom:0">Progress</p>
      <span id="prog-label" class="text-xs font-mono" style="color:var(--muted)">0 / 0</span>
    </div>
    <div id="prog-track" class="mb-2"><div id="prog-fill" style="width:0%"></div></div>
    <p id="prog-file" class="text-xs mb-4 truncate font-mono" style="color:var(--muted)"></p>
    <div id="log-box"></div>
  </div>

  <!-- File manager card -->
  <div id="files-card" class="card p-5">
    <div class="flex items-center justify-between mb-1">
      <p class="section-label" style="margin-bottom:0">
        Files
        <span id="file-count" style="color:var(--muted);font-weight:400;margin-left:4px"></span>
      </p>
      <button class="btn btn-ghost" style="padding:5px 10px;font-size:.75rem" onclick="loadFiles()">Refresh</button>
    </div>

    <!-- File toolbar -->
    <div id="file-toolbar" class="hidden flex flex-wrap gap-2 items-center mb-3 pb-3" style="border-bottom:1px solid var(--border)">
      <button class="btn btn-ghost" style="padding:5px 10px;font-size:.75rem" id="btn-sel-all" onclick="toggleSelectAll()">Select All</button>
      <span class="text-xs" style="color:var(--muted)" id="sel-count">0 selected</span>
      <div class="flex-1"></div>
      <button class="btn btn-green" style="padding:5px 12px;font-size:.75rem" onclick="downloadSelected()">Download Selected</button>
      <button class="btn btn-amber" style="padding:5px 12px;font-size:.75rem" onclick="deleteSelected()">Delete Selected</button>
      <button class="btn btn-red"   style="padding:5px 12px;font-size:.75rem" onclick="cleanUpAll()">Clean Up Disk</button>
    </div>

    <div id="file-list" class="space-y-2">
      <p class="text-xs" style="color:var(--muted)">No files yet.</p>
    </div>
  </div>

</main>

<script>
/* ─── state ─── */
let polling = null;
let allFilesSelected = false;
let thumbAllSelected = false;
let scannedLink = '';
let currentMode = 'save';

/* ─── Mode toggle ─── */
function setMode(mode) {
  currentMode = mode;
  const isFwd = mode === 'forward';
  document.getElementById('bot-config').classList.toggle('hidden', !isFwd);
  document.getElementById('btn-mode-save').className = 'btn flex-1 ' + (isFwd ? 'btn-ghost' : 'btn-accent');
  document.getElementById('btn-mode-fwd').className  = 'btn flex-1 ' + (isFwd ? 'btn-accent' : 'btn-ghost');
  document.getElementById('btn-dl-range').textContent = isFwd ? '🤖 Forward Range' : 'Download Range';
}

async function validateBot() {
  const token = document.getElementById('bot-token').value.trim();
  const chat  = document.getElementById('target-chat').value.trim();
  const statusEl = document.getElementById('bot-status');
  const spinner  = document.getElementById('bot-spinner');
  if (!token || !chat) {
    statusEl.textContent = 'กรอก Bot Token และ Chat ID ก่อน';
    statusEl.style.color = 'var(--red)'; return;
  }
  spinner.classList.remove('hidden');
  statusEl.textContent = 'กำลังทดสอบ…'; statusEl.style.color = 'var(--muted)';
  const d = await post('/api/bot/validate', { bot_token: token, target_chat_id: chat });
  spinner.classList.add('hidden');
  if (d.ok) {
    statusEl.textContent = '✓ @' + d.bot_username + ' พร้อมส่งแล้ว';
    statusEl.style.color = 'var(--green)';
  } else {
    statusEl.textContent = '✗ ' + (d.error || 'ผิดพลาด');
    statusEl.style.color = 'var(--red)';
  }
}

/* ─── Auth ─── */
async function checkAuth() {
  try {
    const d = await (await fetch('/api/auth/status')).json();
    const dot = document.getElementById('status-dot');
    const lbl = document.getElementById('status-label');
    const banner = document.getElementById('no-creds-banner');
    if (d.credentials_missing) {
      dot.className = 'dot dot-amber';
      lbl.textContent = 'Missing API credentials';
      banner.classList.remove('hidden');
      document.getElementById('auth-card').classList.add('hidden');
      document.getElementById('dl-card').classList.add('hidden');
      document.getElementById('clone-card').classList.add('hidden');
    } else if (d.authorized) {
      dot.className = 'dot dot-green';
      lbl.textContent = d.user?.name || 'Authenticated';
      banner.classList.add('hidden');
      document.getElementById('auth-card').classList.add('hidden');
      document.getElementById('dl-card').classList.remove('hidden');
      document.getElementById('clone-card').classList.remove('hidden');
      loadFiles();
    } else {
      dot.className = 'dot dot-amber';
      lbl.textContent = 'Not logged in';
      banner.classList.add('hidden');
      document.getElementById('auth-card').classList.remove('hidden');
      document.getElementById('dl-card').classList.add('hidden');
      document.getElementById('clone-card').classList.add('hidden');
    }
  } catch (e) {}
}

async function sendCode() {
  const phone = document.getElementById('auth-phone').value.trim();
  setMsg('auth-msg', '', '');
  const d = await post('/api/auth/send_code', { phone });
  if (d.ok) {
    document.getElementById('otp-row').classList.remove('hidden');
    document.getElementById('btn-verify').classList.remove('hidden');
    document.getElementById('btn-send').textContent = 'Resend Code';
    setMsg('auth-msg', 'Code sent — check Telegram.', 'green');
  } else setMsg('auth-msg', d.error || 'Failed.', 'red');
}

async function verifyCode() {
  const phone = document.getElementById('auth-phone').value.trim();
  const code = document.getElementById('auth-otp').value.trim();
  const password = document.getElementById('auth-2fa').value.trim();
  const d = await post('/api/auth/sign_in', { phone, code, password });
  if (d.ok) { setMsg('auth-msg', 'Authenticated.', 'green'); setTimeout(checkAuth, 600); }
  else if (d.need_2fa) setMsg('auth-msg', 'Enter your 2FA password.', 'amber');
  else setMsg('auth-msg', d.error || 'Failed.', 'red');
}

/* ─── Clone Topic ─── */
async function validateCloneBot() {
  const token = document.getElementById('clone-bot-token').value.trim();
  const chat  = document.getElementById('clone-target-chat').value.trim();
  const statusEl = document.getElementById('clone-bot-status');
  const spinner  = document.getElementById('clone-bot-spinner');
  if (!token || !chat) {
    statusEl.textContent = 'กรอก Bot Token และ Chat ID ก่อน';
    statusEl.style.color = 'var(--red)'; return;
  }
  spinner.classList.remove('hidden');
  statusEl.textContent = 'กำลังทดสอบ…'; statusEl.style.color = 'var(--muted)';
  const d = await post('/api/bot/validate', { bot_token: token, target_chat_id: chat });
  spinner.classList.add('hidden');
  if (d.ok) {
    statusEl.textContent = '✓ @' + d.bot_username + ' พร้อมส่งแล้ว';
    statusEl.style.color = 'var(--green)';
  } else {
    statusEl.textContent = '✗ ' + (d.error || 'ผิดพลาด');
    statusEl.style.color = 'var(--red)';
  }
}

async function startClone() {
  const link  = document.getElementById('clone-link').value.trim();
  const token = document.getElementById('clone-bot-token').value.trim();
  const chat  = document.getElementById('clone-target-chat').value.trim();
  if (!link)  { alert('กรอก link ข้อความแรกของ Topic ก่อนครับ'); return; }
  if (!token || !chat) { alert('กรอก Bot Token และ Target Chat ID ก่อนครับ'); return; }
  const d = await post('/api/clone/start', { link, bot_token: token, target_chat_id: chat });
  if (d.ok) {
    document.getElementById('prog-card').classList.remove('hidden');
    document.getElementById('prog-card').scrollIntoView({ behavior: 'smooth' });
    startPolling();
  } else alert(d.error || 'ไม่สามารถเริ่มได้');
}

/* ─── Scan & Preview ─── */
async function scanPreview() {
  const link = document.getElementById('dl-link').value.trim();
  const count = Math.min(parseInt(document.getElementById('dl-count').value) || 10, 24);
  const offset = parseInt(document.getElementById('dl-offset').value) || 0;
  if (!link) { alert('Enter a Telegram link first.'); return; }

  scannedLink = link;
  const spinner = document.getElementById('scan-spinner');
  spinner.classList.remove('hidden');

  try {
    const d = await post('/api/scan', { link, count, start_offset: offset });
    if (d.error) { alert(d.error); return; }
    renderThumbs(d.items || []);
    document.getElementById('preview-card').classList.remove('hidden');
  } catch (e) { alert('Scan failed: ' + e); }
  finally { spinner.classList.add('hidden'); }
}

function renderThumbs(items) {
  const grid = document.getElementById('thumb-grid');
  thumbAllSelected = false;
  grid.innerHTML = items.map(it => {
    const hasMedia = it.has_media;
    const thumbSrc = it.thumb ? `data:image/jpeg;base64,${it.thumb}` : null;
    const dur = it.duration ? `${Math.floor(it.duration/60)}:${String(it.duration%60).padStart(2,'0')}` : '';
    return `
    <div class="thumb-card${hasMedia ? '' : ' no-media'}" data-id="${it.msg_id}" data-has="${hasMedia}"
         onclick="${hasMedia ? 'toggleThumb(this)' : ''}">
      <div class="cb-overlay"></div>
      ${it.type ? `<div class="type-badge">${escHtml(it.type)}</div>` : ''}
      ${thumbSrc
        ? `<img class="thumb-img" src="${thumbSrc}" loading="lazy"/>`
        : `<div class="thumb-placeholder">${hasMedia ? 'no thumb' : 'no media'}</div>`}
      <div class="thumb-meta">
        <div class="msg-id">#${it.msg_id}</div>
        ${it.size ? `<div>${escHtml(it.size)}${dur ? ' · ' + dur + 's' : ''}</div>` : ''}
        ${it.error ? `<div style="color:var(--red)">${escHtml(it.error.substring(0,40))}</div>` : ''}
      </div>
    </div>`;
  }).join('');
  updateThumbSelCount();
}

function toggleThumb(el) {
  el.classList.toggle('selected');
  updateThumbSelCount();
}

function selectAllThumbs() {
  thumbAllSelected = !thumbAllSelected;
  document.querySelectorAll('.thumb-card[data-has="true"]').forEach(c => {
    c.classList.toggle('selected', thumbAllSelected);
  });
  document.querySelector('[onclick="selectAllThumbs()"]').textContent =
    thumbAllSelected ? 'Deselect All' : 'Select All';
  updateThumbSelCount();
}

function updateThumbSelCount() {
  const n = document.querySelectorAll('.thumb-card.selected').length;
  document.getElementById('thumb-sel-count').textContent = `${n} selected`;
}

async function downloadScanned() {
  const ids = [...document.querySelectorAll('.thumb-card.selected')]
    .map(el => parseInt(el.dataset.id));
  if (!ids.length) { alert('Select at least one item.'); return; }
  const body = { link: scannedLink, msg_ids: ids };
  if (currentMode === 'forward') {
    body.forward_mode = true;
    body.bot_token = document.getElementById('bot-token').value.trim();
    body.target_chat_id = document.getElementById('target-chat').value.trim();
    if (!body.bot_token || !body.target_chat_id) {
      alert('กรอก Bot Token และ Target Chat ID ในส่วน ⚙️ ตั้งค่าบอท ก่อนครับ'); return;
    }
  }
  const d = await post('/api/download/start_ids', body);
  if (d.ok) {
    document.getElementById('prog-card').classList.remove('hidden');
    startPolling();
  } else alert(d.error || 'Could not start.');
}

/* ─── Batch download ─── */
async function startBatch() {
  const link = document.getElementById('dl-link').value.trim();
  const count = parseInt(document.getElementById('dl-count').value) || 10;
  const offset = parseInt(document.getElementById('dl-offset').value) || 0;
  if (!link) { alert('Enter a Telegram link.'); return; }
  const body = { link, count, start_offset: offset };
  if (currentMode === 'forward') {
    body.forward_mode = true;
    body.bot_token = document.getElementById('bot-token').value.trim();
    body.target_chat_id = document.getElementById('target-chat').value.trim();
    if (!body.bot_token || !body.target_chat_id) {
      alert('กรอก Bot Token และ Target Chat ID ในส่วน ⚙️ ตั้งค่าบอท ก่อนครับ'); return;
    }
  }
  const d = await post('/api/download/start', body);
  if (d.ok) {
    document.getElementById('prog-card').classList.remove('hidden');
    startPolling();
  } else alert(d.error || 'Could not start.');
}

async function stopDownload() { await post('/api/download/stop', {}); }

function startPolling() {
  if (polling) clearInterval(polling);
  document.getElementById('prog-fill').classList.remove('done');
  polling = setInterval(pollStatus, 800);
}

async function pollStatus() {
  const d = await (await fetch('/api/download/status')).json();
  const pct = d.total ? Math.round(d.current / d.total * 100) : 0;
  const fill = document.getElementById('prog-fill');
  fill.style.width = pct + '%';
  document.getElementById('prog-label').textContent =
    `${d.downloaded} ok  ${d.skipped} skipped  ${d.current}/${d.total}`;
  document.getElementById('prog-file').textContent = d.current_file || '';

  const logBox = document.getElementById('log-box');
  logBox.innerHTML = (d.log || []).slice(-40).reverse().map(l => {
    let cls = 'log-info';
    if (l.includes('saved:') || l.includes('Done')) cls = 'log-ok';
    else if (l.includes('error') || l.includes('Fatal')) cls = 'log-err';
    return `<div class="${cls}">${escHtml(l)}</div>`;
  }).join('');

  if (!d.running) {
    clearInterval(polling); polling = null;
    if (pct >= 100 || d.downloaded > 0) fill.classList.add('done');
    loadFiles();
  }
}

/* ─── File manager ─── */
async function loadFiles() {
  const d = await (await fetch('/api/files')).json();
  const list = document.getElementById('file-list');
  const toolbar = document.getElementById('file-toolbar');
  const cntEl = document.getElementById('file-count');
  if (!d.files || !d.files.length) {
    list.innerHTML = '<p class="text-xs" style="color:var(--muted)">No files yet.</p>';
    toolbar.classList.add('hidden'); cntEl.textContent = ''; return;
  }
  cntEl.textContent = `(${d.files.length})`;
  toolbar.classList.remove('hidden');
  allFilesSelected = false;
  document.getElementById('btn-sel-all').textContent = 'Select All';
  list.innerHTML = d.files.map(f => `
    <div class="file-row" data-name="${escAttr(f.name)}" onclick="toggleFileRow(this)">
      <input type="checkbox" class="fcb" data-name="${escAttr(f.name)}"
             onclick="event.stopPropagation();toggleFileRow(this.closest('.file-row'))"/>
      <div class="flex-1 min-w-0">
        <p class="text-xs font-mono truncate" style="color:var(--text)">${escHtml(f.name)}</p>
        <p class="text-xs" style="color:var(--muted)">${escHtml(f.size)}</p>
      </div>
      <a href="/files/${encodeURIComponent(f.name)}" download onclick="event.stopPropagation()"
         class="btn btn-green" style="padding:5px 12px;font-size:.75rem">Save</a>
    </div>`).join('');
  updateSelCount();
}

function toggleFileRow(row) {
  const cb = row.querySelector('.fcb');
  cb.checked = !cb.checked;
  row.classList.toggle('selected', cb.checked);
  updateSelCount();
}

function updateSelCount() {
  const n = document.querySelectorAll('.fcb:checked').length;
  document.getElementById('sel-count').textContent = `${n} selected`;
}

function toggleSelectAll() {
  allFilesSelected = !allFilesSelected;
  document.querySelectorAll('.fcb').forEach(cb => {
    cb.checked = allFilesSelected;
    cb.closest('.file-row').classList.toggle('selected', allFilesSelected);
  });
  document.getElementById('btn-sel-all').textContent =
    allFilesSelected ? 'Deselect All' : 'Select All';
  updateSelCount();
}

function getSelectedFileNames() {
  return [...document.querySelectorAll('.fcb:checked')].map(cb => cb.dataset.name);
}

function downloadSelected() {
  const names = getSelectedFileNames();
  if (!names.length) { alert('Select at least one file.'); return; }
  names.forEach((name, i) => setTimeout(() => {
    const a = document.createElement('a');
    a.href = '/files/' + encodeURIComponent(name);
    a.download = name; document.body.appendChild(a); a.click();
    setTimeout(() => a.remove(), 1000);
  }, i * 400));
}

async function deleteSelected() {
  const names = getSelectedFileNames();
  if (!names.length) { alert('Select at least one file.'); return; }
  if (!confirm(`Delete ${names.length} file(s)?`)) return;
  const d = await post('/api/files/delete', { files: names });
  if (d.ok) loadFiles(); else alert(d.error || 'Delete failed.');
}

async function cleanUpAll() {
  if (!confirm('Delete ALL files from disk to free up Replit space?')) return;
  const d = await post('/api/files/delete_all', {});
  if (d.ok) { loadFiles(); } else alert(d.error || 'Failed.');
}

/* ─── Helpers ─── */
async function post(url, body) {
  const r = await fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
  return r.json();
}
function setMsg(id, text, color) {
  const el = document.getElementById(id);
  el.textContent = text;
  el.style.color = color === 'green' ? 'var(--green)' : color === 'red' ? 'var(--red)' : color === 'amber' ? 'var(--amber)' : 'var(--muted)';
  el.classList.toggle('hidden', !text);
}
function escHtml(s) { return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }
function escAttr(s) { return String(s).replace(/"/g,'&quot;').replace(/'/g,'&#39;'); }

checkAuth();
setInterval(checkAuth, 30000);
</script>
</body>
</html>
"""


# ── Flask app ──────────────────────────────────────────────────────────────────

def create_app(tg_client, loop: asyncio.AbstractEventLoop) -> Flask:
    app = Flask(__name__)

    download_state = {
        "running": False, "total": 0, "current": 0,
        "downloaded": 0, "skipped": 0,
        "current_file": "", "current_progress": 0,
        "log": [], "new_files": [],
    }

    def run_async(coro, timeout=30):
        return asyncio.run_coroutine_threadsafe(coro, loop).result(timeout=timeout)

    @app.route("/")
    def index():
        return render_template_string(INDEX_HTML, phone=PHONE_NUMBER)

    # ── Auth ──────────────────────────────────────────────────────────────────

    @app.route("/api/auth/status")
    def auth_status():
        if tg_client.credentials_missing:
            return jsonify({"authorized": False, "credentials_missing": True})
        if tg_client.is_authorized:
            try:
                user = run_async(tg_client.get_me(), timeout=10)
            except Exception:
                user = {}
            return jsonify({"authorized": True, "user": user, "credentials_missing": False})
        return jsonify({"authorized": False, "credentials_missing": False})

    @app.route("/api/auth/send_code", methods=["POST"])
    def send_code():
        data = request.get_json(force=True)
        phone = data.get("phone", "").strip()
        if not phone:
            return jsonify({"ok": False, "error": "Phone number required."})
        try:
            return jsonify(run_async(tg_client.send_code(phone), timeout=20))
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)})

    @app.route("/api/auth/sign_in", methods=["POST"])
    def sign_in():
        data = request.get_json(force=True)
        try:
            result = run_async(
                tg_client.sign_in(
                    data.get("phone", "").strip(),
                    data.get("code", "").strip(),
                    data.get("password", "").strip(),
                ), timeout=30
            )
            return jsonify(result)
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)})

    # ── Scan thumbnails ───────────────────────────────────────────────────────

    @app.route("/api/scan", methods=["POST"])
    def scan():
        if not tg_client.is_authorized:
            return jsonify({"error": "Not authenticated."})
        data = request.get_json(force=True)
        link = data.get("link", "").strip()
        count = max(1, min(int(data.get("count", 10)), 24))
        offset = int(data.get("start_offset", 0))
        try:
            dl = BatchDownloader(tg_client, download_state)
            items = run_async(dl.scan_thumbnails(link, count, offset), timeout=60)
            return jsonify({"items": items})
        except Exception as e:
            return jsonify({"error": str(e)})

    # ── Downloads ─────────────────────────────────────────────────────────────

    @app.route("/api/bot/validate", methods=["POST"])
    def bot_validate():
        data = request.get_json(force=True)
        token = data.get("bot_token", "").strip()
        chat  = data.get("target_chat_id", "").strip()
        if not token or not chat:
            return jsonify({"ok": False, "error": "กรอกข้อมูลให้ครบ"})
        fwd = BotForwarder(token, chat)
        ok, result = fwd.validate()
        if ok:
            return jsonify({"ok": True, "bot_username": result})
        return jsonify({"ok": False, "error": result})

    @app.route("/api/download/start", methods=["POST"])
    def download_start():
        if download_state["running"]:
            return jsonify({"ok": False, "error": "Already running."})
        if not tg_client.is_authorized:
            return jsonify({"ok": False, "error": "Not authenticated."})
        data = request.get_json(force=True)
        link = data.get("link", "").strip()
        count = max(1, min(int(data.get("count", 10)), 500))
        offset = int(data.get("start_offset", 0))
        if not link:
            return jsonify({"ok": False, "error": "Link required."})
        try:
            parse_link(link)
        except ValueError as e:
            return jsonify({"ok": False, "error": str(e)})
        forwarder = None
        if data.get("forward_mode"):
            token = data.get("bot_token", "").strip()
            chat  = data.get("target_chat_id", "").strip()
            if not token or not chat:
                return jsonify({"ok": False, "error": "Bot Token และ Target Chat ID จำเป็นสำหรับ Forward Mode"})
            forwarder = BotForwarder(token, chat)
        dl = BatchDownloader(tg_client, download_state)
        asyncio.run_coroutine_threadsafe(dl.run(link, count, offset, forwarder=forwarder), loop)
        return jsonify({"ok": True})

    @app.route("/api/download/start_ids", methods=["POST"])
    def download_start_ids():
        if download_state["running"]:
            return jsonify({"ok": False, "error": "Already running."})
        if not tg_client.is_authorized:
            return jsonify({"ok": False, "error": "Not authenticated."})
        data = request.get_json(force=True)
        link = data.get("link", "").strip()
        msg_ids = [int(x) for x in data.get("msg_ids", [])]
        if not link or not msg_ids:
            return jsonify({"ok": False, "error": "Link and msg_ids required."})
        try:
            parse_link(link)
        except ValueError as e:
            return jsonify({"ok": False, "error": str(e)})
        forwarder = None
        if data.get("forward_mode"):
            token = data.get("bot_token", "").strip()
            chat  = data.get("target_chat_id", "").strip()
            if not token or not chat:
                return jsonify({"ok": False, "error": "Bot Token และ Target Chat ID จำเป็นสำหรับ Forward Mode"})
            forwarder = BotForwarder(token, chat)
        dl = BatchDownloader(tg_client, download_state)
        asyncio.run_coroutine_threadsafe(dl.run_specific(link, msg_ids, forwarder=forwarder), loop)
        return jsonify({"ok": True})

    @app.route("/api/download/stop", methods=["POST"])
    def download_stop():
        download_state["running"] = False
        return jsonify({"ok": True})

    @app.route("/api/download/status")
    def download_status():
        return jsonify(download_state)

    # ── Files ─────────────────────────────────────────────────────────────────

    @app.route("/api/files")
    def list_files():
        files = []
        if DOWNLOADS_DIR.exists():
            for f in sorted(DOWNLOADS_DIR.iterdir(), key=lambda x: x.stat().st_mtime, reverse=True):
                if f.is_file():
                    files.append({"name": f.name, "size": _fmt_size(f.stat().st_size)})
        return jsonify({"files": files})

    @app.route("/files/<path:filename>")
    def serve_file(filename):
        return send_from_directory(str(DOWNLOADS_DIR.absolute()), filename, as_attachment=True)

    @app.route("/api/files/delete", methods=["POST"])
    def delete_files():
        names = request.get_json(force=True).get("files", [])
        deleted = 0
        for name in names:
            p = DOWNLOADS_DIR / Path(name).name
            if p.is_file():
                p.unlink(); deleted += 1
        return jsonify({"ok": True, "deleted": deleted})

    @app.route("/api/files/delete_all", methods=["POST"])
    def delete_all():
        deleted = 0
        for f in DOWNLOADS_DIR.iterdir():
            if f.is_file():
                f.unlink(); deleted += 1
        return jsonify({"ok": True, "deleted": deleted})

    # ── Clone Topic ───────────────────────────────────────────────────────────

    @app.route("/api/clone/start", methods=["POST"])
    def clone_start():
        if download_state["running"]:
            return jsonify({"ok": False, "error": "มีงานค้างอยู่ รอให้เสร็จก่อนครับ"})
        if not tg_client.is_authorized:
            return jsonify({"ok": False, "error": "Not authenticated."})
        data = request.get_json(force=True)
        link  = data.get("link", "").strip()
        token = data.get("bot_token", "").strip()
        chat  = data.get("target_chat_id", "").strip()
        max_gap = int(data.get("max_gap", 30))
        if not link:
            return jsonify({"ok": False, "error": "Link required."})
        if not token or not chat:
            return jsonify({"ok": False, "error": "Bot Token และ Target Chat ID จำเป็น"})
        try:
            parse_link(link)
        except ValueError as e:
            return jsonify({"ok": False, "error": str(e)})
        forwarder = BotForwarder(token, chat)
        dl = BatchDownloader(tg_client, download_state)
        asyncio.run_coroutine_threadsafe(dl.clone_topic(link, forwarder, max_gap), loop)
        return jsonify({"ok": True})

    # ── Health check (required by Render) ─────────────────────────────────────

    @app.route("/healthz")
    def healthz():
        return jsonify({"status": "ok"})

    return app
