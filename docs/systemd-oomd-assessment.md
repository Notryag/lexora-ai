# systemd-oomd Assessment

## Decision

Install `systemd-oomd` with a conservative Swap-only policy. It was enabled on 2026-08-16 after
the user explicitly requested protection against an accidental production-host Docker build.

Phase 1 moved Lexora builds off the host, and Phase 2 now gives every running container explicit
memory, Memory + Swap, and PID limits. After the changes, the host retained about 1.5 GiB
`MemAvailable`, used about 2 MiB of its 2 GiB Swap, and all application and database checks passed.
Docker build cache was also removed and the recurring cleanup policy prevents it from accumulating.

The root slice uses `ManagedOOMSwap=kill` with `SwapUsedLimit=80%`. Normal memory-pressure killing
remains disabled. An action therefore requires both memory and Swap use above 80%, and only
descendant cgroups using more than 5% of total Swap are candidates. Production containers have
equal memory and Memory + Swap limits, so they cannot consume host Swap. An accidental unlimited
BuildKit workload remains eligible because its temporary Docker scope is not covered by those
container limits.

SSH, Docker, containerd, and Nginx use `ManagedOOMPreference=avoid`. The two running PostgreSQL
scopes received the same runtime preference; their persistent protection is the no-Swap container
limit because transient scope preferences do not survive container recreation. No production
memory exhaustion test was performed.

Immediately after installation, `systemd-oomd` used about 6 MiB RSS (about 1.2 MiB of private
cgroup-accounted memory) and negligible CPU. All application and container health checks remained
healthy with no restart or OOM event.

## Monitoring And Rollback

Review `oomctl` and `journalctl -u systemd-oomd` after any unexpected process or container exit.
The tracked configuration and installation instructions are in `/home/zx/platform-infra`.

To stop intervention immediately, run `systemctl disable --now systemd-oomd.service`. To remove the
policy, also remove the local oomd and unit drop-ins documented by `platform-infra`, then run
`systemctl daemon-reload`. Do not validate the policy with a production memory exhaustion test.
