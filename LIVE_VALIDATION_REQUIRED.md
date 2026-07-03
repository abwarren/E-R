# LIVE_VALIDATION_REQUIRED — Seat Stability (w4p-seat-stability-v1)

**Created:** 2026-07-02
**Prerequisite:** EC2 reachable (SSH to 16.28.18.179), laptop tunnel active, live poker table open
**Blocking:** None — release is conditional, not blocked

## Context

Commit `94a6cfc` made sitting-out players remain visible in the Remote UI
grid in their assigned seat position. The change is isolated to
`source/remote-w4p.html` — no extension, backend, or API changes.

26/26 unit tests pass. Live production verification was deferred because EC2
SSH was unavailable at the time of release.

## Acceptance Criteria

On a live poker table (GoldRush/PokerBet), verify:

- [ ] Hero seated and visible in Remote UI
- [ ] A player sits out — same seat slot, greyed out, "SITTING OUT" label visible
- [ ] A second player sits out — neither player's seat position changes
- [ ] Player sits back in — returns to normal appearance in same seat slot
- [ ] No other players' grid positions shift during any of the above
- [ ] Hand completes, new hand starts — all seat assignments remain unchanged
- [ ] Player leaves table entirely — slot eventually clears (30s TTL)

For each state, capture screenshots:

1. Before sitting out (baseline — all active)
2. During sitting out (at least one greyed out)
3. After sitting back in (returned to normal)

**Visual proof:** The sequence must show `Bob → Bob (SITTING OUT) → Bob` —
never `Bob → EMPTY → Charlie`.

## Environment Setup

```bash
# 1. EC2 must be reachable
ssh -o ConnectTimeout=5 ubuntu@16.28.18.179 'echo OK'

# 2. Tunnel must be up
ss -tn | grep ':19999' | grep ESTAB

# 3. Laptop services running
ssh -p 19999 wa@127.0.0.1 'ss -tlnp | grep -E ":4000|:1080"'

# 4. Poker table open in browser with extension loaded
```

## Procedure

1. Open Remote UI: http://potlimitomaha.xyz or http://localhost:4000/remote
2. Observe the seat grid
3. Trigger sitting out on the poker table (click "Sit Out" or wait for auto-sit-out)
4. Capture Remote UI state
5. Trigger sitting back in
6. Capture Remote UI state
7. Repeat with a different player

## Related

- Commit: `94a6cfc` fix(remote): preserve seat positions for sitting-out players
- Tag: `w4p-seat-stability-v1`
- Test: `scripts/test_seat_stability.js`
- Release notes: `RELEASE_NOTES.md`
- Separate ticket: TODO — Investigate transient name disappearance (backend `name=null` → seat omission)
