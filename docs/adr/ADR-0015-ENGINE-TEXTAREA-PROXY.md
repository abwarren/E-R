# ADR-0015: Engine Textarea Polling — Reverse Proxy Architecture

**Date:** 2026-07-01
**Status:** PROPOSED
**Severity:** P1 (High)
**Commit:** (pending acceptance)
**Decision Maker:** Engineering Investigation Protocol

---

## Problem Statement

The Engine UI (port 5002) polls `/api/table/latest` to populate its textarea with live hand data. The poller used a relative URL which resolved to `http://localhost:5002/api/table/latest`. The Engine Flask app had no such route — only `er-remote:4000` serves it. Result: HTTP 404, textarea never populated.

Two primary solutions were evaluated.

---

## Options Considered

### Option A: Change frontend `fetch()` URL to `http://localhost:4000/api/table/latest`

**Advantages:**
- 30-second fix
- No backend changes
- Immediate diagnostic confirmation

**Disadvantages:**
- Hardcoded URL — breaks staging, production, HTTPS, reverse proxy
- Introduces CORS dependency (cross-origin from port 5002 to port 4000)
- Frontend becomes environment-aware — violates separation of concerns
- Every port/scheme change requires frontend redeployment
- Locks the architecture to a specific topology

**Verdict:** REJECTED. Only useful as a temporary diagnostic verification.

---

### Option B: Reverse proxy in Engine Flask backend ⭐ SELECTED

`fetch("/api/table/latest")` → Engine Flask → proxy → `er-remote:4000/api/table/latest`

```
Browser (localhost:5002)
        │
        ▼
Engine Flask app
        │  REMOTE_BASE=http://er-remote:4000
        ▼
er-remote:4000 (Express + Flask table_state)
        │
        ▼
JSON response ← unchanged ← Engine Flask ← Browser
```

**Advantages:**
- Zero frontend changes — poller code untouched
- No CORS — same-origin from browser perspective
- No hardcoded URLs — backend knows the topology
- Environment-independent — `REMOTE_BASE` env var controls target
- Works in all environments (localhost, Docker, staging, production)
- Same pattern as enterprise systems (nginx reverse proxy, API gateway)
- Backend topology changes don't require frontend redeployment

**Disadvantages:**
- Adds ~35 lines to Engine Flask app
- Adds one network hop per poll (negligible: both on same Docker network)
- `REMOTE_BASE` env var must be set in non-Docker environments

**Verdict:** ACCEPTED. Clean separation of concerns, production-grade pattern.

---

### Option C: Serve Engine SPA from er-remote (port 4000)

**Advantages:**
- Same-origin by default — no proxy needed
- Zero backend code changes

**Disadvantages:**
- Tightly couples two independent applications (Equity Engine + Table State)
- Future separation requires untangling
- Engine container becomes deployment overhead for a static SPA
- Violates service boundaries established by Docker Compose

**Verdict:** REJECTED. Short-term convenience at the cost of long-term architecture debt.

---

## Decision

**Option B: Reverse proxy via Engine Flask backend.**

Frontend polls `/api/table/latest` — Engine Flask internally forwards to `er-remote:4000`. The browser never needs to know where the data actually lives.

### Implementation

```python
# source/app.py — added after logout route, before Config section
REMOTE_BASE = os.environ.get("REMOTE_BASE", "http://er-remote:4000")

@app.route("/api/table/", defaults={"subpath": ""}, methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
@app.route("/api/table/<path:subpath>", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
def proxy_table_api(subpath):
    target = f"{REMOTE_BASE}/api/table/{subpath}"
    # ... preserves method, headers, query params, status, body
```

### Targeted Endpoints

| Frontend Request | Proxied To |
|---|---|
| `GET /api/table/latest` | `GET http://er-remote:4000/api/table/latest` |
| Any `/api/table/*` | Forwarded identically |

---

## Consequences

- **Positive:** Textarea polling restored. No CORS. No frontend changes. Environment-independent.
- **Negative:** One additional network hop. `REMOTE_BASE` env var must be set in non-Docker environments.
- **Risk:** If er-remote:4000 is down, Engine UI polling fails gracefully (HTTP 502 proxy error, not silent).

---

## References

- ENGINE_TEXTAREA_TRACE.md — root cause investigation
- docker-compose.yml — services on `er-net` bridge network
- source/app.py — proxy implementation
