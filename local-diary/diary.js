/**
 * diary.js — Evan Diary Core Logic
 * Uses File System Access API (Chrome/Edge 86+)
 */

/* ════════════════════════════════════════════════
   Config — loaded from config.json at startup
   ════════════════════════════════════════════════ */

/**
 * AppConfig holds runtime configuration.
 * Populated by loadConfig() before init() runs.
 * API credentials have NO fallback defaults (security).
 */
const AppConfig = {
  ai: {
    apiUrl:    null,   // required — no default
    apiKey:    null,   // required — no default
    model:     'glm-5',
    maxTokens: 4096,
  },
  editor: {
    autoSaveIntervalMs: 30_000,
    language:           'zh-CN',
  },
};

/**
 * Fetch and merge config.json into AppConfig.
 * Missing or unreadable file is silently ignored (non-fatal).
 * Missing apiUrl/apiKey are left as null — AI features will show a clear error.
 */
async function loadConfig() {
  try {
    const res = await fetch('./config.json', { cache: 'no-store' });
    if (!res.ok) return; // file not found — use defaults

    const cfg = await res.json();

    // AI section — only merge fields that are present and non-empty
    if (cfg.ai) {
      if (cfg.ai.apiUrl    ) AppConfig.ai.apiUrl     = cfg.ai.apiUrl;
      if (cfg.ai.apiKey    ) AppConfig.ai.apiKey      = cfg.ai.apiKey;
      if (cfg.ai.model     ) AppConfig.ai.model       = cfg.ai.model;
      if (cfg.ai.maxTokens ) AppConfig.ai.maxTokens   = cfg.ai.maxTokens;
    }

    // Editor section
    if (cfg.editor) {
      if (cfg.editor.autoSaveIntervalMs) AppConfig.editor.autoSaveIntervalMs = cfg.editor.autoSaveIntervalMs;
      if (cfg.editor.language          ) AppConfig.editor.language            = cfg.editor.language;
    }

    console.info('[Diary] config.json loaded.');
  } catch (err) {
    console.warn('[Diary] config.json not loaded:', err.message);
  }
}

/* ── State ── */
const State = {
  dirHandle:     null,   // FileSystemDirectoryHandle
  currentFile:   null,   // filename string (e.g. "2026-03-19.md")
  fileHandle:    null,   // FileSystemFileHandle for current file
  isDirty:       false,
  autoSaveTimer: null,
  allDiaries:    [],     // [{name, preview}]
};

/* ── DOM References ── */
const $ = id => document.getElementById(id);
const editor       = $('editor');
const preview      = $('preview');
const diaryList    = $('diary-list');
const searchBox    = $('search-box');
const editorFile   = $('editor-filename');
const statusDot    = $('status-dot');
const statusSave   = $('status-save');
const statusWords  = $('status-words');
const statusFile   = $('status-file');
const statusMsg    = $('status-message');
const dropOverlay  = $('drop-overlay');

/* ════════════════════════════════════════════════
   Directory & File System
   ════════════════════════════════════════════════ */

/* ════════════════════════════════════════════════
   IndexedDB — persist FileSystemDirectoryHandle
   ════════════════════════════════════════════════ */

const IDB_NAME    = 'evan-diary';
const IDB_STORE   = 'handles';
const IDB_KEY     = 'dir';

function openIDB() {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(IDB_NAME, 1);
    req.onupgradeneeded = e => e.target.result.createObjectStore(IDB_STORE);
    req.onsuccess = e => resolve(e.target.result);
    req.onerror   = e => reject(e.target.error);
  });
}

async function saveHandleToIDB(handle) {
  try {
    const db  = await openIDB();
    const tx  = db.transaction(IDB_STORE, 'readwrite');
    tx.objectStore(IDB_STORE).put(handle, IDB_KEY);
    await new Promise((res, rej) => { tx.oncomplete = res; tx.onerror = rej; });
    db.close();
  } catch (_) { /* silently ignore */ }
}

async function loadHandleFromIDB() {
  try {
    const db = await openIDB();
    const tx = db.transaction(IDB_STORE, 'readonly');
    const req = tx.objectStore(IDB_STORE).get(IDB_KEY);
    const handle = await new Promise((res, rej) => { req.onsuccess = () => res(req.result); req.onerror = rej; });
    db.close();
    return handle || null;
  } catch (_) { return null; }
}

/**
 * Prompt user to pick a directory via File System Access API.
 * Persists the handle to IndexedDB so it can be restored after page reload.
 */
async function selectDirectory() {
  if (!('showDirectoryPicker' in window)) {
    updateStatus('您的浏览器不支持 File System Access API，请使用 Chrome 86+', 'error');
    return;
  }
  try {
    const handle = await window.showDirectoryPicker({ mode: 'readwrite' });
    State.dirHandle = handle;
    await saveHandleToIDB(handle);
    updateStatus(`已选择目录：${handle.name}`);
    await loadDiaryList();
  } catch (err) {
    if (err.name !== 'AbortError') {
      updateStatus('目录选择失败：' + err.message, 'error');
    }
  }
}

/**
 * Try to restore the last directory handle from IndexedDB.
 * If permission has expired, prompt the user to re-grant via a click.
 */
async function restoreDirectory() {
  const handle = await loadHandleFromIDB();
  if (!handle) return;

  try {
    // Check current permission state
    const perm = await handle.queryPermission({ mode: 'readwrite' });
    if (perm === 'granted') {
      State.dirHandle = handle;
      updateStatus(`已恢复目录：${handle.name}`);
      await loadDiaryList();
      return;
    }

    // Permission needs user gesture to re-grant — show a one-time prompt banner
    showRestoreBanner(handle);
  } catch (_) { /* handle may be stale */ }
}

/**
 * Show a non-intrusive banner asking the user to click to restore directory access.
 */
function showRestoreBanner(handle) {
  const banner = document.createElement('div');
  banner.id = 'restore-banner';
  banner.innerHTML = `
    <span>上次目录：<b>${handle.name}</b></span>
    <button id="btn-restore-dir">点击恢复访问</button>
    <button id="btn-dismiss-banner" title="关闭">✕</button>`;
  document.getElementById('toolbar').appendChild(banner);

  document.getElementById('btn-restore-dir').addEventListener('click', async () => {
    try {
      const perm = await handle.requestPermission({ mode: 'readwrite' });
      if (perm === 'granted') {
        State.dirHandle = handle;
        await saveHandleToIDB(handle);
        updateStatus(`已恢复目录：${handle.name}`);
        await loadDiaryList();
        banner.remove();
      } else {
        updateStatus('目录权限被拒绝', 'error');
      }
    } catch (err) {
      updateStatus('恢复失败：' + err.message, 'error');
    }
  });

  document.getElementById('btn-dismiss-banner').addEventListener('click', () => banner.remove());
}

/**
 * Scan the selected directory for .md files, sort by date descending.
 */
async function loadDiaryList() {
  if (!State.dirHandle) return;

  const entries = [];
  try {
    for await (const [name, handle] of State.dirHandle.entries()) {
      if (handle.kind === 'file' && name.endsWith('.md')) {
        let preview = '';
        try {
          const file = await handle.getFile();
          const text = await file.text();
          preview = text.trim().replace(/^#+\s*/mg, '').split('\n').find(l => l.trim()) || '';
          preview = preview.slice(0, 60);
        } catch (_) {}
        entries.push({ name, preview });
      }
    }
  } catch (err) {
    updateStatus('读取目录失败：' + err.message, 'error');
    return;
  }

  // Sort by filename (date) descending
  entries.sort((a, b) => b.name.localeCompare(a.name));
  State.allDiaries = entries;
  renderDiaryList(entries);
}

/* ════════════════════════════════════════════════
   List Rendering
   ════════════════════════════════════════════════ */

function renderDiaryList(entries) {
  if (entries.length === 0) {
    diaryList.innerHTML = `
      <div class="diary-empty">
        <span>📝</span>
        暂无日记<br/>
        点击「新建」创建今天的日记
      </div>`;
    return;
  }

  const items = entries.map(({ name, preview: excerpt }) => {
    const item = document.createElement('div');
    item.className = name === State.currentFile ? 'diary-item active' : 'diary-item';
    item.dataset.name = name;
    const date = document.createElement('div');
    date.className = 'diary-item-date';
    date.textContent = name.replace(/\.md$/, '');
    const text = document.createElement('div');
    text.className = 'diary-item-preview';
    text.textContent = excerpt || '（空白日记）';
    item.append(date, text);
    item.addEventListener('click', () => openDiary(name));
    return item;
  });
  diaryList.replaceChildren(...items);
}

/* ════════════════════════════════════════════════
   CRUD Operations
   ════════════════════════════════════════════════ */

/**
 * Get all today's diary filenames sorted descending, and compute next filename.
 * First file: YYYY-MM-DD.md, second: YYYY-MM-DD-2.md, etc.
 */
async function getTodayDiaryFiles(today) {
  const files = [];
  for await (const [name] of State.dirHandle.entries()) {
    if (name.startsWith(today) && name.endsWith('.md')) {
      files.push(name);
    }
  }
  files.sort((a, b) => b.localeCompare(a));
  return files;
}

function getNextTodayFilename(today, existingFiles) {
  if (existingFiles.length === 0) return `${today}.md`;
  // Find max index among existing files
  let maxIdx = 1;
  for (const name of existingFiles) {
    const base = name.slice(0, -3); // strip .md
    if (base === today) {
      maxIdx = Math.max(maxIdx, 1);
    } else {
      const match = base.match(new RegExp(`^${today}-(\\d+)$`));
      if (match) maxIdx = Math.max(maxIdx, parseInt(match[1], 10));
    }
  }
  const nextIdx = maxIdx + 1;
  return `${today}-${nextIdx}.md`;
}

/**
 * Create a new diary file for today (supports multiple per day) and open it.
 */
async function newDiary() {
  if (!State.dirHandle) {
    await selectDirectory();
    if (!State.dirHandle) return;
  }

  const today = getTodayStr();
  const defaultContent = `# ${today}\n\n`;

  try {
    const existingFiles = await getTodayDiaryFiles(today);
    const filename = getNextTodayFilename(today, existingFiles);

    const fileHandle = await State.dirHandle.getFileHandle(filename, { create: true });
    const writable = await fileHandle.createWritable();
    await writable.write(defaultContent);
    await writable.close();

    State.fileHandle = fileHandle;
    State.currentFile = filename;
    editor.value = defaultContent;
    markClean();
    renderPreview();
    updateEditorUI();
    await loadDiaryList();
    scrollToActive();
    updateStatus(`已创建 ${filename}`);
  } catch (err) {
    updateStatus('创建日记失败：' + err.message, 'error');
  }
}

/**
 * Open a diary by filename from the sidebar.
 */
async function openDiary(name) {
  if (!State.dirHandle) return;

  // Save current before switching
  if (State.isDirty) {
    if (!(await saveDiary())) return;
  }

  try {
    const fileHandle = await State.dirHandle.getFileHandle(name);
    const file = await fileHandle.getFile();
    const text = await file.text();

    State.fileHandle  = fileHandle;
    State.currentFile = name;
    editor.value = text;
    markClean();
    renderPreview();
    updateEditorUI();
    renderDiaryList(filterDiaries(searchBox.value));
    scrollToActive();
    editor.focus();
    updateStatus(`已打开 ${name}`);
  } catch (err) {
    updateStatus('打开失败：' + err.message, 'error');
  }
}

/**
 * Save current editor content to the file.
 * If no file is open, prompt user to save as today's diary.
 */
let pendingSave = null;

function saveDiary() {
  if (pendingSave) return pendingSave;
  pendingSave = writeDiary().finally(() => { pendingSave = null; });
  return pendingSave;
}

async function writeDiary() {
  const draft = editor.value;
  if (!State.fileHandle) {
    const confirmed = confirm('当前没有打开的文件。\n是否将内容保存为今天的日记？');
    if (!confirmed) return false;

    if (!State.dirHandle) {
      await selectDirectory();
      if (!State.dirHandle) return false;
    }

    const today = getTodayStr();
    const defaultContent = `# ${today}\n\n`;

    try {
      // Find today's files (descending), take the latest one to append
      const todayFiles = await getTodayDiaryFiles(today);

      let fileHandle;
      let filename;
      let finalContent;

      if (todayFiles.length === 0) {
        // No file today — create new
        filename = `${today}.md`;
        fileHandle = await State.dirHandle.getFileHandle(filename, { create: true });
        finalContent = defaultContent + draft;
      } else {
        // Append to the latest existing file
        filename = todayFiles[0]; // descending sort, first = latest
        fileHandle = await State.dirHandle.getFileHandle(filename);
        const file = await fileHandle.getFile();
        const existing = await file.text();
        finalContent = existing + '\n\n' + draft;
      }

      setStatusSaving();
      const writable = await fileHandle.createWritable();
      await writable.write(finalContent);
      await writable.close();

      // Update state to reflect the now-open file
      State.fileHandle = fileHandle;
      State.currentFile = filename;
      if (editor.value === draft) {
        editor.value = finalContent;
        markClean();
      }
      renderPreview();
      updateEditorUI();
      await loadDiaryList();
      scrollToActive();
      updateStatus(`已保存到 ${filename}`);
      return !State.isDirty;
    } catch (err) {
      updateStatus('保存失败：' + err.message, 'error');
      return false;
    }
  }

  setStatusSaving();
  try {
    const writable = await State.fileHandle.createWritable();
    await writable.write(draft);
    await writable.close();
    if (editor.value === draft) markClean();
    updateStatus(`已保存 ${State.currentFile}`);
    // Refresh preview entry in sidebar
    await refreshCurrentPreview();
    return !State.isDirty;
  } catch (err) {
    updateStatus('保存失败：' + err.message, 'error');
    return false;
  }
}

/**
 * Refresh the preview text for the current file in the list.
 */
async function refreshCurrentPreview() {
  if (!State.currentFile) return;
  const text = editor.value.trim().replace(/^#+\s*/mg, '').split('\n').find(l => l.trim()) || '';
  const idx = State.allDiaries.findIndex(d => d.name === State.currentFile);
  if (idx >= 0) {
    State.allDiaries[idx].preview = text.slice(0, 60);
    renderDiaryList(filterDiaries(searchBox.value));
  }
}

/* ════════════════════════════════════════════════
   Auto-Save
   ════════════════════════════════════════════════ */

function setupAutoSave() {
  // Save on blur
  editor.addEventListener('blur', () => {
    if (State.isDirty) saveDiary();
  });

  // Auto-save every N seconds if dirty (interval from config)
  State.autoSaveTimer = setInterval(() => {
    if (State.isDirty) saveDiary();
  }, AppConfig.editor.autoSaveIntervalMs);
}

/* ════════════════════════════════════════════════
   Preview Rendering
   ════════════════════════════════════════════════ */

let previewRevision = 0;
const previewImages = new Set();

function renderPreview() {
  const revision = ++previewRevision;
  for (const original of previewImages) URL.revokeObjectURL(original);
  previewImages.clear();
  const md = editor.value;
  if (!md.trim()) {
    preview.innerHTML = `<div style="color:var(--muted); font-size:13px; padding: 10px 0; font-family: var(--font-mono);">开始编写后，Markdown 预览将在此处实时显示...</div>`;
    return;
  }
  try {
    const fragment = DOMPurify.sanitize(marked.parse(md), {
      RETURN_DOM_FRAGMENT: true,
      USE_PROFILES: { html: true },
      FORBID_TAGS: ['style', 'form', 'input', 'button'],
      FORBID_ATTR: ['srcset', 'style'],
    });
    for (const image of fragment.querySelectorAll('img')) {
      const src = image.getAttribute('src') || '';
      image.removeAttribute('src');
      const local = src.match(/^images\/([A-Za-z0-9_.-]+)$/);
      if (local && State.dirHandle) loadPreviewImage(image, local[1], revision);
    }
    preview.replaceChildren(fragment);
  } catch (err) {
    preview.textContent = md;
  }
}

async function loadPreviewImage(image, name, revision) {
  try {
    const directory = await State.dirHandle.getDirectoryHandle('images');
    const handle = await directory.getFileHandle(name);
    const file = await handle.getFile();
    if (previewRevision !== revision) return;
    const url = URL.createObjectURL(file);
    previewImages.add(url);
    image.src = url;
  } catch {
    // The selected diary directory may not contain the attachment.
  }
}

/* ════════════════════════════════════════════════
   Search
   ════════════════════════════════════════════════ */

function filterDiaries(query) {
  if (!query.trim()) return State.allDiaries;
  const q = query.toLowerCase();
  return State.allDiaries.filter(d =>
    d.name.toLowerCase().includes(q) ||
    d.preview.toLowerCase().includes(q)
  );
}

function searchDiaries(query) {
  renderDiaryList(filterDiaries(query));
}

/* ════════════════════════════════════════════════
   Image Paste & Drop
   ════════════════════════════════════════════════ */

/**
 * Handle image paste or drop.
 * Saves image to images/ subdirectory and inserts Markdown syntax.
 */
async function handleImagePaste(e) {
  const items = (e.clipboardData || e.dataTransfer)?.items;
  if (!items) return;

  for (const item of items) {
    if (!item.type.startsWith('image/')) continue;

    if (!State.dirHandle) {
      updateStatus('请先选择日记目录', 'error');
      return;
    }

    e.preventDefault();
    const blob = item.getAsFile();
    if (!blob) continue;

    try {
      // Ensure images/ dir exists
      const imagesDir = await State.dirHandle.getDirectoryHandle('images', { create: true });
      const ext = blob.type.split('/')[1] || 'png';
      const imgName = `${Date.now()}.${ext}`;
      const imgHandle = await imagesDir.getFileHandle(imgName, { create: true });
      const writable = await imgHandle.createWritable();
      await writable.write(await blob.arrayBuffer());
      await writable.close();

      // Insert Markdown image syntax at cursor
      const mdSyntax = `![image](images/${imgName})`;
      insertAtCursor(editor, mdSyntax);
      renderPreview();
      markDirty();
      updateStatus(`图片已存储：images/${imgName}`);
    } catch (err) {
      updateStatus('图片存储失败：' + err.message, 'error');
    }
    break;
  }
}

function insertAtCursor(textarea, text) {
  const start = textarea.selectionStart;
  const end   = textarea.selectionEnd;
  textarea.value = textarea.value.slice(0, start) + text + textarea.value.slice(end);
  textarea.selectionStart = textarea.selectionEnd = start + text.length;
}

/* ════════════════════════════════════════════════
   Status Bar
   ════════════════════════════════════════════════ */

function updateStatus(msg, type = 'ok') {
  statusMsg.textContent = msg;
  statusMsg.className = type === 'error' ? 'error' : '';
  if (type !== 'error') {
    setTimeout(() => { statusMsg.textContent = ''; }, 4000);
  }
}

function setStatusSaving() {
  statusDot.className = 'status-dot saving';
  statusSave.textContent = '保存中…';
}

function markDirty() {
  State.isDirty = true;
  statusDot.className = 'status-dot saving';
  statusSave.textContent = '未保存';
}

function markClean() {
  State.isDirty = false;
  statusDot.className = 'status-dot';
  statusSave.textContent = '已保存';
}

function updateWordCount() {
  const text = editor.value;
  // Count CJK chars + western words
  const cjk = (text.match(/[\u4e00-\u9fff\u3400-\u4dbf]/g) || []).length;
  const words = (text.match(/[a-zA-Z]+/g) || []).length;
  statusWords.textContent = cjk + words;
}

function updateEditorUI() {
  if (State.currentFile) {
    editorFile.textContent = State.currentFile;
    editorFile.className = 'active';
    statusFile.textContent = State.currentFile;
  } else {
    editorFile.textContent = '未打开文件';
    editorFile.className = '';
    statusFile.textContent = '—';
  }
}

function scrollToActive() {
  const active = diaryList.querySelector('.diary-item.active');
  if (active) active.scrollIntoView({ block: 'nearest' });
}

/* ════════════════════════════════════════════════
   Helpers
   ════════════════════════════════════════════════ */

function getTodayStr() {
  const d = new Date();
  const pad = n => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

/* ════════════════════════════════════════════════
   AI Format
   ════════════════════════════════════════════════ */

async function formatWithAI() {
  const content = editor.value;
  if (!content.trim()) {
    updateStatus('没有可排版的内容', 'error');
    return;
  }

  // Guard: require config
  if (!AppConfig.ai.apiUrl || !AppConfig.ai.apiKey) {
    updateStatus('AI 排版未配置：请在 config.json 中填写 ai.apiUrl 和 ai.apiKey', 'error');
    return;
  }

  const btnFormat = $('btn-format');
  // Set loading state
  btnFormat.disabled = true;
  btnFormat.innerHTML = '<span class="btn-icon">✨</span> 排版中…';

  // Auto-save if dirty and file is open
  if (State.isDirty && State.fileHandle) {
    if (!(await saveDiary())) return;
  }

  try {
    const response = await fetch(AppConfig.ai.apiUrl, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${AppConfig.ai.apiKey}`,
      },
      body: JSON.stringify({
        model: AppConfig.ai.model,
        max_tokens: AppConfig.ai.maxTokens,
        messages: [
          {
            role: 'system',
            content: `你是一个专业的写作排版助手。用户会给你一段日记或文字内容，你需要：
1. 保留所有原有内容和信息，不增删实质内容
2. 将大段连续文字分成逻辑清晰的段落
3. 适当添加 Markdown 标题层级（## / ###）来组织结构
4. 修正明显的标点符号问题
5. 只输出排版后的 Markdown 文本，不要任何解释或说明`
          },
          {
            role: 'user',
            content: editor.value
          }
        ]
      })
    });

    if (!response.ok) {
      const errText = await response.text().catch(() => '');
      throw new Error(`HTTP ${response.status}: ${response.statusText}${errText ? ' — ' + errText.slice(0, 200) : ''}`);
    }

    const data = await response.json();
    const formatted = data.choices?.[0]?.message?.content;
    if (!formatted) throw new Error('返回数据异常，未获取到排版内容');

    editor.value = formatted;
    markDirty();
    renderPreview();
    updateWordCount();
    updateStatus('排版完成');
  } catch (err) {
    updateStatus('排版失败：' + err.message, 'error');
  } finally {
    // Restore button
    btnFormat.disabled = false;
    btnFormat.innerHTML = '<span class="btn-icon">✨</span> 排版';
  }
}

/* ════════════════════════════════════════════════
   Keyboard Shortcuts
   ════════════════════════════════════════════════ */

function setupKeyboardShortcuts() {
  document.addEventListener('keydown', e => {
    if (e.ctrlKey || e.metaKey) {
      if (e.key === 's') {
        e.preventDefault();
        saveDiary();
      } else if (e.key === 'n') {
        e.preventDefault();
        newDiary();
      } else if (e.shiftKey && e.key === 'F') {
        e.preventDefault();
        formatWithAI();
      }
    }
  });
}

/* ════════════════════════════════════════════════
   Drag-and-Drop visual feedback
   ════════════════════════════════════════════════ */

function setupDragDrop() {
  let dragCounter = 0;

  document.addEventListener('dragenter', e => {
    if ([...e.dataTransfer.items].some(i => i.type.startsWith('image/'))) {
      dragCounter++;
      dropOverlay.classList.add('visible');
    }
  });

  document.addEventListener('dragleave', () => {
    dragCounter--;
    if (dragCounter <= 0) {
      dragCounter = 0;
      dropOverlay.classList.remove('visible');
    }
  });

  document.addEventListener('dragover', e => e.preventDefault());

  document.addEventListener('drop', async e => {
    e.preventDefault();
    dragCounter = 0;
    dropOverlay.classList.remove('visible');
    await handleImagePaste(e);
  });
}

/* ════════════════════════════════════════════════
   Initialisation
   ════════════════════════════════════════════════ */

async function init() {
  // Load config.json first — must complete before anything else
  await loadConfig();

  // Configure marked
  marked.setOptions({
    breaks: true,
    gfm: true,
  });

  // Toolbar buttons
  $('btn-new').addEventListener('click', newDiary);
  $('btn-open-dir').addEventListener('click', selectDirectory);
  $('btn-save').addEventListener('click', saveDiary);
  $('btn-format').addEventListener('click', formatWithAI);
  // btn-sync is handled in sync.js

  // Editor events
  editor.addEventListener('input', () => {
    markDirty();
    renderPreview();
    updateWordCount();
  });

  // Paste for images
  editor.addEventListener('paste', handleImagePaste);

  // Search
  searchBox.addEventListener('input', e => searchDiaries(e.target.value));

  // Auto-save
  setupAutoSave();

  // Keyboard shortcuts
  setupKeyboardShortcuts();

  // Drag-and-drop
  setupDragDrop();

  // Restore last directory handle from IndexedDB
  await restoreDirectory();

  // Initial state
  updateEditorUI();
  updateWordCount();
}

document.addEventListener('DOMContentLoaded', init);
