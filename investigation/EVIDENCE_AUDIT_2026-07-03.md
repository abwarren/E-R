# EVIDENCE AUDIT — Tracer Bullet Report Verification
## Source-Code-Verified Evidence Matrix

**Date:** 2026-07-03
**Auditor:** Evidence Auditor (automated)
**Report Audited:** `/home/wa/projects/poker/E&R/investigation/TRACER_BULLET_REPORT_2026-07-03.md`
**Source Files Audited:**
- `/home/wa/projects/poker/E&R/backend/app.py` (3546 lines)
- `/home/wa/projects/poker/E&R/backend/buffer.py` (221 lines)
- `/home/wa/projects/poker/E&R/source/w4p.js` (2158 lines)
- `/home/wa/projects/poker/E&R/source/engine_flow_controls.js` (412 lines)

---

## USER'S ASSESSMENT: Verdict Per Claim

| ID | Claim | User Class | Verdict | Source Verified | Correction |
|----|-------|-----------|---------|-----------------|------------|
| U1 | _select_best_table() oscillates — multiple (table_id, bot_id) entries, last_ts tiebreaker, bots post ~300ms, different "latest" on successive polls | STRONG | ✅ VERIFIED | TRUE | None |
| U2 | Tables are keyed by (table_id, bot_id) — per-bot isolation confirmed at code level | STRONG | ✅ VERIFIED | TRUE | None |
| U3 | back_to_game fails authority validation — is_authoritative_snapshot() returns False when only action is back_to_game, because POKER_ACTIONS doesn't include it | STRONG | ⚠️ NUANCED | PARTIALLY TRUE | See Correction C1 below |
| U4 | Selector degenerates into timestamp race — logical consequence of street=null for all entries making street_ranks equal | MODERATE | ✅ VERIFIED | TRUE | None |
| U5 | Flicker is caused by selection oscillation — browser-side TRACE not deployed, no complete vertical slice observed | WEAK | ⚠️ CORRECTLY FLAGGED | PARTIALLY TRUE (infrastructure gap, not code truth) | None |
| U6 | No end-to-end proof correlating SELECT change with Engine UI flicker | MISSING | ✅ CONFIRMED GAP | TRUE | None |

---

## DETAILED SOURCE CODE VERIFICATION

### U1: _select_best_table() Oscillation

**Source:** `backend/app.py` lines 1702-1779

```
Line 1702: def _entry_score(t, now):
Line 1709:     is_recent = 1 if (now - t.get("last_ts", 0)) < FRESHNESS_WINDOW else 0
Line 1710:     street_rank = STREET_RANK.get(t.get("street", "PREFLOP"), 0)
Line 1711:     reason_rank = _AUTH_REASON_RANK.get(t.get("_last_auth_reason"), 0)
Line 1712:     last_ts = t.get("last_ts", 0)
Line 1713:     tiebreak = hash(t.get("bot_id", "")) % 1000000
Line 1714:     return (is_recent, street_rank, reason_rank, last_ts, tiebreak)

Line 1717: def _select_best_table(table_id=None):
Line 1735:     for (tid, bid), t in _tables.items():
Line 1750:     recent = [(t, bid) for t, bid in candidates if (now - t.get("last_ts", 0)) < FRESHNESS_WINDOW]
Line 1753:     pool = recent if recent else candidates
Line 1754:     pool.sort(key=lambda x: _entry_score(x[0], now), reverse=True)
```

**Verdict:** The 5-tuple score `(freshness, street_rank, reason_rank, last_ts, tiebreak)` means entries with equal freshness + street_rank + reason_rank are sorted by `last_ts` descending. Since `last_ts` is updated on each snapshot POST (`app.py:1463`: `table["last_ts"] = ts`), and bots send at interleaved intervals (~300ms in the SCRAPE_INTERVAL from w4p.js), different bots become the "latest" entry on successive polls. **VERIFIED — the mechanism is correctly described.**

### U2: Tables Keyed by (table_id, bot_id)

**Source:** `backend/app.py` lines 183, 502-504, 507-527

```
Line 183: _tables = {}   # key: table_id → canonical table state  (DOCSTRING IS STALE)
Line 502: def _table_key(table_id, bot_id=None):
Line 503:     """Stable key for _tables dict — isolates per-bot state."""
Line 504:     return (table_id, bot_id or '__observer__')
Line 507: def get_or_create_table(table_id, bot_id=None):
Line 508:     key = _table_key(table_id, bot_id)
Line 509:     if key not in _tables:
Line 510:         _tables[key] = { ... "bot_id": bot_id or '__observer__', ... }
Line 527:     return _tables[key]
```

**Verdict:** _tables is keyed by `(table_id, bot_id)` tuple. `_select_best_table()` iterates by `for (tid, bid), t in _tables.items()` (line 1735). Each bot gets its own independent entry. The docstring on line 183 is stale (says "key: table_id") but the code is clear. **VERIFIED.**

### U3: back_to_game Fails Authority Validation

**Source:** `backend/app.py` lines 203, 427-474

```
Line 203: POKER_ACTIONS = frozenset({"fold", "check", "call", "bet", "raise", "all_in"})

Line 427: def is_authoritative_snapshot(snapshot):
Line 446:     actions = set(snapshot.get("available_actions", []))
Line 450:     if actions & POKER_ACTIONS:     # Signal 1
Line 451:         return True, "poker_actions"
Line 455:     if street in STREET_RANK and STREET_RANK.get(street, 0) > 0:  # Signal 2
Line 456:         return True, "street_advanced"
Line 462:     if hero:
Line 463:         has_cards = len(hero.get("hole_cards", [])) > 0
Line 464:         has_pot   = float(snapshot.get("pot_zar", 0) or 0) > 0
Line 465:         if has_cards and has_pot:     # Signal 3
Line 466:             return True, "cards_and_pot"
Line 471:     if board.get("flop"):           # Signal 4
Line 472:         return True, "board_present"
Line 474:     return False, None
```

**Verdict with Correction (C1):** The user's claim states `is_authoritative_snapshot()` returns False "when only action is back_to_game, because POKER_ACTIONS doesn't include it." This is **only conditionally true**. The function has 4 independent signals; ANY one is sufficient:

- **Signal 1** (poker actions): Always fails if only action is `back_to_game` ✅
- **Signal 2** (street advanced): Returns True if street is FLOP/TURN/RIVER REGARDLESS of actions
- **Signal 3** (cards_and_pot): Returns True if hero has hole_cards AND pot > 0 REGARDLESS of actions
- **Signal 4** (board present): Returns True if board.flop has cards REGARDLESS of actions

In the specific trace (TRACER report Section 1: street=PREFLOP, no board, likely no cards/pot), all 4 signals fail and the function returns False. **But the blanket statement is not universally true.** A `back_to_game` snapshot at FLOP street with visible community cards WOULD pass Signal 2 and/or Signal 4, making it authoritative.

The TRACER report's Section 5 statement — *"When a bot's only action is back_to_game, is_authoritative_snapshot() returns False, so street, board, and pot_zar are never written to the table entry"* — is **MISLEADING** as a general claim. See the False/Misleading section below.

### U4: Selector Degenerates into Timestamp Race

**Source:** `backend/app.py` lines 521, 1709-1714, 1337-1347

```
Line 521:         "street":        None,   # initial value in get_or_create_table()
Line 1337:         authoritative, reason = is_authoritative_snapshot(payload)
Line 1338:         if authoritative:
Line 1339:             table["street"] = payload.get("street")  # only set when authoritative

Line 1710:     street_rank = STREET_RANK.get(t.get("street", "PREFLOP"), 0)
```

**Verdict:** When all entries are non-authoritative (street remains `None`), `t.get("street", "PREFLOP")` returns `None` (key exists with value None), then `STREET_RANK.get(None, 0)` returns 0. All entries have street_rank=0. With equal freshness (both recent), equal reason_rank (0 for all), selection is purely on `last_ts`. **VERIFIED — the mechanism is a logical consequence of the scoring design.**

However, the "timestampe race" only manifests when ALL entries are non-authoritative. During active play, many snapshots DO become authoritative (via street_advanced at FLOP+, or board_present, or cards_and_pot), giving them non-zero street_rank. The race is most pronounced at PREFLOP when no bot has poker actions and board is empty.

### U5: Flicker Caused by Selection Oscillation (No Browser Proof)

**Source:** `engine_flow_controls.js` lines 291-342, `w4p.js` lines 1429-1441

```
engine_flow_controls.js:291: async function pollLatest() {
engine_flow_controls.js:297:       const res = await fetch(BRIDGE_URL, ...);
engine_flow_controls.js:312:       const text = formatTableDataToCanonical(data.table);
engine_flow_controls.js:313:       if (!text || text === lastSnapshotHash) { return; }  // dedup
engine_flow_controls.js:338:       lastSnapshotHash = text;
engine_flow_controls.js:341:       if (state.autoFill && text) { ... setTextareaValue(textarea, text); }
```

**Verdict:** The code path exists — SELECT oscillation → different API response → different formatted text → Engine accepts (text !== lastSnapshotHash) → textarea updated. But the TRACER report Section 4 explicitly states w4p.js TRACE and engine_flow_controls.js TRACE are **NOT DEPLOYED** to browser. **The user correctly identifies this as WEAK evidence — the causal chain is plausible from code but has no runtime browser confirmation.**

### U6: No End-to-End Proof

**Source:** TRACER report Section 4 (lines 57-58, 87-90, 137-148)

**Verdict:** The TRACER report explicitly documents that browser-side components are not deployed. Without ENGINE_FETCH → DIFF → TEXTAREA trace logs from a running browser, there is no empirical proof that backend SELECT oscillation causes visible textarea flicker. **CONFIRMED GAP.**

---

## CLAIMS IN TRACER REPORT MISSED BY USER ASSESSMENT

These are substantive claims in the TRACER report that the user did not evaluate:

| ID | Claim | TRACER Section | Evidence Class |
|----|-------|----------------|----------------|
| M1 | Different streets produce deterministic selection (higher street always wins regardless of timestamp) | Section 3, lines 117-124 | STRONG (directly verified by _entry_score at app.py:1710-1714) |
| M2 | 30-second FRESHNESS_WINDOW (app.py:1687) allows multiple bots to stay "recent" long enough to compete for selection | Section 6, Factor 2 | STRONG (code-verified: FRESHNESS_WINDOW=30 at app.py:1687) |
| M3 | Engine polls without bot_id query parameter, forcing _select_best_table() instead of targeted _find_table_for_bot() | Section 6, Factor 4 | STRONG (verified: BRIDGE_URL line 6 of engine_flow_controls.js has no bot_id param; _handle_table_latest at app.py:1869 falls through to _select_best_table()) |
| M4 | _table_view() performs sibling hero card merging across bot entries (Phase D) — the selected view may pull hole_cards from a different bot's entry | Section 5 (implied), app.py:900-952 | MODERATE (code-verified at app.py:908-922) |
| M5 | Hand ID cascading (_cascade_hand_id at app.py:1141-1161) propagates hand_id to sibling bot entries | Section 5 (implied) | MODERATE (code-verified) |
| M6 | Recommended fix #1: Selection hysteresis — add cache of last selected bot, prefer it on tied scores | Section 7 | RECOMMENDATION (not a factual claim) |
| M7 | Recommended fix #2: Include resume_hand / back_to_game in authority considerations | Section 7 | RECOMMENDATION |
| M8 | Recommended fix #3: Engine should track hand_id to detect perspective shifts | Section 7 | RECOMMENDATION |
| M9 | Regression risk: per-bot isolation was a critical prior fix; reverting to merged model reintroduces original flicker | Section 8 | STRONG (referenced from ROOT_CAUSE_VERIFICATION.md) |

---

## FALSE OR MISLEADING CLAIMS IN TRACER REPORT

### F1: is_authoritative_snapshot() ALWAYS rejects back_to_game snapshots

**Location:** TRACER report Section 5, lines 163-170

**What the report says:**
> "When a bot's only action is back_to_game, is_authoritative_snapshot() returns False, so street, board, and pot_zar are never written to the table entry. This results in street: null in the table, which means all entries have the same street rank (0), and selection devolves to a pure last_ts race."

**What the code actually does:** `is_authoritative_snapshot()` (app.py:427-474) has 4 independent signals. With only `back_to_game` as the action:
- Signal 1 (poker_actions): FAILS — back_to_game not in POKER_ACTIONS ✅
- Signal 2 (street_advanced): PASSES if street is FLOP/TURN/RIVER — **contradicts the blanket claim**
- Signal 3 (cards_and_pot): PASSES if hero has hole_cards AND pot > 0 — **contradicts**
- Signal 4 (board_present): PASSES if board.flop has cards — **contradicts**

**Correction:** The claim is only true for PREFLOP snapshots with no board and no cards/pot. At FLOP+ streets or with visible community cards, a `back_to_game` snapshot IS authoritative via Signals 2 or 4. The report should say: *"At PREFLOP with no visible board and no poker actions, is_authoritative_snapshot() returns False..."*

### F2: Footnote 49 oversimplifies the failure reason

**Location:** TRACER report Section 1, footnote 49 (line 49)

**What it says:**
> "null for street in the table entry because is_authoritative_snapshot() returns False when the only action is back_to_game (not in POKER_ACTIONS set)."

**Correction:** The POKER_ACTIONS exclusion is only ONE of the reasons Signal 1 fails. The function would still return True if any of Signals 2-4 succeeded. The footnote attributes the failure solely to POKER_ACTIONS exclusion, which is inaccurate.

### F3: _select_best_table() docstring omits authority_reason_rank

**Location:** app.py:1727-1730 (code docstring, not TRACER report)

**What it says:**
> "Selection priority (higher wins):
>  1. FRESHNESS — entry must be recent (< FRESHNESS_WINDOW seconds)
>  2. STREET RANK — RIVER > TURN > FLOP > PREFLOP
>  3. LAST_TS — most recently updated
>  4. HASH(bot_id) — deterministic tiebreak"

**Correction:** The actual _entry_score uses a 5-tuple: `(freshness, street_rank, auth_reason_rank, last_ts, tiebreak)`. The `auth_reason_rank` (poker_actions=3 > street_advanced=2 > others=1 > none=0) at position 3 is missing from the docstring. This is a **code documentation defect** (not a TRACER report error, but the TRACER report references this function without noting the omission).

### F4: Line number reference for Engine dedup is stale

**Location:** TRACER report Section 5, line 175:
> "Line: 289  if (!text || text === lastSnapshotHash) return;"

**Correction:** In the instrumented `engine_flow_controls.js`, the dedup check is at line 313, not 289. The pre-instrumentation line was 289, but the TRACER changes shifted it. Minor, but it could mislead someone looking at the instrumented file.

---

## JSON STRUCTURED EVIDENCE MATRIX

```json
{
  "audit_metadata": {
    "date": "2026-07-03",
    "auditor": "evidence_auditor",
    "report_audited": "/home/wa/projects/poker/E&R/investigation/TRACER_BULLET_REPORT_2026-07-03.md",
    "source_files": [
      "/home/wa/projects/poker/E&R/backend/app.py",
      "/home/wa/projects/poker/E&R/backend/buffer.py",
      "/home/wa/projects/poker/E&R/source/w4p.js",
      "/home/wa/projects/poker/E&R/source/engine_flow_controls.js"
    ]
  },
  "user_assessment_verification": [
    {
      "claim_id": "U1",
      "claim_text": "_select_best_table() oscillates — Multiple (table_id, bot_id) entries exist, selector uses last_ts as tiebreaker, bots post every ~300ms, different bots become 'latest' on successive polls.",
      "user_evidence_class": "STRONG",
      "source_verified": true,
      "verdict": "VERIFIED",
      "source_citations": [
        "backend/app.py:1702-1714:_entry_score: Score 5-tuple: (freshness, street_rank, reason_rank, last_ts, tiebreak)",
        "backend/app.py:1717-1779:_select_best_table: Iterates _tables items, sorts by _entry_score descending",
        "backend/app.py:1754:pool.sort: Reversed sort on _entry_score — highest last_ts wins when scores tied",
        "backend/app.py:1463:table['last_ts']=ts: last_ts updated on every snapshot POST",
        "backend/app.py:1687:FRESHNESS_WINDOW=30: 30-second freshness window"
      ],
      "notes": "Mechanism confirmed: when freshness + street_rank + reason_rank are equal, winner is determined by last_ts alone. With interleaved bot snapshots, the last-posting bot wins each poll cycle."
    },
    {
      "claim_id": "U2",
      "claim_text": "Tables are keyed by (table_id, bot_id) — per-bot isolation confirmed at code level.",
      "user_evidence_class": "STRONG",
      "source_verified": true,
      "verdict": "VERIFIED",
      "source_citations": [
        "backend/app.py:183:_tables={}: In-memory store",
        "backend/app.py:502-504:_table_key: Returns (table_id, bot_id or '__observer__')",
        "backend/app.py:507-527:get_or_create_table: Uses _table_key for dict access, creates separate entry per bot",
        "backend/app.py:1735:_select_best_table: for (tid, bid), t in _tables.items()"
      ],
      "notes": "Confirmed. Note: _tables docstring on line 183 is stale ('key: table_id') but code is correct."
    },
    {
      "claim_id": "U3",
      "claim_text": "back_to_game fails authority validation — is_authoritative_snapshot() returns False when only action is back_to_game, because POKER_ACTIONS doesn't include it.",
      "user_evidence_class": "STRONG",
      "source_verified": false,
      "verdict": "NUANCED — CONDITIONALLY TRUE",
      "source_citations": [
        "backend/app.py:203:POKER_ACTIONS=frozenset({'fold','check','call','bet','raise','all_in'})",
        "backend/app.py:427-474:is_authoritative_snapshot: Four independent signals, ANY sufficient",
        "backend/app.py:450-451:Signal 1 — actions & POKER_ACTIONS (fails for back_to_game)",
        "backend/app.py:455-456:Signal 2 — street in STREET_RANK and rank > 0 (SUCCEEDS at FLOP+)",
        "backend/app.py:462-466:Signal 3 — hero cards AND pot > 0 (SUCCEEDS if true)",
        "backend/app.py:470-472:Signal 4 — board.flop has cards (SUCCEEDS if board visible)"
      ],
      "notes": "CORRECTION: The claim is true ONLY if all 4 signals fail. At PREFLOP with no board and no cards/pot, this holds. But at FLOP+ or with visible board, Signal 2 or 4 makes the snapshot authoritative even with only back_to_game action. The TRACER report's blanket statement in Section 5 is misleading — see F1 in false/misleading section."
    },
    {
      "claim_id": "U4",
      "claim_text": "The selector degenerates into a timestamp race — logical consequence of street=null for all entries making all street_ranks equal.",
      "user_evidence_class": "MODERATE",
      "source_verified": true,
      "verdict": "VERIFIED",
      "source_citations": [
        "backend/app.py:521:street=None — initial value in get_or_create_table()",
        "backend/app.py:1337-1339:street only set when authoritative() returns True",
        "backend/app.py:1710:street_rank = STREET_RANK.get(t.get('street','PREFLOP'), 0)",
        "backend/app.py:204:STREET_RANK = {'PREFLOP':0, 'FLOP':1, 'TURN':2, 'RIVER':3}"
      ],
      "notes": "When street=None, t.get('street','PREFLOP') returns None (key exists with value None), and STREET_RANK.get(None, 0) returns 0. All non-authoritative entries get street_rank=0. With equal freshness+reason_rank, last_ts decides. This race is most pronounced at PREFLOP but is not inevitable during active play when boards are visible."
    },
    {
      "claim_id": "U5",
      "claim_text": "Flicker is caused by selection oscillation — browser-side TRACE not deployed, no complete vertical slice observed.",
      "user_evidence_class": "WEAK",
      "source_verified": true,
      "verdict": "CORRECTLY FLAGGED AS WEAK",
      "source_citations": [
        "engine_flow_controls.js:291-342:pollLatest: Fetches /api/latest, formats to canonical, dedup by text hash",
        "engine_flow_controls.js:312-313: Dedup — if (!text || text === lastSnapshotHash) return",
        "engine_flow_controls.js:338-341: On new hash, updates lastSnapshotHash, calls setTextareaValue",
        "TRACER report Section 4 lines 57-58,87-90,137-148: Browser components NOT DEPLOYED"
      ],
      "notes": "Code path exists: SELECT oscillation → different table view → different formatted text → Engine dedup passes → textarea updated. But no browser-side TRACE logs confirm this chain in a running browser. Assessment is correct."
    },
    {
      "claim_id": "U6",
      "claim_text": "No end-to-end proof correlating SELECT change with Engine UI flicker.",
      "user_evidence_class": "MISSING",
      "source_verified": true,
      "verdict": "CONFIRMED GAP",
      "source_citations": [
        "TRACER report Section 4 lines 143-144: w4p.js TRACE — NOT DEPLOYED",
        "TRACER report Section 4 lines 143-144: engine_flow_controls.js TRACE — NOT DEPLOYED"
      ],
      "notes": "Without ENGINE_FETCH/DIFF/TEXTAREA trace logs from a running browser, the causal chain (SELECT oscillation → API response change → Engine textarea change) cannot be empirically proven. Backend-side evidence shows SELECT oscillation; browser-side confirmation is missing."
    }
  ],
  "missed_claims_from_tracer_report": [
    {
      "claim_id": "M1",
      "claim_text": "Different streets produce deterministic selection — higher street always wins regardless of timestamp.",
      "tracer_section": "Section 3, lines 117-124",
      "source_citations": [
        "backend/app.py:1702-1714:_entry_score: street_rank is position 2 in 5-tuple, compared before last_ts",
        "backend/app.py:204:STREET_RANK = {'PREFLOP':0, 'FLOP':1, 'TURN':2, 'RIVER':3}"
      ],
      "notes": "Directly verified: STREET_RANK ensures RIVER > TURN > FLOP > PREFLOP in scoring. Higher street wins regardless of timestamp, even if its entry is old."
    },
    {
      "claim_id": "M2",
      "claim_text": "30-second freshness window allows multiple bots to stay 'recent' long enough to compete for selection.",
      "tracer_section": "Section 6, Contributing Factor 2",
      "source_citations": [
        "backend/app.py:1687:FRESHNESS_WINDOW = 30"
      ],
      "notes": "At ~300ms snapshot interval, 30 seconds covers ~100 snapshots per bot. Multiple bots easily remain 'recent' simultaneously."
    },
    {
      "claim_id": "M3",
      "claim_text": "Engine polls without bot_id query parameter, forcing _select_best_table() instead of targeted bot lookup.",
      "tracer_section": "Section 6, Contributing Factor 4",
      "source_citations": [
        "engine_flow_controls.js:6:BRIDGE_URL = ... '/api/latest' (no bot_id param)",
        "backend/app.py:1799:bot_id = request.args.get('bot_id')",
        "backend/app.py:1867-1869:if not table: table = _select_best_table()"
      ],
      "notes": "Without bot_id in the Engine request URL, _find_table_for_bot() returns None, and the fallback is _select_best_table() — which performs the stateless multi-bot selection."
    },
    {
      "claim_id": "M4",
      "claim_text": "_table_view() merges sibling hero cards across bot entries — selected view may pull hole_cards from other bots.",
      "tracer_section": "Implied by Section 5 Phase D architecture",
      "source_citations": [
        "backend/app.py:900-952:_table_view: Phase D sibling hero card merge",
        "backend/app.py:908-922: Iterates sibling _tables entries, merges hero hole_cards by seat_no"
      ],
      "notes": "This means even when _select_best_table picks one bot's entry, the resulting view may contain hole_cards from other bots at the same table. The flicker may include cards from multiple perspectives."
    },
    {
      "claim_id": "M5",
      "claim_text": "Hand ID cascading propagates new hand_id to all sibling bot entries at same table.",
      "tracer_section": "Implied by Section 5 Phase C",
      "source_citations": [
        "backend/app.py:1141-1161:_cascade_hand_id: Iterates _tables, updates hand_id for same table_id, different bot"
      ],
      "notes": "This ensures hand_id convergence across bots. But the Engine does not use hand_id for dedup, so convergence doesn't affect flicker."
    }
  ],
  "false_or_misleading_claims_in_tracer_report": [
    {
      "claim_id": "F1",
      "claim_text": "TRACER Section 5: 'When a bot's only action is back_to_game, is_authoritative_snapshot() returns False, so street, board, and pot_zar are never written to the table entry.'",
      "correction": "MISLEADING. is_authoritative_snapshot() has 4 independent signals with OR logic. Signals 2 (street_advanced at FLOP+), 3 (cards_and_pot), and 4 (board_present) can independently return True regardless of available_actions. The blanket statement is only true for PREFLOP snapshots with no board and no hero cards+pot.",
      "source_citations": [
        "backend/app.py:427-474:is_authoritative_snapshot — 4 independent signals with ANY-sufficient logic",
        "backend/app.py:455-456: Signal 2 succeeds at any street > PREFLOP, regardless of actions",
        "backend/app.py:470-472: Signal 4 succeeds if board has flop cards, regardless of actions"
      ]
    },
    {
      "claim_id": "F2",
      "claim_text": "TRACER footnote 49: 'is_authoritative_snapshot() returns False when the only action is back_to_game (not in POKER_ACTIONS set).'",
      "correction": "MISLEADING. Attributes the False result solely to POKER_ACTIONS exclusion. The function fails because ALL 4 signals fail for that specific trace (PREFLOP + no board + no cards/pot). The POKER_ACTIONS exclusion is only ONE necessary condition for Signal 1 failure, not a sufficient condition for overall failure.",
      "source_citations": [
        "backend/app.py:427-474:is_authoritative_snapshot"
      ]
    },
    {
      "claim_id": "F3",
      "claim_text": "_select_best_table() docstring at app.py:1727-1730 omits 'authority reason rank' from the listed selection priority, describing only 4 criteria when _entry_score() uses 5.",
      "correction": "CODE DOCUMENTATION DEFECT (not TRACER report error, but the TRACER report references this function without noting the omission). The actual priority is: freshness > street_rank > auth_reason_rank > last_ts > hash(bot_id).",
      "source_citations": [
        "backend/app.py:1702-1714:_entry_score: Returns 5-tuple (freshness, street_rank, reason_rank, last_ts, tiebreak)",
        "backend/app.py:1694-1699:_AUTH_REASON_RANK: poker_actions=3, street_advanced=2, cards_and_pot/board_present=1"
      ]
    },
    {
      "claim_id": "F4",
      "claim_text": "TRACER Section 5 line 175 references 'Line: 289' for Engine dedup in engine_flow_controls.js.",
      "correction": "MINOR STALE LINE NUMBER. The dedup check in the instrumented version is at line 313. Pre-instrumentation line was 289 but TRACER changes shifted it.",
      "source_citations": [
        "engine_flow_controls.js:313:if (!text || text === lastSnapshotHash) { return; }"
      ]
    }
  ],
  "summary": {
    "total_user_claims": 6,
    "verified": 4,
    "verified_with_correction": 1,
    "correctly_flagged_weak": 1,
    "missed_tracer_claims": 5,
    "false_or_misleading_tracer_claims": 4,
    "critical_finding": "Claim U3 and the TRACER report's blanket statement about back_to_game/authority are oversimplified. is_authoritative_snapshot() uses OR logic across 4 signals, not a single gate on POKER_ACTIONS. The race condition is real but not as inevitable as the report implies — it's a PREFLOP-specific edge case rather than a universal selector failure mode."
  }
}
```

---

## AUDIT SUMMARY

| Category | Count | Details |
|----------|-------|---------|
| User claims verified as-is | 4 | U1, U2, U4, U6 |
| User claims with corrections | 1 | U3 — back_to_game/authority claim is conditionally true, not universally true |
| User claims correctly flagged | 1 | U5 — correctly marked WEAK due to missing browser evidence |
| Missed TRACER claims | 5 (substantive) + 4 (recommendations) | Deterministic different-street selection, freshness window impact, bot_id-less polling, sibling card merge, hand_id cascading |
| False/misleading TRACER claims | 4 | F1 (authority blanket statement), F2 (oversimplified footnote), F3 (code docstring omission), F4 (stale line number) |

### Critical Finding

**The most impactful correction (F1):** The TRACER report's Section 5 states that `is_authoritative_snapshot()` returns False whenever the only action is `back_to_game`. This is misleading. The function uses **OR logic across 4 independent signals**. A `back_to_game` snapshot at FLOP/TURN/RIVER street or with visible community cards **will** return True via Signal 2 (street_advanced) or Signal 4 (board_present). The race condition is real at PREFLOP when no board exists, but not a universal property of the selection system.

**Recommendation:** Reframe the root cause analysis: the oscillation is a **PREFLOP-specific edge case** caused by the intersection of (a) all non-authoritative entries at PREFLOP, (b) equal street ranks (all 0), and (c) the `last_ts` tiebreaker. During post-flop play with visible boards, the selection stabilizes because at least one entry typically gains street_rank > 0 or board_present authority.
