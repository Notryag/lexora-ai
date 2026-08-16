# Production Resource Measurements

Measured on 2026-08-16 before and after applying production limits. No stress workload, local
image build, destructive database operation, or volume deletion was performed.

## Host Baseline

| Metric | Result |
|---|---:|
| CPU | 2 vCPU |
| Physical memory | 3,497,992,192 bytes (3.26 GiB) |
| `MemAvailable` | 1,704,693,760 bytes (1.59 GiB) |
| Swap | 2.00 GiB, about 1.5 MiB used |
| `vm.swappiness` | 10 |
| Root filesystem available | 7,776,845,824 bytes (7.24 GiB) |
| Root filesystem use | 88% |
| Docker cgroup mode | cgroup v2, systemd driver |

The kernel does not expose `memory.peak` in the container cgroups on this host. The values below
are the maximum `memory.current` and `pids.current` observed during a 30-second passive sample.
They are a short idle/normal-traffic sample, not a proven request peak.

## Container Sample

| Container | Role | Sampled memory max | PID max | Existing memory limit |
|---|---|---:|---:|---:|
| `lexora-ai-api-1` | API/agent runtime | 142 MiB | 1 | 512 MiB proposed |
| `lexora-ai-postgres-1` | PostgreSQL (pre-migration) | 38 MiB | 6 | removed after cutover |
| `lexora-ai-web-1` | Next.js | 36 MiB | 11 | 192 MiB proposed |
| `debug-relay-api-1` | API | 93 MiB | 5 | none |
| `dayboard-api-1` | API/agent runtime | 147 MiB | 6 | none |
| `dayboard-worker-1` | background worker | 141 MiB | 4 | none |
| `dayboard-web-1` | Next.js | 74 MiB | 11 | none |
| `platform-postgres` | shared PostgreSQL | 46 MiB | 12 | none |
| `platform-redis` | shared Redis | 11 MiB | 6 | none |
| `sub2api` | API | 162 MiB | 9 | none |
| `sub2api-postgres` | PostgreSQL | 97 MiB | 12 | none |
| `sub2api-redis` | Redis | 15 MiB | 7 | none |

All containers reported `OOMKilled=false`, zero restarts, and healthy application endpoints during
the sample. Debug Relay, Dayboard, Sub2API, both PostgreSQL instances, and both Redis instances
responded to their normal health commands. The Sub2API Redis check also emitted an authentication
warning before `PONG`; its container health status remained healthy and no configuration was changed.

## Applied Limits

Limits were applied one project at a time, with health verification between projects. The totals
reserve about 743 MiB of physical memory outside container hard limits.

| Container | Memory | Memory + Swap | PIDs | Post-change working set |
|---|---:|---:|---:|---:|
| `lexora-ai-api-1` | 512 MiB | 512 MiB | 256 | 183 MiB |
| `lexora-ai-web-1` | 192 MiB | 192 MiB | 128 | 37 MiB |
| `debug-relay-api-1` | 192 MiB | 192 MiB | 64 | 85 MiB |
| `dayboard-api-1` | 256 MiB | 256 MiB | 128 | 122 MiB |
| `dayboard-worker-1` | 256 MiB | 256 MiB | 128 | 109 MiB |
| `dayboard-web-1` | 128 MiB | 128 MiB | 128 | 32 MiB |
| `platform-postgres` | 384 MiB | 384 MiB | 128 | 163 MiB |
| `platform-redis` | 64 MiB | 64 MiB | 64 | 7 MiB |
| `sub2api` | 320 MiB | 320 MiB | 256 | 98 MiB |
| `sub2api-postgres` | 224 MiB | 224 MiB | 128 | 91 MiB |
| `sub2api-redis` | 64 MiB | 64 MiB | 128 | 12 MiB |

The final inspection found no running container with `memory=0`, `swap=0`, or an empty PID limit.
All containers with configured health checks were healthy; Dayboard Web has no container health
check and responded through its normal HTTP route. Host `MemAvailable` was about 1.5 GiB and Swap
use was about 2 MiB after the changes.

## Capacity Decision

The running-container hard limits total 2,592 MiB on a 3.26 GiB host. Current working sets are well
below their limits and preserve the required host reserve under the observed workload. This is a
short production sample, so memory usage and OOM counters still need routine observation during
real traffic peaks. Upgrade to at least 8 GiB if representative peaks cannot remain within these
limits while retaining roughly 700-800 MiB for the host.

Lexora PostgreSQL now runs in `platform-postgres`; the stopped former Lexora PostgreSQL container
and its volume remain available for rollback. Docker build cache was reduced from about 2.58 GiB to
zero without pruning images, containers, or volumes. The platform cleanup timer now removes build
cache daily and only prunes unused images older than seven days.

Continue to avoid production-host builds and stress tests. Do not increase Swap as a substitute for
resource isolation. The separate systemd-oomd assessment records the conservative Swap-only policy
installed after the user requested protection against accidental local builds.
