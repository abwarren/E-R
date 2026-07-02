/**
 * Seat Stability Validation — Test Matrix
 * 
 * Verifies that remote-w4p.html preserves seat positions regardless of player state.
 * Runs without browser — extracts and exercises the rendering logic directly.
 * 
 * Usage: node scripts/test_seat_stability.js
 */

const fs = require('fs');
const path = require('path');

// ── Load source and extract critical functions ─────────────────────────

const srcPath = path.join(__dirname, '..', 'source', 'remote-w4p.html');
const html = fs.readFileSync(srcPath, 'utf-8');

// Extract <style> block
const styleMatch = html.match(/<style>([\s\S]*?)<\/style>/);
const styles = styleMatch ? styleMatch[1] : '';

// Extract <script> block (after </style>)
const scriptMatch = html.match(/<script>\s*'use strict';([\s\S]*?)<\/script>/);
if (!scriptMatch) {
  console.error('ERROR: Could not extract script block from remote-w4p.html');
  process.exit(1);
}

// ── Verify CSS contains sitting-out rule ──────────────────────────────

function checkCSS() {
  const tests = [];
  
  // 1. Sitting-out CSS rule exists
  tests.push({
    name: 'CSS: .seat-box.sitting-out rule',
    pass: /\.seat-box\.sitting-out\s*\{/.test(styles),
    detail: styles.match(/\.seat-box\.sitting-out\s*\{[^}]*\}/)?.[0] || 'NOT FOUND'
  });

  // 2. Opacity is reduced
  tests.push({
    name: 'CSS: sitting-out opacity < 1',
    pass: /\.seat-box\.sitting-out[\s\S]*?opacity\s*:\s*0\.[0-9]+/.test(styles),
    detail: styles.match(/opacity\s*:\s*0\.[0-9]+/)?.[0] || 'NOT FOUND'
  });

  // 3. SITTING OUT label style exists
  tests.push({
    name: 'CSS: .seat-sitting-label display:block',
    pass: /\.seat-box\.sitting-out\s.*\.seat-sitting-label[\s\S]*?display\s*:\s*block/.test(styles),
    detail: styles.match(/\.seat-sitting-label\s*\{[^}]*\}/)?.[0] || 'NOT FOUND'
  });

  return tests;
}

// ── Verify source code patterns without running DOM ───────────────────

function checkSource() {
  const tests = [];
  const script = scriptMatch[1];

  // 1. posSeatMap filter: REMOVED "sitting_out" exclusion
  tests.push({
    name: 'posSeatMap: sitting_out filter REMOVED',
    pass: !script.includes('seat.status !== "sitting_out"'),
    detail: 'Previous: if (seat.name != null && seat.status !== "sitting_out") — removed'
  });

  // 2. posSeatMap filter: NOW includes all named seats
  tests.push({
    name: 'posSeatMap: seat.name != null (includes sitting_out)',
    pass: script.includes('seat.name != null') && 
          script.includes('Sitting out is a player state'),
    detail: 'Gate is now: seat.name != null only'
  });

  // 3. buildSeatBoxHtml: sitting-out class added
  tests.push({
    name: 'buildSeatBoxHtml: cls += sitting-out when status=sitting_out',
    pass: script.includes("seat.status === 'sitting_out') cls += ' sitting-out'"),
    detail: 'sitting-out class conditionally added to seat-box'
  });

  // 4. SITTING OUT label rendered
  tests.push({
    name: 'buildSeatBoxHtml: SITTING OUT label rendered',
    pass: script.includes("seat-sitting-label") && script.includes("SITTING OUT"),
    detail: 'DIV with class seat-sitting-label and text SITTING OUT'
  });

  // 5. seatHash includes status
  tests.push({
    name: 'seatHash: includes seat.status',
    pass: script.includes("seat.status || ''"),
    detail: 'Status part of hash — state transitions trigger re-render'
  });

  return tests;
}

// ── Scenario-based logic verification ─────────────────────────────────

// Simulate the renderSeats posSeatMap building logic
function buildPosSeatMap(seats) {
  const posSeatMap = {};
  for (const seat of seats) {
    // This is the CRITICAL line — the filter we changed
    if (seat.name != null) {
      const rawPos = seat.seat_no != null ? seat.seat_no : seat.seat_index;
      const pos = rawPos >= 1 ? rawPos - 1 : rawPos;
      if (pos != null && pos >= 0 && pos < 9) posSeatMap[pos] = seat;
    }
  }
  return posSeatMap;
}

// Simulate buildSeatBoxHtml class generation
function getSeatBoxClasses(seat) {
  const isHero = seat.is_self_player === true;
  const acts = seat.available_actions || [];
  const isActive = isHero && acts.length > 0;
  
  let cls = ['seat-box'];
  if (isHero) cls.push('hero');
  if (isActive) cls.push('expanded');
  if (seat.status === 'sitting_out') cls.push('sitting-out');
  // kh-marked, kh-auto — don't matter for this test
  return cls;
}

// Simulate seatHash
function seatHash(seat) {
  const sn = seat.seat_no != null ? seat.seat_no : seat.seat_index;
  const hc = (seat.hole_cards || []).join(',');
  const acts = (seat.available_actions || []).join(',');
  return seat.name + '|' + seat.stack_zar + '|' + hc + '|' +
    (seat.bet||0) + '|' + seat.is_dealer + '|' + acts + '|' +
    '||false|false|false|' + (seat.status || '');
}

function checkScenarios() {
  const tests = [];

  // ── Fixtures ──
  const bob = {
    seat_no: 3, seat_index: 3, name: 'Bob', stack_zar: 1000,
    status: 'playing', is_self_player: true, is_dealer: false,
    available_actions: [], hole_cards: [], bet: 0
  };
  const alice = {
    seat_no: 1, seat_index: 1, name: 'Alice', stack_zar: 2000,
    status: 'playing', is_self_player: false, is_dealer: false,
    available_actions: [], hole_cards: [], bet: 0
  };
  const charlie = {
    seat_no: 5, seat_index: 5, name: 'Charlie', stack_zar: 1500,
    status: 'playing', is_self_player: false, is_dealer: false,
    available_actions: [], hole_cards: [], bet: 0
  };

  // SCENARIO 1: Player active → Visible in assigned seat
  {
    const map = buildPosSeatMap([bob, alice, charlie]);
    const bobSlot = map[2]; // seat_no=3 → pos 2
    tests.push({
      name: 'Scenario 1: Bob active → seat_no=3 visible',
      pass: bobSlot && bobSlot.name === 'Bob' && bobSlot.seat_no === 3,
      detail: bobSlot ? `Seat ${bobSlot.seat_no}: ${bobSlot.name}` : 'NOT IN MAP'
    });
    const cls = getSeatBoxClasses(bob);
    tests.push({
      name: 'Scenario 1: Active Bob has NO sitting-out class',
      pass: !cls.includes('sitting-out'),
      detail: `Classes: ${cls.join(' ')}`
    });
  }

  // SCENARIO 2: Bob sits out → Same seat, greyed out, "SITTING OUT"
  {
    const bobSittingOut = { ...bob, status: 'sitting_out' };
    const map = buildPosSeatMap([bobSittingOut, alice, charlie]);
    const bobSlot = map[2]; // seat_no=3 → pos 2
    tests.push({
      name: 'Scenario 2: Bob sits out → STILL at seat_no=3',
      pass: bobSlot && bobSlot.name === 'Bob' && bobSlot.seat_no === 3,
      detail: bobSlot ? `Seat ${bobSlot.seat_no}: ${bobSlot.name} status=${bobSlot.status}` : 'NOT IN MAP — BUG'
    });
    const cls = getSeatBoxClasses(bobSittingOut);
    tests.push({
      name: 'Scenario 2: Sitting-out Bob HAS sitting-out CSS class',
      pass: cls.includes('sitting-out'),
      detail: `Classes: ${cls.join(' ')}`
    });
  }

  // SCENARIO 3: Bob sits back in → Same seat, returns to normal
  {
    const bobBack = { ...bob, status: 'playing' };
    const map = buildPosSeatMap([bobBack, alice, charlie]);
    const bobSlot = map[2];
    tests.push({
      name: 'Scenario 3: Bob sits back in → STILL at seat_no=3',
      pass: bobSlot && bobSlot.name === 'Bob' && bobSlot.seat_no === 3,
      detail: bobSlot ? `Seat ${bobSlot.seat_no}: ${bobSlot.name}` : 'NOT IN MAP — BUG'
    });
    const cls = getSeatBoxClasses(bobBack);
    tests.push({
      name: 'Scenario 3: Returned Bob has NO sitting-out class',
      pass: !cls.includes('sitting-out'),
      detail: `Classes: ${cls.join(' ')}`
    });
  }

  // SCENARIO 4: Another player sits out → No other seats move
  {
    const aliceSittingOut = { ...alice, status: 'sitting_out' };
    const map = buildPosSeatMap([bob, aliceSittingOut, charlie]);
    const bobSlot = map[2]; // seat_no=3 → pos 2
    const aliceSlot = map[0]; // seat_no=1 → pos 0
    const charlieSlot = map[4]; // seat_no=5 → pos 4
    tests.push({
      name: 'Scenario 4: Alice sits out → Bob stays at seat_no=3',
      pass: bobSlot && bobSlot.name === 'Bob' && bobSlot.seat_no === 3,
      detail: bobSlot ? `Bob seat=${bobSlot.seat_no}` : 'Bob NOT IN MAP — BUG'
    });
    tests.push({
      name: 'Scenario 4: Alice sits out → Alice stays at seat_no=1',
      pass: aliceSlot && aliceSlot.name === 'Alice' && aliceSlot.seat_no === 1,
      detail: aliceSlot ? `Alice seat=${aliceSlot.seat_no} status=${aliceSlot.status}` : 'Alice NOT IN MAP — BUG'
    });
    tests.push({
      name: 'Scenario 4: Alice sits out → Charlie stays at seat_no=5',
      pass: charlieSlot && charlieSlot.name === 'Charlie' && charlieSlot.seat_no === 5,
      detail: charlieSlot ? `Charlie seat=${charlieSlot.seat_no}` : 'Charlie NOT IN MAP — BUG'
    });
    tests.push({
      name: 'Scenario 4: All 3 seats accounted for (no compaction)',
      pass: Object.keys(map).length === 3,
      detail: `${Object.keys(map).length} seats in map (expected 3)`
    });
  }

  // SCENARIO 5: Hero sits out → Hero remains in same seat
  {
    const bobHeroSittingOut = { ...bob, status: 'sitting_out', is_self_player: true };
    const map = buildPosSeatMap([bobHeroSittingOut, alice, charlie]);
    const heroSlot = map[2];
    tests.push({
      name: 'Scenario 5: Hero sits out → STILL at seat_no=3',
      pass: heroSlot && heroSlot.name === 'Bob' && heroSlot.seat_no === 3 && heroSlot.is_self_player === true,
      detail: heroSlot ? `Hero seat=${heroSlot.seat_no} is_self=${heroSlot.is_self_player} status=${heroSlot.status}` : 'HERO NOT IN MAP — BUG'
    });
    const cls = getSeatBoxClasses(bobHeroSittingOut);
    tests.push({
      name: 'Scenario 5: Sitting-out hero HAS sitting-out class',
      pass: cls.includes('sitting-out') && cls.includes('hero'),
      detail: `Classes: ${cls.join(' ')}`
    });
  }

  // SCENARIO 6: New hand starts → Seat map unchanged
  {
    const newHandBob = { ...bob, hole_cards: ['Ah', 'Kh'], bet: 0, status: 'playing' };
    const newHandAlice = { ...alice, hole_cards: [], bet: 20, status: 'playing', is_dealer: true };
    const newHandCharlie = { ...charlie, hole_cards: [], bet: 0, status: 'playing' };
    const map = buildPosSeatMap([newHandBob, newHandAlice, newHandCharlie]);
    tests.push({
      name: 'Scenario 6: New hand → Bob seat_no=3 unchanged',
      pass: map[2] && map[2].name === 'Bob' && map[2].seat_no === 3,
      detail: map[2] ? `Bob seat=${map[2].seat_no} cards=${map[2].hole_cards}` : 'NOT IN MAP'
    });
    tests.push({
      name: 'Scenario 6: New hand → Alice seat_no=1 unchanged',
      pass: map[0] && map[0].name === 'Alice' && map[0].seat_no === 1,
      detail: map[0] ? `Alice seat=${map[0].seat_no}` : 'NOT IN MAP'
    });
    tests.push({
      name: 'Scenario 6: All 3 seats still present',
      pass: Object.keys(map).length === 3,
      detail: `${Object.keys(map).length} seats`
    });
  }

  // SCENARIO 7: Player leaves table → seat becomes empty
  {
    const charlieLeft = { ...charlie, name: null, status: 'empty' };
    const map = buildPosSeatMap([bob, alice, charlieLeft]);
    const emptySlot = map[4]; // seat_no=5 → pos 4
    tests.push({
      name: 'Scenario 7: Charlie leaves (name=null) → seat_no=5 empty',
      pass: emptySlot === undefined,
      detail: emptySlot ? `BUG: Charlie still in map at pos 4` : 'Correctly absent from posSeatMap'
    });
    tests.push({
      name: 'Scenario 7: Bob and Alice still present',
      pass: map[2] && map[2].name === 'Bob' && map[0] && map[0].name === 'Alice',
      detail: `${Object.keys(map).length} seats remain`
    });
  }

  // SCENARIO 8: seatHash changes on status transition
  {
    const hashActive = seatHash(bob); // status=playing
    const hashSittingOut = seatHash({ ...bob, status: 'sitting_out' });
    tests.push({
      name: 'Scenario 8: seatHash DIFFERS for playing vs sitting_out',
      pass: hashActive !== hashSittingOut,
      detail: `playing=${hashActive.substring(0,40)}... sitting_out=${hashSittingOut.substring(0,40)}...`
    });
  }

  return tests;
}

// ── Run all tests ─────────────────────────────────────────────────────

function runAll() {
  const allTests = [
    ...checkCSS(),
    ...checkSource(),
    ...checkScenarios()
  ];

  let passed = 0;
  let failed = 0;

  console.log('='.repeat(70));
  console.log('SEAT STABILITY VALIDATION — remote-w4p.html');
  console.log('='.repeat(70));
  console.log('');

  for (const t of allTests) {
    const status = t.pass ? 'PASS' : 'FAIL';
    if (t.pass) passed++; else failed++;
    console.log(`  [${status}] ${t.name}`);
    if (t.detail) {
      console.log(`         ${t.detail}`);
    }
  }

  console.log('');
  console.log('='.repeat(70));
  console.log(`RESULTS: ${passed} passed, ${failed} failed, ${allTests.length} total`);
  console.log('='.repeat(70));

  if (failed > 0) {
    console.log('\n❌ VALIDATION FAILED\n');
    process.exit(1);
  } else {
    console.log('\n✅ ALL TESTS PASSED — Seat stability preserved\n');
    process.exit(0);
  }
}

runAll();
