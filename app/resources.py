"""Read Linux container limits and counters; never substitute host memory for container usage."""

import os
import time
from pathlib import Path


def _read(root: Path, *names: str) -> str:
    for name in names:
        try:
            return (root / name).read_text().strip()
        except OSError:
            continue
    raise OSError("Container counter unavailable")


def _cpu_seconds(root: Path) -> float:
    try:
        return int(_read(root, "cpuacct/cpuacct.usage", "cpuacct.usage")) / 1e9
    except OSError:
        values = dict(line.split() for line in _read(root, "cpu.stat").splitlines())
        return int(values["usage_usec"]) / 1e6


def container_resources(root: Path = Path("/sys/fs/cgroup")) -> dict[str, object]:
    memory: dict[str, object] = {"used_bytes": None, "total_bytes": None, "free_bytes": None}
    cpu: dict[str, object] = {"usage_percentage": None, "cores": None, "sample_seconds": 0.25}
    try:
        used = int(_read(root, "memory.current", "memory/memory.usage_in_bytes"))
        limit = int(_read(root, "memory.max", "memory/memory.limit_in_bytes"))
        # Unlimited cgroup v1 limits use a sentinel near 2**63.
        if 0 < limit < 2**60:
            memory = {"used_bytes": used, "total_bytes": limit, "free_bytes": max(0, limit - used)}
    except (OSError, ValueError):
        pass
    try:
        cores = (
            float(len(os.sched_getaffinity(0)))
            if hasattr(os, "sched_getaffinity")
            else float(os.cpu_count() or 1)
        )
        try:
            quota, period = _read(root, "cpu.max").split()
            if quota != "max":
                cores = min(cores, int(quota) / int(period))
        except OSError:
            try:
                quota_value = int(_read(root, "cpu/cpu.cfs_quota_us"))
                period_value = int(_read(root, "cpu/cpu.cfs_period_us"))
                if quota_value > 0:
                    cores = min(cores, quota_value / period_value)
            except OSError:
                # Older kernels without CFS bandwidth control have no hard CPU quota.
                pass
        start = time.monotonic()
        before = _cpu_seconds(root)
        time.sleep(0.25)
        after = _cpu_seconds(root)
        elapsed = time.monotonic() - start
        cpu.update(
            usage_percentage=max(0, min(100, (after - before) / elapsed / cores * 100)), cores=cores
        )
    except (OSError, ValueError, KeyError, ZeroDivisionError):
        pass
    return {"memory": memory, "cpu": cpu, "scope": "Iris container"}
