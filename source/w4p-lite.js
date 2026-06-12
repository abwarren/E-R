(function(){
  const LOCAL_BRIDGE = ["localhost", "127.0.0.1", "::1"].includes(window.location.hostname) || window.location.port === '4000';
  const API_BASE = LOCAL_BRIDGE ? "/api" : "https://haaats.xyz/api";
  const API_KEY = "03622c896cfbeacdfc537e9434f9ddc5";

  function normCard(x){
    if(!x) return null;
    x = String(x).trim()
      .replace(/10/g,'T')
      .replace(/ace/i,'A').replace(/king/i,'K').replace(/queen/i,'Q').replace(/jack/i,'J')
      .replace(/spades?/i,'s').replace(/hearts?/i,'h').replace(/diamonds?/i,'d').replace(/clubs?/i,'c')
      .replace(/♠/g,'s').replace(/♥/g,'h').replace(/♦/g,'d').replace(/♣/g,'c')
      .replace(/[^AKQJT2-9shdc]/gi,'');

    const m = x.match(/([AKQJT2-9])([shdc])/i);
    return m ? (m[1].toUpperCase() + m[2].toLowerCase()) : null;
  }

  function collectStrings(root){
    const out = [];
    [...root.querySelectorAll('*')].forEach(e => {
      out.push(String(e.className || ''));
      out.push(String(e.getAttribute('class') || ''));
      out.push(String(e.getAttribute('aria-label') || ''));
      out.push(String(e.getAttribute('title') || ''));
      out.push(String(e.getAttribute('alt') || ''));
      out.push(String(e.getAttribute('src') || ''));
      out.push(String(e.getAttribute('style') || ''));
      out.push(String(e.innerText || e.textContent || ''));
      out.push(String(e.outerHTML || '').slice(0, 500));
    });
    return out.join(' ');
  }

  function extractCardsFrom(root){
    const hay = collectStrings(root || document);
    const found = [];

    const patterns = [
      /(?:card|rank|playing-card|poker-card)[^A-Za-z0-9]{0,8}([AKQJT2-9]|10)[_\-\s:]*(spade|heart|diamond|club|spades|hearts|diamonds|clubs|[shdc])/ig,
      /([AKQJT2-9]|10)[_\-\s]*(spade|heart|diamond|club|spades|hearts|diamonds|clubs|[shdc])/ig,
      /(spade|heart|diamond|club|spades|hearts|diamonds|clubs|[shdc])[_\-\s]*([AKQJT2-9]|10)/ig
    ];

    for (const re of patterns) {
      let m;
      while ((m = re.exec(hay)) !== null) {
        let c;
        if (/[AKQJT2-9]|10/i.test(m[1]) && /(spade|heart|diamond|club|spades|hearts|diamonds|clubs|[shdc])/i.test(m[2])) {
          c = normCard(m[1] + m[2]);
        } else {
          c = normCard(m[2] + m[1]);
        }
        if (c && !found.includes(c)) found.push(c);
      }
    }

    return found.slice(0, 7);
  }

  function heroRoot(){
    return document.querySelector('.player-mini-container-p.self-player')
        || document.querySelector('.self-player')
        || document.querySelector('[class*="self-player"]')
        || document.querySelector('[class*="hero"]')
        || document.body;
  }

  function getSnapshot(){
    let snap = null;
    try {
      if (typeof window._w4p_buildSnapshot === 'function') {
        snap = window._w4p_buildSnapshot();
      }
    } catch(e) {}

    if (!snap) {
      snap = {
        table_id: (location.href.match(/tbl\/(\d+)/) || [null, "manual"])[1],
        bot_id: "Atros",
        seats: [{ seat_index: 0, name: "Atros", is_hero: true, status: "playing", hole_cards: [] }],
        board: { flop: [], turn: null, river: null },
        street: "PREFLOP",
        variant: "plo",
        source_key: "w4p_lite_fetch_eval",
        ts: new Date().toISOString()
      };
    }

    if (!snap.seats || !snap.seats.length) {
      snap.seats = [{ seat_index: 0, name: "Atros", is_hero: true, status: "playing", hole_cards: [] }];
    }

    return snap;
  }

  async function postSnapshot(cards){
    const snap = getSnapshot();
    const hero = snap.seats.find(s => s.is_hero || s.is_self_player || s.name === snap.bot_id) || snap.seats[0];

    hero.name = hero.name || snap.bot_id || "Atros";
    hero.bot_id = hero.bot_id || hero.name;
    hero.status = hero.status || "playing";
    hero.hole_cards = cards;

    snap.bot_id = hero.name;
    snap.variant = cards.length >= 4 ? ("plo" + cards.length) : "plo";
    snap.source_key = "w4p_lite_fetch_eval";
    snap.ts = new Date().toISOString();

    const res = await fetch(API_BASE + "/snapshot", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-API-Key": API_KEY
      },
      body: JSON.stringify(snap)
    });

    const txt = await res.text();
    console.log("[W4P-LITE][POST]", res.status, txt, snap);
    return snap;
  }

  window.w4pLiteSend = async function(){
    let cards = extractCardsFrom(heroRoot());

    if (!cards.length) {
      const manual = prompt("No cards auto-detected. Enter cards, e.g. Ah Kd Qs Jc");
      cards = String(manual || '').split(/[\s,]+/).map(normCard).filter(Boolean);
    }

    console.log("[W4P-LITE][CARDS]", cards);
    if (!cards.length) return console.warn("[W4P-LITE] No cards found/supplied");

    return postSnapshot(cards);
  };

  window.w4pLiteFillEngine = async function(){
    const j = await fetch(API_BASE + "/table/latest").then(r => r.json());
    const seats = ((j.table || {}).seats || []).filter(s => s.name || (s.hole_cards || []).length);
    const board = j.table && j.table.board;
    const lines = [];

    const n = Math.max(...seats.map(s => (s.hole_cards || []).length), 4);
    lines.push("PLO" + n + " " + seats.length + " players");

    if (board) {
      const b = []
        .concat(board.flop || [])
        .concat(board.turn ? [board.turn] : [])
        .concat(board.river ? [board.river] : []);
      if (b.length) lines.push("BOARD: " + b.join(" "));
    }

    lines.push("");
    seats.forEach(s => lines.push((s.name || s.bot_id || "Player") + ": " + (s.hole_cards || []).join(" ")));

    const ta = document.querySelector("textarea");
    if (!ta) return console.warn("[W4P-LITE] No textarea found");
    ta.value = lines.join("\n");
    ta.dispatchEvent(new Event("input", {bubbles:true}));
    ta.dispatchEvent(new Event("change", {bubbles:true}));
    console.log("[W4P-LITE][ENGINE_FILLED]", ta.value);
  };

  function addButton(){
    if (document.getElementById("w4p-lite-send")) return;
    const b = document.createElement("button");
    b.id = "w4p-lite-send";
    b.textContent = location.href.includes("/engine") ? "Fill Engine" : "Send Cards";
    b.style.cssText = "position:fixed;z-index:999999;right:12px;bottom:12px;padding:10px 14px;background:#111;color:#fff;border:2px solid #fff;border-radius:8px;font:14px Arial;cursor:pointer";
    b.onclick = location.href.includes("/engine") ? window.w4pLiteFillEngine : window.w4pLiteSend;
    document.body.appendChild(b);
  }

  addButton();
  console.log("[W4P-LITE] loaded. Use w4pLiteSend() on poker page or w4pLiteFillEngine() on engine page.");
})();
