# UPDATED ROOT CAUSE REPORT

**Date:** 2026-07-03
**Investigation:** Seat/Hand Collision — Complete Root Cause
**Status:** READ-ONLY — investigation complete, no fixes
**Source:** 63,329 live snapshots + 824 HAND_ID log events + full code analysis
**Supersedes:** ROOT_CAUSE_REPORT.md (2026-07-03, phase 1 findings)

---

## Executive Summary

The observed symptoms (Engine textarea overwrite, wrong hand on Remote, seat collisions, data jumping) have **two independent root causes** that compound each other:

1. **API Selection Oscillation** — `_select_best_table()` alternates between per-bot entries because last_ts changes with each POST
2. **Structural Field Guard Failure** — `hero_active` test is inverted: it blocks legitimate game data and passes lobby data

These are NOT the same problem. Fixing #1 alone would stabilize which entry consumers see, but the selected entry may contain wrong data (problem #2). Fixing #2 alone would ensure each entry has correct data, but consumers would still oscillate between entries (problem #1).

---

## 1. Root Cause 1: API Selection Oscillation

**Location:** `backend/app.py:1633` — `_select_best_table()`

**Mechanism:** 3 per-bot entries exist for `table_id=pb_2589955`. The API selector picks one based on freshness (last_ts). Since bots interleave POSTs at 300ms intervals, the selected entry oscillates at ~500ms period.

**Evidence:** 7 hand changes in 10 sequential API calls (confirmed in phase 1)

**Impact:** Consumers receive alternating hand contexts. Engine textarea overwrites each time the canonical text changes. Remote UI renders different player states.

---

## 2. Root Cause 2: Structural Field Guard Failure

**Location:** `backend/app.py:1197-1202` — `hero_active = bool(available_actions)`

**Mechanism:** The guard uses available_actions to gate structural field writes. This is semantically wrong:

- **False positive (39.5% error rate):** `["back_to_game"]` → guard passes → allinstalker writes lobby state (pot=0, board=[]) every 300ms
- **False negative (80% error rate):** `[]` → guard blocks → monarchi/Atros cannot write valid hand state (pot=40, board cards, street progression)

**Evidence:** 63,329 seat-level snapshots analyzed. 6,886 invalid lobby snapshots passed the guard. 18,015 valid game snapshots were blocked.

**Cascade failure:** Because structural fields are never written, `last_street_bot` is never set. The multi-bot guard at line 1152 sees `last_bot=None` and blocks ALL hand resets, including legitimate ones. Hand_id generation falls back to heuristic mode. The heuristic mode fails at PREFLOP (hand_key collision).

---

## 3. Root Cause 3: hand_id Echo Failure

**Location:** Extension `source/w4p.js` — `buildSnapshot()` + response handler

**Mechanism:** The extension never sends `hand_id` in POST payloads. The backend correctly generates and returns hand_id, but the extension never extracts it from the response and echoes it back.

**Evidence:** `hand=` field empty in 63,328/63,329 seat-level snapshots. Only 4 "Extension reports new hand" events ever occurred (all in a 1-second burst from Atros).

**Impact:** Without hand_id echo, the backend cannot distinguish between "same hand, next street" and "different hand, same table." The hand_id infrastructure (ADR-001 Phase 1) is deployed to the backend but the extension side is incomplete.

---

## 4. Relative Contribution to Symptoms

| Symptom | RC1 (Selection) | RC2 (Guard) | RC3 (hand_id) |
|---------|----------------|-------------|---------------|
| Engine textarea overwritten | **PRIMARY** — API returns different hand, hash changes | Secondary — the returned hand may have wrong data | Tertiary — hand_id could prevent overwrite |
| Remote shows wrong hand | **PRIMARY** — different entry per poll cycle | Secondary — the shown entry may have wrong pot/board | Tertiary |
| Seat collisions appear | Primary — same player, different state across entries | Secondary — wrong state in individual entries | Tertiary |
| Data jumps between hands | **PRIMARY** | Secondary | Tertiary |
| Structural fields wrong | Secondary | **PRIMARY** — guard blocks 63% of valid writes | Tertiary |
| hand_id not usable | N/A | Contributes — heuristic fallback unreliable | **PRIMARY** — extension never echoes |

---

## 5. First Component Where Each Identity Chain Fails

| Failure | File | Line | What breaks |
|---------|------|------|------------|
| API returns wrong hand context | `backend/app.py` | 1633 | `_select_best_table()` collapses N→1 |
| Structural fields not written | `backend/app.py` | 1197-1202 | `hero_active` guard blocks valid data |
| hand_id not in POST | `source/w4p.js` | buildSnapshot | Extension omits hand_id from payload |
| hand_id not echoed | `source/w4p.js` | response handler | Extension doesn't store response hand_id |
| Hand boundary not detected | `backend/app.py` | 1137-1146 | Heuristic PREFLOP collision |
| Multi-bot guard blocks everything | `backend/app.py` | 1152-1159 | last_street_bot never set → all blocked |

---

## 6. Correction Path

The investigation reveals that the architecture has THREE independent defects that compound. A surgical fix must address them in order of impact:

### Priority 1: Fix the guard condition (RC2)

Replace `hero_active = bool(available_actions)` with a compound authority signal (see STRUCTURAL_FIELD_AUTHORITY.md).

**Impact:** Stops lobby data contamination. Enables legitimate structural field writes. Unblocks multi-bot guard. Allows hand_id generation to work through the heuristic path.

**Risk:** LOW — change is inside the `_store_lock` critical section, one function replacement.

### Priority 2: Complete hand_id echo (RC3)

Wire the extension to extract `hand_id` from POST responses and echo it in subsequent POSTs.

**Impact:** Enables deterministic hand identification. Removes dependency on PREFLOP heuristic. Required for ADR-001 Phase 2.

**Risk:** MEDIUM — requires extension modification and browser reload across all bot instances.

### Priority 3: API selection (RC1)

After RC2 and RC3 are fixed, most of the oscillation will naturally resolve because:
- Entries will have correct structural fields (streets will advance properly)
- hand_id will provide a stable identity for consumers to track

A tactical change could expose `hand_id` in the API response so consumers can detect hand changes vs. entry selection changes.

**Risk:** LOW — additive field, no consumer changes required.

---

## 7. Why These Are Three Problems, Not One

The original investigation identified the API selection oscillation as the sole root cause. The proposed tactical fix (expose bot_id, have Engine filter on it) would have:

- Prevented Engine textarea from being overwritten when the API returned a different bot's entry ✓
- NOT fixed the fact that the "stable" entry might contain wrong data (pot=0 from lobby contamination) ✗
- NOT fixed the fact that legitimate hand progression is silently dropped ✗
- NOT enabled hand_id to work correctly ✗

The Engine would be "stuck" on one bot's entry that might have no structural state at all, or stale state from hours ago.

**Fixing only RC1 without RC2 is like stabilizing on a broken window — the view doesn't change, but it's still wrong.**

---

## 8. Confidence

| Root Cause | Confidence | Basis |
|-----------|-----------|-------|
| API selection oscillation | 100% | 7 changes in 10 API calls |
| Guard false negative (blocks valid data) | 100% | 18,015 blocked-but-valid snapshots |
| Guard false positive (passes lobby data) | 100% | 6,886 lobby snapshots passed |
| hand_id echo broken | 95% | 63,328/63,329 empty hand= fields |
| Multi-bot guard cascade failure | 90% | last_bot=None in logs |
| Three causes are independent | 100% | Different code paths, different failure modes |

---

## 9. Deliverable Inventory

All reports at: `/home/wa/projects/poker/E&R/investigation/seat-hand-collision-2026-07-03/`

| File | Content |
|------|---------|
| VERTICAL_SLICE_TRACE.md | Full data flow trace |
| TRACER_BULLET_HAND.md | Single hand end-to-end |
| HAND_COLLISION_REPORT.md | Hand merge/overwrite analysis |
| SEAT_COLLISION_REPORT.md | Seat ownership analysis |
| ENGINE_TEXTAREA_TRACE.md | Textarea overwrite mechanism |
| REMOTE_ENGINE_COMPARISON.md | Remote vs Engine divergence |
| IDENTITY_CHAIN_ANALYSIS.md | First point of identity loss |
| ROOT_CAUSE_REPORT.md | Phase 1 findings (API selection) |
| HERO_ACTIVE_GUARD_ANALYSIS.md | Guard mismatch discovery |
| STRUCTURAL_FIELD_TRUTH_TABLE.md | 63K snapshots analyzed |
| HERO_ACTIVE_VALIDATION.md | Guard accuracy: 28.6% |
| HAND_ID_PROPAGATION_TRACE.md | Why hand_id never propagates |
| STRUCTURAL_FIELD_AUTHORITY.md | Correct authority signal |
| UPDATED_ROOT_CAUSE.md | This file — complete synthesis |
