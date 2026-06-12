// Copy-paste this into Engine UI console (F12) to run stress test

console.log("=== SMART TRIGGER STRESS TEST ===");
console.log("This will simulate 10 scenarios in 20 seconds\n");

const scenarios = [
  { name: "PREFLOP (4 players)", board: {flop:[]}, players: 4, expect: "skip" },
  { name: "FLOP #1 (6 players)", board: {flop:["Ah","Kd","Qs"]}, players: 6, expect: "TRIGGER" },
  { name: "SAME FLOP (duplicate)", board: {flop:["Ah","Kd","Qs"]}, players: 6, expect: "skip (dup)" },
  { name: "TURN (4 cards)", board: {flop:["Ah","Kd","Qs"],turn:"Jc"}, players: 6, expect: "skip (turn)" },
  { name: "RIVER (5 cards)", board: {flop:["Ah","Kd","Qs"],turn:"Jc",river:"Tc"}, players: 6, expect: "skip (river)" },
  { name: "NEW HAND PREFLOP", board: {flop:[]}, players: 6, expect: "skip" },
  { name: "FLOP #2 (6 players)", board: {flop:["9s","8h","7c"]}, players: 6, expect: "TRIGGER" },
  { name: "FLOP #2 duplicate", board: {flop:["9s","8h","7c"]}, players: 6, expect: "skip (dup)" },
  { name: "FLOP #3 (5 players)", board: {flop:["2s","3s","4s"]}, players: 5, expect: "skip (<6)" },
  { name: "FLOP #3 (6 players)", board: {flop:["2s","3s","4s"]}, players: 6, expect: "TRIGGER" },
];

let testIndex = 0;
const results = [];

function runTest() {
  if (testIndex >= scenarios.length) {
    console.log("\n=== TEST COMPLETE ===");
    console.log("Results:");
    results.forEach(r => {
      const status = r.pass ? "✓" : "✗";
      console.log(`${status} ${r.name}: expected ${r.expect}, got ${r.actual}`);
    });
    const passCount = results.filter(r => r.pass).length;
    console.log(`\nPassed: ${passCount}/${results.length}`);
    return;
  }

  const scenario = scenarios[testIndex];
  console.log(`\nTest ${testIndex + 1}/${scenarios.length}: ${scenario.name}`);
  console.log(`  Expected: ${scenario.expect}`);

  const snapshot = {
    ok: true,
    table: {
      hand_key: `test_${testIndex}_${Date.now()}`,
      board: scenario.board,
      seats: Array.from({length: scenario.players}, (_, i) => ({
        seat_no: i,
        name: `Player${i+1}`,
        hole_cards: ["As","Ad","Kh","Kc"]
      }))
    }
  };

  // Capture console output
  const originalLog = console.log;
  let capturedLogs = [];
  console.log = function(...args) {
    const msg = args.join(' ');
    if (msg.includes('[AUTO]')) {
      capturedLogs.push(msg);
    }
    originalLog.apply(console, args);
  };

  // Run trigger
  if (typeof engineFlowProcessSnapshot === 'function') {
    engineFlowProcessSnapshot(snapshot).then(() => {
      console.log = originalLog;
      
      const triggered = capturedLogs.some(log => log.includes('NEW FLOP DETECTED'));
      const skipped = capturedLogs.some(log => log.includes('Skipped'));
      
      let actual = triggered ? "TRIGGER" : skipped ? "skip" : "none";
      let pass = scenario.expect.includes(actual) || actual.includes(scenario.expect.split(' ')[0]);
      
      results.push({ name: scenario.name, expect: scenario.expect, actual, pass });
      
      testIndex++;
      setTimeout(runTest, 2000);
    });
  } else {
    console.log = originalLog;
    console.error("ERROR: engineFlowProcessSnapshot not found. Is the script loaded?");
  }
}

console.log("Starting in 2 seconds...");
setTimeout(runTest, 2000);
