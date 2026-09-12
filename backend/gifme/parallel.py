"""Multicore helpers for the CPU-bound Pillow work (palette quantization,
thumbnailing, crossfade blending) that ffmpeg/gifsicle/ImageMagick never
touch - that work runs in plain Python otherwise, one frame at a time.

Also home to cpu_count(), used to size every external tool's own thread/job
flag too - see runner.py.
"""
from __future__ import annotations

import atexit
import os
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

# Below this many items, spinning up worker processes costs more (pickling,
# process startup) than running the loop right here saves.
MIN_PARALLEL_ITEMS = 4

_executor: ProcessPoolExecutor | None = None


def _cgroup_cpu_quota() -> int | None:
    """CPU count implied by a `--cpus` / `deploy.resources.limits.cpus`
    container quota, if one is set. `os.cpu_count()` and
    `os.sched_getaffinity()` both only ever report the host's real core
    count - neither sees a CFS quota - so a container capped to e.g. 2 cores
    on a 15-core host would otherwise spawn 15 worker processes to fight
    over 2."""
    v2 = Path("/sys/fs/cgroup/cpu.max")
    try:
        if v2.exists():
            quota, period = v2.read_text().split()
            return max(1, int(quota) // int(period)) if quota != "max" else None
    except (OSError, ValueError):
        pass
    try:
        quota = int(Path("/sys/fs/cgroup/cpu/cpu.cfs_quota_us").read_text())
        period = int(Path("/sys/fs/cgroup/cpu/cpu.cfs_period_us").read_text())
        if quota > 0:
            return max(1, quota // period)
    except (OSError, ValueError):
        pass
    return None


def cpu_count() -> int:
    """Usable CPU count for this process - cpuset-aware, and capped to a
    cgroup CPU quota when a container sets one."""
    try:
        n = len(os.sched_getaffinity(0))
    except AttributeError:  # sched_getaffinity is POSIX-only, no macOS/Windows
        n = os.cpu_count() or 1
    quota = _cgroup_cpu_quota()
    if quota:
        n = min(n, quota)
    return max(1, n)


def get_executor() -> ProcessPoolExecutor:
    """One pool, reused for the process's lifetime - creating a fresh one
    per call would spend most of its own benefit on startup cost.

    Deliberately left on each platform's own default start method rather
    than forced onto "fork": that default is already "fork" on Linux (the
    Docker target), and on macOS/Windows it's "spawn" - which costs a
    slightly slower one-time worker startup (paid once per worker process,
    not per task, since the pool is reused) in exchange for safety. Forcing
    fork here would mean calling it from a process that's likely running an
    asyncio event loop plus starlette's request threadpool, and fork()ing a
    multi-threaded process risks the child deadlocking on a lock some other
    thread held at the moment of the fork - exactly why CPython moved
    macOS's default off fork in 3.8. Every function handed to the pool below
    (to_palette, _save_thumbnail, _blend) lives at module level specifically
    so spawn can re-import and locate it in the worker with no __main__
    re-execution risk - that risk only applies to whatever script is
    actually run as __main__ (uvicorn's own entry point), which is not this
    module and already carries its own `if __name__ == "__main__"` guard.
    """
    global _executor
    if _executor is None:
        _executor = ProcessPoolExecutor(max_workers=cpu_count())
        atexit.register(_executor.shutdown, cancel_futures=True)
    return _executor


def pmap(fn, *iterables) -> list:
    """map(), parallelized across every core once there's enough work to be
    worth it - otherwise runs inline. Every iterable must be finite and the
    same length as the first (bound an itertools.repeat() yourself)."""
    items = [list(it) for it in iterables]
    n = len(items[0]) if items else 0
    workers = cpu_count()
    if n < MIN_PARALLEL_ITEMS or workers < 2:
        return list(map(fn, *items))
    chunksize = max(1, n // (workers * 4))
    return list(get_executor().map(fn, *items, chunksize=chunksize))
