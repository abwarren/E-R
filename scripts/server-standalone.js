/**
 * PLO Engine UI — Standalone Server (port 4001)
 *
 * Serves the Engine UI independently of the Remote UI.
 * Routes equity/RNG API calls to the real engine Flask (port 5002)
 * and all other API calls to the shared backend (port 1080).
 *
 * Routing:
 *   /api/run, /api/results/*, /api/stream/*, /api/rng/generate,
 *   /api/validate, /api/fix, /api/download/*, /api/run-batch
 *     → http://127.0.0.1:5002 (real engine Flask)
 *   All other /api/*
 *     → http://127.0.0.1:1080 (shared backend)
 */

const express = require('express');
const { createProxyMiddleware } = require('http-proxy-middleware');
const path = require('path');

const app = express();
const PORT = 4001;
const ENGINE_DIR = path.resolve(__dirname, '..');
const STATIC_DIR = path.join(ENGINE_DIR, 'source', 'static');
const ENGINE_FLASK = 'http://127.0.0.1:5002';
const SHARED_BACKEND = 'http://127.0.0.1:1080';

// =============================================================================
// Equity/RNG routes — these go to the real engine Flask (port 5002)
// which runs the Monte Carlo scripts powered by eval7.
// =============================================================================
const EQUITY_ROUTES = [
  '/run',
  '/run-batch',
  '/rng/generate',
  '/validate',
  '/fix',
  '/login',
  '/auth/verify',
  '/logout',
  '/collector/save',
  '/current-hands',
  '/tracker',
  '/analytics',
  '/ai',
  '/scanner',
];

function isEquityRoute(path) {
  // Exact match — path is relative to /api mount point, so no /api prefix
  if (EQUITY_ROUTES.includes(path)) return true;
  // Prefix match for /api/stream/<id>, /api/results/<id>, /api/download/<id>, /api/commands/<id>, /api/batch/*
  const prefixes = ['/stream/', '/results/', '/download/', '/commands/', '/batch/'];
  for (const p of prefixes) {
    if (path.startsWith(p)) return true;
  }
  return false;
}

// =============================================================================
// CORS
// =============================================================================
app.use((req, res, next) => {
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'GET, POST, OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type, X-API-Key, X-Api-Key, x-api-key, X-Auth-Token');
  res.setHeader('Access-Control-Allow-Private-Network', 'true');
  if (req.method === 'OPTIONS') {
    return res.status(204).end();
  }
  next();
});

// =============================================================================
// HEALTH CHECK
// =============================================================================
app.get('/health', (_req, res) => {
  res.json({
    ok: true,
    service: 'engine-ui-standalone',
    port: PORT,
    engine_flask: ENGINE_FLASK,
    shared_backend: SHARED_BACKEND,
    mode: 'standalone',
    version: '1.0',
  });
});

// =============================================================================
// ENGINE STATIC FILES: /engine/* -> ENGINEENGINE/source/static/
// =============================================================================
app.get(['/engine', '/engine/'], (req, res) => {
  res.sendFile(path.join(STATIC_DIR, 'engine-index.html'), {
    headers: { 'Cache-Control': 'no-cache' },
  }, err => {
    if (err) {
      console.error('[engine] Error sending engine-index.html:', err.message);
      if (!res.headersSent) res.status(500).send('Internal Server Error');
    }
  });
});

// Simple equity calculator page (no React)
app.get('/engine/calculator', (req, res) => {
  res.sendFile(path.join(ENGINE_DIR, 'source', 'engine.html'), {
    headers: { 'Cache-Control': 'no-cache' },
  });
});

// Engine static assets
app.use('/engine', express.static(STATIC_DIR, {
  etag: true,
  lastModified: true,
  index: false,
  redirect: false,
}));

// =============================================================================
// DIRECT ASSETS: /assets/* -> ENGINEENGINE/source/static/assets/
// =============================================================================
app.use('/assets', express.static(path.join(STATIC_DIR, 'assets'), {
  maxAge: '1y',
  immutable: true,
  etag: true,
}));

// =============================================================================
// API PROXY — dual target routing
// =============================================================================
// Shared proxy options generator
function makeProxyOptions(target) {
  return {
    target: target,
    changeOrigin: true,
    proxyTimeout: 90000,
    timeout: 90000,
    on: {
      proxyReq: (proxyReq, req, _res) => {
        const targetHost = target === ENGINE_FLASK ? '127.0.0.1:5002' : '127.0.0.1:1080';
        proxyReq.setHeader('Host', targetHost);
        proxyReq.setHeader('X-Real-IP', req.ip || req.connection.remoteAddress);
        proxyReq.setHeader('X-Forwarded-For', req.headers['x-forwarded-for'] || req.ip || '');
        proxyReq.setHeader('X-Forwarded-Proto', req.protocol || 'http');
      },
      error: (err, _req, res) => {
        console.error(`[API Proxy Error → ${target}]`, err.message);
        if (!res.headersSent) {
          res.status(502).json({ error: 'Bad Gateway', message: `Backend ${target} unavailable.` });
        }
      },
    },
  };
}

// Create proxy middleware for each target
const engineProxy = createProxyMiddleware(makeProxyOptions(ENGINE_FLASK));
const sharedProxy = createProxyMiddleware(makeProxyOptions(SHARED_BACKEND));

// Route /api/* calls based on path
app.use('/api', (req, res, next) => {
  if (isEquityRoute(req.path)) {
    console.log('[ROUTE] equity → 5002:', req.method, req.path);
    return engineProxy(req, res, next);
  }
  console.log('[ROUTE] shared → 1080:', req.method, req.path);
  return sharedProxy(req, res, next);
});

// =============================================================================
// FAVICON
// =============================================================================
app.get('/favicon.ico', (_req, res) => res.status(204).end());

// =============================================================================
// 404 handler
// =============================================================================
app.use((_req, res) => {
  res.status(404).json({ error: 'Not Found', path: _req.path });
});

// =============================================================================
// START
// =============================================================================
console.log('');
console.log('  PLO Engine UI — Standalone (port 4001)');
console.log('  ------------------------------------------');
console.log('');
console.log('  URLs:');
console.log('    Engine UI:       http://localhost:' + PORT + '/engine');
console.log('    Calculator:      http://localhost:' + PORT + '/engine/calculator');
console.log('    Health:          http://localhost:' + PORT + '/health');
console.log('');
console.log('  Routing:');
console.log('    Equity/RNG API:  /api/* → ' + ENGINE_FLASK + ' (real engine)');
console.log('    Shared API:      /api/* → ' + SHARED_BACKEND + ' (table state)');
console.log('');
console.log('  Prerequisites:');
console.log('    Engine Flask:  ' + ENGINE_FLASK + ' (python app.py)');
console.log('    Shared API:    ' + SHARED_BACKEND + ' (python app.py from REMOTEREMOTE)');
console.log('');
console.log('  Press Ctrl+C to stop.');
console.log('');

const server = app.listen(PORT, '0.0.0.0', () => {
  console.log('  ✓ Engine UI server is running on port ' + PORT);
});

// Graceful shutdown
process.on('SIGINT', () => {
  console.log('\n  Shutting down...');
  server.close(() => process.exit(0));
});
process.on('SIGTERM', () => {
  server.close(() => process.exit(0));
});
