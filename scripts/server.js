const express = require('express');
const { createProxyMiddleware } = require('http-proxy-middleware');
const path = require('path');

const app = express();
const PORT = 4002;
const SOURCE_DIR = path.join(__dirname, '..', 'source');
const STATIC_DIR = path.join(SOURCE_DIR, 'static');
const FLASK_BACKEND = 'http://127.0.0.1:5002';

// =============================================================================
// ENGINE API PROXY: /engine/api/* -> /api/* on Flask (port 5002)
// =============================================================================
// Matches nginx: location /engine/api/ { rewrite /engine/api/(.*) /api/$1 break; ... }
// MUST be defined BEFORE /engine static middleware so API paths take priority.
// =============================================================================
const engineApiProxy = createProxyMiddleware({
  target: FLASK_BACKEND,
  changeOrigin: true,
  pathRewrite: { '^/engine/api': '/api' },
  proxyTimeout: 90000,
  timeout: 90000,
  on: {
    proxyReq: (proxyReq, req, _res) => {
      proxyReq.setHeader('Host', '127.0.0.1:5002');
      proxyReq.setHeader('X-Real-IP', req.ip || req.connection.remoteAddress);
      proxyReq.setHeader('X-Forwarded-For', req.headers['x-forwarded-for'] || req.ip || '');
      proxyReq.setHeader('X-Forwarded-Proto', req.protocol || 'http');
    },
    error: (err, _req, res) => {
      console.error('[Engine API Proxy Error]', err.message);
      if (!res.headersSent) {
        res.status(502).json({ error: 'Bad Gateway', message: 'Flask backend unavailable on port 5002' });
      }
    },
  },
});

app.use('/engine/api', engineApiProxy);

// =============================================================================
// ENGINE STATIC FILES: /engine/* -> ./source/static/
// =============================================================================
// Matches nginx: location /engine/ { alias /opt/plo-engine-backend/static/; ... }
// Serves the React build (engine-index.html) and all static assets like
// /engine/assets/index-Ddit1nUd.js, /engine/assets/engine_flow_controls.js
// =============================================================================
// Serve /engine and /engine/ with the engine index directly
app.get(['/engine', '/engine/'], (req, res) => {
  res.sendFile(path.join(STATIC_DIR, 'engine-index.html'), {
    headers: { 'Cache-Control': 'no-cache' },
  }, err => {
    if (err) {
      console.error('[serveEngine] Error sending file:', err.message);
      if (!res.headersSent) res.status(500).send('Internal Server Error');
    }
  });
});

app.use('/engine', express.static(STATIC_DIR, {
  etag: true,
  lastModified: true,
  index: 'engine-index.html',
  redirect: false,
}));

// Fallback for React client-side routing under /engine/
// Any /engine/* path that doesn't match a real file -> engine-index.html
app.use('/engine', (req, res, next) => {
  if (req.method === 'GET' && !res.headersSent) {
    res.sendFile(path.join(STATIC_DIR, 'engine-index.html'), {
      headers: { 'Cache-Control': 'no-cache' },
    }, err => {
      if (err) {
        console.error('[engine/*] Error:', err.message);
        if (!res.headersSent) res.status(500).send('Internal Server Error');
      }
    });
  } else {
    next();
  }
});

// =============================================================================
// DIRECT ASSETS: /assets/* -> ./source/static/assets/
// =============================================================================
// index.html references /assets/index-Ddit1nUd.js and /assets/index-DgTzSuxS.css
// These are served directly for performance.
// =============================================================================
app.use('/assets', express.static(path.join(STATIC_DIR, 'assets'), {
  maxAge: '1y',
  immutable: true,
  etag: true,
}));

// =============================================================================
// API PROXY: /api/* -> Flask (port 5002)
// =============================================================================
const apiProxy = createProxyMiddleware({
  target: FLASK_BACKEND,
  changeOrigin: true,
  proxyTimeout: 90000,
  timeout: 90000,
  on: {
    proxyReq: (proxyReq, req, _res) => {
      proxyReq.setHeader('Host', '127.0.0.1:5002');
      proxyReq.setHeader('X-Real-IP', req.ip || req.connection.remoteAddress);
      proxyReq.setHeader('X-Forwarded-For', req.headers['x-forwarded-for'] || req.ip || '');
      proxyReq.setHeader('X-Forwarded-Proto', req.protocol || 'http');
    },
    error: (err, _req, res) => {
      console.error('[API Proxy Error]', err.message);
      if (!res.headersSent) {
        res.status(502).json({ error: 'Bad Gateway', message: 'Backend unavailable.' });
      }
    },
  },
});

app.use('/api', apiProxy);

// =============================================================================
// FAVICON: Prevent 404 noise (defined BEFORE root proxy to take priority)
// =============================================================================
app.get('/favicon.ico', (_req, res) => res.status(204).end());

// =============================================================================
// ROOT PROXY: /* -> Flask (port 5002)
// =============================================================================
// Matches nginx: location / { proxy_pass http://127.0.0.1:5002; }
// Flask serves index.html at / which references /assets/* and /engine/assets/*
// =============================================================================
const rootProxy = createProxyMiddleware({
  target: FLASK_BACKEND,
  changeOrigin: true,
  on: {
    proxyReq: (proxyReq, req, _res) => {
      proxyReq.setHeader('Host', '127.0.0.1:5002');
      proxyReq.setHeader('X-Real-IP', req.ip || req.connection.remoteAddress);
      proxyReq.setHeader('X-Forwarded-For', req.headers['x-forwarded-for'] || req.ip || '');
      proxyReq.setHeader('X-Forwarded-Proto', req.protocol || 'http');
    },
    error: (err, _req, res) => {
      console.error('[Root Proxy Error]', err.message);
      if (!res.headersSent) {
        res.status(502).json({ error: 'Bad Gateway', message: 'Backend unavailable.' });
      }
    },
  },
});

app.use('/', rootProxy);

// =============================================================================
// 404 handler (should rarely fire since root proxies everything)
// =============================================================================
app.use((_req, res) => {
  res.status(404).json({ error: 'Not Found', path: _req.path });
});

// =============================================================================
// START
// =============================================================================
const server = app.listen(PORT, '0.0.0.0', () => {
  console.log('');
  console.log('  PLO Equity Engine - Local Clone');
  console.log('  ----------------------------------------');
  console.log('  Local URL:    http://localhost:' + PORT);
  console.log('  Engine URL:   http://localhost:' + PORT + '/engine');
  console.log('  Flask API:    http://localhost:5002');
  console.log('  Login:        admin / PokerPass12345');
  console.log('');
});

// =============================================================================
// GRACEFUL SHUTDOWN
// =============================================================================
process.on('SIGINT', () => {
  console.log('  Shutting down...');
  server.close(() => process.exit(0));
});
process.on('SIGTERM', () => {
  server.close(() => process.exit(0));
});
