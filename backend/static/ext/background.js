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

// ── DIAG: message counter for correlation ──────────────────────────────
var _diagSeq = 0;

// Listen for config updates
chrome.runtime.onMessage.addListener(function(msg, sender, sendResponse) {
  _diagSeq++;
  var diagId = _diagSeq;

  // ── DIAG 1: entry into onMessage ──
  console.log('[W4P-BG][DIAG:' + diagId + '] onMessage ENTRY type=' + (msg.type || 'UNDEFINED') +
    ' path=' + (msg.path || 'NONE') + ' method=' + (msg.method || 'NONE') +
    ' rawPath=' + msg.rawPath + ' hasBody=' + (!!msg.body) +
    ' sender=' + (sender && sender.id ? sender.id : 'NONE'));

  if (msg.type === 'W4P_FETCH') {
    // ── DIAG 2: message received ──
    console.log('[W4P-BG][DIAG:' + diagId + '] W4P_FETCH received' +
      ' API_BASE=' + API_BASE + ' SITE_BASE=' + SITE_BASE);

    // rawPath: use SITE_BASE (no /api prefix), otherwise use API_BASE
    var url = msg.rawPath ? (SITE_BASE + msg.path) : (API_BASE + msg.path);
    var opts = { method: msg.method || 'GET', headers: {} };

    if (msg.body) {
      opts.headers['Content-Type'] = 'application/json';
      opts.body = JSON.stringify(msg.body);
    }
    // Use provided apiKey, or fallback to hardcoded key
    opts.headers['X-API-Key'] = msg.apiKey || API_KEY;

    // ── DIAG 3: exact URL and fetch options ──
    var bodyLen = opts.body ? opts.body.length : 0;
    console.log('[W4P-BG][DIAG:' + diagId + '] FETCH URL=' + url +
      ' method=' + opts.method +
      ' Content-Type=' + (opts.headers['Content-Type'] || 'NOT SET') +
      ' X-API-Key=' + (opts.headers['X-API-Key'] ? opts.headers['X-API-Key'].substring(0,8) + '...' : 'NOT SET') +
      ' bodyBytes=' + bodyLen +
      ' ts=' + Date.now());

    // ── DIAG 4: fetch() called ──
    var fetchStart = Date.now();
    console.log('[W4P-BG][DIAG:' + diagId + '] fetch() CALLED');

    fetch(url, opts)
      .then(function(r) {
        // ── DIAG 5: response status ──
        var elapsed = Date.now() - fetchStart;
        console.log('[W4P-BG][DIAG:' + diagId + '] fetch() RESPONSE' +
          ' status=' + r.status + ' ' + r.statusText +
          ' elapsed=' + elapsed + 'ms' +
          ' content-type=' + (r.headers.get('content-type') || 'NONE') +
          ' content-length=' + (r.headers.get('content-length') || 'NONE'));

        if (!r.ok) {
          console.error('[W4P-BG][DIAG:' + diagId + '] fetch() NON-OK: ' + r.status);
          sendResponse({ ok: false, error: 'HTTP ' + r.status, status: r.status });
          console.log('[W4P-BG][DIAG:' + diagId + '] sendResponse RETURNED (error)');
          return;
        }
        return r.text().then(function(txt) {
          // ── DIAG 6: response body ──
          var preview = txt.length > 200 ? txt.substring(0,200) + '...' : txt;
          console.log('[W4P-BG][DIAG:' + diagId + '] fetch() BODY' +
            ' len=' + txt.length + ' preview=' + preview);

          try {
            var data = JSON.parse(txt);
            sendResponse({ ok: true, data: data, status: r.status });
            console.log('[W4P-BG][DIAG:' + diagId + '] sendResponse RETURNED (JSON ok)');
          }
          catch (parseErr) {
            console.warn('[W4P-BG][DIAG:' + diagId + '] JSON parse failed: ' + parseErr.message);
            sendResponse({ ok: true, data: txt, status: r.status });
            console.log('[W4P-BG][DIAG:' + diagId + '] sendResponse RETURNED (text, JSON parse failed)');
          }
        });
      })
      .catch(function(e) {
        // ── DIAG 7: exception ──
        var elapsed = Date.now() - fetchStart;
        console.error('[W4P-BG][DIAG:' + diagId + '] fetch() EXCEPTION' +
          ' message=' + e.message +
          ' name=' + e.name +
          ' stack=' + (e.stack ? e.stack.substring(0,300) : 'NONE') +
          ' elapsed=' + elapsed + 'ms');
        sendResponse({ ok: false, error: e.message, status: 0 });
        console.log('[W4P-BG][DIAG:' + diagId + '] sendResponse RETURNED (exception)');
      });

    // ── DIAG 8: returning true for async ──
    console.log('[W4P-BG][DIAG:' + diagId + '] onMessage RETURNING true (async)');

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

console.log('[W4P-BG] Service worker loaded. Default API_BASE=' + DEFAULT_API_BASE);
