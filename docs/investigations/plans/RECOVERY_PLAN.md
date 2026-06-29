# E&R Poker Platform — Recovery Plan

**Date:** 2026-06-23
**Status:** Draft — awaiting approval before execution
**Downtime estimate:** 2-4 hours
**Risk level:** HIGH (secrets exposed on GitHub)

---

## URGENT: Repository Exposure

Both repos are on **GitHub** (`github.com/abwarren/E-R.git`). All secrets listed below are potentially visible to anyone with access to that repository. If the repository is **public**, these secrets are exposed to the entire internet.

**This plan assumes all secrets are compromised and must be rotated.**

---

## Phase 1: EC2 Access Recovery

### Current State

| Property | Value |
|----------|-------|
| EC2 IP | 16.28.18.179 |
| SSH | OpenSSH 10.2p1 (responding on port 22) |
| Auth methods | publickey only |
| Host key | Unchanged (same ed25519 fingerprint in known_hosts) |
| Hermes VM keys | All 4 rejected |
| AWS CLI | Broken (SignatureDoesNotMatch) |
| AWS region | af-south-1 (Cape Town) |

### Recovery Options (in priority order)

#### Option A: AWS Console → EC2 Instance Connect

**Prerequisites:** Web browser access to AWS Console at https://console.aws.amazon.com

1. Log into AWS Console → EC2 → Instances
2. Find instance with public IP 16.28.18.179
3. Select instance → Connect → EC2 Instance Connect
4. Once connected, run:
```bash
# Add Hermes VM's ED25519 public key
echo "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAILL/wePqLeMAD18fshe/jKgteNa4/1QrhGm+Kui+6S1J" >> ~/.ssh/authorized_keys

# Verify it was added
tail -1 ~/.ssh/authorized_keys

# Check what's currently in authorized_keys
cat ~/.ssh/authorized_keys
```
5. Test from Hermes VM:
```bash
ssh -o ConnectTimeout=5 ubuntu@16.28.18.179 "echo OK && hostname"
```
6. If successful, proceed to Phase 1 verification steps.

**Effort:** 15 minutes (if AWS console access available)
**Risk:** None

#### Option B: AWS Systems Manager Session Manager

**Prerequisites:** SSM Agent installed on EC2, IAM role with `AmazonSSMManagedInstanceCore`

1. AWS Console → Systems Manager → Session Manager → Start Session
2. Select the instance → Start Session
3. Add Hermes VM public key to authorized_keys (same as Option A step 4)

**Effort:** 15 minutes
**Risk:** None

#### Option C: EC2 User Data (Reboot Injection)

**Prerequisites:** Ability to modify EC2 instance user data (requires AWS console/API)

1. AWS Console → EC2 → Instances → select instance
2. Instance Settings → Edit User Data
3. Add:
```bash
#!/bin/bash
mkdir -p /home/ubuntu/.ssh
echo "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAILL/wePqLeMAD18fshe/jKgteNa4/1QrhGm+Kui+6S1J" >> /home/ubuntu/.ssh/authorized_keys
chown ubuntu:ubuntu /home/ubuntu/.ssh/authorized_keys
chmod 600 /home/ubuntu/.ssh/authorized_keys
```
4. Stop → Start the instance (new public IP likely)
5. Test SSH with the new IP

**Effort:** 30 minutes (includes reboot)
**Risk:** Public IP will change; DNS update needed for haaats.xyz

#### Option D: Launch Replacement EC2

**Prerequisites:** AWS console/API access, knowledge of current instance configuration

1. Launch new EC2 instance with Hermes VM's public key in launch template
2. Assign Elastic IP or update DNS
3. Re-deploy application code (from git)
4. Restore any persistent data from old instance (if recoverable)

**Effort:** 2-4 hours
**Risk:** Data loss if old instance has uncommitted state. Full redeployment required.

#### Option E: Fix AWS CLI Credentials

**Prerequisites:** Valid AWS access key

1. Get working AWS credentials
2. Configure: `aws configure --profile capetown`
3. Use AWS CLI to run SSM command or modify instance:
```bash
aws ssm send-command \
  --instance-ids i-xxxxx \
  --document-name AWS-RunShellScript \
  --parameters 'commands=["echo ssh-ed25519 AAAA... >> /home/ubuntu/.ssh/authorized_keys"]' \
  --region af-south-1
```

**Effort:** Depends on obtaining valid credentials
**Risk:** None

### Post-Recovery Verification (ONCE ACCESS RESTORED)

Run these commands on the EC2 to understand what happened:

```bash
# 1. Check authorized_keys
cat ~/.ssh/authorized_keys
ls -la ~/.ssh/

# 2. Check cloud-init logs for clues
sudo cat /var/log/cloud-init-output.log | tail -100
sudo grep -i "ssh\|authorized\|key" /var/log/cloud-init.log | tail -20

# 3. Check sshd config
sudo grep -E "PasswordAuthentication|PubkeyAuthentication|AuthorizedKeysFile" /etc/ssh/sshd_config

# 4. Check user account
id ubuntu
sudo grep ubuntu /etc/shadow | head -1

# 5. Check OS version and upgrade history
cat /etc/os-release
ls -la /var/log/apt/history.log*
grep "openssh-server" /var/log/apt/history.log*

# 6. Check when authorized_keys was last modified
stat ~/.ssh/authorized_keys

# 7. List all user home directories
ls -la /home/
```

Restore the tunnel **after** Phase 2 (key rotation):

```bash
# On Hermes VM, restart the tunnel service
systemctl --user restart er-tunnel.service

# Verify ports are forwarded
sleep 10
systemctl --user status er-tunnel.service --no-pager
ss -tlnp | grep 19999
```

**Tunnel restart should wait until SSH keypair is rotated (Phase 3).**

---

## Phase 2: Secret Rotation

### 2.1 SSH Keypair

| Asset | Current State | Action |
|-------|--------------|--------|
| LINUXSSHKEY.pem | RSA 2048-bit in git | **DELETE from all locations, REGENERATE** |
| ~/.ssh/ploxyz.pem | Identical copy of above | **DELETE** |
| Public key on EC2 | Unknown (likely wiped) | **REPLACE** with new key |
| Public key on Hermes VM authorized_keys | Present | **No change needed** (EC2 doesn't push to VM) |

**Procedure:**
```bash
# 1. Generate new ED25519 keypair on Hermes VM
ssh-keygen -t ed25519 -f ~/.ssh/er_ec2_ed25519 -C "er-tunnel@hermes-vm" -N ""

# 2. Authorize it on EC2 (after Phase 1 access restored)
# On EC2:
echo "ssh-ed25519 AAA...newkey... er-tunnel@hermes-vm" >> ~/.ssh/authorized_keys

# 3. Delete old key files
rm /home/wa/projects/poker/E&R/LINUXSSHKEY.pem
rm /home/wa/.ssh/ploxyz.pem

# 4. Update tunnel service to use new key
# Edit ~/.config/systemd/user/er-tunnel.service
# Add: -i /home/wa/.ssh/er_ec2_ed25519 \
```

### 2.2 Flask Session Secrets

| Asset | Location | Current Value | Action |
|-------|----------|---------------|--------|
| Session secret v1 | backend/data/secret_key | `912d7575...c32c10` | **ROTATE** |
| Session secret v2 | data/secret_key | `16777a88...20948b` | **DELETE** (duplicate file) |

**Procedure:**
```bash
# 1. Generate new secret
python3 -c "import secrets; print(secrets.token_hex(32))" > /home/wa/projects/poker/E&R/backend/data/secret_key

# 2. Delete duplicate
rm /home/wa/projects/poker/E&R/data/secret_key

# 3. Verify permissions
chmod 600 /home/wa/projects/poker/E&R/backend/data/secret_key
```

**Impact:** All existing user sessions invalidated. Users must re-login. Acceptable — local dev only.

### 2.3 N4P_SEAT_SECRET (HMAC Key)

| Asset | Current Value | Action |
|-------|--------------|--------|
| backend/.env | `778bb8...462f` | **ROTATE** |

**Procedure:**
```bash
# In /home/wa/projects/poker/E&R/backend/.env:
# Replace N4P_SEAT_SECRET with newly generated value
python3 -c "import secrets; print('N4P_SEAT_SECRET=' + secrets.token_hex(32))"
```

**Impact:** All existing seat tokens invalidated. Browsers must reload the poker page to get new tokens.

### 2.4 TRACKER_API_KEY

| Asset | Location | Value | Action |
|-------|----------|-------|--------|
| Old key (code default) | 12 source files | `03622c896cfbeacdfc537e9434f9ddc5` | **REMOVE from all files** |
| Current key (.env) | backend/.env | `80cafdf71c072d03dd99ac1396d25c97a3f9af26393aea68fc6ec470fd431816` | **ROTATE** |
| Extension JS files | 3+ files | `03622c...` | **REMOVE, use runtime config** |

**Procedure:**
```bash
# 1. Generate new key
python3 -c "import secrets; print('TRACKER_API_KEY=' + secrets.token_hex(32))"

# 2. Update .env with new key
# Edit /home/wa/projects/poker/E&R/backend/.env

# 3. Remove hardcoded default from app.py:172
# Change: DEFAULT_TRACKER_API_KEY = os.getenv('DEFAULT_TRACKER_API_KEY', '03622c...')
# To:     TRACKER_API_KEY = os.getenv('TRACKER_API_KEY')  # REQUIRED, no default

# 4. Remove key from all JS files:
# - backend/static/ext/background.js:16
# - backend/static/ext/w4p.js
# - backend/static/w4p.js
# - source/w4p.js
# - source/w4p-lite.js
# - ENGINEENGINE/source/static/w4p.js:19
# - ENGINEENGINE/source/static/w4p-full.js:16
# - ENGINEENGINE/source/static/n4p-full.js:16
# - ENGINEENGINE/source/static/dl/plo-chrome-extension/background.js:5
# - ENGINEENGINE/source/static/dl/plo-chrome-extension/content.js:13

# Replace with: var API_KEY = null; // configured at runtime via extension storage
# Or fetch from backend: fetch('/api/config').then(r=>r.json()).then(c=>{API_KEY=c.api_key})
```

**Impact:** All API consumers must be updated with new key. Coordinate with extension reload.

### 2.5 Database Passwords

| Asset | Location | Current Value | Action |
|-------|----------|---------------|--------|
| PostgreSQL password | db_logger.py:24 | `sunbet2024` | **ROTATE** |
| Default postgres user | db_logger.py:23 | `postgres` | **Review** |

**Procedure:**
```bash
# 1. Change PostgreSQL password
sudo -u postgres psql -c "ALTER USER postgres PASSWORD 'new-password-here';"

# 2. Update E&R .env
echo "DB_PASS=new-password-here" >> /home/wa/projects/poker/E&R/backend/.env

# 3. Remove hardcoded default from db_logger.py:24
# Change: DB_PASS = os.getenv("DB_PASS", "sunbet2024")
# To:     DB_PASS = os.getenv("DB_PASS")  # REQUIRED, no default
```

**Impact:** Flask app must restart to pick up new password. PostgreSQL connections drop briefly.

### 2.6 ENGINEENGINE Secrets

| Asset | Location | Value | Action |
|-------|----------|-------|--------|
| SCANNER_API_KEY | source/.env | `b36c7...76a2` | **ROTATE** |
| SCANNER_API_KEY default | source/app.py:1044 | `a3f9k2b7...` | **REMOVE default** |
| SECRET_KEY default | source/app.py:55 | `plo-equity-secret-change-me` | **GENERATE random** |
| Auth credentials | source/app.py:62-67 | 4 hashed passwords | **MIGRATE to DB** |
| BEDROCK config | source/.env | ARN/profile | **NOT a secret** — ARN is not sensitive |

**Procedure:**
```bash
# 1. Generate and update SCANNER_API_KEY
python3 -c "import secrets; print('SCANNER_API_KEY=' + secrets.token_hex(32))"
# Update source/.env

# 2. Generate SECRET_KEY
python3 -c "import secrets; print('SECRET_KEY=' + secrets.token_hex(32))"
# Update source/.env or generate at startup

# 3. Remove hardcoded auth from app.py:62-67
# Replace with database-backed auth (defer to REFACTOR_PLAN.md Phase 6)
# For now, move to .env with bcrypt hashes
```

**Impact:** Engine auth sessions invalidated. Scanner connections drop until key updated.

### 2.7 PokerBet Account Passwords

| Asset | Location | Count | Action |
|-------|----------|-------|--------|
| PokerBet accounts | ENGINEENGINE/source/static/remote.html | **1075 accounts** (935 with shared `PokerPass123`) | **ROTATE ALL, REMOVE FROM FILE** |

**Procedure:**
1. The 935 accounts with shared password need individual password changes on pokerbet.co.za
2. The ~140 accounts with unique passwords also need rotation
3. After rotation, replace the hardcoded array with a runtime loader:
```javascript
// Instead of:
const BOTS = [{username: "...", password: "...", platform: "PokerBet"}, ...];

// Use:
async function loadBots() {
    const resp = await fetch('/api/bot-credentials', {
        headers: {'X-API-Key': API_KEY}
    });
    return resp.json();
}
```
4. Move credentials to an encrypted file or environment variable:
```bash
# Store as JSON in a .gitignored file
echo '[{"username":"...","password":"...","platform":"PokerBet"},...]' > /home/wa/projects/poker/ENGINEENGINE/bot-credentials.json
echo "bot-credentials.json" >> /home/wa/projects/poker/ENGINEENGINE/.gitignore
```

**Impact:** All 1075 bots will fail to auto-login until credentials are updated. This is the largest coordination effort.

---

## Phase 3: Git Sanitization

### 3.1 Files to Untrack Immediately

```bash
cd /home/wa/projects/poker/E&R

# Remove from git tracking (files stay on disk)
git rm --cached LINUXSSHKEY.pem
git rm --cached backend/.env
git rm --cached backend/data/secret_key
git rm --cached data/secret_key
git rm --cached state/state_snapshot.json

git commit -m "security: untrack sensitive files"
```

### 3.2 Update .gitignore (E&R repo)

Add to `/home/wa/projects/poker/E&R/.gitignore`:
```
# Secrets — NEVER commit
*.pem                          # ✓ already present (line 39)
*.key                          # ✓ already present (line 40)
.env                           # ← ADD
secret_key                     # ← ADD
backend/data/secret_key        # ← ADD
data/secret_key                # ← ADD

# Backup artifacts from failed operations
*.broken.*                     # ← ADD
*.current_broken.*             # ← ADD

# Runtime data
state/state_snapshot.json      # ✓ already present (line 32)
*.db                           # ← ADD (audit.db, auth.db, players.db)
logs/                          # ✓ already present (line 29)
```

### 3.3 Create .gitignore (ENGINEENGINE repo)

ENGINEENGINE has NO .gitignore. Create one:

```
# Python
__pycache__/
*.py[cod]
*.so

# Virtual env
venv/
.venv/

# Secrets
.env
*.pem
*.key
secret_key

# Backups / broken artifacts
*.bak
*.bak.*
*.broken.*
*.current_broken.*

# Credentials
bot-credentials.json
source/bot-credentials.json

# Runtime
*.db
*.log
logs/
cache/

# IDE
.vscode/
.idea/

# OS
.DS_Store
Thumbs.db

# Build
node_modules/
dist/
build/
```

### 3.4 Untrack ENGINEENGINE Secrets

```bash
cd /home/wa/projects/poker/ENGINEENGINE

# Create .gitignore first (content above)
# Then untrack:
git rm --cached source/.env
git rm --cached source/app.py.broken.1777445519
git rm --cached source/app.py.current_broken.1777445870
git rm --cached source/app.py.current_broken.1777445955
git rm --cached source/static/remote.html

# Remove backup files from disk
rm source/app.py.broken.1777445519
rm source/app.py.current_broken.1777445870
rm source/app.py.current_broken.1777445955

git commit -m "security: untrack secrets and remove broken backup files"
```

### 3.5 Git History Rewrite (if repo is shared)

If the repository has other collaborators or is public, rewrite history to purge secrets:

```bash
# Option A: BFG Repo-Cleaner (recommended)
java -jar bfg.jar --delete-files LINUXSSHKEY.pem --delete-files secret_key .git
git reflog expire --expire=now --all
git gc --prune=now --aggressive

# Option B: git filter-branch (built-in)
git filter-branch --force --index-filter \
  "git rm --cached --ignore-unmatch LINUXSSHKEY.pem backend/.env backend/data/secret_key data/secret_key state/state_snapshot.json" \
  --prune-empty --tag-name-filter cat -- --all

# After rewrite, force push
git push origin --force --all
git push origin --force --tags
```

**WARNING:** Force push will break all other clones and forks. Coordinate with collaborators.

---

## Phase 4: Validation Checklist

### After Phase 1 (EC2 Access)

- [ ] Can SSH into EC2: `ssh ubuntu@16.28.18.179 "hostname"`
- [ ] authorized_keys contains Hermes VM's public key
- [ ] cloud-init logs reviewed — root cause identified
- [ ] sshd_config confirmed correct
- [ ] ubuntu user confirmed active
- [ ] Root cause documented

### After Phase 2 (Secret Rotation)

- [ ] New SSH keypair generated, old keys deleted
- [ ] New Flask session secret generated
- [ ] New N4P_SEAT_SECRET in .env
- [ ] New TRACKER_API_KEY in .env
- [ ] All 12+ source files no longer contain old TRACKER_API_KEY
- [ ] JS files use runtime config or placeholder (not hardcoded key)
- [ ] PostgreSQL password changed
- [ ] db_logger.py hardcoded default removed
- [ ] ENGINEENGINE SCANNER_API_KEY rotated
- [ ] ENGINEENGINE SECRET_KEY generated
- [ ] PokerBet credentials removed from remote.html (or file untracked)
- [ ] All secrets verified working (Flask starts, engine runs, commands flow)

### After Phase 3 (Git Sanitization)

- [ ] `git ls-files` shows NO secret files
- [ ] `.gitignore` covers all patterns
- [ ] ENGINEENGINE has `.gitignore`
- [ ] `git status` shows no untracked secrets
- [ ] Backups committed and pushed
- [ ] History rewritten (if repo is shared)
- [ ] Force push coordinated (if applicable)

### Integration Tests

- [ ] Flask backend starts and responds: `curl http://127.0.0.1:1080/api/health`
- [ ] Express starts and proxies: `curl http://127.0.0.1:4000/api/health`
- [ ] Engine starts: `curl http://127.0.0.1:5002/api/health`
- [ ] Extension loads in Chrome without API key errors
- [ ] Tunnel connects: `systemctl --user status er-tunnel.service`
- [ ] SSH to laptop works: `ssh -p 19999 wa@127.0.0.1 "echo OK"`

---

## Phase 5: Rollback Plan

### If Phase 1 Fails (Cannot Recover EC2)

1. Document the failure and which options were tried
2. Consider launching a new EC2 instance (Option D)
3. The Hermes VM remains functional for local development
4. Tunnel remains down — remote access blocked

### If Phase 2 Fails (Secret Rotation Breaks Services)

1. **Before starting:** Back up all current .env files and secret_key files
```bash
cp /home/wa/projects/poker/E&R/backend/.env /home/wa/projects/poker/E&R/backend/.env.pre-rotate
cp /home/wa/projects/poker/E&R/backend/data/secret_key /home/wa/projects/poker/E&R/backend/data/secret_key.pre-rotate
cp /home/wa/projects/poker/ENGINEENGINE/source/.env /home/wa/projects/poker/ENGINEENGINE/source/.env.pre-rotate
```

2. **To rollback:** Restore from backups and restart services
```bash
cp /home/wa/projects/poker/E&R/backend/.env.pre-rotate /home/wa/projects/poker/E&R/backend/.env
cp /home/wa/projects/poker/E&R/backend/data/secret_key.pre-rotate /home/wa/projects/poker/E&R/backend/data/secret_key
# Restart Flask + Express
```

### If Phase 3 Fails (Git Problems)

1. The `git rm --cached` operation is safe — files remain on disk
2. If `git filter-branch` fails, the original repo is recoverable from reflog
3. Worst case: the old secrets remain in git history (current state — no worse)

---

## Execution Order & Dependencies

```
Phase 1 (EC2 Access) ──────────────────────────────────────────────────────┐
    │                                                                       │
    ├── Success → Phase 2.1 (SSH keypair) ──→ restart tunnel               │
    │                                                                       │
    └── Failure → Options B/C/D/E → retry or skip tunnel entirely          │
                                                                           │
Phase 2.2 (session secrets) ── independent ──► can do NOW                  │
Phase 2.3 (N4P_SEAT_SECRET) ── depends on Phase 2.5 (DB)                  │
Phase 2.4 (TRACKER_API_KEY) ── independent ──► can do NOW                 │
Phase 2.5 (DB password) ── independent ──► can do NOW                      │
Phase 2.6 (engine secrets) ── independent ──► can do NOW                   │
Phase 2.7 (PokerBet creds) ── LARGEST EFFORT ──► defer if needed          │
                                                                           │
Phase 3 (git sanitization) ── depends on Phase 2 completion               │
Phase 4 (validation) ── depends on Phase 1+2+3                            │
```

**Independent actions (can start immediately, no EC2 needed):**
- Phase 2.2: Rotate Flask session secret
- Phase 2.4: Rotate TRACKER_API_KEY
- Phase 2.5: Rotate DB password
- Phase 2.6: Rotate engine secrets
- Phase 2.7: Remove PokerBet credentials from file (password rotation on sites separately)
- Phase 3: Git untrack + .gitignore updates

**Blocked actions (need EC2 access first):**
- Phase 1: EC2 recovery
- Phase 2.1: SSH keypair rotation (needs access to EC2 to add new public key)
- Tunnel restart

---

## Downtime Estimate

| Activity | Duration | Service Impact |
|----------|----------|---------------|
| EC2 recovery (Phase 1) | 15 min - 4 hours | None (already down) |
| SSH keypair rotation | 10 min | Tunnel down during rotation |
| Flask session secret rotation | 2 min | Sessions invalidated (re-login needed) |
| N4P_SEAT_SECRET rotation | 5 min | Seat tokens invalid (browser reload) |
| TRACKER_API_KEY rotation | 20 min | API calls fail until JS updated |
| DB password rotation | 5 min | PostgreSQL connection drop (~2s) |
| Engine secret rotation | 10 min | Engine restart needed |
| PokerBet credential removal | 1 hour | Bots can't auto-login until re-deployed |
| Git sanitization | 30 min | None (git operations are offline) |
| Validation | 30 min | Read-only checks |
| **Total (best case)** | **~2 hours** | Intermittent service interruptions |
| **Total (worst case)** | **~6 hours** | Extended downtime if EC2 recovery is difficult |

---

## Files Created/Modified by This Plan

| File | Action |
|------|--------|
| `~/.ssh/er_ec2_ed25519` | CREATE (new SSH keypair) |
| `~/.ssh/er_ec2_ed25519.pub` | CREATE (new SSH public key) |
| `E&R/LINUXSSHKEY.pem` | DELETE |
| `~/.ssh/ploxyz.pem` | DELETE |
| `E&R/backend/.env` | MODIFY (new secrets) |
| `E&R/backend/data/secret_key` | REPLACE (new session secret) |
| `E&R/data/secret_key` | DELETE (duplicate) |
| `E&R/backend/db_logger.py:24` | MODIFY (remove default) |
| `E&R/backend/app.py:171-172` | MODIFY (remove defaults) |
| `E&R/.gitignore` | MODIFY (add patterns) |
| `E&R/backend/static/ext/background.js:16` | MODIFY (remove hardcoded key) |
| `E&R/backend/static/ext/w4p.js` | MODIFY (remove hardcoded key) |
| `E&R/backend/static/w4p.js` | MODIFY (remove hardcoded key) |
| `E&R/source/w4p.js` | MODIFY (remove hardcoded key) |
| `E&R/source/w4p-lite.js` | MODIFY (remove hardcoded key) |
| `E&R/scripts/start-local.sh` | MODIFY (remove hardcoded key) |
| `E&R/scripts/tracer.py` | MODIFY (remove hardcoded key) |
| `E&R/tests/tracer_bullet_e2e.py` | MODIFY (remove hardcoded key) |
| `ENGINEENGINE/.gitignore` | CREATE |
| `ENGINEENGINE/source/.env` | MODIFY (new secrets) |
| `ENGINEENGINE/source/app.py:55` | MODIFY (remove default) |
| `ENGINEENGINE/source/app.py:1044` | MODIFY (remove default) |
| `ENGINEENGINE/source/app.py.broken.*` | DELETE |
| `ENGINEENGINE/source/app.py.current_broken.*` | DELETE |
| `ENGINEENGINE/source/static/remote.html` | MODIFY or UNTRACK |
| `ENGINEENGINE/source/static/w4p.js:19` | MODIFY (remove hardcoded key) |
| `ENGINEENGINE/source/static/w4p-full.js:16` | MODIFY (remove hardcoded key) |
| `ENGINEENGINE/source/static/n4p-full.js:16` | MODIFY (remove hardcoded key) |
| `ENGINEENGINE/bot-credentials.json` | CREATE (migrated creds, .gitignored) |
| `~/.config/systemd/user/er-tunnel.service` | MODIFY (add -i flag) |
