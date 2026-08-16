# systemd-oomd Assessment

## Decision

Do not install or enable `systemd-oomd` on this production host at this time.

Phase 1 moved Lexora builds off the host, and Phase 2 now gives every running container explicit
memory, Memory + Swap, and PID limits. After the changes, the host retained about 1.5 GiB
`MemAvailable`, used about 2 MiB of its 2 GiB Swap, and all application and database checks passed.
Docker build cache was also removed and the recurring cleanup policy prevents it from accumulating.

Adding a host-level early-kill policy would introduce another failure mode without addressing a
current unbounded workload. In particular, monitoring `system.slice` would include Docker,
databases, and other essential services whose cgroup hierarchy has not been validated in a safe test
environment.

## Re-evaluation Trigger

Re-evaluate only if normal traffic repeatedly drives host `MemAvailable` below about 700 MiB or
causes sustained Swap growth despite the container limits. Before any production change, validate
the exact Docker scope hierarchy and kill target on a non-production host, define protection for
SSH, Docker, and PostgreSQL, and document recovery and rollback. Do not use a production memory
exhaustion test for validation.
