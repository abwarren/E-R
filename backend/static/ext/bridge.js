// W4P Bridge — ISOLATED world content script
// Relays messages between MAIN world (w4p.js via postMessage) and
// the background service worker (via chrome.runtime.sendMessage).

window.addEventListener('message', function(e) {
  if (!e.data || e.data.channel !== 'W4P_BRIDGE') return;

  var msg = e.data;
  console.log('[W4P_BRIDGE] RX from MAIN:', msg.path, msg.method);
  chrome.runtime.sendMessage(
    { type: 'W4P_FETCH', path: msg.path, method: msg.method, body: msg.body, apiKey: msg.apiKey, rawPath: msg.rawPath },
    function(response) {
      console.log('[W4P_BRIDGE] SW response:', response ? (response.ok ? 'OK' : 'FAIL: '+response.error) : 'no response');
      window.postMessage({
        channel: 'W4P_BRIDGE_RESPONSE',
        reqId: msg.reqId,
        response: response
      }, '*');
    }
  );
});

console.log('[W4P_BRIDGE] ISOLATED bridge loaded — listening for MAIN world messages');
// reload_1782265551