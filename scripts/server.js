const express = require('express');
const { createProxyMiddleware } = require('http-proxy-middleware');
const path = require('path');

const app = express();
const PORT = 4000;
const SOURCE_DIR = path.join(__dirname, '..', 'source');
const ENGINE_DIR = path.resolve(__dirname, '..', '..', 'ENGINEENGINE');
const ENGINE_STATIC = path.join(ENGINE_DIR, 'source', 'static');
const BACKEND_API = 'http://127.0.0.1:1080';

// =============================================================================
// CORS — required for extension content script direct fetch from Goldrush
// Chrome Private Network Access (PNA) blocks https→localhost without these.
// =============================================================================
app.use((req, res, next) => {
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'GET, POST, OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type, X-API-Key, X-Api-Key, x-api-key');
  res.setHeader('Access-Control-Allow-Private-Network', 'true');
  if (req.method === 'OPTIONS') {
    return res.status(204).end();
  }
  next();
});

app.get('/health', (_req, res) => {
  res.json({ ok: true, service: 'local-bridge', mode: 'proxy', version: '1.0' });
});

// =============================================================================
// ROUTE: /hand-export -> hand-export.html
// =============================================================================
app.get('/hand-export', (_req, res) => {
  res.sendFile(path.join(SOURCE_DIR, 'hand-export.html'), {
    headers: { 'Cache-Control': 'no-cache' },
  }, err => {
    if (err) {
      console.error('[serveHandExport] Error:', err.message);
      res.status(500).send('Internal Server Error');
    }
  });
});

// =============================================================================
// ROUTES: /, /remote, /remote/ -> remote-w4p.html
// =============================================================================
// These must be defined BEFORE the static middleware so they take priority.
// Matches nginx config:
//   location ~ ^/remote/?$ {
//       root /opt/plo-engine/static;
//       try_files /remote-w4p.html =404;
//       add_header Cache-Control "no-cache" always;
//   }
// =============================================================================
const serveRemote = (_req, res) => {
  res.sendFile(path.join(SOURCE_DIR, 'remote-w4p.html'), {
    headers: {
      'Cache-Control': 'no-cache',
    },
  }, err => {
    if (err) {
      console.error('[serveRemote] Error sending file:', err.message);
      res.status(500).send('Internal Server Error');
    }
  });
};

// Root -> remote UI
app.get('/', serveRemote);

// /remote and /remote/ -> remote UI (matches nginx location ~ ^/remote/?$)
app.get('/remote', serveRemote);
app.get('/remote/', serveRemote);

// =============================================================================
// ENGINE UI: /engine -> ENGINEENGINE source/static/engine-index.html
// =============================================================================
const serveEngine = (_req, res) => {
  res.sendFile(path.join(ENGINE_STATIC, 'engine-index.html'), {
    headers: { 'Cache-Control': 'no-cache' },
  }, err => {
    if (err) {
      console.error('[serveEngine] Error:', err.message);
      res.status(500).send('Internal Server Error');
    }
  });
};
app.get('/engine', serveEngine);
app.get('/engine/', serveEngine);
// Static assets for engine (scripts, css, etc.)
app.use('/engine/', express.static(ENGINE_STATIC, { maxAge: 0 }));

// =============================================================================
// EQUITY/RNG API PROXY: specific routes -> engine Flask (127.0.0.1:1080)
// =============================================================================
const ENGINE_FLASK = 'http://127.0.0.1:5002';
// POST /api/run now handled by backend equity_routes.py (card validation + engine forwarding)
app.post('/api/rng/generate', createProxyMiddleware({ target: ENGINE_FLASK, changeOrigin: true }));
app.post('/api/equity', createProxyMiddleware({ target: ENGINE_FLASK, changeOrigin: true }));
app.get('/api/results/latest', createProxyMiddleware({ target: ENGINE_FLASK, changeOrigin: true }));
app.post('/api/validate', createProxyMiddleware({ target: ENGINE_FLASK, changeOrigin: true }));
app.post('/api/run-batch', createProxyMiddleware({ target: ENGINE_FLASK, changeOrigin: true }));
app.post('/api/login', createProxyMiddleware({ target: ENGINE_FLASK, changeOrigin: true }));
app.get('/api/auth/verify', createProxyMiddleware({ target: ENGINE_FLASK, changeOrigin: true }));
app.post('/api/logout', createProxyMiddleware({ target: ENGINE_FLASK, changeOrigin: true }));
// All /api/stream/* and /api/results/* now handled by backend equity_routes.py

// =============================================================================
// SHARED BACKEND PROXY: /api/* -> local backend (127.0.0.1:1080)
// =============================================================================
// The remote UI calls:
//   - GET  /api/table/latest   (poll for table state)
//   - POST /api/commands/queue  (send poker actions)
// All /api/* requests are proxied to the local backend on this machine.
// =============================================================================
const proxyOptions = {
  target: BACKEND_API,
  changeOrigin: true,
  proxyTimeout: 30000,
  timeout: 30000,
  on: {
    proxyReq: (proxyReq, req, _res) => {
      proxyReq.setHeader('Host', 'localhost:1080');
      proxyReq.setHeader('X-Real-IP', req.ip || req.connection.remoteAddress);
      proxyReq.setHeader('X-Forwarded-For', req.headers['x-forwarded-for'] || req.ip || '');
      proxyReq.setHeader('X-Forwarded-Proto', req.protocol || 'http');
      if (req.headers['x-api-key']) proxyReq.setHeader('X-API-Key', req.headers['x-api-key']);
    },
    proxyRes: (proxyRes, req, res) => {
      proxyRes.headers['access-control-allow-origin'] = '*';
      proxyRes.headers['access-control-allow-methods'] = 'GET, POST, OPTIONS';
      proxyRes.headers['access-control-allow-headers'] = 'Content-Type, X-API-Key, X-Api-Key, x-api-key';
      proxyRes.headers['access-control-allow-private-network'] = 'true';
    },
    error: (err, _req, res) => {
      console.error('[API Proxy Error]', err.message);
      if (!res.headersSent) {
        res.status(502).json({ error: 'Bad Gateway', message: err.message });
      }
    },
  },
};


// Proxy ALL /api/* routes to the backend (snapshots, commands, table state, etc.)
app.use('/api', createProxyMiddleware(proxyOptions));



// =============================================================================
// STATIC ASSETS: /assets/* -> ./source/assets/
// =============================================================================
// Matches nginx config:
//   location ^~ /assets/ {
//       alias /opt/plo-engine/static/assets/;
//       expires 1y;
//       add_header Cache-Control "public, immutable" always;
//   }
// =============================================================================
app.use(
  '/assets',
  express.static(path.join(SOURCE_DIR, 'assets'), {
    maxAge: '1y',
    immutable: true,
    etag: true,
  })
);

// =============================================================================
// STATIC FILES: Serve all other static files from ./source/
// =============================================================================
app.use(express.static(SOURCE_DIR, {
  etag: true,
  lastModified: true,
  index: false,     // Don't auto-serve index.html on /
  redirect: false,  // Don't auto-redirect to /
}));

// =============================================================================
// W4P EXTENSION API: Absorb extension requests that shouldn't reach proxy
// =============================================================================
// The W4P extension calls these from the browser directly. They hit the
// bridge, not the backend proxy. Return clean empty responses to prevent
// console error spam when the player isn't in a hand.
// =============================================================================

// Snapshot POST — extension sends table state here
app.post('/snapshot', (_req, res) => {
  res.status(200).json({ ok: true, queued: false, reason: 'idle' });
});

// Pending commands — extension polls here for actions to take
app.get('/commands/pending', (_req, res) => {
  res.status(200).json({ ok: true, commands: [] });
});

// Command acknowledgement
app.post('/commands/ack', (_req, res) => {
  res.status(200).json({ ok: true });
});

// =============================================================================
// COLLECTOR SAVE: Proxy /collector/save → local backend (127.0.0.1:1080)
// The engine poller and W4P scraper send hand data here for the textarea.
// =============================================================================
app.post('/collector/save', createProxyMiddleware({
  target: BACKEND_API,
  changeOrigin: true,
}));

// =============================================================================
// FAVICON: Prevent 404 noise in browser console
// =============================================================================
app.get('/favicon.ico', (_req, res) => res.status(204).end());
app.get('/favicon.png', (_req, res) => res.status(204).end());

// =============================================================================
// 404 handler — catch-all for anything else, but return 204 not 404 JSON
// to avoid console noise from extension polling stale routes
// =============================================================================
app.use((_req, res) => {
  res.status(204).end();
});

// =============================================================================
// START
// =============================================================================
const server = app.listen(PORT, '0.0.0.0', () => {
  console.log(`\n  🎯 W4P Remote Control — Local Clone`);
  console.log(`  ─────────────────────────────────────`);
  console.log(`  Local URL:    http://localhost:${PORT}`);
  console.log(`  Remote route: http://localhost:${PORT}/remote`);
  console.log(`  API proxy:    /api/* → ${BACKEND_API}/api/*`);
  console.log(`  Static files: ${SOURCE_DIR}`);
  console.log(`  CORS:         Enabled (PNA support for extension)`);
  console.log(`\n  Press Ctrl+C to stop.\n`);
});

// =============================================================================
// GRACEFUL SHUTDOWN
// =============================================================================
process.on('SIGINT', () => {
  console.log('\n  Shutting down...');
  server.close(() => process.exit(0));
});
process.on('SIGTERM', () => {
  server.close(() => process.exit(0));
});
