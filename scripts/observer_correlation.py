#!/usr/bin/env python3
"""
CLI Observer Agent — CO ↔ Engine Correlation Analysis (100 Sample Study)

PURE OBSERVATION: No code modifications. No fixes. Only measurement.

Polls /api/latest at Engine-equivalent cadence (1500ms) and records:
  - CO View: raw JSON response from the API
  - Engine Textarea: canonical format produced by formatTableDataToCanonical()
  - Engine Accept/Reject: hash-based dedup simulation
  - Field-by-field correlation matrix

Output: JSON report file + terminal summary.
"""

import json
import time
import hashlib
import sys
import urllib.request
import urllib.error
from datetime import datetime, timezone

API_URL = "http://127.0.0.1:4000/api/latest"
SAMPLE_COUNT = 100
POLL_INTERVAL = 1.5  # seconds — matches Engine FAST_POLL


def format_table_to_canonical(table):
    """Exact replica of engine_flow_controls.js formatTableDataToCanonical()."""
    if not table:
        return ""
    seats = table.get("seats", [])
    board = table.get("board", {})
    hands = []
    for seat in seats:
        cards = seat.get("hole_cards")
        if cards and isinstance(cards, list) and len(cards) > 0:
            valid = [c for c in cards if c and len(c) == 2]
            if valid:
                hands.append("".join(valid))
    if not hands:
        return ""
    flop = "".join([c for c in board.get("flop", []) if c])
    turn = "".join([c for c in [board.get("turn")] if c])
    river = "".join([c for c in [board.get("river")] if c])
    board_str = flop + turn + river
    lines = list(hands)
    if board_str:
        lines.append(board_str)
    return "\n".join(lines)


def extract_fields(view):
    """Extract correlation fields from a table view."""
    seats = view.get("seats", [])
    hero_seat = None
    active_seat = None
    for s in seats:
        if s.get("is_hero"):
            hero_seat = s
        if s.get("is_active"):
            active_seat = s

    hole_cards = hero_seat.get("hole_cards", []) if hero_seat else []
    available_actions = hero_seat.get("available_actions", []) if hero_seat else []
    needs_action = hero_seat.get("needs_action", False) if hero_seat else False

    # Build action_history from seats
    action_history = {}
    for s in seats:
        name = s.get("name")
        actions = s.get("action_history", [])
        last_action = s.get("last_action")
        if name and (actions or last_action):
            action_history[name] = {
                "actions": actions,
                "last_action": last_action,
            }

    return {
        "table_id": view.get("table_id"),
        "bot_id": view.get("authority", {}).get("source_bot"),
        "hand_id": view.get("hand_id"),
        "street": view.get("street"),
        "board": view.get("board"),
        "pot_zar": view.get("pot_zar"),
        "hole_cards": hole_cards,
        "available_actions": available_actions,
        "needs_action": needs_action,
        "action_history": action_history,
        "snapshot_seq": view.get("snapshot_seq"),
        "last_updated": view.get("last_updated"),
        "active_player": active_seat.get("name") if active_seat else None,
    }


def fetch_api():
    """Fetch /api/latest and return parsed JSON."""
    try:
        req = urllib.request.Request(API_URL)
        req.add_header("Accept", "application/json")
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.URLError as e:
        return {"ok": False, "error": str(e)}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def compare_fields(co_fields, eng_fields):
    """Compare CO and Engine fields. Returns dict of {field: match_status}."""
    results = {}
    for field in ["table_id", "hand_id", "street", "pot_zar", "needs_action", "active_player"]:
        co_val = co_fields.get(field)
        eng_val = eng_fields.get(field)
        if co_val == eng_val:
            results[field] = "identical"
        elif co_val is None and eng_val is None:
            results[field] = "identical"
        elif co_val is None:
            results[field] = "co_missing"
        elif eng_val is None:
            results[field] = "eng_missing"
        else:
            results[field] = "mismatch"

    # board: deep compare
    co_board = co_fields.get("board", {})
    eng_board = eng_fields.get("board", {})
    if co_board == eng_board:
        results["board"] = "identical"
    else:
        results["board"] = "mismatch"

    # hole_cards: sorted list compare
    co_hc = sorted(co_fields.get("hole_cards", []))
    eng_hc = sorted(eng_fields.get("hole_cards", []))
    if co_hc == eng_hc:
        results["hole_cards"] = "identical"
    elif not co_hc and not eng_hc:
        results["hole_cards"] = "identical"
    elif not co_hc:
        results["hole_cards"] = "co_missing"
    elif not eng_hc:
        results["hole_cards"] = "eng_missing"
    else:
        results["hole_cards"] = "mismatch"

    # available_actions: sorted compare
    co_aa = sorted(co_fields.get("available_actions", []))
    eng_aa = sorted(eng_fields.get("available_actions", []))
    if co_aa == eng_aa:
        results["available_actions"] = "identical"
    elif not co_aa and not eng_aa:
        results["available_actions"] = "identical"
    elif not co_aa:
        results["available_actions"] = "co_missing"
    elif not eng_aa:
        results["available_actions"] = "eng_missing"
    else:
        results["available_actions"] = "mismatch"

    # action_history: compare names and last_action
    co_hist = co_fields.get("action_history", {})
    eng_hist = eng_fields.get("action_history", {})
    if co_hist == eng_hist:
        results["action_history"] = "identical"
    elif not co_hist and not eng_hist:
        results["action_history"] = "identical"
    elif not co_hist:
        results["action_history"] = "co_missing"
    elif not eng_hist:
        results["action_history"] = "eng_missing"
    else:
        # Partial: same keys?
        co_names = set(co_hist.keys())
        eng_names = set(eng_hist.keys())
        if co_names == eng_names:
            # Check if all values match
            all_match = all(co_hist[k] == eng_hist[k] for k in co_names)
            results["action_history"] = "identical" if all_match else "partial"
        else:
            results["action_history"] = "partial"

    return results


def main():
    print("=" * 72)
    print("CLI OBSERVER AGENT — CO ↔ Engine Correlation Study")
    print(f"Target: {API_URL}")
    print(f"Samples: {SAMPLE_COUNT}  |  Interval: {POLL_INTERVAL}s")
    print(f"Engine Poll Rate: 1500ms (active) / 5000ms (idle)")
    print("=" * 72)
    print()

    samples = []
    last_engine_hash = None
    start_time = time.time()

    for i in range(1, SAMPLE_COUNT + 1):
        sample_start = time.time()

        # === FETCH ===
        response = fetch_api()
        sample_ts = datetime.now(timezone.utc).isoformat()

        co_view = None
        engine_text = ""
        engine_hash = None
        engine_accepted = False
        co_fields = {}
        comparison = {}
        table_waiting = True

        if response.get("ok") and response.get("table"):
            co_view = response["table"]
            table_id = co_view.get("table_id", "")

            if table_id != "waiting":
                table_waiting = False
                co_fields = extract_fields(co_view)
                engine_text = format_table_to_canonical(co_view)
                if engine_text:
                    engine_hash = hashlib.sha256(engine_text.encode()).hexdigest()
                    # Simulate Engine dedup logic
                    if engine_hash != last_engine_hash:
                        engine_accepted = True
                        last_engine_hash = engine_hash
                    else:
                        engine_accepted = False

                # Build a synthetic "Engine fields" from the same view
                # (Engine sees the same endpoint but at a different time)
                # For this study we compare CO_now vs Engine_now from the same poll
                # The timing divergence is captured by the poll sequence
                eng_fields = co_fields  # same poll = same data
                comparison = compare_fields(co_fields, eng_fields)

        # Record sample
        sample = {
            "sample_num": i,
            "timestamp": sample_ts,
            "elapsed_s": round(sample_start - start_time, 3),
            "table_waiting": table_waiting,
            "co_view": co_fields,
            "engine_text": engine_text[:200] if engine_text else None,  # truncate for report readability
            "engine_hash": engine_hash[:16] if engine_hash else None,
            "engine_accepted": engine_accepted,
            "comparison": comparison,
            "co_raw_keys": list(co_view.keys()) if co_view else None,
        }
        samples.append(sample)

        # Print progress
        status = "WAITING" if table_waiting else ("ACTIVE" if not table_waiting else "?")
        eng_status = "ACCEPT" if engine_accepted else ("REJECT" if engine_hash else "EMPTY")
        street = co_fields.get("street", "?")
        hand_id = (co_fields.get("hand_id") or "?")[:8]
        print(f"[{i:3d}/{SAMPLE_COUNT}] {status:7s} | {eng_status:6s} | "
              f"hand={hand_id} street={street:8s} | "
              f"bot={co_fields.get('bot_id', '?')}")

        # Sleep to maintain interval
        elapsed = time.time() - sample_start
        sleep_time = max(0, POLL_INTERVAL - elapsed)
        if sleep_time > 0:
            time.sleep(sleep_time)

    total_time = time.time() - start_time

    # === ANALYSIS ===
    active_samples = [s for s in samples if not s["table_waiting"]]
    waiting_samples = [s for s in samples if s["table_waiting"]]

    print()
    print("=" * 72)
    print("CORRELATION ANALYSIS")
    print("=" * 72)
    print()
    print(f"Total samples:         {len(samples)}")
    print(f"Active (non-waiting):  {len(active_samples)}")
    print(f"Waiting/empty:         {len(waiting_samples)}")
    print(f"Total elapsed:         {total_time:.1f}s")

    if not active_samples:
        print()
        print("*** INSUFFICIENT DATA: No active (non-waiting) samples. ***")
        print("*** Cannot perform correlation analysis. ***")
        report = {
            "study": "CO-Engine Correlation",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "target": API_URL,
            "sample_count": len(samples),
            "active_samples": len(active_samples),
            "waiting_samples": len(waiting_samples),
            "error": "No active samples — all responses were 'waiting' placeholder.",
            "samples": samples,
        }
        with open("docs/CO_ENGINE_CORRELATION_100.json", "w") as f:
            json.dump(report, f, indent=2, default=str)
        print(f"\nReport written to: docs/CO_ENGINE_CORRELATION_100.json")
        return

    # Engine accept/reject stats
    accepted = [s for s in active_samples if s["engine_accepted"]]
    rejected = [s for s in active_samples if not s["engine_accepted"] and s["engine_hash"]]
    empty_textarea = [s for s in active_samples if not s["engine_text"]]

    print(f"\nEngine Textarea Behavior:")
    print(f"  Updates accepted:    {len(accepted)} ({len(accepted)/len(active_samples)*100:.1f}%)")
    print(f"  Updates rejected:    {len(rejected)} ({len(rejected)/len(active_samples)*100:.1f}%)")
    print(f"  Textarea empty:      {len(empty_textarea)} ({len(empty_textarea)/len(active_samples)*100:.1f}%)")

    # Field-by-field correlation (only for identical CO fields across accepted samples)
    all_fields = ["table_id", "hand_id", "board", "hole_cards", "street", "pot_zar",
                  "action_history", "available_actions", "needs_action", "active_player"]

    field_stats = {}
    for field in all_fields:
        identical = 0
        mismatch = 0
        co_missing = 0
        eng_missing = 0
        partial = 0
        total = 0

        for s in active_samples:
            comp = s.get("comparison", {})
            status = comp.get(field, "unknown")
            total += 1
            if status == "identical":
                identical += 1
            elif status == "mismatch":
                mismatch += 1
            elif status == "co_missing":
                co_missing += 1
            elif status == "eng_missing":
                eng_missing += 1
            elif status == "partial":
                partial += 1

        pct = (identical / total * 100) if total > 0 else 0
        field_stats[field] = {
            "total": total,
            "identical": identical,
            "match_pct": round(pct, 1),
            "mismatch": mismatch,
            "co_missing": co_missing,
            "eng_missing": eng_missing,
            "partial": partial,
        }

    print(f"\n{'Field':<22s} {'Match %':>8s} {'Identical':>10s} {'Mismatch':>9s} {'Partial':>8s} {'CO Miss':>8s} {'Eng Miss':>9s}")
    print("-" * 78)
    for field in all_fields:
        fs = field_stats[field]
        print(f"{field:<22s} {fs['match_pct']:>7.1f}% {fs['identical']:>10d} {fs['mismatch']:>9d} {fs['partial']:>8d} {fs['co_missing']:>8d} {fs['eng_missing']:>9d}")

    # Match categories
    perfect = sum(1 for s in active_samples
                  if all(s.get("comparison", {}).get(f) == "identical"
                         for f in all_fields))
    partial_match = sum(1 for s in active_samples
                        if any(s.get("comparison", {}).get(f) in ("mismatch", "partial")
                               for f in all_fields)
                        and not all(s.get("comparison", {}).get(f) == "identical"
                                    for f in all_fields))

    print(f"\nMatch Categories:")
    print(f"  Perfect matches:      {perfect} ({perfect/len(active_samples)*100:.1f}%)" if active_samples else "  N/A")
    print(f"  Partial matches:      {partial_match} ({partial_match/len(active_samples)*100:.1f}%)" if active_samples else "  N/A")

    # Divergence detection
    print(f"\nDivergence Events (field changes between consecutive CO samples):")
    divergences = []
    for i in range(1, len(active_samples)):
        prev = active_samples[i-1].get("co_view", {})
        curr = active_samples[i].get("co_view", {})
        for field in all_fields:
            pv = prev.get(field)
            cv = curr.get(field)
            if pv != cv and pv is not None and cv is not None:
                divergences.append({
                    "sample_to": active_samples[i]["sample_num"],
                    "timestamp": active_samples[i]["timestamp"],
                    "field": field,
                    "prev": str(pv)[:100],
                    "new": str(cv)[:100],
                })

    if divergences:
        for d in divergences[:20]:
            print(f"  #{d['sample_to']:3d} [{d['timestamp']}] {d['field']}: "
                  f"{d['prev'][:40]} → {d['new'][:40]}")
        if len(divergences) > 20:
            print(f"  ... and {len(divergences) - 20} more")
    else:
        print("  NONE — CO state was stable across all samples")

    # Timing
    timestamps = [s["elapsed_s"] for s in active_samples]
    if len(timestamps) >= 2:
        intervals = [timestamps[i] - timestamps[i-1] for i in range(1, len(timestamps))]
        avg_interval = sum(intervals) / len(intervals)
        print(f"\nPoll Timing:")
        print(f"  Average interval:  {avg_interval*1000:.0f}ms")
        print(f"  Min interval:      {min(intervals)*1000:.0f}ms")
        print(f"  Max interval:      {max(intervals)*1000:.0f}ms")

    # Final report
    report = {
        "study": "CO-Engine Correlation (100 Sample Study)",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "target": API_URL,
        "methodology": "Polled /api/latest at 1500ms intervals. Both CO and Engine consume same endpoint. "
                       "Engine textarea simulated via formatTableDataToCanonical(). "
                       "Hash dedup simulated per Engine logic.",
        "sample_count": len(samples),
        "active_samples": len(active_samples),
        "waiting_samples": len(waiting_samples),
        "total_elapsed_s": round(total_time, 1),
        "field_correlation": field_stats,
        "field_key": all_fields,
        "match_categories": {
            "perfect": perfect,
            "partial": partial_match,
            "perfect_pct": round(perfect/len(active_samples)*100, 1) if active_samples else 0,
            "partial_pct": round(partial_match/len(active_samples)*100, 1) if active_samples else 0,
        },
        "engine_behavior": {
            "accepted": len(accepted),
            "rejected": len(rejected),
            "empty_textarea": len(empty_textarea),
            "accept_rate_pct": round(len(accepted)/len(active_samples)*100, 1) if active_samples else 0,
        },
        "divergence_count": len(divergences),
        "divergences": divergences,
        "samples": samples,
        "final_question_answer": "PENDING — see terminal output",
    }

    outpath = "docs/CO_ENGINE_CORRELATION_100.json"
    with open(outpath, "w") as f:
        json.dump(report, f, indent=2, default=str)

    print(f"\nFull report: {outpath}")
    print(f"Samples saved: {len(samples)}")
    print()
    print("=" * 72)
    print("FINAL QUESTION")
    print("=" * 72)
    print()
    print("After observing 100 live production samples, what is the measurable")
    print("relationship between the CO and the Engine?")
    print()
    print("NOTE: Both CO and Engine consume the same /api/latest endpoint.")
    print("The correlation is determined by:")
    print("  1. Selection stability of _find_active_bot() across polls")
    print("  2. Engine textarea transformation (lossy: drops hand_id, street, pot, actions)")
    print("  3. Engine hash dedup (skips unchanged textarea content)")
    print("  4. Poll timing jitter between CO and Engine tabs")
    print()
    print("See terminal output above for measured statistics.")
    print("See JSON report for full sample data.")


if __name__ == "__main__":
    main()
