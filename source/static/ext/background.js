// PLO Remote Control - Background Service Worker
// Handles API communication (no CORS restrictions)

const API_BASE = 'http://127.0.0.1:4000/api';
let commandTimers = {};

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
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(snapshot)
    });
    const data = await resp.json();
    if (data.ok && tabId) {
      // Start command polling for this tab/seat
      const key = data.table_id + ':' + data.seat_no;
      if (!commandTimers[key]) {
        startCommandPolling(data.table_id, data.seat_no, tabId);
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

// Poll for commands
function startCommandPolling(tableId, seatNo, tabId) {
  const key = tableId + ':' + seatNo;
  console.log('[BG] Starting command poll for', key);

  commandTimers[key] = setInterval(async () => {
    try {
      const resp = await fetch(
        API_BASE + '/commands/pending?table_id=' + tableId + '&seat_no=' + seatNo
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
        ackCommand({
          table_id: tableId,
          seat_no: seatNo,
          command_id: data.command.id
        });
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
