"""Feature flags for W4P platform. Read from env vars, default OFF for safe migration."""
import os

FLAGS = {
    # Phase A: Event bus with typed events, replay, versioning
    "USE_EVENT_BUS":    os.getenv("W4P_USE_EVENT_BUS", "true").lower() == "true",
    # Phase B: Unified frontend (engine panel embedded in remote)
    "USE_UNIFIED_LAYOUT": os.getenv("W4P_USE_UNIFIED_LAYOUT", "false").lower() == "true",
    # Phase C: Versioned state + diff-based updates
    "USE_VERSIONED_STATE": os.getenv("W4P_USE_VERSIONED_STATE", "false").lower() == "true",
    # Phase D: Formal hand lifecycle FSM
    "USE_HAND_FSM":     os.getenv("W4P_USE_HAND_FSM", "false").lower() == "true",
    # Phase E: Observability metrics
    "USE_OBSERVABILITY": os.getenv("W4P_USE_OBSERVABILITY", "true").lower() == "true",
}

def flag(name: str) -> bool:
    return FLAGS.get(name, False)
