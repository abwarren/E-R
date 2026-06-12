"""
action_router.py — CDP Action Injection Router
================================================
Takes engine decision output → maps to DOM selectors → injects clicks
directly into Vivaldi browser tabs via Chrome DevTools Protocol (CDP).

Connection: ws://127.0.0.1:9222 (Vivaldi remote debugging port)

Usage:
    router = ActionRouter()
    router.execute_action(tab_id, selector)       # click element
    router.execute_script(tab_id, js_code)        # arbitrary JS
    router.find_goldrush_tabs()                   # list goldrush tabs
    router.decide_and_act(decision)               # full decide→act pipeline
"""

import json
import logging
import time
from typing import Optional, Dict, List, Any

import websocket

logger = logging.getLogger(__name__)

# ── CDP command ID counter (monotonic, per-connection) ────────────────────────
_cdp_id_counter = 0


def _next_cdp_id() -> int:
    global _cdp_id_counter
    _cdp_id_counter += 1
    return _cdp_id_counter


# ── Decision → DOM Selector map ────────────────────────────────────────────────
# Maps engine equity decision types to CSS selectors on the Goldrush table UI.
DECISION_SELECTORS: Dict[str, str] = {
    # Action buttons (Goldrush Poker)
    "fold":      'button[data-action="fold"], .action-fold, [class*="fold"]',
    "check":     'button[data-action="check"], .action-check, [class*="check"]',
    "call":      'button[data-action="call"], .action-call, [class*="call"]',
    "bet":       'button[data-action="bet"], .action-bet, [class*="bet"]',
    "raise":     'button[data-action="raise"], .action-raise, [class*="raise"]',
    "allin":     'button[data-action="allin"], .action-allin, [class*="allin"]',
    # Bet sizing
    "bet_25":    'button[data-amount="0.25"], .bet-quarter',
    "bet_33":    'button[data-amount="0.33"], .bet-third',
    "bet_50":    'button[data-amount="0.50"], .bet-half',
    "bet_66":    'button[data-amount="0.66"], .bet-two-thirds',
    "bet_75":    'button[data-amount="0.75"], .bet-three-quarters',
    "bet_pot":   'button[data-amount="1.00"], .bet-pot, [class*="pot"]',
    # Slider
    "slider":    'input[type="range"], .bet-slider input',
    "confirm":   'button[data-action="confirm"], .confirm-bet',
}


class ActionRouter:
    """Routes equity engine decisions to CDP-injected browser actions.

    Connects to Vivaldi via Chrome DevTools Protocol on ws://127.0.0.1:9222.
    Each execute_* call opens a fresh WebSocket, sends the command, waits for
    the response, and closes.  This keeps connections short-lived and avoids
    stale-socket issues in a long-running Flask process.

    HIGH-LATENCY operation: CDP round-trip ~3-10ms per command.
    """

    def __init__(self, cdp_url: str = "http://127.0.0.1:9222"):
        self.cdp_url = cdp_url.rstrip("/")
        self._ws_timeout = 5.0  # seconds

    # ── Public API ─────────────────────────────────────────────────────────

    def execute_action(self, tab_id: str, selector: str) -> Dict[str, Any]:
        """Click the first element matching *selector* in *tab_id*.

        Returns:
            {"ok": True, "tab_id": ..., "selector": ..., "result": ...}
            {"ok": False, "error": ...}
        """
        js = f'document.querySelector("{selector}")?.click()'
        return self.execute_script(tab_id, js)

    def execute_script(self, tab_id: str, js_code: str) -> Dict[str, Any]:
        """Evaluate arbitrary JavaScript in *tab_id* via Runtime.evaluate.

        Args:
            tab_id:  CDP page ID (e.g. "E0F791272A5782755107BA817FF4CB50")
            js_code: JavaScript to evaluate in the page context

        Returns:
            {"ok": True/False, "result": CDP result dict, ...}
        """
        ws_url = f"ws://127.0.0.1:9222/devtools/page/{tab_id}"
        result = self._cdp_call(ws_url, "Runtime.evaluate", {
            "expression": js_code,
            "returnByValue": True,
            "awaitPromise": True,
        })
        if result.get("ok"):
            cdp_result = result.get("result", {})
            # Check for exception
            exception = cdp_result.get("exceptionDetails")
            if exception:
                return {
                    "ok": False,
                    "error": "JS exception",
                    "exception": exception,
                    "tab_id": tab_id,
                    "js": js_code[:120],
                }
            return {
                "ok": True,
                "tab_id": tab_id,
                "js": js_code[:120],
                "result": cdp_result.get("result", {}),
            }
        return result

    def execute_click_text(self, tab_id: str, text: str) -> Dict[str, Any]:
        """Click a button by its visible text content (case-insensitive).

        Useful when DOM structure varies but button labels are stable.
        """
        js = (
            f'(function(){{'
            f'var btns=document.querySelectorAll("button, a, [role=button]");'
            f'var t={json.dumps(text.lower())};'
            f'for(var i=0;i<btns.length;i++){{'
            f'if((btns[i].textContent||"").trim().toLowerCase()===t){{btns[i].click();return true;}}'
            f'}}'
            f'return false;'
            f'}})()'
        )
        return self.execute_script(tab_id, js)

    def execute_decision(self, tab_id: str, decision: str) -> Dict[str, Any]:
        """Execute a named decision action on the Goldrush table.

        Args:
            tab_id:   CDP page ID for the Goldrush tab
            decision: One of "fold", "check", "call", "bet", "raise",
                      "allin", or a bet size like "bet_50", "bet_pot"

        Returns:
            {"ok": True/False, "action": decision, ...}
        """
        decision_lower = decision.lower().strip()
        selector = DECISION_SELECTORS.get(decision_lower)
        if not selector:
            # Try clicking by visible text as fallback
            action_text = decision_lower.replace("_", " ")
            result = self.execute_click_text(tab_id, action_text)
            result["action"] = decision_lower
            result["method"] = "text_match"
            return result

        result = self.execute_action(tab_id, selector)
        result["action"] = decision_lower
        result["method"] = "selector"
        return result

    def find_goldrush_tabs(self) -> List[Dict[str, str]]:
        """Return list of open Goldrush tabs with their CDP ids."""
        import urllib.request
        try:
            with urllib.request.urlopen(f"{self.cdp_url}/json/list", timeout=5) as resp:
                tabs = json.loads(resp.read().decode())
        except Exception as e:
            logger.error("[CDP] Failed to list tabs: %s", e)
            return []

        goldrush = []
        for t in tabs:
            url = t.get("url", "")
            title = t.get("title", "")
            if "goldrush" in url.lower() or "goldrush" in title.lower():
                goldrush.append({
                    "id": t["id"],
                    "title": title,
                    "url": url,
                    "ws_url": t.get("webSocketDebuggerUrl", ""),
                })
        return goldrush

    def get_tab_by_url_substring(self, substring: str) -> Optional[Dict[str, str]]:
        """Find a tab whose URL contains *substring*."""
        tabs = self.find_goldrush_tabs()
        for t in tabs:
            if substring.lower() in t.get("url", "").lower():
                return t
        # Fallback: search all tabs
        import urllib.request
        try:
            with urllib.request.urlopen(f"{self.cdp_url}/json/list", timeout=5) as resp:
                all_tabs = json.loads(resp.read().decode())
            for t in all_tabs:
                if substring.lower() in t.get("url", "").lower():
                    return {
                        "id": t["id"],
                        "title": t.get("title", ""),
                        "url": t.get("url", ""),
                        "ws_url": t.get("webSocketDebuggerUrl", ""),
                    }
        except Exception as e:
            logger.error("[CDP] Failed to list all tabs: %s", e)
        return None

    # ── Decide + Act pipeline ──────────────────────────────────────────────

    def decide_and_act(self, equity_result: Dict[str, Any],
                       tab_id: Optional[str] = None,
                       decision_mode: str = "auto") -> Dict[str, Any]:
        """Full pipeline: take equity results → decide action → inject into browser.

        Args:
            equity_result: The equity engine results dict (from /api/run)
            tab_id:        CDP tab ID. If None, auto-discover the Goldrush tab.
            decision_mode: "auto" (highest EV), "conservative", "aggressive"

        Returns:
            {"ok": True, "decision": ..., "action_result": ..., "equity": ...}
        """
        # 1. Auto-discover Goldrush tab if not provided
        if not tab_id:
            tabs = self.find_goldrush_tabs()
            if not tabs:
                return {"ok": False, "error": "No Goldrush tabs found"}
            tab_id = tabs[0]["id"]
            logger.info("[CDP] Auto-selected Goldrush tab: %s", tab_id)

        # 2. Derive decision from equity results
        decision = self._derive_decision(equity_result, decision_mode)
        if not decision:
            return {"ok": False, "error": "Could not derive decision from equity result"}

        # 3. Execute the action via CDP
        action_result = self.execute_decision(tab_id, decision)

        return {
            "ok": action_result.get("ok", False),
            "tab_id": tab_id,
            "decision": decision,
            "decision_mode": decision_mode,
            "action_result": action_result,
        }

    # ── Internal helpers ───────────────────────────────────────────────────

    def _derive_decision(self, equity_result: Dict[str, Any],
                         mode: str = "auto") -> Optional[str]:
        """Derive a poker action from equity engine results.

        Simple heuristic: if hero equity > 50%, bet/raise; else check/call/fold.
        """
        data = equity_result.get("data", equity_result)
        equities = equity_result.get("equities", [])
        matchups = data.get("matchups", [])

        # Extract hero equity from matchups
        hero_equity = None
        for m in matchups:
            names = [m.get("underdog_name", ""), m.get("favourite_name", "")]
            if "hero" in " ".join(names).lower() or "p1" in " ".join(names).lower():
                if "hero" in m.get("underdog_name", "").lower() or "p1" in m.get("underdog_name", "").lower():
                    hero_equity = m.get("und_real", m.get("und_raw", 50))
                else:
                    hero_equity = m.get("fav_real", m.get("fav_raw", 50))
                break

        # Fallback: use equities list
        if hero_equity is None and equities:
            hero_equity = equities[0]

        if hero_equity is None:
            hero_equity = 50.0

        # Derive action
        if mode == "conservative":
            if hero_equity < 30:
                return "fold"
            elif hero_equity < 45:
                return "check"
            elif hero_equity < 55:
                return "call"
            else:
                return "bet_50"
        elif mode == "aggressive":
            if hero_equity < 25:
                return "fold"
            elif hero_equity < 40:
                return "bet_33"
            elif hero_equity < 55:
                return "bet_66"
            else:
                return "bet_pot"
        else:  # auto
            if hero_equity < 25:
                return "fold"
            elif hero_equity < 45:
                return "check"
            elif hero_equity < 60:
                return "call"
            elif hero_equity < 75:
                return "bet_50"
            else:
                return "bet_pot"

    def _cdp_call(self, ws_url: str, method: str,
                  params: Optional[Dict] = None) -> Dict[str, Any]:
        """Low-level CDP call: open WS, send command, await response, close.

        Args:
            ws_url: Full WebSocket URL for the tab
            method: CDP method (e.g. "Runtime.evaluate")
            params: CDP params dict

        Returns:
            {"ok": True, "result": ...} or {"ok": False, "error": ...}
        """
        try:
            ws = websocket.create_connection(ws_url, timeout=self._ws_timeout)
        except Exception as e:
            logger.error("[CDP] WebSocket connect failed: %s", e)
            return {"ok": False, "error": f"WebSocket connect failed: {e}"}

        try:
            msg_id = _next_cdp_id()
            cmd = {
                "id": msg_id,
                "method": method,
                "params": params or {},
            }
            ws.send(json.dumps(cmd))

            # Read response — CDP sends back JSON with matching id
            deadline = time.time() + self._ws_timeout
            while time.time() < deadline:
                try:
                    ws.settimeout(max(0.1, deadline - time.time()))
                    raw = ws.recv()
                    response = json.loads(raw)
                    if response.get("id") == msg_id:
                        return {"ok": True, "result": response.get("result", response)}
                except websocket.WebSocketTimeoutException:
                    continue
                except Exception as e:
                    logger.warning("[CDP] recv error: %s", e)
                    break

            return {"ok": False, "error": "CDP response timeout"}

        except Exception as e:
            logger.error("[CDP] CDP call failed: %s", e)
            return {"ok": False, "error": str(e)}
        finally:
            try:
                ws.close()
            except Exception:
                pass


# ── Module-level convenience ──────────────────────────────────────────────────

_default_router: Optional[ActionRouter] = None


def get_router() -> ActionRouter:
    """Get or create the module-level ActionRouter singleton."""
    global _default_router
    if _default_router is None:
        _default_router = ActionRouter()
    return _default_router
