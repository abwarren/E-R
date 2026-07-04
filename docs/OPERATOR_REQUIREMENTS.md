# OPERATOR REQUIREMENTS

## Product Contract — W4P Remote Operator Console

**Status:** LOCKED
**Version:** 1.0.0
**Date:** 2026-07-03

---

## Purpose

The purpose of W4P is to enable a human operator to remotely play multiple poker clients.

No more. No less.

W4P is not a poker engine. It is not a distributed systems project. It is not a data pipeline. Those things exist to serve the operator, not the other way around.

---

## What the Operator Needs

The operator sits at a single screen. Multiple browser instances are playing poker on their behalf. The system must answer one question at every moment:

**"Whose turn is it, and what do they have?"**

Everything else is infrastructure.

---

## Production Requirements

These eight requirements define success. A change that does not advance at least one of them is out of scope.

### OP-1: Detect Which Bot Requires Action

The operator must never guess whose turn it is. The system must identify the bot whose poker client is waiting for an action and surface that bot immediately.

The active bot's browser DOM — specifically, the presence of action buttons — is the only authoritative signal.

### OP-2: Display That Bot's Hand

When a bot is selected, the operator must see the complete hand state:

- Hole cards
- Board cards (flop, turn, river)
- Pot amount
- Available actions (as buttons)

No partial information. No stale information from a previous hand.

### OP-3: Display Board, Pot, and Action History

The operator must see the full table context, not just the hero's cards. Board texture, pot size, and what actions other players have taken are essential for decision-making.

### OP-4: Send Identical Data to the Engine

The Engine textarea must receive exactly the same hand data the operator sees on the Remote. One source of truth. No transformation, no reinterpretation, no divergence.

### OP-5: Execute Fold, Call, and Raise

When the operator clicks a button, the correct action must execute on the correct browser instance. The command pipeline must be reliable and the operator must receive confirmation.

Fold. Call. Raise. These are the only actions that matter in production. Everything else — sit in, sit out, table selection — is secondary.

### OP-6: Never Lose the Current Hand

The system must never blank the display, clear the textarea, or discard hand state while a hand is in progress. If the system cannot determine the current state, it must retain the last known state rather than showing nothing.

A stale hand is better than no hand.

### OP-7: Never Clear the UI Unnecessarily

The Remote and Engine must not flash empty, show waiting placeholders, or reset to default state unless the underlying data genuinely requires it. Every unnecessary clear is a failure that costs the operator information.

### OP-8: Prefer Stable Information Over Perfect Synchronization

When there is a trade-off between showing the absolute latest data and showing stable, usable data, stability wins.

An operator can act on a hand that is 500ms old. An operator cannot act on a display that oscillates between three different hands.

---

## What Stability Means

Stability is not a nice-to-have. It is a requirement equal to data correctness.

**The stability rule:** If the operator looks away and looks back, the display must not have changed unless the underlying poker state has genuinely changed.

A display that changes because a different bot posted a snapshot 3ms more recently than another bot is not a genuine state change — it is a selection artifact. The system must suppress these artifacts.

---

## Explicitly Out of Scope

The following are recorded as future enhancements. They are not production requirements. Engineering resources must not be allocated to them until all eight operator requirements are met and stable.

- Perfect multi-bot table reconstruction
- Simultaneous display of multiple bots' hands
- Cross-bot state arbitration or merging
- Timestamp-based selection heuristics
- Street-rank-based authority models
- Multi-table dashboard or orchestration
- Polling rate optimization beyond what is needed for stability
- Any feature that adds complexity without directly serving OP-1 through OP-8

---

## Decision Framework

Every engineering decision must answer:

1. Which operator requirement does this serve (OP-1 through OP-8)?
2. Does this change make the operator's display more stable or less stable?
3. Is this solving a problem the operator actually has, or a problem that is interesting to solve?

If the answer to question 1 is "none" — the change is out of scope.

If the answer to question 2 is "less stable" — the change needs an explicit stability justification.

If the answer to question 3 is "interesting to solve" — defer it.

---

## Relationship to Other Documents

| Document | Role |
|----------|------|
| **OPERATOR_REQUIREMENTS.md** (this file) | Product contract. WHAT the system must do for the operator. |
| `W4P_MVP_REQUIREMENTS.md` | Engineering specification. HOW the system implements the contract. |
| `MVP_PROGRESS.md` | Status tracker. What has been done and what remains. |
| `REGRESSION_LOG.md` | Defect record. What broke, why, and how it was fixed. |

These four documents form a complete governance layer. No engineering work begins without referencing them.

---

## Sign-Off

This document is the product contract. It takes precedence over any implementation detail, architecture decision, or engineering preference. If an implementation conflicts with these requirements, the requirements win.

Changes to this document require operator sign-off. Engineering may not modify these requirements to accommodate implementation convenience.

---

**Locked:** 2026-07-03
**Next review:** When all eight operator requirements are verified in production.
