#!/usr/bin/env python3
"""Machine metrics and ComfyUI progress for the review dashboard (tools/review/). Host side, standard library only.

  python tools/review/monitor.py [--interval 2] [--comfy-log PATH] [--comfy-url URL] [--url INGEST]
  python tools/review/monitor.py --once --print          # collect once, print the two events, send nothing

Every --interval seconds two events go to the review ingest port (FILM_REVIEW_URL, default http://127.0.0.1:8791):
  metrics  CPU %, RAM used/total, per GPU (nvidia-smi) utilisation %, VRAM used/total, temperature, power draw, free
           space of every fixed drive, and the running heavy jobs as allow-listed labels with a count ("blender" x2,
           "ComfyUI (python)")
  comfy    server up/down and queue running/pending (GET <FILM_COMFY_URL>/queue), the current job's step progress
           (step i/n, s/step, elapsed, ETA, %) and the last 10 jobs, parsed from the tqdm lines of the ComfyUI log

Privacy: the dashboard is public and has no login. Only allow-listed labels and counts leave this process: never a
command line, path, window title, environment variable or user name. The ComfyUI log is read for numbers only; none of
its text is sent. A python process counts as "ComfyUI (python)" when it listens on the ComfyUI port (Windows) or runs
ComfyUI's main.py (Linux, read locally, never sent).

Offline-safe: a collector that fails gives null values; when the review server does not answer the monitor backs off
(2 s -> 60 s) and keeps collecting; the loop never exits on an error. `review.py up` starts it detached
(out/_review/monitor.pid), `review.py down` or `review.py monitor --stop` stops it.
Env: FILM_REVIEW_URL, FILM_COMFY_URL (default http://127.0.0.1:8188), FILM_COMFY_LOG (default
$FILM_COMFY_WORK/server.log, else <lab>/out/_comfy/server.log: the log that `comfy.py start` writes). For the Comfy
Desktop app pass --comfy-log %LOCALAPPDATA%\\Comfy-Desktop\\ComfyUI-Installs\\ComfyUI\\logs\\comfyui.log and its URL.
"""
import argparse
import codecs
import collections
import ctypes
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
LAB = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
import client  # noqa: E402  (ingest_url: the same FILM_REVIEW_URL rules as every other publisher)

IS_WIN = os.name == "nt"
NO_WINDOW = 0x08000000                       # CREATE_NO_WINDOW: a console child of a detached process stays hidden
DEFAULT_COMFY_URL = "http://127.0.0.1:8188"
POST_TIMEOUT = 1.5
QUEUE_TIMEOUT = 1.0
MAX_BACKOFF = 60.0
GPU_RETRY = 60.0                             # nvidia-smi missing or broken: look again after a minute
LOG_BACKLOG = 256 * 1024                     # bytes of an existing log read on start (the job that runs right now)
LOG_READ_CAP = 4 << 20
STALE_JOB = 60.0                             # an open job nobody runs any more is dropped after this many seconds
HISTORY = 10
_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))      # never through a system proxy

# ------------------------------------------------------------------ allow list of heavy jobs
# lower-case executable name without .exe -> the label shown on the public dashboard. Nothing else is ever reported.
# server.py PROC_LABELS accepts exactly these labels (+ COMFY_PY): add a new one to both.
HEAVY = {
    "blender": "blender",
    "comfyui": "ComfyUI Desktop",
    "ffmpeg": "ffmpeg",
    "resolve": "DaVinci Resolve",
    "unrealeditor": "Unreal Editor",
    "houdini": "Houdini", "houdinifx": "Houdini", "hython": "Houdini",
    "maya": "Maya",
    "ollama": "ollama", "ollama_llama_server": "ollama",
    "llama-server": "llama.cpp",
}
COMFY_PY = "ComfyUI (python)"
PYTHON = re.compile(r"^python(\d+(\.\d+)?)?w?$")
PROMPT_ID = re.compile(r"^[A-Za-z0-9-]{1,64}$")


def exe_key(name):
    """'C:\\x\\Blender.EXE' -> 'blender' (the base name only, lower case, no .exe)."""
    base = str(name).replace("\\", "/").rsplit("/", 1)[-1].strip().lower()
    return base[:-4] if base.endswith(".exe") else base


def heavy_jobs(procs, comfy_pids=()):
    """procs: iterable of (pid, executable name) -> [{"name": label, "count": n}] for allow-listed programs only."""
    counts = collections.Counter()
    comfy_pids = set(comfy_pids or ())
    for pid, name in procs:
        key = exe_key(name)
        label = HEAVY.get(key)
        if label is None and pid in comfy_pids and PYTHON.match(key):
            label = COMFY_PY
        if label:
            counts[label] += 1
    return [{"name": k, "count": v} for k, v in sorted(counts.items())]


# ------------------------------------------------------------------ Linux (/proc) readers
def proc_cpu_times(proc="/proc"):
    """(idle, total) jiffies from /proc/stat, or None."""
    try:
        with open(os.path.join(proc, "stat"), encoding="ascii", errors="replace") as f:
            for line in f:
                if line.startswith("cpu "):
                    v = [int(x) for x in line.split()[1:]]
                    v += [0] * (8 - len(v))
                    return v[3] + v[4], sum(v[:8])        # idle + iowait; user..steal
    except (OSError, ValueError):
        pass
    return None


def proc_meminfo(proc="/proc"):
    """(used, total) bytes from /proc/meminfo, or None."""
    vals = {}
    try:
        with open(os.path.join(proc, "meminfo"), encoding="ascii", errors="replace") as f:
            for line in f:
                k, _, rest = line.partition(":")
                parts = rest.split()
                if parts and parts[0].isdigit():
                    vals[k.strip()] = int(parts[0]) * 1024
    except OSError:
        return None
    total = vals.get("MemTotal")
    if not total:
        return None
    avail = vals.get("MemAvailable")
    if avail is None:
        avail = vals.get("MemFree", 0) + vals.get("Buffers", 0) + vals.get("Cached", 0)
    return max(0, total - avail), total


def proc_processes(proc="/proc"):
    """([(pid, comm)], {pids of ComfyUI python}) from /proc. The command line is read here only to recognise ComfyUI;
    it is never returned."""
    out, comfy = [], set()
    try:
        names = os.listdir(proc)
    except OSError:
        return out, comfy
    for d in names:
        if not d.isdigit():
            continue
        pid = int(d)
        try:
            with open(os.path.join(proc, d, "comm"), encoding="utf-8", errors="replace") as f:
                comm = f.read().strip()
        except OSError:
            continue
        out.append((pid, comm))
        if PYTHON.match(exe_key(comm)):
            try:
                with open(os.path.join(proc, d, "cmdline"), "rb") as f:
                    cmd = f.read(4096).lower()
                if b"main.py" in cmd and b"comfy" in cmd:
                    comfy.add(pid)
            except OSError:
                pass
    return out, comfy


# ------------------------------------------------------------------ Windows (ctypes) readers
class _FILETIME(ctypes.Structure):
    _fields_ = [("lo", ctypes.c_uint32), ("hi", ctypes.c_uint32)]


class _MEMSTATEX(ctypes.Structure):
    _fields_ = [("dwLength", ctypes.c_uint32), ("dwMemoryLoad", ctypes.c_uint32),
                ("ullTotalPhys", ctypes.c_uint64), ("ullAvailPhys", ctypes.c_uint64),
                ("ullTotalPageFile", ctypes.c_uint64), ("ullAvailPageFile", ctypes.c_uint64),
                ("ullTotalVirtual", ctypes.c_uint64), ("ullAvailVirtual", ctypes.c_uint64),
                ("ullAvailExtendedVirtual", ctypes.c_uint64)]


class _PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [("dwSize", ctypes.c_uint32), ("cntUsage", ctypes.c_uint32), ("th32ProcessID", ctypes.c_uint32),
                ("th32DefaultHeapID", ctypes.c_size_t), ("th32ModuleID", ctypes.c_uint32),
                ("cntThreads", ctypes.c_uint32), ("th32ParentProcessID", ctypes.c_uint32),
                ("pcPriClassBase", ctypes.c_long), ("dwFlags", ctypes.c_uint32), ("szExeFile", ctypes.c_wchar * 260)]


def _k32():
    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.CreateToolhelp32Snapshot.restype = ctypes.c_void_p
    k.CreateToolhelp32Snapshot.argtypes = [ctypes.c_uint32, ctypes.c_uint32]
    k.Process32FirstW.argtypes = [ctypes.c_void_p, ctypes.POINTER(_PROCESSENTRY32W)]
    k.Process32NextW.argtypes = [ctypes.c_void_p, ctypes.POINTER(_PROCESSENTRY32W)]
    k.CloseHandle.argtypes = [ctypes.c_void_p]
    k.GetDriveTypeW.argtypes = [ctypes.c_wchar_p]
    return k


def win_cpu_times():
    """(idle, total) 100-ns ticks from GetSystemTimes (kernel time includes idle), or None."""
    idle, kern, user = _FILETIME(), _FILETIME(), _FILETIME()
    if not ctypes.windll.kernel32.GetSystemTimes(ctypes.byref(idle), ctypes.byref(kern), ctypes.byref(user)):
        return None
    ft = lambda f: (f.hi << 32) | f.lo       # noqa: E731
    return ft(idle), ft(kern) + ft(user)


def win_memory():
    m = _MEMSTATEX()
    m.dwLength = ctypes.sizeof(_MEMSTATEX)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m)):
        return None
    return m.ullTotalPhys - m.ullAvailPhys, m.ullTotalPhys


def win_processes():
    """[(pid, exe name)] from a Toolhelp32 snapshot (names only: no command lines), else from `tasklist`."""
    try:
        k = _k32()
        snap = k.CreateToolhelp32Snapshot(0x2, 0)                     # TH32CS_SNAPPROCESS
        if snap in (None, ctypes.c_void_p(-1).value):
            raise OSError("CreateToolhelp32Snapshot failed")
        out = []
        try:
            e = _PROCESSENTRY32W()
            e.dwSize = ctypes.sizeof(_PROCESSENTRY32W)
            ok = k.Process32FirstW(snap, ctypes.byref(e))
            while ok:
                out.append((int(e.th32ProcessID), e.szExeFile))
                ok = k.Process32NextW(snap, ctypes.byref(e))
        finally:
            k.CloseHandle(snap)
        return out
    except (OSError, AttributeError, ValueError):
        return tasklist_processes()


def parse_tasklist(text):
    """[(pid, image name)] from `tasklist /fo csv /nh` output."""
    out = []
    for line in text.splitlines():
        m = re.match(r'^"([^"]*)","(\d+)"', line.strip())
        if m:
            out.append((int(m.group(2)), m.group(1)))
    return out


def tasklist_processes():
    try:
        r = subprocess.run(["tasklist", "/fo", "csv", "/nh"], capture_output=True, timeout=5,
                           creationflags=NO_WINDOW if IS_WIN else 0)
        return parse_tasklist(r.stdout.decode("utf-8", "replace"))
    except (OSError, subprocess.SubprocessError):
        return []


def win_listen_pids(port):
    """PIDs listening on 127.0.0.1/0.0.0.0:port (IPv4 TCP), from GetExtendedTcpTable; empty on any error."""
    try:
        iph = ctypes.windll.iphlpapi
        size = ctypes.c_uint32(0)
        iph.GetExtendedTcpTable(None, ctypes.byref(size), False, 2, 3, 0)    # AF_INET, TCP_TABLE_OWNER_PID_LISTENER
        for _ in range(3):
            buf = ctypes.create_string_buffer(size.value + 4096)
            size = ctypes.c_uint32(len(buf))
            rc = iph.GetExtendedTcpTable(buf, ctypes.byref(size), False, 2, 3, 0)
            if rc == 0:
                break
            if rc != 122:                                              # ERROR_INSUFFICIENT_BUFFER: try again
                return set()
        else:
            return set()
        return listen_pids_from_table(buf.raw, port)
    except (OSError, AttributeError, ValueError):
        return set()


def listen_pids_from_table(raw, port):
    """MIB_TCPTABLE_OWNER_PID bytes -> {pid} whose local port is port (ports are in network byte order)."""
    n = struct.unpack_from("<I", raw, 0)[0]
    pids = set()
    for i in range(n):
        off = 4 + i * 24
        if off + 24 > len(raw):
            break
        _state, _addr, lport, _raddr, _rport, pid = struct.unpack_from("<6I", raw, off)
        if ((lport & 0xFF) << 8 | (lport >> 8) & 0xFF) == port:
            pids.add(pid)
    return pids


def win_fixed_drives():
    """['C:', 'D:', ...]: fixed drives only (no network, removable, optical or RAM drives)."""
    k = _k32()
    mask = k.GetLogicalDrives()
    out = []
    for i in range(26):
        if mask & (1 << i):
            letter = chr(65 + i) + ":"
            if k.GetDriveTypeW(letter + "\\") == 3:                    # DRIVE_FIXED
                out.append(letter)
    return out


# ------------------------------------------------------------------ portable parts
def cpu_percent(prev, cur):
    """CPU busy % between two (idle, total) samples, or None."""
    if not prev or not cur:
        return None
    didle, dtotal = cur[0] - prev[0], cur[1] - prev[1]
    if dtotal <= 0:
        return None
    return round(max(0.0, min(100.0, 100.0 * (1.0 - didle / dtotal))), 1)


def disks():
    """[{"name": "C:", "free": bytes, "total": bytes}] for every fixed drive (Windows) or / (elsewhere)."""
    names = win_fixed_drives() if IS_WIN else ["/"]
    out = []
    for name in names:
        try:
            u = shutil.disk_usage(name + "\\" if IS_WIN else name)
        except OSError:
            continue
        out.append({"name": name, "free": int(u.free), "total": int(u.total)})
    return out


GPU_QUERY = "utilization.gpu,memory.used,memory.total,temperature.gpu,power.draw,name"


def _num(s):
    try:
        v = float(s)
    except (TypeError, ValueError):
        return None                      # "[N/A]", "[Not Supported]"
    return v if v == v and abs(v) != float("inf") else None


def parse_nvidia_smi(text):
    """`nvidia-smi --query-gpu=<GPU_QUERY> --format=csv,noheader,nounits` -> [{name, util, mem_used, mem_total (bytes),
    temp, power}]."""
    out = []
    for line in (text or "").splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 6:
            continue
        util, used, total, temp, power = (_num(p) for p in parts[:5])
        name = re.sub(r"[^A-Za-z0-9 ._()+-]", "", ",".join(parts[5:])).strip()[:60] or "GPU"
        mib = 1024 * 1024
        out.append({"name": name, "util": util, "mem_used": int(used * mib) if used is not None else None,
                    "mem_total": int(total * mib) if total is not None else None, "temp": temp, "power": power})
    return out


def find_nvidia_smi():
    exe = shutil.which("nvidia-smi")
    if exe:
        return exe
    if IS_WIN:
        for cand in (os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "nvidia-smi.exe"),
                     r"C:\Program Files\NVIDIA Corporation\NVSMI\nvidia-smi.exe"):
            if os.path.isfile(cand):
                return cand
    return None


# ------------------------------------------------------------------ ComfyUI log (tqdm) parser
ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
TQDM = re.compile(r"(\d{1,3})%\|[^|\r\n]*\|\s*(\d+)/(\d+)\s*\[([0-9:]+)<([0-9:?]+),\s*(\?|[0-9.]+)\s*(s/it|it/s)\s*\]")
EXECUTED = re.compile(r"Prompt executed in\s+(?:(\d+(?::\d{1,2}){1,2}(?:\.\d+)?)|([0-9]+(?:\.[0-9]+)?)\s*(?:s\b|sec|seconds))")
FAILED = re.compile(r"Exception during processing|Error occurred when executing")
INTERRUPTED = re.compile(r"Processing interrupted|Interrupted by user", re.I)


def hms(s):
    """'11:03' -> 663.0, '1:02:03' -> 3723.0, '?' or junk -> None."""
    parts = s.split(":")
    try:
        sec = 0.0
        for p in parts:
            sec = sec * 60 + float(p)
        return sec
    except ValueError:
        return None


def parse_tqdm(line):
    """One tqdm progress line -> {step, total, pct, elapsed, eta, s_per_step} (None when it is not one)."""
    m = TQDM.search(line)
    if not m:
        return None
    step, total = int(m.group(2)), int(m.group(3))
    if total <= 0 or step > total:
        return None
    elapsed = hms(m.group(4))
    rate = None if m.group(6) == "?" else _num(m.group(6))
    if rate is not None and m.group(7) == "it/s":
        rate = 1.0 / rate if rate > 0 else None
    eta = hms(m.group(5)) if m.group(5) != "?" else None
    if eta is None and rate is not None:
        eta = rate * (total - step)
    return {"step": step, "total": total, "pct": round(100.0 * step / total, 1), "elapsed": elapsed,
            "eta": eta, "s_per_step": round(rate, 3) if rate is not None else None}


class ComfyLog:
    """State of ComfyUI's jobs from its log text: the open job (its tqdm bars) and the last 10 finished jobs.

    Lines end with \\n or \\r (tqdm writes '\\r' before each update, so the newest update has no line end yet: it is
    read from the unfinished tail, idempotently). A job opens at its first progress bar and closes at
    'Prompt executed in ...'; a bar whose total changes or whose step goes back is the job's next bar."""

    def __init__(self, keep=HISTORY):
        self.job = None
        self.history = collections.deque(maxlen=keep)
        self.buf = ""

    def feed(self, text, now, backlog=False):
        text = self.buf + (text or "")
        parts = re.split(r"[\r\n]", text)
        self.buf = parts.pop()[-4096:]
        for seg in parts:
            self._line(seg, now, backlog)
        if self.buf:
            p = parse_tqdm(ANSI.sub("", self.buf))
            if p:
                self._progress(p, now)

    def _line(self, line, now, backlog):
        line = ANSI.sub("", line)
        if not line.strip():
            return
        p = parse_tqdm(line)
        if p:
            self._progress(p, now)
            return
        m = EXECUTED.search(line)
        if m:
            secs = hms(m.group(1)) if m.group(1) else _num(m.group(2))
            self._finish(now, secs, backlog)
            return
        if FAILED.search(line) or INTERRUPTED.search(line):
            if self.job is None:
                self.job = {"started": now, "bars": [], "status": "ok", "prompt_id": None, "seen": now}
            self.job["status"] = "interrupted" if INTERRUPTED.search(line) else "failed"
            self.job["seen"] = now

    def _progress(self, p, now):
        job = self.job
        if job is None:
            job = self.job = {"started": now - (p["elapsed"] or 0.0), "bars": [], "status": "ok", "prompt_id": None,
                              "seen": now}
        job["started"] = min(job["started"], now - (p["elapsed"] or 0.0))   # joined mid-job: tqdm knows better
        bars = job["bars"]
        cur = bars[-1] if bars else None
        if cur is None or p["total"] != cur["total"] or p["step"] < cur["step"]:
            bars.append(dict(p))
        else:
            cur.update(p)
        job["seen"] = now

    def _finish(self, now, secs, backlog):
        job, self.job = self.job, None
        bars = job["bars"] if job else []
        main = max(bars, key=lambda b: ((b["elapsed"] or 0.0), b["total"])) if bars else None
        dur = secs if secs is not None else (now - job["started"] if job else None)
        self.history.append({
            "t": None if backlog else round(now, 1),
            "duration": round(dur, 1) if dur is not None else None,
            "steps": main["total"] if main else None,
            "s_per_step": main["s_per_step"] if main else None,
            "bars": len(bars),
            "status": job["status"] if job else "ok",
            "prompt_id": job["prompt_id"] if job else None,
        })

    def expire(self, now, active):
        """Drop an open job that no running prompt explains for STALE_JOB seconds (an old log, a crashed server)."""
        if self.job and not active and now - self.job["seen"] > STALE_JOB:
            self.job = None

    def current(self, now):
        job = self.job
        if not job or not job["bars"]:
            return None
        b = job["bars"][-1]
        return {"step": b["step"], "total": b["total"], "pct": b["pct"], "s_per_step": b["s_per_step"],
                "elapsed": b["elapsed"], "eta": b["eta"], "bar": len(job["bars"]),
                "job_elapsed": round(max(0.0, now - job["started"]), 1)}

    def spp(self):
        b = self.job["bars"][-1] if self.job and self.job["bars"] else None
        return (b or {}).get("s_per_step") or 0.0


class LogTail:
    """New text of a growing log file. Starts LOG_BACKLOG bytes before the end; a file that shrinks (rotated or
    truncated) is read again from the start. Never raises."""

    def __init__(self, path, backlog=LOG_BACKLOG):
        self.path = path
        self.backlog = backlog
        self.pos = None
        self.dec = None
        self.mtime = None
        self.first = True

    def read(self):
        """-> new text ('' when nothing is new) or None when the file is missing/unreadable."""
        try:
            st = os.stat(self.path)
        except OSError:
            self.pos = None
            return None
        self.mtime = st.st_mtime
        if self.pos is None or st.st_size < self.pos:
            self.pos = max(0, st.st_size - self.backlog) if self.pos is None else 0
            self.dec = codecs.getincrementaldecoder("utf-8")(errors="replace")
        if st.st_size == self.pos:
            return ""
        try:
            with open(self.path, "rb") as f:
                f.seek(self.pos)
                data = f.read(min(LOG_READ_CAP, st.st_size - self.pos))
        except OSError:
            return None
        self.pos += len(data)
        return self.dec.decode(data)


def comfy_queue(url, timeout=QUEUE_TIMEOUT):
    """{"up", "running", "pending", "prompt_id"} from GET <url>/queue; up False when nothing answers."""
    try:
        with _OPENER.open(url.rstrip("/") + "/queue", timeout=timeout) as r:
            q = json.loads(r.read().decode("utf-8"))
    except Exception:
        return {"up": False, "running": None, "pending": None, "prompt_id": None}
    run = q.get("queue_running") or []
    pend = q.get("queue_pending") or []
    pid = None
    for item in run:
        if isinstance(item, (list, tuple)) and len(item) > 1 and isinstance(item[1], str)                 and PROMPT_ID.fullmatch(item[1]):
            pid = item[1]
            break
    return {"up": True, "running": len(run) if isinstance(run, list) else 0,
            "pending": len(pend) if isinstance(pend, list) else 0, "prompt_id": pid}


def default_comfy_log():
    env = os.environ.get("FILM_COMFY_LOG")
    if env:
        return os.path.abspath(env)
    work = os.environ.get("FILM_COMFY_WORK")
    return os.path.join(os.path.abspath(work) if work else os.path.join(LAB, "out", "_comfy"), "server.log")


def comfy_port(url):
    m = re.match(r"^\w+://[^/:]+:(\d+)", url or "")
    return int(m.group(1)) if m else 80


# ------------------------------------------------------------------ the collector
class Monitor:
    def __init__(self, ingest=None, comfy_url=None, comfy_log=None, interval=2.0, clock=time.time):
        self.ingest = client.ingest_url(ingest)
        self.comfy_url = (comfy_url or os.environ.get("FILM_COMFY_URL") or DEFAULT_COMFY_URL).rstrip("/")
        self.tail = LogTail(comfy_log) if comfy_log else None
        self.log = ComfyLog()
        self.interval = max(0.5, float(interval))
        self.clock = clock
        self.cpu_prev = None
        self.gpu_exe = None
        self.gpu_next = 0.0
        self.backoff = 0.0
        self.next_post = 0.0
        self.online = None
        self.comfy_pids = set()

    # --- metrics
    def cpu(self):
        cur = win_cpu_times() if IS_WIN else proc_cpu_times()
        pct = cpu_percent(self.cpu_prev, cur)
        self.cpu_prev = cur
        return pct

    def gpus(self):
        now = time.monotonic()
        if self.gpu_exe is None:
            if now < self.gpu_next:
                return []
            self.gpu_exe = find_nvidia_smi()
            if not self.gpu_exe:
                self.gpu_next = now + GPU_RETRY
                return []
        try:
            r = subprocess.run([self.gpu_exe, f"--query-gpu={GPU_QUERY}", "--format=csv,noheader,nounits"],
                               capture_output=True, timeout=4, creationflags=NO_WINDOW if IS_WIN else 0)
            if r.returncode == 0:
                return parse_nvidia_smi(r.stdout.decode("utf-8", "replace"))
        except (OSError, subprocess.SubprocessError):
            pass
        self.gpu_exe, self.gpu_next = None, now + GPU_RETRY
        return []

    def procs(self):
        if IS_WIN:
            plist = win_processes()
            comfy = win_listen_pids(comfy_port(self.comfy_url))
        else:
            plist, comfy = proc_processes()
        return heavy_jobs(plist, comfy)

    def metrics(self):
        ev = {"type": "metrics", "t": round(self.clock(), 2), "cpu": None, "ram_used": None, "ram_total": None,
              "gpus": [], "disks": [], "procs": []}
        for key, fn in (("cpu", self.cpu), ("ram", win_memory if IS_WIN else proc_meminfo), ("gpus", self.gpus),
                        ("disks", disks), ("procs", self.procs)):
            try:
                v = fn()
            except Exception:              # one broken reader never stops the others
                v = None
            if key == "ram":
                if v:
                    ev["ram_used"], ev["ram_total"] = int(v[0]), int(v[1])
            elif v is not None:
                ev[key] = v
        return ev

    # --- ComfyUI
    def comfy(self):
        now = self.clock()
        q = comfy_queue(self.comfy_url)
        found = False
        if self.tail:
            try:
                text = self.tail.read()
                found = text is not None
                if text:
                    first, self.tail.first = self.tail.first, False
                    self.log.feed(text, now, backlog=first)
            except Exception:
                pass
        if q["prompt_id"] and self.log.job and not self.log.job["prompt_id"]:
            self.log.job["prompt_id"] = q["prompt_id"]
        mtime = self.tail.mtime if self.tail and found else None
        fresh = mtime is not None and now - mtime < max(60.0, 3 * self.log.spp())
        active = fresh and (not q["up"] or (q["running"] or 0) > 0)
        self.log.expire(now, active)
        return {"type": "comfy", "t": round(now, 2), "up": q["up"], "running": q["running"], "pending": q["pending"],
                "prompt_id": q["prompt_id"], "log": found,
                "current": self.log.current(now) if active else None,
                "history": list(self.log.history)}

    # --- delivery
    def post(self, ev):
        body = json.dumps(ev, separators=(",", ":")).encode("utf-8")
        req = urllib.request.Request(self.ingest, data=body, method="POST",
                                     headers={"Content-Type": "application/json"})
        with _OPENER.open(req, timeout=POST_TIMEOUT) as r:
            r.read()

    def tick(self):
        """Collect both events and send them unless backing off. -> (metrics, comfy, delivered)."""
        m = self.metrics()
        c = self.comfy()
        if not self.ingest:
            return m, c, False
        now = time.monotonic()
        if now < self.next_post:
            return m, c, False
        try:
            self.post(m)
            self.post(c)
        except Exception as e:
            self.backoff = min(MAX_BACKOFF, max(self.interval, self.backoff * 2))
            self.next_post = now + self.backoff
            if self.online is not False:
                say(f"review server unreachable ({type(e).__name__}); retrying every <= {MAX_BACKOFF:g} s")
            self.online = False
            return m, c, False
        if self.online is False:
            say("review server back")
        self.online, self.backoff, self.next_post = True, 0.0, 0.0
        return m, c, True

    def run(self):
        say(f"monitor: every {self.interval:g} s -> {self.ingest} · ComfyUI {self.comfy_url} · log "
            f"{'yes' if self.tail else 'off'}")
        while True:
            t0 = time.monotonic()
            try:
                self.tick()
            except Exception as e:            # never exit on a collector or delivery error
                say(f"tick failed: {type(e).__name__}: {e}")
            time.sleep(max(0.2, self.interval - (time.monotonic() - t0)))


def say(msg):
    try:
        print(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {msg}", flush=True)
    except Exception:
        pass


def main(argv=None):
    p = argparse.ArgumentParser(prog="monitor.py", description=__doc__.split("\n\n")[0],
                                formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    p.add_argument("--interval", type=float, default=2.0, help="seconds between samples (default 2)")
    p.add_argument("--comfy-log", default=None, help="ComfyUI log to follow (default FILM_COMFY_LOG or "
                                                     "<FILM_COMFY_WORK|lab out/_comfy>/server.log); 'off' disables")
    p.add_argument("--comfy-url", default=None, help="ComfyUI base URL (default FILM_COMFY_URL or 127.0.0.1:8188)")
    p.add_argument("--url", default=None, help="review ingest base URL (default FILM_REVIEW_URL or 127.0.0.1:8791)")
    p.add_argument("--once", action="store_true", help="collect one sample and stop")
    p.add_argument("--print", dest="show", action="store_true", help="print the events (with --once: send nothing)")
    a = p.parse_args(argv)
    log = None if (a.comfy_log or "").lower() == "off" else os.path.abspath(a.comfy_log or default_comfy_log())
    mon = Monitor(a.url, a.comfy_url, log, a.interval)
    if a.once:
        mon.cpu()
        time.sleep(0.5)
        m, c = mon.metrics(), mon.comfy()
        if a.show:
            print(json.dumps(m, ensure_ascii=False, indent=1))
            print(json.dumps(c, ensure_ascii=False, indent=1))
            return 0
        try:
            mon.post(m)
            mon.post(c)
        except Exception as e:
            print(f"monitor: not delivered ({type(e).__name__}: {e})", file=sys.stderr)
            return 1
        return 0
    try:
        mon.run()
    except KeyboardInterrupt:
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
