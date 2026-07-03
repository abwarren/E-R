# PERFORMANCE BASELINE — E&R Poker Platform

**Date:** 2026-07-01 11:47 UTC

---

## API Latency (average of 3 requests)

| Endpoint | Method | Avg | Min | Max |
|----------|--------|-----|-----|-----|
| /api/health | GET | 14ms | 13ms | 15ms |
| /api/latest | GET | 13ms | 12ms | 13ms |
| /api/table/latest | GET | 13ms | 13ms | 13ms |
| /api/status | GET | 12ms | 12ms | 13ms |
| /api/version | GET | 12ms | 12ms | 12ms |
| /api/snapshot | POST | 15ms | — | — |
| /api/run (submit) | POST | 16ms | — | — |
| /api/results/<id> | GET | 13ms | — | — |

---

## Resource Usage

### Docker Containers

```
Container    CPU     Memory            Network I/O
er-remote    1.37%   73.38 MiB / 23.16 GiB  63.5 MB in / 168 MB out
er-engine    0.31%   67.88 MiB / 23.16 GiB  651 kB in / 75.6 kB out
```

### Flask Process

```
Memory:        52.4 MB
Uptime:        11.4 hours
Error count:   0
Queue depth:   0
Active tables: 0 (no extension sending)
```

---

## Snapshot Pipeline Performance

```
Pre-injection:   seq=0  tables=0
Injection #1:    seq=1  tables=1  (15ms)
Injection #2:    seq=2  tables=1  (15ms)

Snapshot age (after 3 min idle): 175.94s → cleanup evicted table
Snapshot TTL:   30s (SEAT_TTL)
Cleanup cycle:  every 10s
```

---

## Remote UI Performance

```
Page load:      ~200ms (54KB single-file HTML)
API config:     ~11ms (3KB api-config.js)
Poll interval:  Varies (300ms active / 2000ms idle per w4p.js config)
Console errors: 0
Network errors: 0
```

---

## Engine Performance

```
Equity submission: 16ms (queue)
Equity computation: 2-3s (2 hands, 3-card board, PLO4, Monte Carlo)
Result retrieval:   13ms
```

---

## Polling Frequency (from w4p.js source)

```
Active table (hero present + actions):  300ms
Idle table (no actions):                2000ms
New player debounce:                    3 polls before accepting (v24)
Seat cache TTL:                         120,000ms (2 min)
Stale seat TTL:                         5.0s (non-hero controlled seats)
```

---

## Network

```
ESTABLISHED browser connections: 0
Express :4000 listeners:         2 (IPv4 + IPv6)
Flask :1080 listeners:           internal only (not published)
Engine :5002 listeners:          2 (IPv4 + IPv6)
```

---

## No Performance Regressions Detected

- No memory leaks (stable 52-73MB across 11+ hours)
- No error accumulation (0 errors in status endpoint)
- No queue buildup (0 commands queued)
- No CPU spikes (1.37% remote, 0.31% engine)
- API latencies consistent across repeated calls (12-15ms)
