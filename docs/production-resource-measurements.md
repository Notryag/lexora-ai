# Production Resource Measurements

Measured on 2026-08-16 before adding limits to services outside Lexora. No stress workload,
container restart, image build, or volume operation was performed.

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

## Capacity Decision

The nine currently unlimited containers used about 786 MiB at the sampled maxima. The reviewed
Lexora application defaults total 704 MiB, reduced from 1,536 MiB; its database moves into the shared
PostgreSQL budget. About 1,863 MiB of the 3.26 GiB host remains
for the other containers after reserving the plan's minimum 768 MiB for the operating system, SSH,
Docker, Nginx, and file cache.

That leaves about 693 MiB above the nine services' short passive sample. This is materially better,
but the sample does not establish normal request peaks for two independent agent runtimes, the
Dayboard worker, PostgreSQL cache growth, or Sub2API traffic. Final limits for those services still
need a representative passive measurement window.

Phase 2 applies only the reviewed Lexora defaults and stops before changing another project or
recreating any container. Repeat passive sampling over a representative traffic window, then set
limits one Compose project at a time. Upgrade to at least 8 GiB if those measured limits cannot fit
while preserving the required host reserve. Until then:

- keep the reviewed Lexora application defaults at API 512 MiB and Web 192 MiB;
- do not run builds or stress tests on the production host;
- do not add Swap as a substitute for isolation;
- preserve the current PostgreSQL/Redis volumes and Sub2API bind-mounted data;
- defer `systemd-oomd`, because Phase 2 has not passed and host-wide kill policy is not a capacity
  substitute.

Dayboard and Debug Relay also had unrelated, uncommitted health-check interval changes during this
audit. Their Compose files were intentionally left untouched rather than mixing ownership or
restarting services from a dirty production checkout.
