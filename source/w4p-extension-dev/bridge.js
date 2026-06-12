// W4P Bridge — ISOLATED world content script
// Relays messages between MAIN world (w4p.js via postMessage) and
// the background service worker (via chrome.runtime.sendMessage).

window.addEventListener('message', function(e) {
  if (!e.data || e.data.channel !== 'W4P_BRIDGE') return;

  var msg = e.data;
  chrome.runtime.sendMessage(
    { type: 'W4P_FETCH', path: msg.path, method: msg.method, body: msg.body, apiKey: msg.apiKey, rawPath: msg.rawPath },
    function(response) {
      window.postMessage({
        channel: 'W4P_BRIDGE_RESPONSE',
        reqId: msg.reqId,
        response: response
      }, '*');
    }
  );
});
