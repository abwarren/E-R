const { spawn } = require('child_process');
const http = require('http');
const { WebSocket } = require('ws');

let chrome = null;
function cleanup() {
  if (chrome) { try { chrome.kill('SIGKILL'); } catch(e) {} chrome = null; }
}
process.on('exit', cleanup);
process.on('SIGINT', () => { cleanup(); process.exit(1); });

// Start Chrome
chrome = spawn('google-chrome-stable', [
  '--headless=new', '--no-sandbox', '--disable-gpu', '--disable-dev-shm-usage',
  '--remote-debugging-port=9222',
  'http://ec2-13-245-8-248.af-south-1.compute.amazonaws.com/'
], { stdio: ['ignore', 'pipe', 'pipe'] });
chrome.stderr.on('data', () => {});

function waitForWS() {
  return new Promise((resolve, reject) => {
    function tryConnect() {
      http.get('http://127.0.0.1:9222/json', (res) => {
        let data = '';
        res.on('data', c => data += c);
        res.on('end', () => {
          try {
            const pages = JSON.parse(data);
            if (pages.length > 0 && pages[0].webSocketDebuggerUrl) {
              resolve(pages[0].webSocketDebuggerUrl);
            } else { setTimeout(tryConnect, 500); }
          } catch(e) { setTimeout(tryConnect, 500); }
        });
      }).on('error', () => setTimeout(tryConnect, 500));
    }
    tryConnect();
    setTimeout(() => reject(new Error('WS timeout')), 20000);
  });
}

async function evalOnPage(ws, expression) {
  return new Promise((resolve, reject) => {
    const id = Date.now() + Math.random() * 1000;
    ws.send(JSON.stringify({ id, method: 'Runtime.evaluate', params: { expression, awaitPromise: true, timeout: 15000 } }));
    const to = setTimeout(() => reject(new Error('Eval timeout for: ' + expression.substring(0, 80))), 20000);
    const handler = (data) => {
      try {
        const msg = JSON.parse(data.toString());
        if (msg.id === id) {
          clearTimeout(to);
          ws.off('message', handler);
          if (msg.result && msg.result.value !== undefined) resolve(msg.result.value);
          else if (msg.result && msg.result.exceptionDetails) reject(new Error(msg.result.exceptionDetails.text));
          else reject(new Error('No result value'));
        }
      } catch(e) {}
    };
    ws.on('message', handler);
  });
}

async function main() {
  console.error('Waiting for Chrome...');
  const wsUrl = await waitForWS();
  const ws = new WebSocket(wsUrl);
  await new Promise((r, j) => { ws.on('open', r); ws.on('error', j); setTimeout(() => j(new Error('WS connect timeout')), 10000); });

  // Enable domains
  ws.send(JSON.stringify({ id: 1, method: 'Runtime.enable' }));
  ws.send(JSON.stringify({ id: 2, method: 'Page.enable' }));
  ws.send(JSON.stringify({ id: 3, method: 'DOM.enable' }));
  await new Promise(r => setTimeout(r, 1000));

  console.error('Navigating to page...');
  // Wait for page to load
  await new Promise((resolve) => {
    const id = 4;
    const handler = (data) => {
      try {
        const msg = JSON.parse(data.toString());
        if (msg.method === 'Page.loadEventFired') {
          ws.off('message', handler);
          resolve();
        }
      } catch(e) {}
    };
    ws.on('message', handler);
    ws.send(JSON.stringify({ id, method: 'Page.enable' }));
    // Also resolve after timeout
    setTimeout(resolve, 15000);
  });

  console.error('Page loaded. Checking for login form...');
  await new Promise(r => setTimeout(r, 3000));

  // Check current page state
  let pageState = await evalOnPage(ws, `document.title + ' | ' + (document.querySelector('input[placeholder*=\"username\" i], input[placeholder*=\"user\" i], input[name=\"username\"], input[type=\"text\"]') ? 'has_username_input' : 'no_username')`);
  console.error('Page state:', pageState);

  // Find login form fields
  let loginFields = await evalOnPage(ws, `JSON.stringify(Array.from(document.querySelectorAll('input')).map(function(i) { return {type: i.type, name: i.name, placeholder: i.placeholder, id: i.id, className: i.className.substring(0,40)}; }))`);
  console.error('Login fields:', loginFields);

  // Fill username field - try various selectors
  let fillResult = await evalOnPage(ws, `(function() {
    var field = document.querySelector('input[placeholder*=\"USERNAME\" i], input[placeholder*=\"user\" i], input[name=\"username\"], input[type=\"text\"]');
    if (!field) return 'NO_USERNAME_FIELD';
    var nativeSet = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
    nativeSet.call(field, 'admin');
    field.dispatchEvent(new Event('input', {bubbles:true}));
    field.dispatchEvent(new Event('change', {bubbles:true}));
    return 'set_username:' + field.value;
  })()`);
  console.error('Username fill:', fillResult);

  // Fill password field
  let passResult = await evalOnPage(ws, `(function() {
    var field = document.querySelector('input[type=\"password\"]');
    if (!field) return 'NO_PASSWORD_FIELD';
    var nativeSet = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
    nativeSet.call(field, 'PokerPass12345');
    field.dispatchEvent(new Event('input', {bubbles:true}));
    field.dispatchEvent(new Event('change', {bubbles:true}));
    return 'set_password:' + field.value;
  })()`);
  console.error('Password fill:', passResult);

  // Click Sign In button
  let clickResult = await evalOnPage(ws, `(function() {
    var btn = document.querySelector('button');
    if (!btn) return 'NO_BUTTON';
    if (btn.disabled) return 'BUTTON_DISABLED';
    btn.click();
    return 'CLICKED';
  })()`);
  console.error('Click result:', clickResult);

  // If button was disabled, try to enable it
  if (clickResult === 'BUTTON_DISABLED') {
    console.error('Button disabled - trying to enable it...');
    await evalOnPage(ws, `(function() {
      var btn = document.querySelector('button');
      if (btn) { btn.disabled = false; btn.click(); }
    })()`);
  }

  // Wait for page transition after login
  console.error('Waiting for post-login render...');
  await new Promise(r => setTimeout(r, 5000));

  // Check what's on the page now
  let postLoginState = await evalOnPage(ws, `(function() {
    var result = { title: document.title, textareaCount: 0, textareas: [], tabs: [], bodyPreview: '' };
    result.bodyPreview = (document.body ? document.body.innerHTML.substring(0, 2000) : 'NO_BODY');
    var allTas = document.querySelectorAll('textarea');
    result.textareaCount = allTas.length;
    for (var i = 0; i < allTas.length; i++) {
      var ta = allTas[i];
      result.textareas.push({
        id: ta.id || '',
        className: (ta.className || '').substring(0, 100),
        rows: ta.rows,
        placeholder: (ta.placeholder || '').substring(0, 60),
        value: (ta.value || '').substring(0, 100),
      });
    }
    // Find all visible buttons and tabs
    var btns = document.querySelectorAll('button, [class*=\"tab\"], [class*=\"btn\"]');
    var seen = {};
    for (var j = 0; j < btns.length; j++) {
      var txt = (btns[j].textContent || '').trim();
      if (txt && txt.length < 40 && !seen[txt]) { seen[txt] = true; result.tabs.push({text: txt, cls: btns[j].className.substring(0, 60)}); }
    }
    return JSON.stringify(result);
  })()`);

  console.log(postLoginState);
  cleanup();
  process.exit(0);
}

main().catch(e => { console.error('FATAL:', e.message); cleanup(); process.exit(1); });
