"""The MEASURED resource envelope — what this box can actually do, read from the box.

⚠ MOVED FROM `ember.runtime.resource` TO `prism.envelope` ON 2026-07-31, AND RENAMED. It sat in the
runner only because the runner was the first thing that needed it. 251 lines whose only import is
`os` — it never had a reason to be coupled to anything.

The rename is not cosmetic. Every other layer already calls this an ENVELOPE: the standing rule is
that associative reach is bounded by the MEASURED envelope (cgroup + time) and never by a constant,
and `agience-cloud/nodes/*/node.env` carries `PROVISIONED_*` numbers that are explicitly NOT this.
Two names for one concept is how a config constant eventually gets read as the envelope.

It also unblocked five files: `store/content_tier.py`, `mesh/daemon.py`, `mesh/demand.py` and
`mesh/sync.py` all reached into `ember.runtime` for it, which was the last thing keeping them from
landing in mantle. mantle -> prism is legal; mantle -> ember is not. So is chorus -> prism, which
matters: a persona sizing its working set needs this too.

═══════════════════════════════════════════════════════════════════════════════════════════════════
THE ONE ENVELOPE — every "how much can I hold / how far can I reach" question reads THIS
═══════════════════════════════════════════════════════════════════════════════════════════════════
[John, 2026-08-01: *"the aperture ONLY has a single resource envelope. NOTHING ELSE LIMITS THE
APERTURE FLOW"*; *"The corpus is infinite. The aperture is finite."*]

ONE reading of this machine, in one module, read by everything. Not one per repo, not one per
question. A screen's working memory, a reach's depth, a resampling draw count and a row requirement
are the SAME question asked four times, and four answers is how a launcher sized from one reader and
a worker pool sized from the other disagree until the cgroup OOM-kills something while `free` still
looks fine — the scar `agience-ember/node/envelope.py` was gutted down to a CLI for. Every layer can
reach here: prism sits below beam, mantle, ember and chorus alike.

    mem_available_bytes()   what can be taken RIGHT NOW    cgroup headroom / MemAvailable / Win32
    mem_limit_bytes()       the ceiling this box HAS       cgroup / job object / installed RAM
    time_budget_seconds()   the CPU-time slice granted     RLIMIT_CPU / job object   (None on 71)
    cpus()                  effective cores                cgroup quota / cpuset / os.cpu_count
    disk_free_bytes(path)   free bytes on a volume
    holds(cost_bytes)       ⭐ available / measured cost = HOW MANY OF A THING FIT
    snapshot(path)          all of the above, for a log line

⚠ EVERY ONE OF THEM RETURNS `None` WHERE THE PLATFORM DID NOT ANSWER, AND `None` IS NOT A SMALL
NUMBER. It means the caller has learned that this box publishes no limit — so the thing being sized
is UNBOUNDED and must say so. There are no fallbacks here and there must never be: this module has
already had to delete a fabricated `8 * _GB` ceiling that had a 2 GB Pi and a 512 GB node reporting
the same figure, and PUBLISHED it to peers as measured capacity.

⚠ CGROUP BEFORE HOST, ALWAYS ([[containers-read-the-cgroup]]): `free`, `top`, `ps`, `nproc` and
`os.cpu_count()` all report the HOST from inside a container, so a host reading is the answer only
once the cgroup has been asked and had nothing to say.

⚠ WINDOWS IS NOT AN ABSENCE OF A PLATFORM. This module could not measure the box it mostly runs on
until 2026-08-01 — `os.sysconf` does not exist there and there is no `/sys/fs/cgroup`, so BOTH
sources failed and node 71 reported `mem_source: unmeasured-default` while sitting on 31.7 GiB it
could have simply been asked for. The Win32 analogues are exact; see `_win_memory_status` /
`_query_job_limits`.
"""

from __future__ import annotations

import os

_GB = 1 << 30


# ── measured ceilings (cgroup first, host as fallback) ──────────────────────────────────────────
def _read_int(path: str):
    try:
        v = open(path).read().strip()
        return int(v) if v.isdigit() else None
    except Exception:
        return None


def _own_cgroup_paths():
    """Candidate cgroup files for THIS PROCESS, own-slice first then the mount root.

    ⛔ READING ONLY THE MOUNT ROOT DEFEATS THE MODULE'S PURPOSE ON BARE METAL.
    Under Docker with a private cgroup namespace the root happens to BE our cgroup, so it worked.
    Under systemd it is not: a unit with `MemoryMax=8G` has its real limit at
    `/sys/fs/cgroup/system.slice/<unit>/memory.max`, while the root reads "max". `_read_int` then
    correctly returns None, we fall through to host RAM — 755GB on the host in question — and
    the then-`arcade_heap_gb()` returned 339, so the JVM was OOM-killed by the very cgroup this
    module exists to respect. Resolve our own path from /proc/self/cgroup first."""
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


# ── WINDOWS READS THE SAME FACTS THROUGH A DIFFERENT DOOR ───────────────────────────────────────
# ⛔ THIS MODULE COULD NOT MEASURE THE BOX IT MOSTLY RUNS ON. `_host_mem_bytes` was `os.sysconf`
# only, and `os.sysconf` DOES NOT EXIST on Windows; there is no `/sys/fs/cgroup` either. So on node
# 71 — a Windows box, this repo's primary environment — BOTH sources failed, `mem_limit_bytes()`
# returned None, and `snapshot()["mem_source"]` read `"unmeasured-default"`. The module's own header
# already names the consequence ("on a 128GB Windows dev box every one of those was derived from a
# number nobody read"); what it did not say is that the box was perfectly capable of answering. It
# was never asked.
#
# The platform analogues are exact, not approximations:
#   cgroup memory.max  <->  the JOB OBJECT's ProcessMemoryLimit / JobMemoryLimit (a real, enforced
#                           per-process-group ceiling — the same kind of fact, same enforcement)
#   SC_PHYS_PAGES      <->  MEMORYSTATUSEX.ullTotalPhys      (installed physical memory)
#   MemAvailable       <->  MEMORYSTATUSEX.ullAvailPhys      (what can be taken without paging)
#
# MEASURED on 71 (2026-08-01): ullTotalPhys 34,048,368,640 (31.71 GiB), ullAvailPhys 7,704,268,800
# (7.17 GiB, load 77%), job object present with LimitFlags 0x1800 — which contains neither
# JOB_OBJECT_LIMIT_PROCESS_MEMORY nor _JOB_MEMORY, so ProcessMemoryLimit and JobMemoryLimit are both
# 0 and NO memory ceiling is declared. Zero is read as "no limit declared", never as a limit of zero.
_JOB_EXTENDED_LIMIT_INFORMATION = 9


def _win_memory_status():
    """`(total_phys, avail_phys)` from `GlobalMemoryStatusEx`, or `None` where that call is not
    available (i.e. not Windows). ctypes only — this module's whole point is that it has no
    dependencies, and adding `psutil` to read a number the OS hands out for free would be a
    dependency edge bought for nothing."""
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
    the query fails. ONE query, read by both the memory and the time axis — two ctypes copies of the
    same structure is how the two would eventually describe different jobs."""
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
    """The Windows JOB OBJECT memory ceiling for this process — the platform's cgroup analogue.

    `ProcessMemoryLimit` bounds one process, `JobMemoryLimit` the whole job; the tighter of the two
    that is actually SET is the ceiling. Both read 0 when the corresponding LimitFlag is clear, and
    0 means NO LIMIT DECLARED — reporting it as a ceiling of zero would be the absence-as-assertion
    this module has already been fixed for once."""
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
    """The TRUE memory ceiling for this box = min(cgroup cap, host RAM), or None if unmeasurable.
    This is the number to size against — NEVER the host figure alone, which lies inside a container.

    ⛔ RETURNED A FABRICATED `8 * _GB` WHEN NOTHING WAS READABLE. A 2 GB Pi and a 512 GB node then
    reported the identical ceiling, and the caller could not tell a measurement from the invention —
    which is exactly what the envelope must never be (associative-reach-bounded-by-envelope,
    containers-read-the-cgroup: the bound is MEASURED, never a constant). Worse, it was PUBLISHED:
    `mesh/sync.publish_manifest` advertised it to peers as this node's measured capacity, so peers
    sized real work against a number nobody read. Same house rule as `disk_free_bytes` directly
    below: None means NOT MEASURED, and a caller has to decide what to do about it."""
    vals = [v for v in (_cgroup_mem_bytes(), _job_object_mem_bytes(), _host_mem_bytes()) if v]
    return min(vals) if vals else None


def _cgroup_mem_available():
    """`memory.max - memory.current` on cgroup v2 (v1: `limit_in_bytes - usage_in_bytes`) — the
    headroom left INSIDE our own slice. `None` when either half is unreadable."""
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
    allocation can take without swapping. Not `MemFree`: free excludes reclaimable page cache and
    therefore understates the envelope by whatever the box happens to have cached."""
    try:
        with open("/proc/meminfo") as fh:
            for line in fh:
                if line.startswith("MemAvailable:"):
                    return int(line.split()[1]) * 1024
    except Exception:
        pass
    return None


def mem_available_bytes():
    """What this box can ACTUALLY give a caller right now, or `None` if unmeasurable.

    ⚠ THIS IS A DIFFERENT QUESTION FROM `mem_limit_bytes`, AND CONFLATING THEM IS A REAL ERROR.
    The ceiling is what the box HAS; this is what is FREE — the box is shared, and a caller sizing a
    working set against the ceiling is claiming memory that other processes are already holding.
    MEASURED on 71 (2026-08-01): ceiling 31.71 GiB, available 7.17 GiB — a factor of 4.4, i.e. the
    difference between a working set that fits and one that pages.

    Sources, in the order a reading must be trusted (own slice before the host, always —
    [[containers-read-the-cgroup]]: `free`/`top`/`ps` all report the host from inside a container):
      1. the cgroup's own headroom (`memory.max - memory.current`);
      2. `/proc/meminfo` `MemAvailable`;
      3. Windows `MEMORYSTATUSEX.ullAvailPhys`.
    `None` when none of them answer — the caller must then NOT size anything, because an unmeasured
    envelope is not a small one."""
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
    `"unmeasured"`. Carried so a caller can record WHAT it measured against, not only the number:
    a bound whose provenance is not stated is indistinguishable from one that was typed."""
    if _cgroup_mem_available() is not None:
        return "cgroup"
    if _meminfo_available() is not None:
        return "meminfo"
    return "win32" if _win_memory_status() else "unmeasured"


def time_budget_seconds():
    """The CPU-TIME budget this environment grants the process, or `None` when it grants none.

    The SECOND axis of the one envelope — [[associative-reach-bounded-by-envelope]] names it in the
    same breath as memory (*"the memory it truly has and its time slice"*). It is what a walk, a
    reach or a resampling draw must spend against; `time.process_time()` measures what has been
    spent, and the difference is what remains.

    Read per platform, limit first, and NEVER a wall clock:
      · POSIX `RLIMIT_CPU` (soft limit; `RLIM_INFINITY` is not a budget);
      · Windows job object `PerProcessUserTimeLimit` / `PerJobUserTimeLimit`, in 100 ns ticks, and
        only when the corresponding LimitFlag is actually set.

    ⚠⚠ MEASURED ON 71 (2026-08-01): **None.** There is no `resource` module on Windows, and the job
    object's LimitFlags read 0x1800 — `DIE_ON_UNHANDLED_EXCEPTION | BREAKAWAY_OK`, containing
    neither `JOB_OBJECT_LIMIT_PROCESS_TIME` (0x2) nor `_JOB_TIME` (0x4). So this box publishes NO
    time budget, and the honest consequence is that nothing in this system may be bounded in time
    here. A default would be a stopwatch nobody set ([[absence-is-not-an-affirmative-claim]]); a
    caller that needs one must say so, and it must say so as an envelope, not as a timeout."""
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
    """The Windows job object's user-time limit in 100 ns ticks, or `None` when none is SET.

    ⚠ THE FLAG DECIDES, NOT THE VALUE. `QueryInformationJobObject` fills the limit fields with
    whatever is in the structure whether or not the corresponding `LimitFlags` bit is set, so
    reading the number alone would publish a budget the OS is not enforcing."""
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
    """Effective CPU count MEASURED, or `None` when nothing reports one.

    ⚠ THE HONEST TWIN OF `cpu_quota`, WHICH CANNOT SAY "I DO NOT KNOW". `cpu_quota()` ends
    `float(os.cpu_count() or 4)` — a fabricated 4 for a box that could not count its own cores, and
    the same shape as the `8 * _GB` memory ceiling this module already had to delete. It is left in
    place because live callers (`pool_workers`, and mantle's mesh sizing) take a float from it; new
    readers of the ONE envelope should take this one and handle the `None`.

    cgroup quota / cpuset first — [[containers-read-the-cgroup]]: `nproc` and `os.cpu_count()` both
    report the HOST from inside a container."""
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
    """How many items of a MEASURED per-item cost the currently-available envelope holds.
    `None` when either side is unmeasured.

    ⭐ THE ONE PLACE THE DIVISION HAPPENS. `capacity = envelope / cost` is the same arithmetic
    wherever it is needed (a screen's working memory, a reach's frontier), and two call sites doing
    it themselves is how one box ends up with two different opinions of its own size — the exact
    defect `node/envelope.py` was gutted for.

    ⚠ `None` IS NOT ZERO AND IS NOT A DEFAULT. A caller handed `None` has learned that this platform
    did not report an envelope, which is a statement about the platform and not about the caller's
    working set. It must then leave the quantity UNBOUNDED and say so — the honest reading, and the
    behaviour that predates any bound at all. `cost_bytes <= 0` is likewise unmeasured, not
    infinite: dividing by it would publish an unbounded capacity as if it had been measured."""
    # The COST is checked first because it is free and the envelope read is a syscall — a caller
    # that could not measure its per-item cost must not be charged for a reading it cannot use.
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
    # No CFS quota? RunPod (and many hosts) cap cores via CPUSET, not a quota — count those, else
    # os.cpu_count() would see the whole HOST (192 cores) and we'd oversubscribe a 3-core pod.
    for cs_path in ("/sys/fs/cgroup/cpuset.cpus.effective", "/sys/fs/cgroup/cpuset/cpuset.cpus"):
        try:
            cs = open(cs_path).read().strip()
            if cs:
                n = 0
                for part in cs.split(","):
                    if "-" in part:
                        a, b = part.split("-"); n += int(b) - int(a) + 1
                    else:
                        n += 1
                if n > 0:
                    return float(n)
        except Exception:
            pass
    return float(os.cpu_count() or 4)


def disk_total_bytes(data_path: str):
    """Total bytes on the data volume, or None if it could not be measured.

    The SAME-UNITS denominator for `disk_free_bytes`. Added 2026-07-30 because the breeding gate
    was dividing free DISK by the MEMORY ceiling — a ratio that exceeds 1 on any box whose data
    volume is larger than its RAM (i.e. every real node) and was then pinned to exactly 1.0, so the
    headroom check read PERFECT everywhere and could never refuse."""
    import shutil
    try:
        return shutil.disk_usage(data_path or ".").total
    except Exception:
        return None


def disk_free_bytes(data_path: str):
    """Free bytes on the data volume, or None if it could not be measured.

    ⛔ RETURNED 0 ON ANY ERROR, WHICH IS ALSO A VALID MEASUREMENT. A path not yet created, an
    unmounted volume or a permissions failure produced byte-identical output to a genuinely full
    disk — and 0 flows straight into `content_cache_cap_gb`, collapsing the cache cap to its 2GB
    floor. An eviction loop targeting that would clear essentially the whole local content cache
    because a directory was missing for a moment. Same house rule as every other measurement in
    this fleet: None means NOT MEASURED, and a caller has to decide what to do about it."""
    import shutil
    try:
        return shutil.disk_usage(data_path or ".").free
    except Exception:
        return None


# ══════════════════════════════════════════════════════════════════════════════════════════════════
# ⚠⚠ EVERYTHING BELOW THIS LINE VIOLATES THE 2026-08-01 RULE AND IS FLAGGED, NOT FIXED
# ══════════════════════════════════════════════════════════════════════════════════════════════════
# [John, 2026-08-01: NO THRESHOLDS · NO TRUNCATION · NO CONSTANTS · NO LIMITS · NO FALLBACKS · NO
# PREDETERMINATION. *"a 'last resort' value that fires when a measurement is unavailable is exactly
# the defect."*]
#
# The MEASUREMENTS above are clean: every one returns `None` where the platform did not answer. The
# helpers below are not, and the section comment they carried — *"each a fraction of a measured
# limit — no bare constants"* — is false on its own terms. Named exactly, so the next lane does not
# have to rediscover them:
#
#   cpu_quota()            `float(os.cpu_count() or 4)`        a FABRICATED 4 for a box that could
#                                                              not count its own cores. `cpus()`
#                                                              above is the honest reader; this one
#                                                              stays only because live callers take
#                                                              a float from it.
#   pool_workers()         `max(2, …)`                         a floor
#   promote_workers()      `return 8` when mem is None         a FALLBACK, and the exact shape of the
#                                                              deleted `8 * _GB` ceiling: a fixed
#                                                              answer for an unmeasured box
#   promote_workers()      `min(512, max(8, GB * 16))`         three typed numbers
#   s3_pool()              `max(10, … + 8)`                    two typed numbers
#   content_cache_cap_gb() `max(2, free_GB * 0.30)`            a chosen fraction and a floor
#   batch_docs()           `return 500` / `min(20000, max(500, GB * 500))`   a fallback + three
#
# ⛔ NOT FIXED HERE BECAUSE THE BLAST RADIUS IS NOT THIS MODULE'S. Their consumers are
# `mantle/store/content_tier.py`, `mantle/mesh/{daemon,demand,sync}.py` and ember's runner pool, and
# each takes a plain `int`/`float` today — turning these into `None` is a cross-repo change with
# real eviction and fan-out behaviour behind it, not an edit. Flagged in the open rather than
# half-done ([[no-arbitrary-caps]]: a labelled seam, never a fabricated cap presented as derived).

# ── derived tunables (⚠ see the block directly above — these are the flagged violations) ─────────
# `arcade_heap_gb` (the ArcadeDB JVM -Xmx sizing) was removed 2026-07-22 with the fleet off
# ArcadeDB — there is no JVM left to size. Everything else here still derives from the ceilings.
def pool_workers() -> int:
    """Ingest/describe pool size = the CPU quota (leave the box responsive; supervise adds/removes)."""
    return max(2, int(cpu_quota()))


def promote_workers() -> int:
    """Content-promotion fan-out (local content cache -> durable OVH).

    DELIBERATELY NOT `pool_workers()`. That one is the CPU quota because ingest/describe is CPU
    work. Promotion is the opposite: every ref is an `exists`/`get`/`put` WAN round-trip at ~44ms,
    so the thread spends essentially all its time blocked on the network. Sizing this to the CPU
    quota would leave the link idle — measured on T5/TU, ~44ms per HEAD means one connection
    sustains ~23 refs/s, so the CPU count is irrelevant to the ceiling.

    Bounded by MEMORY rather than CPU (each in-flight request holds request+response buffers), and
    capped so a small device stays small: a Pi with 1 GB gets 16, a 32 GB box gets 512."""
    env = os.getenv("EMBER_PROMOTE_WORKERS")
    if env:
        try:
            return max(1, int(env))
        except ValueError:
            pass
    mem = mem_limit_bytes()
    if mem is None:
        # Unmeasured ceiling -> the FLOOR, never a scaled guess. Scaling up from a fabricated
        # number is how a 128 GB Windows dev box (no cgroup, no os.sysconf) got its worker count
        # from an 8 GB literal nobody read. A minimum is a machine declaration; a scaled fiction
        # is a claim about a box we could not measure.
        return 8
    return int(min(512, max(8, (mem / _GB) * 16)))


def s3_pool() -> int:
    """boto3 `max_pool_connections`, sized to cover the fan-out.

    ⛔ THIS IS THE ONE THAT WAS MISSING, AND IT WAS THE ACTUAL THROUGHPUT CEILING.
    boto3 defaults to 10 connections. Every promote thread shares ONE client, so with the default
    the pool — not the worker count — decided throughput, and raising workers did nothing:
    64 -> 182 refs/s, 256 -> ~210, 512 -> 225, against a predicted 10 conns / 44ms = 227/s.
    The pool must be a RESOURCE-ENVELOPE quantity for the same reason the heap is: derived from the
    measured ceiling, in one place, so it cannot silently disagree with the fan-out it serves."""
    return max(10, promote_workers() + 8)


def content_cache_cap_gb(data_path: str):
    """Bounded local content cache = ~30% of CURRENT free disk on the data volume, so the full graph
    always has headroom. Eviction targets this; the promote→S3→evict loop keeps the cache under it.

    None when free space could not be measured. The caller MUST NOT substitute the floor: on a real
    full disk the floor is the right answer, on a failed measurement it would evict nearly the whole
    cache — and those were indistinguishable while `disk_free_bytes` returned 0 for both. An
    eviction pass that cannot size its target must not run."""
    free = disk_free_bytes(data_path)
    if free is None:
        return None
    return max(2, int((free / _GB) * 0.30))


def batch_docs() -> int:
    """Rows to hold in a single sync/pull/promote batch — a small fraction of RAM (each row is light),
    bounded so peak memory is independent of DB size. ~500 rows per GB of ceiling, capped."""
    mem = mem_limit_bytes()
    if mem is None:
        return 500          # unmeasured ceiling -> the floor; see promote_workers
    return int(min(20000, max(500, (mem / _GB) * 500)))


def snapshot(data_path: str = ".") -> dict:
    """One call for a box's self-tuning — logged at startup so the true limits are visible."""
    return {
        # None-safe for the same reason as `disk_free_gb` below: the ceiling is now None when
        # nothing was readable, and the snapshot must SHOW that rather than print a literal.
        "mem_ceiling_gb": (None if mem_limit_bytes() is None
                           else round(mem_limit_bytes() / _GB, 1)),
        # ⛔ THIS ONLY DISTINGUISHED cgroup-FROM-NOT-cgroup, SO AN UNMEASURED FALLBACK READ AS "host".
        # On Windows `os.sysconf` does not exist and the cgroup paths are absent, so BOTH sources
        # fail. `mem_limit_bytes()` USED TO return an 8GB literal here — which then drove
        # promote_workers, s3_pool and batch_docs, so on a 128GB Windows dev box (this repo's
        # primary environment) every one of those was derived from a number nobody measured, while
        # the snapshot claimed the source was the host. FIXED 2026-07-30: the ceiling is None when
        # unmeasured and the consumers take their floor instead of scaling from a fiction.
        # ⚠ IT NOW NAMES THE READER THAT ANSWERED, because there are four and they are not
        # interchangeable. `"job-object"` is the Windows cgroup analogue (an enforced ceiling);
        # `"host"` is installed RAM (POSIX `sysconf`, or `MEMORYSTATUSEX.ullTotalPhys`). Reporting
        # "host" for a cgroup-capped box, or "unmeasured-default" for a box that answered, are the
        # same class of error in opposite directions.
        "mem_source": ("cgroup" if _cgroup_mem_bytes()
                       else ("job-object" if _job_object_mem_bytes()
                             else ("host" if _host_mem_bytes() else "unmeasured-default"))),
        # WHAT IS FREE, beside what the box HAS — see `mem_available_bytes`. A working set sized
        # against the ceiling on a shared box claims memory somebody else is already holding.
        "mem_available_gb": (None if mem_available_bytes() is None
                             else round(mem_available_bytes() / _GB, 1)),
        "mem_available_source": mem_available_source(),
        # THE SECOND AXIS. `None` on any box that publishes no CPU-time limit — which is every box
        # in this fleet today, and is exactly why nothing here may be bounded in time yet.
        "time_budget_s": time_budget_seconds(),
        "cpus": cpus(),
        "cpu": round(cpu_quota(), 2),
        # None-safe: `disk_free_bytes` reports None when the volume could not be read, and dividing
        # that raised TypeError out of `snapshot()` — the one call a box makes to log its own limits
        # at startup. An unreadable data path would have taken the whole snapshot down with it.
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


# ── WHO THIS BOX IS ─────────────────────────────────────────────────────────────────────────────
# ⚠ MOVED FROM `ember/surface/stats.py::_node_id` ON 2026-07-31. It sits beside the envelope for the
# same reason the envelope is here: both READ THE BOX. What a host can do and which host it is are
# the same kind of fact, and `mesh/sync.py` was reaching into ember's stats module — a serve-surface
# concern — to learn a node's identity.
def node_id() -> str:
    """Stable per-host id for the shared stats dir. EMBER_NODE_ID wins; else the shard range (unique
    per box in this mesh); else the hostname."""
    import os
    import socket
    return (os.getenv("EMBER_NODE_ID")
            or ("shards-" + os.getenv("EMBER_SHARDS", "") if os.getenv("EMBER_SHARDS") else "")
            or socket.gethostname())


MESH_STATS_PREFIX = "mesh-stats/"
