// ==UserScript==
// @name         MakerWorld Likes -> Local Notion Sync
// @namespace    https://makerworld.com/
// @version      1.0.0
// @description  Send MakerWorld likes from browser to local Notion receiver.
// @match        https://makerworld.com/*
// @grant        GM_xmlhttpRequest
// @connect      127.0.0.1
// ==/UserScript==

(function () {
  'use strict';

  const RECEIVER_URL = 'http://127.0.0.1:8765/sync';
  const DRY_RUN_DEFAULT = false;
  const VERBOSE_DEFAULT = true;
  const AUTO_SYNC_ON_LIKE = true;
  const AUTO_SYNC_COOLDOWN_MS = 5000;

  const MODEL_LINK_RE = /\/models\/(\d+)(?:-([^/?#]+))?/i;

  function normalizeTitle(text) {
    return String(text || '').replace(/\s+/g, ' ').trim();
  }

  function slugToTitle(slug) {
    return String(slug || '').replace(/[-_]+/g, ' ').replace(/\s+/g, ' ').trim();
  }

  function extractFromAnchor(a) {
    const href = a.getAttribute('href') || '';
    const m = href.match(MODEL_LINK_RE);
    if (!m) return null;

    const modelId = m[1];
    const slug = m[2] || '';
    let modelName = normalizeTitle(a.textContent);
    if (!modelName || /^Model\s+\d+$/i.test(modelName)) {
      modelName = slugToTitle(slug) || `Model ${modelId}`;
    }

    return {
      model_id: modelId,
      model_name: modelName,
      model_url: `https://makerworld.com/en/models/${modelId}`,
    };
  }

  function collectItems() {
    const items = [];
    const seen = new Set();
    const anchors = Array.from(document.querySelectorAll('a[href*="/models/"]'));

    for (const a of anchors) {
      const item = extractFromAnchor(a);
      if (!item) continue;
      if (seen.has(item.model_id)) continue;
      seen.add(item.model_id);
      items.push(item);
    }

    return items;
  }

  function findClosestModelAnchor(el) {
    let node = el;
    for (let i = 0; i < 8 && node; i += 1) {
      if (node.querySelectorAll) {
        const direct = node.querySelector('a[href*="/models/"]');
        if (direct) return direct;
      }
      node = node.parentElement;
    }
    return null;
  }

  function isLikelyLikeControl(el) {
    if (!el) return false;
    const text = [
      el.getAttribute?.('aria-label') || '',
      el.getAttribute?.('title') || '',
      el.getAttribute?.('data-testid') || '',
      el.getAttribute?.('data-test') || '',
      el.textContent || '',
      el.className || '',
    ].join(' ').toLowerCase();
    return /\blike\b/.test(text) || /thumb|heart|favorite/.test(text);
  }

  function postToReceiver(payload) {
    return new Promise((resolve, reject) => {
      GM_xmlhttpRequest({
        method: 'POST',
        url: RECEIVER_URL,
        headers: { 'Content-Type': 'application/json' },
        data: JSON.stringify(payload),
        onload: (resp) => {
          try {
            const data = JSON.parse(resp.responseText || '{}');
            resolve({ status: resp.status, data });
          } catch (err) {
            reject(new Error(`Invalid JSON from receiver: ${err.message}`));
          }
        },
        onerror: (err) => reject(new Error(`Receiver request failed: ${JSON.stringify(err)}`)),
      });
    });
  }

  function makeButton() {
    const btn = document.createElement('button');
    btn.textContent = 'Sync Likes to Notion';
    btn.type = 'button';
    btn.style.position = 'fixed';
    btn.style.right = '16px';
    btn.style.bottom = '16px';
    btn.style.zIndex = '999999';
    btn.style.padding = '10px 14px';
    btn.style.background = '#1f7ae0';
    btn.style.color = '#fff';
    btn.style.border = '0';
    btn.style.borderRadius = '8px';
    btn.style.fontWeight = '600';
    btn.style.cursor = 'pointer';
    btn.style.boxShadow = '0 4px 12px rgba(0,0,0,0.2)';

    btn.addEventListener('click', async () => {
      const items = collectItems();
      if (!items.length) {
        alert('No model cards found on this page. Open your likes page first.');
        return;
      }

      const dryRun = confirm('Run in dry-run mode (preview only, no Notion writes)?');
      btn.disabled = true;
      btn.textContent = 'Syncing...';

      try {
        const payload = {
          items,
          dryRun,
          verbose: VERBOSE_DEFAULT,
          enrichMissing: true,
        };
        const result = await postToReceiver(payload);
        console.log('[MakerWorld Sync] result', result);
        alert(`Sync complete\nStatus: ${result.status}\nCreated: ${result.data.createdCount || 0}\nUpdated: ${result.data.updatedCount || 0}\nErrors: ${result.data.errorCount || 0}`);
      } catch (err) {
        console.error('[MakerWorld Sync] error', err);
        alert(`Sync failed: ${err.message}\nMake sure local receiver is running at ${RECEIVER_URL}`);
      } finally {
        btn.disabled = false;
        btn.textContent = 'Sync Likes to Notion';
      }
    });

    return btn;
  }

  const recentlySynced = new Map();

  async function syncSingleItemFromElement(el) {
    const anchor = findClosestModelAnchor(el);
    if (!anchor) return;
    const item = extractFromAnchor(anchor);
    if (!item) return;

    const last = recentlySynced.get(item.model_id) || 0;
    const now = Date.now();
    if (now - last < AUTO_SYNC_COOLDOWN_MS) return;
    recentlySynced.set(item.model_id, now);

    try {
      const payload = {
        items: [item],
        dryRun: false,
        verbose: VERBOSE_DEFAULT,
        enrichMissing: true,
      };
      const result = await postToReceiver(payload);
      console.log('[MakerWorld Sync][Auto Like]', item.model_id, result);
    } catch (err) {
      console.error('[MakerWorld Sync][Auto Like] failed', err);
    }
  }

  function onDocumentClick(event) {
    if (!AUTO_SYNC_ON_LIKE) return;
    const target = event.target;
    if (!target) return;
    const control = target.closest('button,[role="button"],a,div,span');
    if (!control) return;
    if (!isLikelyLikeControl(control)) return;
    // Wait a moment for MakerWorld UI state/navigation updates.
    setTimeout(() => {
      syncSingleItemFromElement(control);
    }, 250);
  }

  function init() {
    if (!document.body) return;
    if (document.getElementById('mw-notion-sync-btn')) return;

    const btn = makeButton();
    btn.id = 'mw-notion-sync-btn';
    document.body.appendChild(btn);
    document.addEventListener('click', onDocumentClick, true);
    console.log('[MakerWorld Sync] button added');
  }

  const observer = new MutationObserver(() => init());
  observer.observe(document.documentElement, { childList: true, subtree: true });
  init();
})();
