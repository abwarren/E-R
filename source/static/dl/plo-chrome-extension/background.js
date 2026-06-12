// PLO Remote Control - Background Service Worker
// Handles API communication (no CORS restrictions)

const API_BASE = 'http://127.0.0.1:4000/api';
const API_KEY = 'trk_default';
let commandTimers = {};
let seatTokens = {};  // key -> seat_token from backend

// Listen for messages from content scripts
chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (msg.type === 'POST_SNAPSHOT') {
    postSnapshot(msg.data, sender.tab?.id);
    sendResponse({ok: true});
  } else if (msg.type === 'ACK_COMMAND') {
    ackCommand(msg.data);
    sendResponse({ok: true});
  }
  return true;
});

// POST snapshot to Flask API
async function postSnapshot(snapshot, tabId) {
  try {
    const resp = await fetch(API_BASE + '/snapshot', {
      method: 'POST',
      headers: {'Content-Type': 'application/json', 'X-API-Key': API_KEY},
      body: JSON.stringify(snapshot)
    });
    const data = await resp.json();
    if (data.ok && tabId) {
      const key = data.table_id + ':' + data.seat_no;
      // Store seat token for command polling
      if (data.seat_token) {
        seatTokens[key] = data.seat_token;
      }
      if (!commandTimers[key] && seatTokens[key]) {
        startCommandPolling(key, tabId);
      }
      // Send seat info back to content script
      chrome.tabs.sendMessage(tabId, {
        type: 'SEAT_ASSIGNED',
        table_id: data.table_id,
        seat_no: data.seat_no
      }).catch(() => {});
    }
    console.log('[BG] Snapshot:', data.ok ? 'OK' : data.error);
  } catch (err) {
    console.log('[BG] Snapshot error:', err.message);
  }
}

// Poll for commands using seat token
function startCommandPolling(key, tabId) {
  const token = seatTokens[key];
  if (!token) return;
  console.log('[BG] Starting command poll for', key);

  commandTimers[key] = setInterval(async () => {
    try {
      const t = seatTokens[key];
      if (!t) return;
      const resp = await fetch(
        API_BASE + '/commands/pending?token=' + encodeURIComponent(t)
      );
      const data = await resp.json();
      if (data.ok && data.command) {
        console.log('[BG] Command:', data.command.type);
        // Send command to content script
        chrome.tabs.sendMessage(tabId, {
          type: 'EXECUTE_COMMAND',
          command: data.command
        }).catch(() => {});
        // Acknowledge
        ackCommand({ token: t, command_id: data.command.id });
      }
    } catch (err) {
      // Silent - server may be down
    }
  }, 250);
}

// Acknowledge command
async function ackCommand(data) {
  try {
    await fetch(API_BASE + '/commands/ack', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(data)
    });
  } catch (err) {
    // Silent
  }
}

console.log('[BG] PLO Remote Control background loaded');
