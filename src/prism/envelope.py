"""The measured resource envelope — what this box can actually do, read from the box.

Every layer calls this an envelope: associative reach is bounded by the measured envelope (cgroup
plus time) rather than by a constant, and the `PROVISIONED_*` numbers in
`agience-cloud/peers/*/node.env` are a different quantity. One name for one concept is what keeps a
config constant from being read as the envelope.

It lives in prism so every layer reaches the same reader. `shard/content_tier.py`, `mesh/daemon.py`,
`mesh/demand.py` and `mesh/sync.py` reach it from mantle, where `mantle -> prism` is a legal edge and
`mantle -> ember` is not. `chorus -> prism` is legal too, which matters because a persona sizing its
working set needs this reading as well.

═══════════════════════════════════════════════════════════════════════════════════════════════════
The one envelope — every "how much can I hold / how far can I reach" question reads this
═══════════════════════════════════════════════════════════════════════════════════════════════════
The aperture has a single resource envelope, and that envelope is what limits the aperture flow. The
corpus is infinite; the aperture is finite.

One reading of this machine, in one module, read by everything — one for the system rather than one
per repo or one per question. A screen's working memory, a reach's depth, a resampling draw count and
a row requirement are the same question asked four times, and four answers is how a launcher sized
from one reader and a worker pool sized from another disagree until the cgroup OOM-kills something
while `free` still looks fine. prism sits below mantle, ember and chorus alike, so every layer can
reach here.

    mem_available_bytes()   what can be taken right now    cgroup headroom / MemAvailable / Win32
    mem_limit_bytes()       the ceiling this box has       cgroup / job object / installed RAM
    time_budget_seconds()   the CPU-time slice granted     RLIMIT_CPU / job object (None where none is declared)
    cpus()                  effective cores                cgroup quota / cpuset / os.cpu_count
    disk_free_bytes(path)   free bytes on a volume

"""

from __future__ import annotations

import os

_GB = 1 << 30


# ── Measured ceilings (cgroup first, host as fallback) ──────────────────────────────────────────
def _read_int(path: str):
    try:
        v = open(path).read().strip()
        return int(v) if v.isdigit() else None
    except Exception:
        return None


def _own_cgroup_paths():
    """Candidate cgroup files for this process, own-slice first and then the mount root.

    The slice this process is in is the ceiling that binds it, so its path is resolved from
    `/proc/self/cgroup` before the mount root is consulted."""
    out = []
    try:
        with open("/proc/self/cgroup", "r") as fh:
            for line in fh:
                parts = line.strip().split(":")
                rel = parts[-1] if parts else ""
                if rel and rel != "/":
                    out.append("/sys/fs/cgroup" + rel)
    except Exception:
        pass
    out.append("/sys/fs/cgroup")
    return out


def _cgroup_mem_bytes():
    # cgroup v2 (memory.max) then v1 (memory.limit_in_bytes). "max" / absurd sentinel = unlimited.
    cands = []
    for base in _own_cgroup_paths():
        cands += [base + "/memory.max", base + "/memory/memory.limit_in_bytes"]
    for p in cands:
        n = _read_int(p)
        if n and 0 < n < (1 << 62):
            return n
    return None


# ── Windows reads the same facts through a different door ───────────────────────────────────────
#
# The platform analogues are exact rather than approximate:
#   cgroup memory.max  <->  the job object's ProcessMemoryLimit / JobMemoryLimit (a real, enforced
#                           per-process-group ceiling — the same kind of fact, same enforcement)
#   SC_PHYS_PAGES      <->  MEMORYSTATUSEX.ullTotalPhys      (installed physical memory)
#   MemAvailable       <->  MEMORYSTATUSEX.ullAvailPhys      (what can be taken without paging)
#
# A job object can be present with LimitFlags clear of JOB_OBJECT_LIMIT_PROCESS_MEMORY and
# _JOB_MEMORY, in which case ProcessMemoryLimit and JobMemoryLimit both read 0 and no memory ceiling
# is declared. Zero reads as "no limit declared" rather than as a limit of zero.
_JOB_EXTENDED_LIMIT_INFORMATION = 9


def _win_memory_status():
    """`(total_phys, avail_phys)` from `GlobalMemoryStatusEx`, or `None` where that call is not
    available (i.e. not Windows). ctypes only: this module has no dependencies, and `psutil` would
    be a dependency edge bought to read a number the OS hands out for free."""
    import ctypes
    try:
        class _MEMORYSTATUSEX(ctypes.Structure):
            _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                        ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                        ("ullTotalPageFile", ctypes.c_ulonglong),
                        ("ullAvailPageFile", ctypes.c_ulonglong),
                        ("ullTotalVirtual", ctypes.c_ulonglong),
                        ("ullAvailVirtual", ctypes.c_ulonglong),
                        ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]

        m = _MEMORYSTATUSEX()
        m.dwLength = ctypes.sizeof(m)
        if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m)):
            return None
        return int(m.ullTotalPhys), int(m.ullAvailPhys)
    except Exception:
        return None


def _query_job_limits():
    """`JOBOBJECT_EXTENDED_LIMIT_INFORMATION` for this process's job, or `None` off Windows / when
    the query fails. One query, read by both the memory and the time axis, so both describe the same
    job; two ctypes copies of the structure would be free to drift apart."""
    import ctypes
    try:
        class _IO_COUNTERS(ctypes.Structure):
            _fields_ = [(n, ctypes.c_ulonglong) for n in
                        ("ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
                         "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]

        class _BASIC(ctypes.Structure):
            _fields_ = [("PerProcessUserTimeLimit", ctypes.c_longlong),
                        ("PerJobUserTimeLimit", ctypes.c_longlong),
                        ("LimitFlags", ctypes.c_ulong),
                        ("MinimumWorkingSetSize", ctypes.c_size_t),
                        ("MaximumWorkingSetSize", ctypes.c_size_t),
                        ("ActiveProcessLimit", ctypes.c_ulong),
                        ("Affinity", ctypes.POINTER(ctypes.c_ulong)),
                        ("PriorityClass", ctypes.c_ulong), ("SchedulingClass", ctypes.c_ulong)]

        class _EXTENDED(ctypes.Structure):
            _fields_ = [("BasicLimitInformation", _BASIC), ("IoInfo", _IO_COUNTERS),
                        ("ProcessMemoryLimit", ctypes.c_size_t),
                        ("JobMemoryLimit", ctypes.c_size_t),
                        ("PeakProcessMemoryUsed", ctypes.c_size_t),
                        ("PeakJobMemoryUsed", ctypes.c_size_t)]

        info, ret = _EXTENDED(), ctypes.c_ulong(0)
        if not ctypes.windll.kernel32.QueryInformationJobObject(
                None, _JOB_EXTENDED_LIMIT_INFORMATION,
                ctypes.byref(info), ctypes.sizeof(info), ctypes.byref(ret)):
            return None
        return info
    except Exception:
        return None


def _job_object_mem_bytes():
    """The Windows job object memory ceiling for this process — the platform's cgroup analogue.

    `ProcessMemoryLimit` bounds one process and `JobMemoryLimit` the whole job; the tighter of the
    two that is set is the ceiling. Both read 0 when the corresponding LimitFlag is clear, and 0
    means no limit declared, so it is reported as `None` rather than as a ceiling of zero."""
    info = _query_job_limits()
    if info is None:
        return None
    declared = [v for v in (int(info.ProcessMemoryLimit), int(info.JobMemoryLimit)) if v > 0]
    return min(declared) if declared else None


def _host_mem_bytes():
    try:
        return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")
    except Exception:
        pass
    st = _win_memory_status()
    return st[0] if st else None


def mem_limit_bytes():
    """The memory ceiling for this box: `min(cgroup cap, job-object cap, host RAM)`, or `None` when
    none of them answered.

    This is the number to size against. The host figure alone reports the machine rather than the
    container, so it is taken only as one candidate among the three. `None` means not measured, and
    the caller decides what to do about it."""
    vals = [v for v in (_cgroup_mem_bytes(), _job_object_mem_bytes(), _host_mem_bytes()) if v]
    return min(vals) if vals else None


def _cgroup_mem_available():
    """`memory.max - memory.current` on cgroup v2 (v1: `limit_in_bytes - usage_in_bytes`) — the
    headroom left inside this process's own slice. `None` when either half is unreadable."""
    for base in _own_cgroup_paths():
        for cap, used in ((base + "/memory.max", base + "/memory.current"),
                          (base + "/memory/memory.limit_in_bytes",
                           base + "/memory/memory.usage_in_bytes")):
            c, u = _read_int(cap), _read_int(used)
            if c and 0 < c < (1 << 62) and u is not None:
                return max(0, c - u)
    return None


def _meminfo_available():
    """`MemAvailable` from `/proc/meminfo` (kB) — the kernel's own estimate of what a new
    allocation can take without swapping. `MemFree` excludes reclaimable page cache and so
    understates the envelope by whatever the box has cached, which is why this reader takes
    `MemAvailable`."""
    try:
        with open("/proc/meminfo") as fh:
            for line in fh:
                if line.startswith("MemAvailable:"):
                    return int(line.split()[1]) * 1024
    except Exception:
        pass
    return None


def mem_available_bytes():
    """What this box can give a caller right now, or `None` when nothing reports it.

    Sources, in the order a reading is trusted — own slice before the host, since
    [[containers-read-the-cgroup]]: `free`, `top` and `ps` all report the host from inside a
    container:
      1. the cgroup's own headroom (`memory.max - memory.current`);
      2. `/proc/meminfo` `MemAvailable`;
      3. Windows `MEMORYSTATUSEX.ullAvailPhys`.
    `None` when none of them answer. A caller holding `None` has an unmeasured envelope rather than a
    small one, so it sizes nothing against it."""
    v = _cgroup_mem_available()
    if v is not None:
        return v
    v = _meminfo_available()
    if v is not None:
        return v
    st = _win_memory_status()
    return st[1] if st else None


def mem_available_source() -> str:
    """Which reader answered `mem_available_bytes` — `"cgroup"` / `"meminfo"` / `"win32"` /
    `"unmeasured"`. Carried so a caller records what it measured against as well as the number: a
    bound that states its provenance is distinguishable from one that was typed in."""
    if _cgroup_mem_available() is not None:
        return "cgroup"
    if _meminfo_available() is not None:
        return "meminfo"
    return "win32" if _win_memory_status() else "unmeasured"


def time_budget_seconds():
    """The CPU-time budget this environment grants the process, or `None` when it grants none.

    The second axis of the one envelope — [[associative-reach-bounded-by-envelope]] names it in the
    same breath as memory: the memory a box truly has, and its time slice. It is what a walk, a reach
    or a resampling draw spends against; `time.process_time()` measures what has been spent, and the
    difference is what remains.

    Read per platform, from the enforced limit rather than a wall clock:
      · POSIX `RLIMIT_CPU` (soft limit; `RLIM_INFINITY` declares no budget);
      · Windows job object `PerProcessUserTimeLimit` / `PerJobUserTimeLimit`, in 100 ns ticks, and
        only when the corresponding LimitFlag is set.

    A caller that needs a budget where the platform declares none states one itself, as an envelope
    rather than as a timeout."""
    try:
        import resource
        soft, _hard = resource.getrlimit(resource.RLIMIT_CPU)
        if soft is not None and soft >= 0 and soft != resource.RLIM_INFINITY:
            return float(soft)
    except Exception:
        pass
    lim = _job_object_time_ticks()
    return None if lim is None else lim / 1e7          # Win32 FILETIME ticks are 100 ns


def _job_object_time_ticks():
    """The Windows job object's user-time limit in 100 ns ticks, or `None` when none is set.

    The LimitFlag is checked alongside the number, because the field carries a value the OS enforces
    only when its flag is set."""
    info = _query_job_limits()
    if info is None:
        return None
    try:
        basic = info.BasicLimitInformation
        flags = int(basic.LimitFlags)
        cands = []
        if flags & 0x00000002:                          # JOB_OBJECT_LIMIT_PROCESS_TIME
            cands.append(int(basic.PerProcessUserTimeLimit))
        if flags & 0x00000004:                          # JOB_OBJECT_LIMIT_JOB_TIME
            cands.append(int(basic.PerJobUserTimeLimit))
        cands = [c for c in cands if c > 0]
        return min(cands) if cands else None
    except Exception:
        return None


def cpus():
    """Effective CPU count as measured, or `None` when nothing reports one.

    cgroup quota or cpuset first — [[containers-read-the-cgroup]]: `nproc` and `os.cpu_count()` both
    report the host from inside a container."""
    n = cpu_quota()
    if _cgroup_cpu_measured():
        return n
    return float(os.cpu_count()) if os.cpu_count() else None


def _cgroup_cpu_measured() -> bool:
    """True when `cpu_quota` answered from the cgroup (a quota or a cpuset) rather than the host."""
    try:
        d = open("/sys/fs/cgroup/cpu.max").read().split()
        if d and d[0] != "max":
            return True
    except Exception:
        pass
    q = _read_int("/sys/fs/cgroup/cpu/cpu.cfs_quota_us")
    if q and q > 0:
        return True
    for cs_path in ("/sys/fs/cgroup/cpuset.cpus.effective", "/sys/fs/cgroup/cpuset/cpuset.cpus"):
        try:
            if open(cs_path).read().strip():
                return True
        except Exception:
            pass
    return False


def holds(cost_bytes):
    """How many items of a measured per-item cost the currently-available envelope holds.

    `None` when either side is unmeasured. A cost of zero or a non-numeric cost yields `None` too:
    dividing by it would publish an unbounded capacity as though it had been measured."""
    # The cost is checked first because it is free and the envelope read is a syscall, so a caller
    # that could not measure its per-item cost is not charged for a reading it cannot use.
    try:
        c = float(cost_bytes)
    except (TypeError, ValueError):
        return None
    if not (c > 0.0):
        return None
    env = mem_available_bytes()
    return None if env is None else int(env // c)


def cpu_quota() -> float:
    """Effective CPU count: cgroup quota if set, else host cpu_count."""
    try:
        d = open("/sys/fs/cgroup/cpu.max").read().split()          # v2: "<quota> <period>" or "max ..."
        if d and d[0] != "max":
            return max(1.0, int(d[0]) / int(d[1]))
    except Exception:
        pass
    q, p = _read_int("/sys/fs/cgroup/cpu/cpu.cfs_quota_us"), _read_int("/sys/fs/cgroup/cpu/cpu.cfs_period_us")
    if q and p and q > 0:
        return max(1.0, q / p)
    # With no CFS quota, RunPod and many hosts cap cores via cpuset instead — count those, since
    # os.cpu_count() sees the whole host (192 cores) and would oversubscribe a 3-core pod.
    for cs_path in ("/sys/fs/cgroup/cpuset.cpus.effective", "/sys/fs/cgroup/cpuset/cpuset.cpus"):
        try:
            cs = open(cs_path).read().strip()
            if cs:
                n = 0
                for part in cs.split(","):
                    if "-" in part:
                        a, b = part.split("-")
                        n += int(b) - int(a) + 1
                    else:
                        n += 1
                if n > 0:
                    return float(n)
        except Exception:
            pass
    return float(os.cpu_count() or 4)


def disk_total_bytes(data_path: str):
    """Total bytes on the data volume, or `None` if it could not be measured.

    The same-units denominator for `disk_free_bytes`. A headroom ratio takes both numbers from this
    volume; dividing free disk by the memory ceiling gives a ratio above 1 on any box whose data
    volume exceeds its RAM, which is every real node, and a clamped 1.0 reads as perfect headroom
    everywhere."""
    import shutil
    try:
        return shutil.disk_usage(data_path or ".").total
    except Exception:
        return None


def disk_free_bytes(data_path: str):
    """Free bytes on the data volume, or `None` if it could not be measured.

    `None` means not measured, and the caller decides what to do about it."""
    import shutil
    try:
        return shutil.disk_usage(data_path or ".").free
    except Exception:
        return None


# ══════════════════════════════════════════════════════════════════════════════════════════════════
#
# The measurements above return `None` wherever the platform did not answer. The sizing helpers
# below hold typed-in numbers, listed here with the constant each one carries:
#
#   cpu_quota()            `float(os.cpu_count() or 4)`        a 4 for a box that could not count
#                                                              its own cores. `cpus()` above is the
#                                                              measuring reader; this one stays
#                                                              because live callers take a float
#                                                              from it.
#   pool_workers()         `max(2, …)`                         a floor
#   promote_workers()      `return 8` when mem is None         a fixed answer for an unmeasured box
#   promote_workers()      `min(512, max(8, GB * 16))`         three typed numbers
#   s3_pool()              `max(10, … + 8)`                    two typed numbers
#   content_cache_cap_gb() `max(2, free_GB * 0.30)`            a chosen fraction and a floor
#   batch_docs()           `return 500` / `min(20000, max(500, GB * 500))`   a fallback and three
#

def pool_workers() -> int:
    """Ingest and describe pool size: the CPU quota, which leaves the box responsive while a
    supervisor adds and removes workers."""
    return max(2, int(cpu_quota()))


def promote_workers() -> int:
    """Content-promotion fan-out (local content cache -> durable OVH).

    Sized separately from `pool_workers()`, which is the CPU quota because ingest and describe are
    CPU work. Promotion is network work: every ref is an `exists`/`get`/`put` WAN round-trip, so the
    thread spends nearly all its time blocked. A round-trip of tens of milliseconds caps what one
    connection sustains well below what the CPU count would suggest, so the CPU count does not set
    the ceiling and sizing to the CPU quota would leave the link idle.

    Bounded by memory rather than CPU, since each in-flight request holds request and response
    buffers, and capped so a small device stays small: a Pi with 1 GB gets 16, a 32 GB box gets
    512."""
    env = os.getenv("EMBER_PROMOTE_WORKERS")
    if env:
        try:
            return max(1, int(env))
        except ValueError:
            pass
    mem = mem_limit_bytes()
    if mem is None:
        # An unmeasured ceiling yields the floor rather than a scaled guess. A minimum is a
        # declaration about this code; scaling a fabricated ceiling would be a claim about a box
        # nothing could measure — a 128 GB Windows dev box with no cgroup and no os.sysconf would
        # take its worker count from an unread literal.
        return 8
    return int(min(512, max(8, (mem / _GB) * 16)))


def s3_pool() -> int:
    """boto3 `max_pool_connections`, sized to cover the fan-out.

    Derived from `promote_workers()` in one place, so the pool and the fan-out it serves stay in
    agreement."""
    return max(10, promote_workers() + 8)


def content_cache_cap_gb(data_path: str):
    """Bounded local content cache: ~30% of current free disk on the data volume, so the full graph
    keeps headroom. Eviction targets this, and the promote→S3→evict loop holds the cache under it.

    `None` when free space could not be measured, and the caller keeps it as `None` rather than
    substituting the floor. On a genuinely full disk the floor is the right target; on a failed
    measurement the same floor would evict nearly the whole cache. An eviction pass that cannot size
    its target stands down."""
    free = disk_free_bytes(data_path)
    if free is None:
        return None
    return max(2, int((free / _GB) * 0.30))


def batch_docs() -> int:
    """Rows to hold in a single sync/pull/promote batch — a small fraction of RAM (each row is light),
    bounded so peak memory is independent of DB size. ~500 rows per GB of ceiling, capped."""
    mem = mem_limit_bytes()
    if mem is None:
        return 500          # an unmeasured ceiling yields the floor; see promote_workers
    return int(min(20000, max(500, (mem / _GB) * 500)))


def snapshot(data_path: str = ".") -> dict:
    """One call for a box's self-tuning — logged at startup so the measured limits are visible."""
    return {
        # None-safe for the same reason as `disk_free_gb` below: the ceiling is None when nothing
        # was readable, and the snapshot shows that rather than printing a literal.
        "mem_ceiling_gb": (None if mem_limit_bytes() is None
                           else round(mem_limit_bytes() / _GB, 1)),
        "mem_source": ("cgroup" if _cgroup_mem_bytes()
                       else ("job-object" if _job_object_mem_bytes()
                             else ("host" if _host_mem_bytes() else "unmeasured-default"))),
        # What is free, beside what the box has — see `mem_available_bytes`. A working set sized
        # against the ceiling on a shared box claims memory somebody else is already holding.
        "mem_available_gb": (None if mem_available_bytes() is None
                             else round(mem_available_bytes() / _GB, 1)),
        "mem_available_source": mem_available_source(),
        # The second axis. `None` on any box that publishes no CPU-time limit, which is every box in
        # this fleet, so time is a reading that nothing here is bounded by.
        "time_budget_s": time_budget_seconds(),
        "cpus": cpus(),
        "cpu": round(cpu_quota(), 2),
        # None-safe: `disk_free_bytes` reports None when the volume could not be read, and dividing
        # that would raise TypeError out of `snapshot()` — the one call a box makes to log its own
        # limits at startup, so an unreadable data path leaves the rest of the snapshot intact.
        "disk_free_gb": (None if disk_free_bytes(data_path) is None
                         else round(disk_free_bytes(data_path) / _GB, 1)),
        "pool_workers": pool_workers(),
        "promote_workers": promote_workers(),
        "s3_pool": s3_pool(),
        "content_cache_cap_gb": content_cache_cap_gb(data_path),
        "batch_docs": batch_docs(),
    }


if __name__ == "__main__":
    import json
    import sys
    print(json.dumps(snapshot(sys.argv[1] if len(sys.argv) > 1 else "."), indent=2))


# ── Who this box is ─────────────────────────────────────────────────────────────────────────────
def node_id() -> str:
    """Stable per-host id for the shared stats dir. `EMBER_NODE_ID` wins; failing that the shard
    range, which is unique per box in this mesh; failing that the hostname."""
    import os
    import socket
    return (os.getenv("EMBER_NODE_ID")
            or ("shards-" + os.getenv("EMBER_SHARDS", "") if os.getenv("EMBER_SHARDS") else "")
            or socket.gethostname())


MESH_STATS_PREFIX = "mesh-stats/"
