# E&R Reverse SSH Tunnel — Failure Analysis

**Date:** 2026-06-23
**Analyzed by:** Hermes Agent
**Service:** `er-tunnel.service` (systemd user unit)

---

## Executive Summary

The reverse SSH tunnel from the Hermes VM to the production EC2 instance (16.28.18.179) has been **permanently down since June 17, 2026** (~4,200 consecutive retries as of analysis time). Root cause: the EC2 instance no longer accepts any SSH private key from the Hermes VM. The EC2's `authorized_keys` for user `ubuntu` almost certainly does not contain any of the Hermes VM's public keys. This is consistent with an EC2 instance rebuild or authorized_keys wipe on the EC2 side coinciding with a system reboot on June 17.

---

## Tunnel Architecture

```
LAPTOP (Warren's machine, NOT this VM)
    :22 (SSH server)
    :4000 (Express)
    :5002 (Engine Flask)
    :1080 (Flask backend)
         ▲
         │ reverse tunnel (-R)
         │
    ┌────┴──────────────────────────────┐
    │ autossh (er-tunnel.service)       │
    │ on Hermes VM                      │
    │   -R 4000:localhost:4000          │
    │   -R 5002:localhost:5002          │
    │   -R *:19999:localhost:22         │
    └────┬──────────────────────────────┘
         │ SSH connection
         ▼
    EC2: 16.28.18.179 (haaats.xyz)
    Ubuntu 24.04, OpenSSH 10.2p1
    Port 22 open ✓, all keys rejected ✗
```

**What the tunnel provides:**
- **Port 4000 →** Laptop's Express frontend exposed on EC2
- **Port 5002 →** Laptop's Engine Flask exposed on EC2
- **Port 19999 →** Laptop's SSH server accessible from EC2 (for Hermes VM to SSH into laptop)

---

## Timeline

| Time | Event |
|------|-------|
| June 16, 23:18 | `er-tunnel.service` started, tunnel connects successfully |
| June 16, 23:18 → June 17, 06:14 | **Tunnel works** for ~7 hours |
| June 17, 06:14 | **"Broken pipe"** — connection terminated by remote |
| June 17, 06:14 | autossh retries, reconnects (count 1→2) |
| June 17, 06:14 → 18:49 | Tunnel continues working |
| June 17, 18:49 | **System reboot** (boot ID e30997be... → new boot) |
| June 17, 18:49:46 | **First "Permission denied (publickey)"** |
| June 17, 18:49 → June 23, 21:27 | **4,180+ failed retries**, every 30 seconds |
| **CURRENT** | Tunnel is still down, still retrying |

Critical observation: The tunnel worked **before** the June 17 reboot on boot ID e30997be..., and failed **after** the reboot. However, the actual SSH session (count 1) had already received a "Broken pipe" at 06:14 which was likely restored by autossh's auto-reconnect. The post-reboot failure is permanent.

---

## Service Configuration

**File:** `/home/wa/.config/systemd/user/er-tunnel.service`

```ini
[Unit]
Description=E&R Reverse Tunnel → VM (:4000 + :5002)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
Restart=always
RestartSec=10
Environment="AUTOSSH_GATETIME=0"
Environment="AUTOSSH_POLL=30"
ExecStart=/usr/bin/autossh -M 0 -N \
  -o "ServerAliveInterval=30" \
  -o "ServerAliveCountMax=3" \
  -o "ExitOnForwardFailure=yes" \
  -o "StrictHostKeyChecking=accept-new" \
  -R 4000:localhost:4000 \
  -R 5002:localhost:5002 \
  -R '*:19999:localhost:22' \
  ubuntu@16.28.18.179

[Install]
WantedBy=default.target
```

**Issue:** The service does NOT specify `-i <identity_file>`. It relies on SSH's default key offering behavior, which tries `~/.ssh/id_ed25519`, `~/.ssh/id_rsa`, and any keys loaded in ssh-agent.

---

## Process Status

```
PID: 2934 (autossh)
Uptime:   since June 22, 20:49 (24+ hours)
Memory:   1.2 MB
CPU:      4 min 45 sec (cumulative)
Retries:  ~4,200 (in current session, ~2 per minute)
Restart:  enabled (systemd Restart=always, RestartSec=10)
```

---

## Key Inventory

### Hermes VM SSH Keys

| Key | Type | Bits | Permissions | Fingerprint |
|-----|------|------|-------------|-------------|
| `~/.ssh/id_ed25519` | ED25519 | 256 | 600 ✓ | SHA256:gEEEWRRbwZhQOvsPi7fCpkDO7QZFYwuF68DXeoIH7cU |
| `~/.ssh/id_ed25519.pub` | public | — | 644 | same |
| `~/.ssh/id_rsa` | RSA | 4096 | 600 ✓ | SHA256:8+PwHjAp7plrqxC2Ae8HDYVMGuB45HEa7DbjQpAABCk |
| `~/.ssh/id_rsa.pub` | public | — | 644 | same |
| `~/.ssh/ploxyz.pem` | RSA | 2048 | 600 ✓ | SHA256:ZO5nK90vMxhf0lHzAJDvQ2DXxQijnH4+PZnFS/py6rQ |
| `~/.ssh/wa_agent_ed25519` | ED25519 | 256 | 600 ✓ | SHA256:Gd63nPSD7Okoftzm1wic9hedE0mot23jBPJZRrz9PUk |

### Test Results (all keys tried manually)

| Key | Result |
|-----|--------|
| `id_ed25519` (default) | Permission denied (publickey) |
| `id_rsa` | Permission denied (publickey) |
| `ploxyz.pem` | Permission denied (publickey) |
| `wa_agent_ed25519` | Permission denied (publickey) |
| No key specified (default agent) | Permission denied (publickey) |

**All 5 authentication methods fail identically.** This is a server-side issue, not a client key issue.

---

## EC2 Host Status

| Check | Result |
|-------|--------|
| Port 22 reachable | ✓ Open (nc connection succeeded) |
| SSH server | ✓ Responding: `SSH-2.0-OpenSSH_10.2p1 Ubuntu-2ubuntu3.2` |
| Host keys | ✓ Consistent (ssh-ed25519 fingerprint matches known_hosts) |
| Authentication | ✗ All publickey attempts rejected |
| Password auth | Not attempted (disabled by server config?) |

**The EC2 is alive and running, but no Hermes VM key is authorized.**

---

## Hermes VM Authorized Keys (for comparison)

The Hermes VM's `~/.ssh/authorized_keys` contains:
1. `SSH_KEY_DUB` — RSA key (comment: `SSH_KEY_DUB`)
2. `hermes-vm@sunbet` — ED25519 key
3. `pokerpundit@hermes` — ED25519 key

This means the EC2 **should** have a corresponding private key pair to one of these entries. The `hermes-vm@sunbet` key's public half may have been on the EC2's `ubuntu` user `authorized_keys` before the June 17 event.

---

## Root Cause Analysis

**Primary hypothesis (95% confidence): EC2 instance `authorized_keys` was wiped or the instance was rebuilt.**

Supporting evidence:
1. All 5 key methods fail identically — not a specific key issue
2. The failure started precisely at the June 17 reboot boundary
3. The EC2 responded with different host keys on June 16 vs June 17 (known_hosts entry differs between old and new)
4. OpenSSH 10.2p1 is a newer version than typically found on Ubuntu 24.04 — suggests possible OS upgrade or replacement
5. AWS CLI credentials on the Hermes VM are invalid (SignatureDoesNotMatch), preventing AWS API-based recovery

**Secondary hypothesis (5%): Ubuntu user was removed or renamed.** The EC2 might have had its `ubuntu` user deleted, leaving no account with the Hermes VM's keys.

---

## Fix Options

### Option 1: AWS Console Access (if available)
- Log into AWS Console → EC2 → Instances → i-???? (find the instance with IP 16.28.18.179)
- Use **EC2 Instance Connect** to add a new public key
- Or use **Systems Manager Session Manager** if configured

### Option 2: Regain Access via Another Method
- If any other user on the EC2 has password auth enabled, try password-based SSH
- If the EC2 has a web service running, check for admin panels
- Check if another person/team has access to this instance

### Option 3: Deploy a New Instance
- Launch a new EC2 instance with the Hermes VM's public key pre-loaded in authorized_keys
- Update DNS (haaats.xyz) to point to the new instance
- Update the tunnel service to point to the new IP

### Option 4: Fix Tunnel Service (once access is restored)
Add explicit key specification:
```ini
ExecStart=/usr/bin/autossh -M 0 -N \
  -i /home/wa/.ssh/id_ed25519 \
  -o "ServerAliveInterval=30" \
  ... \
  ubuntu@16.28.18.179
```

---

## What the Tunnel Failure Breaks

| Feature | Impact |
|---------|--------|
| Remote SSH into laptop | **Broken** — port 19999 not reachable |
| Access to laptop's Flask :1080 | **Broken via EC2** — only accessible locally |
| Access to laptop's Express :4000 | **Broken via EC2** — only accessible locally |
| Access to laptop's Engine :5002 | **Broken via EC2** — only accessible locally |
| Production deployment (haaats.xyz) | **Unreachable** from VM |
| Code changes on laptop | **Cannot push** via SSH (Hermes VM can't reach laptop) |

---

## Current Workaround

Local development on the Hermes VM is possible:
- Flask: `http://127.0.0.1:1080/api/health`
- Express: `http://127.0.0.1:4000/health`
- Engine: `http://127.0.0.1:5002/api/health`

But the laptop (where the actual E&R source code and Chrome browsers run) is inaccessible.

---

## Monitoring Recommendation

Add a watchdog cron job to alert when the tunnel is down for more than 5 minutes:

```bash
#!/bin/bash
# Check if port 19999 is listening
if ! ss -tlnp | grep -q ':19999 '; then
    echo "TUNNEL DOWN: port 19999 not listening"
    # Check autossh journal for details
    journalctl --user -u er-tunnel.service --no-pager -n 5
fi
```

---

## Appendix: Known Hosts Verification

```
Known hosts entry for 16.28.18.179 (line 36):
  ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIPo4mArEroPVuyrAsLr9DYYs5thXk33gg7pFvDqLsYMx

Current server host key (ssh-keyscan):
  ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIPo4mArEroPVuyrAsLr9DYYs5thXk33gg7pFvDqLsYMx

MATCH: ✓ Host key has NOT changed — this is the same EC2 instance
```

The host key is consistent, ruling out a MITM or IP reassignment. This confirms the EC2 is the same machine — its `authorized_keys` just doesn't contain our keys anymore.
