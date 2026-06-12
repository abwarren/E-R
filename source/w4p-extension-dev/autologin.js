// W4P Auto-Login — reads credentials.json from extension and logs into PokerBet
(async function() {
  // Only run on top-level pokerbet page, not iframes
  if (window.self !== window.top) return;
  if (window.__w4p_autologin_done) return;
  window.__w4p_autologin_done = true;

  // Wait for page to settle
  await new Promise(r => setTimeout(r, 3000));

  // Check if already logged in (no Sign In button visible)
  const signInBtn = document.querySelector('button.btn.s-small.sign-in');
  if (!signInBtn) {
    console.log('[W4P-LOGIN] Already logged in or Sign In not found');
    return;
  }

  // Load credentials from extension bundle
  let creds;
  try {
    const url = chrome.runtime.getURL('credentials.json');
    const resp = await fetch(url);
    creds = await resp.json();
  } catch (e) {
    console.error('[W4P-LOGIN] No credentials.json found:', e);
    return;
  }

  if (!creds.username || !creds.password) {
    console.error('[W4P-LOGIN] Missing username/password in credentials.json');
    return;
  }

  console.log('[W4P-LOGIN] Logging in as:', creds.username);

  // Click Sign In
  signInBtn.click();
  await new Promise(r => setTimeout(r, 2000));

  // Fill credentials
  const userInput = document.querySelector('#login_form_id input[type=text], #login_form_id div:nth-child(3) label input');
  const passInput = document.querySelector('#login_form_id input[type=password], #login_form_id div:nth-child(4) label input');

  if (!userInput || !passInput) {
    console.error('[W4P-LOGIN] Login form not found');
    return;
  }

  // Set values using native input setter to trigger React/Angular change detection
  const nativeInputValueSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
  nativeInputValueSetter.call(userInput, creds.username);
  userInput.dispatchEvent(new Event('input', { bubbles: true }));
  userInput.dispatchEvent(new Event('change', { bubbles: true }));

  nativeInputValueSetter.call(passInput, creds.password);
  passInput.dispatchEvent(new Event('input', { bubbles: true }));
  passInput.dispatchEvent(new Event('change', { bubbles: true }));

  await new Promise(r => setTimeout(r, 500));

  // Submit
  const loginBtn = document.querySelector('#login_form_id button[type=submit], #login_form_id .entrance-form-actions-holder-bc button');
  if (loginBtn) {
    loginBtn.click();
    console.log('[W4P-LOGIN] Login submitted for', creds.username);
  } else {
    console.error('[W4P-LOGIN] Submit button not found');
  }
})();
