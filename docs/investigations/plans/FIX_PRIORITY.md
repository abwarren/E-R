# E&R Poker Platform — Fix Priority & Corrected Audit

**Date:** 2026-06-23
**Status:** Verified findings with evidence. Corrections to SECURITY_AUDIT.md noted.

---

## Verification Results

### CRITICAL Findings — Verification

| ID | Finding | Status | Correction |
|----|---------|--------|------------|
| C1 | SSH private key in git (LINUXSSHKEY.pem) | **CONFIRMED** | `git ls-files` shows tracked. 26 lines, 1678 bytes, RSA 2048-bit. `.gitignore` has `*.pem` but file was committed before rule added. |
| C2 | Duplicate SSH key (~/.ssh/ploxyz.pem) | **CONFIRMED** | `diff` confirms byte-identical. Same fingerprint. |
| C3 | PokerBet account credentials | **CONFIRMED — WORSE** | 53 accounts found (audit said 35). Lines 1290-1343 in remote.html. All use `PokerPass123` except DanielleKorevaar (`Ashleyjancouys@1`) and jack.wilson67 (`JokerPass123`). |
| C4 | ANTHROPIC_API_KEY hardcoded | **INCORRECT — RETRACTED** | `app.py:1677` defaults to `""`. No hardcoded key. The system uses AWS Bedrock (BEDROCK_INFERENCE_PROFILE_ARN in .env). **Remove from audit.** |
| **C5** | `.env` tracked in git (contains secrets) | **NEW — MISSED** | `git ls-files` shows `backend/.env` tracked. Contains N4P_SEAT_SECRET + TRACKER_API_KEY (different from code defaults). 184 bytes. |
| **C6** | Flask session secret tracked in git | **NEW — MISSED** | `git ls-files` shows `backend/data/secret_key` tracked. 64-char hex. Anyone with this can forge user sessions. |
| **C7** | Runtime state tracked in git | **NEW — MISSED** | `git ls-files` shows `state/state_snapshot.json` tracked. Contains bot positions + table IDs. |

### HIGH Findings — Verification

| ID | Finding | Status | Correction |
|----|---------|--------|------------|
| H1 | DB password hardcoded (sunbet2024) | **CONFIRMED** | `db_logger.py:24` — `DB_PASS=os.get...
4')` |
| H2 | TRACKER_API_KEY hardcoded (key A: 03622c...) | **CONFIRMED — 12 FILES** | 12 source files contain `03622c...`. This is the OLD key. The .env contains a DIFFERENT key (key B: `80cafd...`). Two keys exist. |
| H3 | Engine auth credentials hardcoded | **CONFIRMED** | `app.py:62-67` — 4 users with unsalted SHA-256 hashes. |
| H4 | SCANNER_API_KEY hardcoded | **CONFIRMED** | `app.py:1044` has default hex key. .env overrides with different value. |
| H5 | N4P_SEAT_SECRET weak default | **CONFIRMED** | `app.py:171` — `'default_secret_change_me'`. .env overrides with real secret. |
| H6 | Engine SECRET_KEY default | **CONFIRMED** | `app.py:55` — `'plo-equity-secret-change-me'`. |
| H7 | API key in served JS files | **CONFIRMED** | 3 JS files embed the old key (03622c...). Extension JS files also have it. |
| H8 | CDP debugging port | **CONFIRMED (conditional)** | Port 9222 not listening on VM (laptop-side). 20+ scripts in ConceptPoker/ connect to it. Risk if port exposed beyond localhost. |

### TUNNEL Root Cause — Verified

| Hypothesis | Evidence | Verdict |
|-----------|----------|---------|
| EC2 rebuilt/replaced | Host key from known_hosts MATCHES live keyscan (same ed25519 fingerprint) | **DISPROVEN** |
| EC2 authorized_keys wiped | All 4 keys rejected. Server only accepts publickey (no password). | **CONFIRMED** |
| EC2 OS upgrade reset config | OpenSSH 10.2p1 (April 2026) — not standard Ubuntu 24.04 (9.6). Suggests major OS upgrade. | **LIKELY** |
| Key permissions wrong | All keys are 600 ✓ | **DISPROVEN** |
| SSH agent issue | No agent running | **DISPROVEN** — tested with explicit `-i` flags |

**Root cause (95% confidence):** The EC2's `ubuntu` user `authorized_keys` no longer contains any Hermes VM public key. The OpenSSH version (10.2p1 vs standard 9.6) and timing (post-June-17 reboot) strongly suggest an OS upgrade that reset the authorized_keys file. The host key is unchanged, confirming it's the same instance.

---

## Updated Severity Ranking

| Rank | ID | Finding | Security | Operational | Effort | Dependencies |
|------|----|---------|----------|-------------|--------|-------------|
| 1 | C6 | Flask session secret in git | CRITICAL | HIGH | 0.1 day | None |
| 2 | C5 | .env with secrets in git | CRITICAL | LOW | 0.1 day | None |
| 3 | C1 | SSH private key in git | CRITICAL | HIGH | 0.2 day | Tunnel fix needed |
| 4 | C3 | PokerBet credentials in source | CRITICAL | HIGH | 0.3 day | Must rotate 53 passwords |
| 5 | H2 | TRACKER_API_KEY in 12 files | HIGH | MEDIUM | 0.3 day | Rotate key on server |
| 6 | H1 | DB password hardcoded | HIGH | LOW | 0.1 day | Update postgres |
| 7 | H5 | N4P_SEAT_SECRET default | HIGH | LOW | 0.1 day | Update .env |
| 8 | H3 | Engine auth credentials | HIGH | LOW | 0.3 day | Migrate to bcrypt+DB |
| 9 | H7 | API key in served JS | MEDIUM | LOW | 0.5 day | JS runtime config |
| 10 | H4 | SCANNER_API_KEY default | MEDIUM | LOW | 0.1 day | Update .env |
| 11 | H6 | Engine SECRET_KEY default | MEDIUM | LOW | 0.1 day | Generate random |
| 12 | T1 | SSH tunnel down | — | CRITICAL | Unknown | EC2 access needed |
| 13 | C7 | Runtime state in git | LOW | LOW | 0.1 day | None |
| 14 | H8 | CDP port exposure | LOW | LOW | 0.1 day | Firewall rule |
| 15 | C2 | Duplicate SSH key | LOW | LOW | 0.1 day | Clean up ~/.ssh |

---

## Recommended Next 5 Actions (In Order)

### Action 1: Remove secrets from git history → .gitignore + untrack

**What:** These files are tracked in git and contain secrets:
- `backend/.env` (184 bytes — N4P_SEAT_SECRET + TRACKER_API_KEY)
- `backend/data/secret_key` (64 bytes — Flask session secret)
- `state/state_snapshot.json` (299 bytes — runtime bot state)
- `LINUXSSHKEY.pem` (1678 bytes — RSA private key)

**How:**
```bash
cd /home/wa/projects/poker/E&R
git rm --cached backend/.env backend/data/secret_key state/state_snapshot.json LINUXSSHKEY.pem
git commit -m "security: remove secrets from git tracking"
# Verify .gitignore covers all patterns
```

**Effort:** 10 minutes
**Risk:** Next commit will REMOVE these files from the repo. They will still exist locally. The .gitignore already has `*.pem`, `state/state_snapshot.json`. Need to add `backend/.env` and `backend/data/secret_key`.
**If skipping:** Secrets remain visible to anyone with repo access.

### Action 2: Rotate TRACKER_API_KEY everywhere

**What:** Two API keys exist:
- OLD: `03622c896cfbeacdfc537e9434f9ddc5` — in 12 source files
- CURRENT: `80cafdf71c072d03dd99ac1396d25c97a3f9af26393aea68fc6ec470fd431816` — in .env only

**How:**
1. Generate new key
2. Update .env with new key (any service that validates this key)
3. Remove all 12 hardcoded references to the old key from source files
4. Replace with placeholder comments or `process.env.API_KEY`
5. For JS files, fetch key from backend at startup instead of embedding

**Effort:** 2 hours
**Risk:** Breaking changes if any service validates only the old key. Must identify all consumers first.
**If skipping:** Old key leaks continue. If old key is still valid on any endpoint, anyone with it has access.

### Action 3: Rotate the Flask session secret

**What:** `backend/data/secret_key` contains `912d75753500f7e5fecd48a30c0e59ef74dff1a3c6854747d3dcf8349ec32c10`. This is in git history. Anyone with this can forge user sessions.

**How:**
1. Delete the tracked file from git (`git rm --cached`)
2. Add `backend/data/secret_key` to .gitignore
3. Generate new secret: `python -c "import secrets; print(secrets.token_hex(32))" > backend/data/secret_key`
4. This will invalidate all existing sessions (acceptable — local dev only)

**Effort:** 5 minutes
**Risk:** All current logged-in sessions invalidated. Must re-login.
**If skipping:** Session forgery possible for anyone with repo access.

### Action 4: Restore EC2 SSH access (tunnel)

**What:** The reverse SSH tunnel has been dead since June 17 with 4,200+ retries. EC2 rejects all keys. OpenSSH 10.2p1 on EC2 suggests OS upgrade wiped authorized_keys.

**How:**
1. **Option A (if AWS console access):** Use EC2 Instance Connect to add Hermes VM's public key to ubuntu's authorized_keys
2. **Option B (if another person has access):** Ask them to add the public key
3. **Option C (if nothing else):** Deploy new EC2 instance with Hermes VM's key pre-loaded

**Effort:** 1-4 hours depending on access method
**Risk:** None — tunnel is already broken. Recovery restores remote access to laptop.
**If skipping:** Laptop remains unreachable from VM. No remote development possible.

### Action 5: Sanitize PokerBet credentials from remote.html

**What:** 53 username/password pairs in `ENGINEENGINE/source/static/remote.html:1290-1343`.

**How:**
1. Move credentials to a separate config file (not tracked in git) or encrypted vault
2. Have the JS fetch credentials from an API endpoint at runtime
3. Replace the hardcoded array with a loader function
4. Rotate all 53 passwords on the poker sites

**Effort:** 2-4 hours (mostly password rotation)
**Risk:** Breaking auto-login for bots if not coordinated with rotation.
**If skipping:** Anyone with repo access can log into 53 poker accounts.

---

## Dependency Graph

```
Action 1 (untrack secrets) ── independent ──► can do NOW
Action 2 (rotate API keys) ── depends on identifying all consumers
Action 3 (rotate session secret) ── independent ──► can do NOW
Action 4 (fix tunnel) ── depends on EC2 access method ──► needs external help
Action 5 (sanitize credentials) ── independent but coordinated with password rotation
```

---

## What NOT to Fix Now

These are real issues but lower priority or blocked:

- **C4 (ANTHROPIC_API_KEY):** Retracted — not a finding. The key comes from AWS Bedrock, not hardcoded.
- **H3 (Engine auth):** Requires database migration. Defer to REFACTOR_PLAN.md Phase 6.
- **H8 (CDP port):** Currently only on laptop localhost. Defer until remote access is restored.
- **Purging git history:** Use `git filter-branch` or BFG to remove secrets from history. Defer until after the above fixes are in place so we're not purging files we're about to change.

---

## Files to Add to .gitignore Immediately

```
backend/.env
backend/data/secret_key
backend/data/hand-collector/
*.broken.*
*.current_broken.*
```

These are already gitignored but need verification:
```
*.pem          ✓ (line 39)
*.bak          ✓ (line 15)
*.bak.*        ✓ (line 16)
state/state_snapshot.json  ✓ (line 32)
```
