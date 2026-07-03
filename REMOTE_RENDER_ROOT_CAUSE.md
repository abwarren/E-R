# REMOTE_RENDER_ROOT_CAUSE.md

**Date:** 2026-07-03
**Status:** READ-ONLY INVESTIGATION — evidence only
**Confidence:** 95%

---

## Root Cause

**The API data oscillates between two states at ~85/15 ratio.**

The Remote UI is not the source of the flicker. It correctly renders whatever the backend API returns. The backend API returns oscillating data because the extension's DOM scraping inconsistently detects the `sitting_out` status.

## Evidence Chain

### Observed Oscillation (30 samples, sn 4552-4574)

| State | Frequency | Status | Stack | Dealer | Actions |
|-------|-----------|--------|-------|--------|---------|
| State A | 26/30 (87%) | `playing` | R63.50 | False | `[]` |
| State B | 4/30 (13%) | `sitting_out` | R59.00 | True | `['back_to_game']` |

Status toggles: 8 in 30 samples (27%)

### Oscillation Pattern

```
playing → playing → playing → sitting_out → playing → playing → playing → playing → playing → sitting_out ...
           ↑                                                              ↑
        87% of time                                                   13% of time
```

State A (playing) persists for 5-7 consecutive snapshots before briefly switching to State B (sitting_out) for 1 snapshot, then switching back.

### Pipeline Verification

```
Extension DOM scrape → status depends on DOM timing
        ↓
POST /api/snapshot → status reaches Flask
        ↓
table["seats"] merge → status stored
        ↓
/api/latest → status returned
        ↓
Remote UI renderSeats() → renders status from API
        ↓
seatHash includes status → hash changes → re-render triggered
```

Every stage in the pipeline faithfully transmits the data it receives. The oscillation originates in the extension's DOM scraping.

### seatHash() Analysis

```
seatHash fields:
  name | stack_zar | hole_cards | bet | is_dealer | available_actions |
  preActionState | cashoutState | autoCcPreflop | globalAutoCcPreflop |
  action_on | status
```

When status toggles between `playing` and `sitting_out`:
- `stack_zar` changes (R63.50 ↔ R59.00)
- `is_dealer` changes (False ↔ True)
- `available_actions` changes ([] ↔ back_to_game)
- `status` changes (playing ↔ sitting_out)

Result: seatHash changes → `renderedSeats[pos] === hash` fails → `innerHTML = buildSeatBoxHtml(seat)` executes → DOM replaced → user sees flicker.

### Render Frequency

| Seat | Hash Changes/20 | Would Render/20 |
|------|----------------|-----------------|
| Seat 1 (hero) | 7 | 7 (35%) |
| Seat 5 (observed) | 1 | 1 (5%) |

---

## First Field That Changes

**`status`** is the root change. When it toggles from `playing` to `sitting_out`:

1. `status: playing → sitting_out`
2. `stack_zar: 63.5 → 59.0` (consequence of different DOM state)
3. `is_dealer: False → True` (consequence of different DOM state)
4. `available_actions: [] → ['back_to_game']` (consequence of status change)

The remaining fields cascade from the status change. The `status` field is the **first observable change** in every oscillation event.

---

## Cause Classification

| Aspect | Finding |
|--------|---------|
| Is the flicker caused by polling? | No — polling frequency is stable, data oscillation is the issue |
| Is the flicker caused by state merge? | No — backend faithfully transmits extension data |
| Is the flicker caused by seatHash? | Partially — seatHash includes volatile fields (stack_zar, status) |
| Is the flicker caused by render logic? | No — renderSeats correctly re-renders when hash changes |
| Is the flicker caused by DOM replacement? | Consequence, not cause — innerHTML replacement happens because data changed |
| Is the flicker caused by extension DOM timing? | **YES** — the sitting_out CSS class is not consistently detected |

---

## File, Function, Line

| Component | File | Function | Line | Issue |
|-----------|------|----------|------|-------|
| Extension | `w4p.js` | `buildSnapshot` | 1347 | `ct.classList.contains('seat-out-v')` returns false most of the time |
| Backend | `app.py` | `_build_seats_list` | ~707 | `seat_data.get("status")` returns whatever extension sent |
| Remote UI | `remote-w4p.html` | `seatHash` | 823 | `seat.status` included in hash — changes trigger re-render |
| Remote UI | `remote-w4p.html` | `renderSeats` | 1084-1085 | Hash comparison — correct behavior, renders when data differs |

---

## Confidence: 95%

The 5% uncertainty is whether the extension's DOM scraping or the poker client's DOM rendering is the root cause of the CSS class not being present consistently. Both would produce the same symptoms.
