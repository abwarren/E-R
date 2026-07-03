/**
 * REMOTEREMOTE Express — Container-aware frontend (port 4000)
 *
 * Serves the remote UI and proxies ALL /api/* to the local Flask backend
 * on port 1080 (same container). The Flask backend's equity_routes.py
 * handles forwarding equity jobs to the engine container at ENGINE_URL.
 *
 * Unlike the bare-metal server.js, this does NOT directly proxy
 * equity routes — those are handled by the engine container.
 * Engine UI is served via /ENGINEENGINE volume mount.
 */

const express = require('express');
const { createProxyMiddleware } = require('http-proxy-middleware');
const path = require('path');

const app = express();
const PORT = 4000;
const SOURCE_DIR = path.join(__dirname, '..', 'source');
const BACKEND_API = 'http://127.0.0.1:1080';

// ── CORS ───────────────────────────────────────────────────────────────────
app.use((req, res, next) => {
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'GET, POST, OPTIONS');
  res.setHeader('Access-Control-Allow-Headers',
    'Content-Type, X-API-Key, X-Api-Key, x-api-key');
  res.setHeader('Access-Control-Allow-Private-Network', 'true');
  if (req.method === 'OPTIONS') {
    return res.status(204).end();
  }
  next();
});

// ── Health ─────────────────────────────────────────────────────────────────
app.get('/health', (_req, res) => {
  res.json({ ok: true, service: 'remote-ui', mode: 'container', version: '1.0' });
});

// ── Routes ─────────────────────────────────────────────────────────────────
const serveRemote = (_req, res) => {
  res.sendFile(path.join(SOURCE_DIR, 'remote-w4p.html'), {
    headers: { 'Cache-Control': 'no-cache' },
  }, err => {
    if (err) {
      console.error('[serveRemote] Error:', err.message);
      res.status(500).send('Internal Server Error');
    }
  });
};

app.get('/', serveRemote);
app.get('/remote', serveRemote);
app.get('/remote/', serveRemote);

app.get('/hand-export', (_req, res) => {
  res.sendFile(path.join(SOURCE_DIR, 'hand-export.html'), {
    headers: { 'Cache-Control': 'no-cache' },
  }, err => {
    if (err) {
      console.error('[handExport] Error:', err.message);
      res.status(500).send('Internal Server Error');
    }
  });
});

// ── Engine UI: /engine -> ENGINEENGINE volume mount ───────────────────────
const ENGINE_STATIC_CONTAINER = '/ENGINEENGINE/source/static';

app.get('/engine', (_req, res) => {
  res.sendFile(path.join(ENGINE_STATIC_CONTAINER, 'engine-index.html'), {
    headers: { 'Cache-Control': 'no-cache' },
  }, err => {
    if (err) {
      console.error('[serveEngine] Error:', err.message);
      res.status(500).send('Internal Server Error');
    }
  });
});
app.get('/engine/', (_req, res) => {
  res.sendFile(path.join(ENGINE_STATIC_CONTAINER, 'engine-index.html'), {
    headers: { 'Cache-Control': 'no-cache' },
  }, err => {
    if (err) {
      console.error('[serveEngine] Error:', err.message);
      res.status(500).send('Internal Server Error');
    }
  });
});
app.use('/engine/', express.static(ENGINE_STATIC_CONTAINER, { maxAge: 0 }));

// ── Frontend API config (served directly — NOT proxied) ────────────────────
// Must be defined BEFORE the /api proxy because http-proxy-middleware strips
// the /api prefix, turning /api-config.js into /-config.js (404).
app.get('/api-config.js', (_req, res) => {
  res.sendFile(path.join(SOURCE_DIR, 'api-config.js'), {
    headers: { 'Cache-Control': 'no-cache, no-store, must-revalidate' },
  }, err => {
    if (err) {
      console.error('[apiConfig] Error:', err.message);
      res.status(500).send('Internal Server Error');
    }
  });
});

// ── API proxy → local Flask (port 1080) ────────────────────────────────────
// SSE passthrough for /api/stream/* and /api/results/*
app.use('/api', createProxyMiddleware({
  target: BACKEND_API,
  changeOrigin: true,
  proxyTimeout: 0,    // no timeout for SSE
  timeout: 0,
  on: {
    proxyReq: (proxyReq, req) => {
      proxyReq.setHeader('Host', 'localhost:1080');
      proxyReq.setHeader('X-Real-IP', req.ip || req.connection.remoteAddress);
      proxyReq.setHeader('X-Forwarded-For',
        req.headers['x-forwarded-for'] || req.ip || '');
      proxyReq.setHeader('X-Forwarded-Proto', req.protocol || 'http');
    },
    proxyRes: (proxyRes, _req, res) => {
      res.setHeader('Access-Control-Allow-Origin', '*');
      res.setHeader('Access-Control-Allow-Methods', 'GET, POST, OPTIONS');
      res.setHeader('Access-Control-Allow-Headers',
        'Content-Type, X-API-Key, X-Api-Key, x-api-key');
      res.setHeader('Access-Control-Allow-Private-Network', 'true');
      // SSE: preserve content-type, disable buffering
      const ct = proxyRes.headers['content-type'] || '';
      if (ct.includes('text/event-stream') || ct.includes('sse')) {
        res.setHeader('Content-Type', ct);
        res.setHeader('Cache-Control', 'no-cache');
        res.setHeader('Connection', 'keep-alive');
        res.flushHeaders();
      }
    },
    error: (err, _req, res) => {
      console.error('[API Proxy Error]', err.message);
      if (!res.headersSent) res.status(502).end();
    },
  },
}));

app.listen(PORT, '0.0.0.0', () => {
  console.log(`[REMOTE-CONTAINER] Express listening on :${PORT}`);
  console.log(`[REMOTE-CONTAINER] API proxy → ${BACKEND_API}`);
});
