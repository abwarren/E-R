# REMOTE_RENDER_FREQUENCY.md

**Date:** 2026-07-03

---

## Per-Seat Render Frequency (20 Snapshots)

| Seat | Name | Hash Changes | Would Render | Would Skip | Render Rate |
|------|------|-------------|-------------|-----------|-------------|
| 1 | Atros | 7 | 7 | 13 | 35% |
| 5 | Atros | 1 | 1 | 19 | 5% |
| 2,3,4,6,7,8,9 | (empty) | 0 | 0 | 20 | 0% |

---

## Render Classification

### Seat 1 (Hero): 7 renders, 20 samples

| Reason | Count | % |
|--------|-------|---|
| Status toggle (playing↔sitting_out) | 7 | 100% |
| Stack change only | 0 | 0% |
| Actions change (different hand) | 0 | 0% |
| No change (would skip) | 13 | — |

**100% of renders are caused by the status oscillation.** No renders were caused by genuine gameplay state changes (new hand, new actions, stack changes from betting).

### Seat 5 (Observed): 1 render, 20 samples

| Reason | Count |
|--------|-------|
| Single field change | 1 |

---

## Unnecessary Renders

**7 of 7 renders (100%) are "unnecessary"** in the sense that they render a transient state that immediately reverts. The sitting_out state appears for exactly 1 snapshot (~300ms) then reverts to playing. The user sees:

1. Normal seat → 2. Greyed-out "SITTING OUT" → 3. Normal seat (within ~600ms)

This creates the visible flicker.

---

## seatHash() Volatility Analysis

Fields that change between the two oscillating states:

| Field | State A (playing) | State B (sitting_out) | Volatile? |
|-------|-------------------|----------------------|-----------|
| name | Atros | Atros | Stable |
| stack_zar | 63.50 | 59.00 | **Yes** |
| hole_cards | [] | [] | Stable |
| bet | null | null | Stable |
| is_dealer | false | true | **Yes** |
| available_actions | [] | [back_to_game] | **Yes** |
| preActionState | (empty) | (empty) | Stable |
| cashoutState | false | false | Stable |
| autoCcPreflop | false | false | Stable |
| globalAutoCcPreflop | false | false | Stable |
| action_on | false | false | Stable |
| status | playing | sitting_out | **Yes** |

4 of 12 hash fields change when the DOM toggles. The hash changes completely.

---

## Snapshot Polling

| Metric | Value |
|--------|-------|
| Poll interval (active) | ~300ms |
| Duplicate snapshots | Yes — sn repeats within same window |
| Snapshot seq increment rate | ~3-4/sec |
| Response latency | <50ms |
| Snapshot staleness age | <1s (healthy) |

The Remote UI long-polls `/api/table/latest?timeout=25`. It receives data when the server unblocks. Each new snapshot wakes the long-poll. The Remote UI then fetches the next frame.
