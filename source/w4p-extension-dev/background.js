// W4P Background Service Worker — proxies fetch calls for MAIN world content script
// MAIN world scripts can't use host_permissions; the service worker can.
//
// ── API_BASE Configuration ──────────────────────────────────────────────
// Default: local development (http://127.0.0.1:4000/api)
// Production: http://127.0.0.1:4000/api
//
// To switch between dev and prod:
// 1. Click the extension icon → set API_BASE in the popup
// 2. Or manually set via chrome.storage:
//    chrome.storage.sync.set({ w4p_api_base: 'http://127.0.0.1:4000/api' })
// ────────────────────────────────────────────────────────────────────────

const DEFAULT_API_BASE = 'http://127.0.0.1:4000/api';
const DEFAULT_SITE_BASE = 'http://127.0.0.1:4000';
const API_KEY  = '03622c896cfbeacdfc537e9434f9ddc5';

let API_BASE = DEFAULT_API_BASE;
let SITE_BASE = DEFAULT_SITE_BASE;

// Load saved config on startup
chrome.storage.sync.get(['w4p_api_base', 'w4p_site_base'], function(result) {
  if (result.w4p_api_base) {
    API_BASE = result.w4p_api_base;
  }
  if (result.w4p_site_base) {
    SITE_BASE = result.w4p_site_base;
  }
  console.log('[W4P-BG] API_BASE=' + API_BASE + ' SITE_BASE=' + SITE_BASE);
});

// Listen for config updates
chrome.runtime.onMessage.addListener(function(msg, sender, sendResponse) {
  if (msg.type === 'W4P_FETCH') {
    // rawPath: use SITE_BASE (no /api prefix), otherwise use API_BASE
    var url = msg.rawPath ? (SITE_BASE + msg.path) : (API_BASE + msg.path);
    var opts = { method: msg.method || 'GET', headers: {} };

    if (msg.body) {
      opts.headers['Content-Type'] = 'application/json';
      opts.body = JSON.stringify(msg.body);
    }
    // Use provided apiKey, or fallback to hardcoded key
    opts.headers['X-API-Key'] = msg.apiKey || API_KEY;

    fetch(url, opts)
      .then(function(r) { return r.json(); })
      .then(function(data) { sendResponse({ ok: true, data: data }); })
      .catch(function(e) { sendResponse({ ok: false, error: e.message }); });

    return true; // keep sendResponse channel open for async
  }

  // Handle config updates from popup/options
  if (msg.type === 'W4P_SET_CONFIG') {
    if (msg.apiBase) {
      API_BASE = msg.apiBase;
      chrome.storage.sync.set({ w4p_api_base: msg.apiBase });
    }
    if (msg.siteBase) {
      SITE_BASE = msg.siteBase;
      chrome.storage.sync.set({ w4p_site_base: msg.siteBase });
    }
    console.log('[W4P-BG] Config updated: API_BASE=' + API_BASE + ' SITE_BASE=' + SITE_BASE);
    sendResponse({ ok: true, apiBase: API_BASE, siteBase: SITE_BASE });
    return true;
  }

  // Handle config query
  if (msg.type === 'W4P_GET_CONFIG') {
    sendResponse({ ok: true, apiBase: API_BASE, siteBase: SITE_BASE });
    return true;
  }
});

console.log('[W4P-BG] Loaded. Default API_BASE=' + DEFAULT_API_BASE);
