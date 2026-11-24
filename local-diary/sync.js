/**
 * sync.js — Evan Diary Sync Module
 * Supports: 语雀 (Yuque) → 飞书 (Feishu) → Notion
 */

/* ════════════════════════════════════════════════
   Config Storage
   ════════════════════════════════════════════════ */

const SYNC_CONFIG_KEY = 'diary_sync_config';

/**
 * Load sync configuration from localStorage.
 * @returns {{
 *   yuque:  { token: string, login: string, slug: string, docId: string },
 *   feishu: { appId: string, appSecret: string, docToken: string },
 *   notion: { token: string, pageId: string }
 * }}
 */
function loadSyncConfig() {
  try {
    const raw = localStorage.getItem(SYNC_CONFIG_KEY);
    return raw ? JSON.parse(raw) : getDefaultConfig();
  } catch (_) {
    return getDefaultConfig();
  }
}

function getDefaultConfig() {
  return {
    yuque:  { token: '', login: '', slug: '', docId: '' },
    feishu: { appId: '', appSecret: '', docToken: '' },
    notion: { token: '', pageId: '' },
  };
}

/**
 * Save sync configuration to localStorage.
 */
function saveSyncConfig(config) {
  localStorage.setItem(SYNC_CONFIG_KEY, JSON.stringify(config));
}

/* ════════════════════════════════════════════════
   Dialog UI
   ════════════════════════════════════════════════ */

/**
 * Show the sync configuration dialog.
 */
function showSyncDialog() {
  const cfg = loadSyncConfig();

  // Remove existing dialog if any
  const existing = document.getElementById('sync-modal-overlay');
  if (existing) existing.remove();

  const overlay = document.createElement('div');
  overlay.className = 'modal-overlay';
  overlay.id = 'sync-modal-overlay';

  overlay.innerHTML = `
    <div class="modal" role="dialog" aria-modal="true" aria-label="同步配置">
      <div class="modal-title">⟳ 云端同步配置</div>

      <!-- 语雀 -->
      <div class="modal-section">
        <div class="modal-section-title">语雀 Yuque</div>
        <input class="modal-input" id="yuque-token"  placeholder="Personal Token" type="password" value="${cfg.yuque.token}" style="margin-bottom:6px;" />
        <input class="modal-input" id="yuque-login"  placeholder="用户名 / 组织 login" value="${cfg.yuque.login}" style="margin-bottom:6px;" />
        <input class="modal-input" id="yuque-slug"   placeholder="知识库 slug" value="${cfg.yuque.slug}" style="margin-bottom:6px;" />
        <input class="modal-input" id="yuque-docid"  placeholder="文档 ID（留空则新建）" value="${cfg.yuque.docId}" />
      </div>

      <!-- 飞书 -->
      <div class="modal-section">
        <div class="modal-section-title">飞书 Feishu</div>
        <input class="modal-input" id="feishu-appid"     placeholder="App ID" type="password" value="${cfg.feishu.appId}" style="margin-bottom:6px;" />
        <input class="modal-input" id="feishu-appsecret" placeholder="App Secret" value="${cfg.feishu.appSecret}" style="margin-bottom:6px;" />
        <input class="modal-input" id="feishu-doctoken"  placeholder="文档 Token" value="${cfg.feishu.docToken}" />
      </div>

      <!-- Notion -->
      <div class="modal-section">
        <div class="modal-section-title">Notion</div>
        <input class="modal-input" id="notion-token"  placeholder="Integration Token" type="password" value="${cfg.notion.token}" style="margin-bottom:6px;" />
        <input class="modal-input" id="notion-pageid" placeholder="Page ID" value="${cfg.notion.pageId}" />
      </div>

      <div class="modal-actions">
        <button class="btn" id="sync-cancel-btn">取消</button>
        <button class="btn btn-primary" id="sync-save-btn">保存配置</button>
        <button class="btn btn-sync" id="sync-now-btn">立即同步</button>
      </div>
    </div>
  `;

  document.body.appendChild(overlay);

  // Close on overlay click
  overlay.addEventListener('click', e => {
    if (e.target === overlay) closeSyncDialog();
  });

  document.getElementById('sync-cancel-btn').addEventListener('click', closeSyncDialog);

  document.getElementById('sync-save-btn').addEventListener('click', () => {
    persistSyncConfig();
    closeSyncDialog();
    updateStatus('同步配置已保存');
  });

  document.getElementById('sync-now-btn').addEventListener('click', async () => {
    persistSyncConfig();
    closeSyncDialog();
    await syncAll();
  });

  // Focus first input
  document.getElementById('yuque-token').focus();
}

function closeSyncDialog() {
  const overlay = document.getElementById('sync-modal-overlay');
  if (overlay) overlay.remove();
}

/** Read form values and save to localStorage. */
function persistSyncConfig() {
  const cfg = {
    yuque: {
      token:  document.getElementById('yuque-token')?.value.trim()  || '',
      login:  document.getElementById('yuque-login')?.value.trim()  || '',
      slug:   document.getElementById('yuque-slug')?.value.trim()   || '',
      docId:  document.getElementById('yuque-docid')?.value.trim()  || '',
    },
    feishu: {
      appId:     document.getElementById('feishu-appid')?.value.trim()     || '',
      appSecret: document.getElementById('feishu-appsecret')?.value.trim() || '',
      docToken:  document.getElementById('feishu-doctoken')?.value.trim()  || '',
    },
    notion: {
      token:  document.getElementById('notion-token')?.value.trim()  || '',
      pageId: document.getElementById('notion-pageid')?.value.trim() || '',
    },
  };
  saveSyncConfig(cfg);
}

/* ════════════════════════════════════════════════
   Helpers
   ════════════════════════════════════════════════ */

function updateStatus(msg, type = 'ok') {
  // delegate to diary.js if available, else console
  const el = document.getElementById('status-message');
  if (el) {
    el.textContent = msg;
    el.className = type === 'error' ? 'error' : '';
    if (type !== 'error') setTimeout(() => { el.textContent = ''; }, 5000);
  } else {
    console.log('[Sync]', msg);
  }
}

/** Get current editor content */
function getCurrentContent() {
  const el = document.getElementById('editor');
  return el ? el.value : '';
}

/** Get current filename as title */
function getCurrentTitle() {
  const el = document.getElementById('editor-filename');
  return el ? el.textContent.replace('.md', '') : 'diary';
}

/* ════════════════════════════════════════════════
   语雀 (Yuque) Sync
   ════════════════════════════════════════════════ */

/**
 * Sync content to 语雀 doc.
 * API: https://www.yuque.com/api/v2/repos/{login}/{slug}/docs
 */
async function syncToYuque(content, title) {
  const cfg = loadSyncConfig().yuque;
  if (!cfg.token || !cfg.login || !cfg.slug) {
    throw new Error('语雀：Token / login / slug 未配置');
  }

  const headers = {
    'Content-Type': 'application/json',
    'X-Auth-Token': cfg.token,
  };

  const body = {
    title,
    body: content,
    format: 'markdown',
    public: 0,
  };

  let url;
  let method;

  if (cfg.docId) {
    // Update existing doc
    url    = `https://www.yuque.com/api/v2/repos/${cfg.login}/${cfg.slug}/docs/${cfg.docId}`;
    method = 'PUT';
  } else {
    // Create new doc
    url    = `https://www.yuque.com/api/v2/repos/${cfg.login}/${cfg.slug}/docs`;
    method = 'POST';
  }

  const res = await fetch(url, { method, headers, body: JSON.stringify(body) });
  if (!res.ok) {
    const errText = await res.text().catch(() => res.statusText);
    throw new Error(`语雀 ${res.status}: ${errText}`);
  }

  const data = await res.json();

  // If we just created, persist the new doc id for future updates
  if (!cfg.docId && data?.data?.id) {
    const fullCfg = loadSyncConfig();
    fullCfg.yuque.docId = String(data.data.id);
    saveSyncConfig(fullCfg);
  }

  return data;
}

/* ════════════════════════════════════════════════
   飞书 (Feishu) Sync
   ════════════════════════════════════════════════ */

/**
 * Get a tenant_access_token from Feishu.
 */
async function getFeishuToken(appId, appSecret) {
  const res = await fetch('https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ app_id: appId, app_secret: appSecret }),
  });
  if (!res.ok) throw new Error(`飞书鉴权失败 ${res.status}`);
  const data = await res.json();
  if (data.code !== 0) throw new Error(`飞书鉴权错误：${data.msg}`);
  return data.tenant_access_token;
}

/**
 * Sync content to a Feishu document (docx).
 * Uses the Feishu Docs v1 API to update raw content.
 */
async function syncToFeishu(content, title) {
  const cfg = loadSyncConfig().feishu;
  if (!cfg.appId || !cfg.appSecret || !cfg.docToken) {
    throw new Error('飞书：AppID / AppSecret / docToken 未配置');
  }

  const accessToken = await getFeishuToken(cfg.appId, cfg.appSecret);
  const headers = {
    'Content-Type': 'application/json',
    'Authorization': `Bearer ${accessToken}`,
  };

  // Update document title + content via Feishu Docx API
  const url = `https://open.feishu.cn/open-apis/docx/v1/documents/${cfg.docToken}/raw_content`;

  // Feishu raw_content only supports reading; to write, use blocks API.
  // We use the document blocks batch_update endpoint to replace content.
  // Simplified: replace all text with markdown-converted plain text.
  const blockUrl = `https://open.feishu.cn/open-apis/docx/v1/documents/${cfg.docToken}/blocks/batch_update`;

  // Build a single text block with content
  const blockBody = {
    requests: [
      {
        update_text_element: {
          block_id: cfg.docToken, // root block
          index: 0,
          length: -1, // replace all
          text_element: {
            content,
          },
        },
      },
    ],
  };

  const res = await fetch(blockUrl, {
    method: 'PATCH',
    headers,
    body: JSON.stringify(blockBody),
  });

  if (!res.ok) {
    const errText = await res.text().catch(() => res.statusText);
    throw new Error(`飞书 ${res.status}: ${errText}`);
  }

  return await res.json();
}

/* ════════════════════════════════════════════════
   Notion Sync
   ════════════════════════════════════════════════ */

/**
 * Convert plain text/markdown to Notion blocks (simplified).
 * Full Markdown → Notion block conversion would require a dedicated library;
 * this implementation maps headings, paragraphs and code blocks.
 */
function markdownToNotionBlocks(md) {
  const lines  = md.split('\n');
  const blocks = [];
  let inCode = false;
  let codeBuffer = [];
  let codeLang   = '';

  for (const line of lines) {
    // Code fences
    if (line.startsWith('```')) {
      if (!inCode) {
        inCode = true;
        codeLang = line.slice(3).trim() || 'plain text';
        codeBuffer = [];
      } else {
        blocks.push({
          object: 'block',
          type: 'code',
          code: {
            language: codeLang,
            rich_text: [{ type: 'text', text: { content: codeBuffer.join('\n') } }],
          },
        });
        inCode = false;
        codeBuffer = [];
      }
      continue;
    }

    if (inCode) {
      codeBuffer.push(line);
      continue;
    }

    // Headings
    const h1 = line.match(/^# (.+)/);
    const h2 = line.match(/^## (.+)/);
    const h3 = line.match(/^### (.+)/);

    if (h1) {
      blocks.push(makeNotionHeading(1, h1[1]));
    } else if (h2) {
      blocks.push(makeNotionHeading(2, h2[1]));
    } else if (h3) {
      blocks.push(makeNotionHeading(3, h3[1]));
    } else if (line.trim() === '') {
      // Skip blank lines (Notion handles spacing)
    } else {
      blocks.push({
        object: 'block',
        type: 'paragraph',
        paragraph: {
          rich_text: [{ type: 'text', text: { content: line } }],
        },
      });
    }
  }

  return blocks;
}

function makeNotionHeading(level, text) {
  const type = `heading_${level}`;
  return {
    object: 'block',
    type,
    [type]: { rich_text: [{ type: 'text', text: { content: text } }] },
  };
}

/**
 * Append a diary entry to a Notion page while preserving its existing blocks.
 */
async function syncToNotion(content, title) {
  const cfg = loadSyncConfig().notion;
  const pageId = cfg.pageId && cfg.pageId.replace(/-/g, '');
  if (!cfg.token || !pageId || !/^[0-9a-f]{32}$/i.test(pageId)) {
    throw new Error('Notion：请配置有效的 Token 和 Page ID');
  }

  const headers = {
    'Content-Type': 'application/json',
    'Authorization': `Bearer ${cfg.token}`,
    'Notion-Version': '2022-06-28',
  };

  const blocks = [...markdownToNotionBlocks(`## ${title}\n\n`), ...markdownToNotionBlocks(content)];
  for (const children of chunkArray(blocks, 100)) {
    const response = await fetch(`https://api.notion.com/v1/blocks/${pageId}/children`, {
      method: 'PATCH',
      headers,
      body: JSON.stringify({ children }),
    });
    if (!response.ok) throw new Error(`Notion 同步失败（HTTP ${response.status}）`);
  }
}

function chunkArray(arr, size) {
  const chunks = [];
  for (let i = 0; i < arr.length; i += size) {
    chunks.push(arr.slice(i, i + size));
  }
  return chunks;
}

/* ════════════════════════════════════════════════
   syncAll — Orchestrator
   Priority: 语雀 → 飞书 → Notion
   ════════════════════════════════════════════════ */

async function syncAll() {
  const content = getCurrentContent();
  const title   = getCurrentTitle();

  if (!content.trim()) {
    updateStatus('没有内容可同步', 'error');
    return;
  }

  const cfg = loadSyncConfig();

  // Build the list of enabled platforms
  const platforms = [
    {
      id:      'yuque',
      label:   '语雀',
      icon:    '🍀',
      enabled: !!(cfg.yuque.token && cfg.yuque.login && cfg.yuque.slug),
      fn:      () => syncToYuque(content, title),
    },
    {
      id:      'feishu',
      label:   '飞书',
      icon:    '🪶',
      enabled: !!(cfg.feishu.appId && cfg.feishu.appSecret && cfg.feishu.docToken),
      fn:      () => syncToFeishu(content, title),
    },
    {
      id:      'notion',
      label:   'Notion',
      icon:    '◻',
      enabled: !!(cfg.notion.token && cfg.notion.pageId),
      fn:      () => syncToNotion(content, title),
    },
  ].filter(p => p.enabled);

  if (platforms.length === 0) {
    updateStatus('尚未配置任何同步平台，请先点击「同步」→ 配置', 'error');
    showSyncDialog();
    return;
  }

  // Show progress dialog
  const progressOverlay = showSyncProgressDialog(platforms);

  let anyError = false;

  for (const platform of platforms) {
    updateSyncItem(platform.id, 'syncing');
    try {
      await platform.fn();
      updateSyncItem(platform.id, 'success');
      updateStatus(`${platform.label} 同步成功`);
    } catch (err) {
      anyError = true;
      updateSyncItem(platform.id, 'error', err.message);
      updateStatus(`${platform.label} 同步失败：${err.message}`, 'error');
      console.error(`[Sync][${platform.label}]`, err);
    }
  }

  // Auto-close after 3 s if all succeeded
  if (!anyError) {
    setTimeout(() => {
      progressOverlay?.remove();
      updateStatus('所有平台同步完成');
    }, 2500);
  }
}

/* ════════════════════════════════════════════════
   Progress Dialog
   ════════════════════════════════════════════════ */

function showSyncProgressDialog(platforms) {
  const existing = document.getElementById('sync-progress-overlay');
  if (existing) existing.remove();

  const overlay = document.createElement('div');
  overlay.className = 'modal-overlay';
  overlay.id = 'sync-progress-overlay';

  const items = platforms.map(p => `
    <div class="sync-item pending" id="sync-item-${p.id}">
      <span class="sync-item-icon">${p.icon}</span>
      <span>${p.label}</span>
      <span style="margin-left:auto; font-family:var(--font-mono); font-size:12px;" id="sync-item-msg-${p.id}">等待中…</span>
    </div>
  `).join('');

  overlay.innerHTML = `
    <div class="modal" role="dialog" aria-label="同步进度">
      <div class="modal-title">⟳ 正在同步</div>
      <div class="sync-progress">${items}</div>
      <div class="modal-actions">
        <button class="btn" id="sync-progress-close">关闭</button>
      </div>
    </div>
  `;

  document.body.appendChild(overlay);
  document.getElementById('sync-progress-close').addEventListener('click', () => overlay.remove());

  return overlay;
}

function updateSyncItem(id, status, errorMsg = '') {
  const el  = document.getElementById(`sync-item-${id}`);
  const msg = document.getElementById(`sync-item-msg-${id}`);
  if (!el) return;

  el.className = `sync-item ${status}`;

  const labels = {
    syncing: '同步中…',
    success: '成功 ✓',
    error:   `失败: ${errorMsg.slice(0, 40)}`,
    pending: '等待中…',
  };

  if (msg) msg.textContent = labels[status] ?? status;
}

/* ════════════════════════════════════════════════
   Init
   ════════════════════════════════════════════════ */

(function initSync() {
  document.addEventListener('DOMContentLoaded', () => {
    const syncBtn = document.getElementById('btn-sync');
    if (syncBtn) {
      syncBtn.addEventListener('click', showSyncDialog);
    }
  });
})();
