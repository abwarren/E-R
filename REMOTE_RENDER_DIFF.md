# REMOTE_RENDER_DIFF.md

**Date:** 2026-07-03
**Investigation:** Flicker event trace — three-frame timeline

---

## Flicker Event: Seat 1 Status Oscillation

Every flicker event follows the same three-frame pattern:

### Frame 1: Stable (playing)
```
sn:       4552
status:   playing
stack:    R63.50
dealer:   false
actions:  []
```

### Frame 2: Toggle (sitting_out) ← FLICKER
```
sn:       4554
status:   sitting_out    ← CHANGED
stack:    R59.00         ← CHANGED
dealer:   true           ← CHANGED
actions:  [back_to_game] ← CHANGED
```

### Frame 3: Restore (playing)
```
sn:       4555
status:   playing        ← restored
stack:    R63.50         ← restored
dealer:   false          ← restored
actions:  []             ← restored
```

---

## What Changed

| Field | Frame 1 | Frame 2 | Frame 3 |
|-------|---------|---------|---------|
| status | playing | **sitting_out** | playing |
| stack_zar | 63.50 | **59.00** | 63.50 |
| is_dealer | false | **true** | false |
| available_actions | [] | **['back_to_game']** | [] |

---

## Timeline (Sample Oscillation Events)

```
sn 4552: playing   R63.50  dealer=F  acts=[]
sn 4553: playing   R63.50  dealer=F  acts=[]
sn 4554: sitting_out R59.00  dealer=T  acts=[back_to_game]  ← FLICKER
sn 4555: playing   R63.50  dealer=F  acts=[]               ← RESTORE

...5 stable samples...

sn 4559: sitting_out R59.00  dealer=T  acts=[back_to_game]  ← FLICKER
sn 4560: playing   R63.50  dealer=F  acts=[]               ← RESTORE

...4 stable samples...

sn 4563: sitting_out R59.00  dealer=T  acts=[back_to_game]  ← FLICKER
sn 4564: playing   R63.50  dealer=F  acts=[]               ← RESTORE
```

Pattern: ~5-7 stable `playing` snapshots, then 1 `sitting_out` snapshot, then immediate restore to `playing`.

---

## Visual Impact on Remote UI

1. Frame 1 → Frame 2: Seat re-renders as sitting_out (45% opacity, greyed, "SITTING OUT" label)
2. Frame 2 → Frame 3: Seat re-renders back to playing (full opacity, normal appearance, dealer chip appears)
3. Two consecutive DOM replacements within ~600ms → visible flicker

---

## seatHash() Change for This Event

```
Frame 1 hash: Atros|63.5|||false|||false|false|false|playing
Frame 2 hash: Atros|59.0|||true|back_to_game||false|false|false|sitting_out
Frame 3 hash: Atros|63.5|||false|||false|false|false|playing
```

Hash changes on both transitions because `stack_zar`, `is_dealer`, `available_actions`, and `status` all differ between the two states.
