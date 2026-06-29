/**
 * W4P Frontend API Configuration
 * ===============================
 * Single source of truth for all frontend API endpoints.
 *
 * Environment-independent — uses window.location.origin to resolve the
 * backend URL automatically in localhost, dev, staging, and production.
 *
 * Usage:
 *   // In HTML: <script src="/api-config.js"></script>
 *   // In JS:   const API = window.W4P_API;
 *   //          fetch(API.LATEST);
 *
 * To add a new endpoint, add it here — do NOT hardcode URLs in other files.
 */
(function () {
  "use strict";

  const BASE = window.location.origin;

  window.W4P_API = {
    /** Base URL (origin only, no trailing slash) */
    BASE: BASE,

    // ── Table State ──────────────────────────────────────────────
    LATEST:       BASE + "/api/latest",
    TABLE_LATEST: BASE + "/api/table/latest",
    TABLES:       BASE + "/api/tables",

    // ── Snapshot Pipeline ────────────────────────────────────────
    SNAPSHOT:     BASE + "/api/snapshot",

    // ── Commands ─────────────────────────────────────────────────
    COMMANDS_PENDING: BASE + "/api/commands/pending",
    COMMANDS_ACK:     BASE + "/api/commands/ack",
    COMMANDS_QUEUE:   BASE + "/api/commands/queue",

    // ── Health & Status ──────────────────────────────────────────
    HEALTH:       BASE + "/api/health",
    STATUS:       BASE + "/api/status",
    VERSION:      BASE + "/api/version",

    // ── Hands ────────────────────────────────────────────────────
    HANDS_RECENT: BASE + "/api/hands/recent",
    HANDS_CLEAR:  BASE + "/api/hands/clear",

    // ── Collector ────────────────────────────────────────────────
    COLLECTOR_SAVE:   BASE + "/collector/save",
    COLLECTOR_LATEST: BASE + "/api/collector/latest",

    // ── Equity Engine (SSE) ──────────────────────────────────────
    STREAM_EQUITY: BASE + "/api/stream/equity",

    // ── Bot Management ───────────────────────────────────────────
    BOTS:         BASE + "/api/bots",
    BOT_DEPLOY:   BASE + "/api/bot/deploy",

    // ── Future endpoints (add here, not in consuming files) ─────
    // REPLAY:    BASE + "/api/replay",
    // STATS:     BASE + "/api/stats",
    // CONFIG:    BASE + "/api/config",
  };

  console.log(
    "[W4P_API] Configured for " +
      BASE +
      " (" +
      Object.keys(window.W4P_API).length +
      " endpoints)"
  );
})();
