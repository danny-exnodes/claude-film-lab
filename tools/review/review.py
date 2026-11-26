#!/usr/bin/env python3
"""Run the Film Lab review web app (Docker) and publish files to it. Standard library only; Windows and Linux.

  python tools/review/review.py up [--tunnel ngrok|tailscale|cloudflared] [--no-ngrok] [--no-monitor]
                                   [--comfy-log PATH] [--dry-run]
                                    # vendor check -> docker compose up -d --build -> monitor.py (detached) -> tunnel
  python tools/review/review.py down                           # stop monitor + container (the volume stays) + our tunnel
  python tools/review/review.py monitor [--stop|--restart] [--comfy-log PATH] [--interval S]   # only monitor.py
  python tools/review/review.py watch <project> [--episode q01t03] [--stop|--restart] [--once]  # watch.py, detached
  python tools/review/review.py url                            # the public URL of port 8790
  python tools/review/review.py status                         # builds, media mount, monitor, watchers, tunnel
  python tools/review/review.py publish-video <mp4> --build ID --label L [--title T] [--project P] [--open]
  python tools/review/review.py publish-model <glb> --build ID [--label L] [--title T] [--project P] [--open]

The public URL shows everything that was published, to anyone who has the link (no login: the owner's choice).
Only files under the media folder are served: FILM_REVIEW_MEDIA, else out/_review/media of the lab's MAIN checkout
(git rev-parse --git-common-dir), so `up` from a worktree mounts the folder every client writes to; `status` warns when
the running container mounts another one. Pid files and logs: out/_review/ of the main checkout.
Tunnels (never installed, never logged in by this script; their config and tokens are never read or printed):
  ngrok        `ngrok http 127.0.0.1:8790` (detached); URL from ngrok's local API (http://127.0.0.1:4040/api/tunnels)
  tailscale    `tailscale funnel --bg 8790`; needs a logged-in Tailscale with Funnel enabled for this machine; URL
               https://<this machine's DNS name>/ (`tailscale status --json`); `down` runs `tailscale funnel --https=443
               off`
  cloudflared  quick tunnel `cloudflared tunnel --url http://127.0.0.1:8790` (no account; a new random
               *.trycloudflare.com URL each start); URL from its metrics endpoint (127.0.0.1:20241/quicktunnel)
Exit: 0 ok · 1 failed (Docker, tunnel, server unreachable) · 2 refused (vendor files missing, tunnel binary missing or
not logged in, bad arguments).
"""
import argparse
import json
import os
import posixpath
import re
import shutil
import struct
import subprocess
import sys
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
LAB = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
import client  # noqa: E402
import vendor_three  # noqa: E402

COMPOSE = os.path.join("tools", "review", "docker-compose.yml")
CONTAINER = "film-lab-review"
MOUNT_ENV = "FILM_REVIEW_MEDIA_MOUNT"          # docker-compose.yml: the host folder mounted read-only at /media
PUBLIC = "http://127.0.0.1:8790"
NGROK_API = "http://127.0.0.1:4040/api/tunnels"
CLOUDFLARED_METRICS = "127.0.0.1:20241"
TUNNELS = ("ngrok", "tailscale", "cloudflared")
STATE = client.lab_out("_review")
NGROK_PID = os.path.join(STATE, "ngrok.pid")
CLOUDFLARED_PID = os.path.join(STATE, "cloudflared.pid")
CLOUDFLARED_LOG = os.path.join(STATE, "cloudflared.log")
TUNNEL_STATE = os.path.join(STATE, "tunnel.json")
MONITOR_PID = os.path.join(STATE, "monitor.pid")
MONITOR_LOG = os.path.join(STATE, "monitor.log")
MONITOR = os.path.join(HERE, "monitor.py")
WATCH = os.path.join(HERE, "watch.py")
PROJECT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))
DETACHED = 0x00000008 | 0x00000200                 # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
NO_WINDOW = 0x08000000


def say(msg):
    print(f"review: {msg}", flush=True)


def err(msg):
    print(f"review: {msg}", file=sys.stderr, flush=True)


def get_json(url, timeout=3):
    with _OPENER.open(url, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def compose_cmd(*args):
    return ["docker", "compose", "-f", COMPOSE] + list(args)


def show(cmd):
    return " ".join(f'"{c}"' if " " in c else c for c in cmd)


def detach_kw():
    if os.name == "nt":
        return {"creationflags": DETACHED}
    return {"start_new_session": True}


# ------------------------------------------------------------------ media folder (client and container must agree)
def media_dir():
    """The folder clients publish into and `up` mounts: FILM_REVIEW_MEDIA, else <main checkout>/out/_review/media."""
    return client.media_root()


def host_path(src):
    """A bind-mount source as Docker reports it -> a host path: Docker Desktop shows D:\\x, /run/desktop/mnt/host/d/x,
    /host_mnt/d/x or /mnt/d/x for D:\\x."""
    m = re.match(r"^(?:/run/desktop/mnt/host|/host_mnt|/mnt/host|/mnt)/([A-Za-z])(/.*)?$", str(src or ""))
    if m:
        return f"{m.group(1).upper()}:{(m.group(2) or '/').replace('/', os.sep)}"
    return str(src or "")


def same_path(a, b):
    """Equal host paths: separators unified; case-insensitive for Windows paths."""
    def norm(p):
        p = posixpath.normpath(str(p).replace("\\", "/"))
        return p.lower() if os.name == "nt" or re.match(r"^[A-Za-z]:", p) else p
    return norm(a) == norm(b)


def container_media_mount():
    """The host folder the running container mounts at /media (docker inspect), or None."""
    if not shutil.which("docker"):
        return None
    try:
        r = subprocess.run(["docker", "inspect", CONTAINER, "--format", "{{json .Mounts}}"], capture_output=True,
                           timeout=20, text=True, encoding="utf-8", errors="replace")
        mounts = json.loads(r.stdout or "null") if r.returncode == 0 else None
    except (OSError, subprocess.SubprocessError, ValueError):
        return None
    for m in mounts or []:
        if isinstance(m, dict) and m.get("Destination") == "/media":
            return host_path(m.get("Source"))
    return None


# ------------------------------------------------------------------ processes (pid files are checked before a kill)
PYTHON_EXE = re.compile(r"^python(\d+(\.\d+)*)?w?$")
PS_QUERY = ("[Console]::OutputEncoding = [Text.Encoding]::UTF8; "
            "$p = Get-CimInstance Win32_Process -Filter 'ProcessId = %d'; "
            "if ($p) { [pscustomobject]@{name = $p.Name; cmdline = $p.CommandLine} | ConvertTo-Json -Compress }")


def process_info(pid):
    """{'name': image name, 'cmdline': command line or None} of a live process, else None (also when it cannot be
    read). Windows: PowerShell Get-CimInstance Win32_Process (no wmic); elsewhere /proc."""
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return None
    if pid <= 0:
        return None
    if os.name == "nt":
        try:
            r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", PS_QUERY % pid],
                               capture_output=True, timeout=30, creationflags=NO_WINDOW)
            d = json.loads(r.stdout.decode("utf-8", "replace").strip() or "null")
        except (OSError, subprocess.SubprocessError, ValueError):
            return None
        return {"name": str(d.get("name") or ""), "cmdline": d.get("cmdline")} if isinstance(d, dict) else None
    try:
        os.kill(pid, 0)
        with open(f"/proc/{pid}/comm", encoding="utf-8") as f:
            name = f.read().strip()
    except (OSError, ValueError):
        return None
    try:
        with open(f"/proc/{pid}/cmdline", "rb") as f:
            cmd = f.read().replace(b"\0", b" ").decode("utf-8", "replace").strip()
    except OSError:
        cmd = None
    return {"name": name, "cmdline": cmd}


def exe_base(name):
    """'C:\\Python314\\python.exe' -> 'python' (lower case, no folder, no .exe)."""
    base = str(name or "").replace("\\", "/").rsplit("/", 1)[-1].strip().lower()
    return base[:-4] if base.endswith(".exe") else base


def is_ngrok(info):
    return exe_base(info.get("name")) == "ngrok"


def is_cloudflared(info):
    return exe_base(info.get("name")) == "cloudflared"


def is_python_running(info, script):
    """A python whose command line runs tools/review/<script> (a reused pid of any other program is not)."""
    cmd = str(info.get("cmdline") or "").replace("\\", "/").lower()
    return bool(PYTHON_EXE.match(exe_base(info.get("name")))) and f"tools/review/{script}" in cmd


def is_monitor(info):
    return is_python_running(info, "monitor.py")


def is_watch(info):
    return is_python_running(info, "watch.py")


def pid_alive(pid):
    """True when a process with this pid runs (monitor.pid_alive: Windows OpenProcess, elsewhere kill 0)."""
    try:
        import monitor
        return monitor.pid_alive(pid)
    except Exception:
        return False


OURS, GONE, UNKNOWN = "ours", "gone", "unknown"


def pid_check(path, verify, what):
    """(state, pid) of the pid file `path`: OURS when the process runs and verify(info) holds; GONE when there is no
    pid file, it is unreadable, its process is dead or is another program (the stale file is deleted; nothing is
    killed); UNKNOWN when the process runs but cannot be inspected (PowerShell timeout, unparsable answer): the pid
    file is kept and nothing is started or stopped, so a live monitor/watcher is never orphaned."""
    try:
        with open(path, encoding="utf-8") as f:
            pid = int(f.read().strip())
    except FileNotFoundError:
        return GONE, None
    except (OSError, ValueError):
        pid = None
    if pid and pid > 0 and pid_alive(pid):
        info = process_info(pid)
        if info is None:
            say(f"cannot verify pid {pid} of the {what} (the process query failed): pid file {path} kept, nothing "
                f"stopped or started; try again, or end that process yourself and delete the pid file")
            return UNKNOWN, pid
        if verify(info):
            return OURS, pid
    try:
        os.remove(path)
        say(f"stale {what} pid file removed (pid {pid} is not our {what}); nothing was stopped")
    except OSError:
        pass
    return GONE, pid


def checked_pid(path, verify, what):
    """The pid in `path` when it is our running process (pid_check OURS), else None."""
    state, pid = pid_check(path, verify, what)
    return pid if state == OURS else None


def kill(pid, tree=False):
    """End pid; tree: with its children (a watcher's Blender export, a tunnel's helpers)."""
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(pid)] + (["/T"] if tree else []) + ["/F"], capture_output=True)
        return
    try:
        if tree and os.getpgid(pid) == pid:   # started with start_new_session: the whole process group
            os.killpg(pid, 15)
        else:
            os.kill(pid, 15)
    except OSError:
        pass


def remove(path):
    try:
        os.remove(path)
    except OSError:
        pass


def start_detached(cmd, pid_file, log_file, what, fresh_log=False):
    """Start cmd detached, its output appended to log_file (fresh_log: the log starts empty, e.g. cloudflared whose
    URL is read back from it, so an earlier run's URL is never found)."""
    os.makedirs(STATE, exist_ok=True)
    try:
        if os.path.getsize(log_file) > 1 << 20:
            os.remove(log_file)
    except OSError:
        pass
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1")
    with open(log_file, "wb" if fresh_log else "ab") as log:
        proc = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, env=env, cwd=LAB,
                                **detach_kw())
    with open(pid_file, "w", encoding="utf-8") as f:
        f.write(str(proc.pid))
    say(f"{what} started (pid {proc.pid}; log {log_file})")
    return proc


# ------------------------------------------------------------------ monitor.py (detached)
def monitor_cmd(a):
    cmd = [sys.executable, MONITOR]
    if getattr(a, "interval", None):
        cmd += ["--interval", f"{a.interval:g}"]
    if getattr(a, "comfy_log", None):
        cmd += ["--comfy-log", a.comfy_log]
    return cmd


def monitor_pid():
    """PID of our running monitor (monitor.pid, verified: python running tools/review/monitor.py), else None."""
    return checked_pid(MONITOR_PID, is_monitor, "monitor")


def ngrok_pid():
    """PID of the ngrok that `up` started (ngrok.pid, verified: the image is ngrok(.exe)), else None."""
    return checked_pid(NGROK_PID, is_ngrok, "ngrok")


def cloudflared_pid():
    return checked_pid(CLOUDFLARED_PID, is_cloudflared, "cloudflared")


def start_monitor(a):
    state, pid = pid_check(MONITOR_PID, is_monitor, "monitor")
    if state == OURS:
        say(f"monitor already runs (pid {pid})")
        return 0
    if state == UNKNOWN:
        err(f"monitor not started: pid {pid} in {MONITOR_PID} may still be our monitor")
        return 1
    start_detached(monitor_cmd(a), MONITOR_PID, MONITOR_LOG, "monitor")
    return 0


def stop_monitor():
    state, pid = pid_check(MONITOR_PID, is_monitor, "monitor")
    if state == OURS:
        kill(pid)
        say(f"stopped monitor (pid {pid})")
        remove(MONITOR_PID)
    return state != UNKNOWN


def cmd_monitor(a):
    if a.dry_run:
        if a.stop:
            say("dry-run: would stop the monitor of " + MONITOR_PID)
        else:
            print(show(monitor_cmd(a)) + "   # detached; pid in " + MONITOR_PID)
        return 0
    if a.stop or a.restart:
        if not stop_monitor():
            return 1
    if a.stop:
        return 0
    return start_monitor(a)


# ------------------------------------------------------------------ watch.py (detached, one per project)
def watch_files(project):
    return os.path.join(STATE, f"watch-{project}.pid"), os.path.join(STATE, f"watch-{project}.log")


def watch_cmd(a):
    cmd = [sys.executable, WATCH, a.project]
    for flag, val in (("--episode", a.episode), ("--interval", a.interval), ("--blender", a.blender),
                      ("--since", a.since), ("--max-glb-mb", a.max_glb_mb), ("--decimate", a.decimate)):
        if val is not None:
            cmd += [flag, f"{val:g}" if isinstance(val, float) else str(val)]
    for d in a.dir or []:
        cmd += ["--dir", d]
    if a.no_glb:
        cmd.append("--no-glb")
    if a.once:
        cmd.append("--once")
    return cmd


def watch_pid(project):
    return checked_pid(watch_files(project)[0], is_watch, f"watcher of {project}")


def stop_watch(project):
    """Stop our watcher of project with its process tree (a running Blender GLB export goes with it). -> False when
    its pid cannot be verified (nothing stopped, pid file kept)."""
    pid_file = watch_files(project)[0]
    state, pid = pid_check(pid_file, is_watch, f"watcher of {project}")
    if state == OURS:
        kill(pid, tree=True)
        say(f"stopped the watcher of {project} (pid {pid})")
        remove(pid_file)
    return state != UNKNOWN


def bad_watch_dir(d):
    """Why a --dir is refused (absolute, a drive, '..'), else None: watched folders stay inside out/<project>/."""
    s = str(d or "").strip()
    if not s or os.path.isabs(s) or re.match(r"^(?:[A-Za-z]:|[\\/])", s):
        return "must be a folder relative to out/<project>/"
    if ".." in re.split(r"[\\/]+", s):
        return "must not contain '..'"
    return None


def cmd_watch(a):
    if not PROJECT.match(a.project):
        err("refused: <project> must match [A-Za-z0-9][A-Za-z0-9._-]{0,63} (the folder under out/)")
        return 2
    if a.episode and not PROJECT.match(a.episode):
        err("refused: --episode must be a folder name like q01t03 or ep01")
        return 2
    for d in a.dir or []:
        why = bad_watch_dir(d)
        if why:
            err(f"refused: --dir {d!r} {why}")
            return 2
    pid_file, log_file = watch_files(a.project)
    cmd = watch_cmd(a)
    if a.dry_run:
        print(show(cmd) + ("" if a.once else "   # detached; pid in " + pid_file))
        return 0
    if a.once:                         # one scan in the foreground (the watcher's own exit code)
        return subprocess.run(cmd, cwd=LAB).returncode
    if a.stop or a.restart:
        if not stop_watch(a.project):
            return 1
    if a.stop:
        return 0
    state, pid = pid_check(pid_file, is_watch, f"watcher of {a.project}")
    if state == OURS:
        say(f"the watcher of {a.project} already runs (pid {pid}); --restart for new options")
        return 0
    if state == UNKNOWN:
        err(f"watcher not started: pid {pid} in {pid_file} may still be our watcher")
        return 1
    start_detached(cmd, pid_file, log_file, f"watcher of {a.project}")
    return 0


def watchers():
    """[(project, pid)] of the watchers that run (stale pid files are removed)."""
    out = []
    try:
        names = sorted(os.listdir(STATE))
    except OSError:
        return out
    for name in names:
        m = re.fullmatch(r"watch-(.+)\.pid", name)
        if m:
            pid = watch_pid(m.group(1))
            if pid:
                out.append((m.group(1), pid))
    return out


# ------------------------------------------------------------------ tunnels
def public_url(tunnels):
    """The https public URL of a tunnel to port 8790 in ngrok's /api/tunnels answer, else None."""
    best = None
    for t in tunnels.get("tunnels") or []:
        addr = str((t.get("config") or {}).get("addr", ""))
        if not addr.rstrip("/").endswith(":8790") and addr != "8790":
            continue
        url = t.get("public_url") or ""
        if url.startswith("https://"):
            return url
        best = best or url
    return best


def ngrok_url():
    try:
        return public_url(get_json(NGROK_API, timeout=2))
    except Exception:
        return None


def cloudflared_url(pid=None):
    """https://<random>.trycloudflare.com of our quick tunnel: its metrics endpoint, else the log `up` wrote, but only
    while our cloudflared runs (`pid`, else cloudflared_pid()): the log of a finished run holds a dead URL."""
    try:
        host = get_json(f"http://{CLOUDFLARED_METRICS}/quicktunnel", timeout=2).get("hostname")
        if host and re.fullmatch(r"[A-Za-z0-9.-]+", host):
            return f"https://{host}"
    except Exception:
        pass
    if not (pid or cloudflared_pid()):
        return None
    try:
        with open(CLOUDFLARED_LOG, encoding="utf-8", errors="replace") as f:
            found = re.findall(r"https://[a-z0-9-]+\.trycloudflare\.com", f.read()[-200000:])
        return found[-1] if found else None
    except OSError:
        return None


def tailscale_status(exe):
    """(BackendState, DNSName) from `tailscale status --json`; only these two fields are read, nothing is printed."""
    try:
        r = subprocess.run([exe, "status", "--json"], capture_output=True, timeout=20, text=True, encoding="utf-8",
                           errors="replace", **({"creationflags": NO_WINDOW} if os.name == "nt" else {}))
        d = json.loads(r.stdout or "null")
    except (OSError, subprocess.SubprocessError, ValueError):
        return None, None
    if not isinstance(d, dict):
        return None, None
    return d.get("BackendState"), ((d.get("Self") or {}).get("DNSName") or "").rstrip(".") or None


def tunnel_state():
    """{kind: {"url", "since"}} of every tunnel `up` started and `down` has not stopped (tunnel.json; the one-kind file
    of older versions is read too). {} when there is none."""
    try:
        with open(TUNNEL_STATE, encoding="utf-8") as f:
            d = json.load(f)
    except (OSError, ValueError):
        return {}
    if not isinstance(d, dict):
        return {}
    if isinstance(d.get("tunnels"), dict):
        found = d["tunnels"]
    elif d.get("kind") in TUNNELS:                      # before: {"kind", "url", "since"}
        found = {d["kind"]: {"url": d.get("url"), "since": d.get("since")}}
    else:
        return {}
    return {k: (v if isinstance(v, dict) else {}) for k, v in found.items() if k in TUNNELS}


def write_tunnels(tunnels):
    if not tunnels:
        remove(TUNNEL_STATE)
        return
    os.makedirs(STATE, exist_ok=True)
    tmp = TUNNEL_STATE + ".part"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"tunnels": tunnels}, f)
    os.replace(tmp, TUNNEL_STATE)


def save_tunnel(kind, url):
    """Record a started tunnel next to the others still recorded (down stops every one of them)."""
    tunnels = tunnel_state()
    tunnels[kind] = {"url": url, "since": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    write_tunnels(tunnels)


def active_tunnels():
    """Kinds of the tunnels `up` started that may still be public: recorded in tunnel.json, or our ngrok/cloudflared
    (pid file) still runs or cannot be verified."""
    kinds = list(tunnel_state())
    for kind, pid_file, verify in (("ngrok", NGROK_PID, is_ngrok), ("cloudflared", CLOUDFLARED_PID, is_cloudflared)):
        if kind not in kinds and pid_check(pid_file, verify, kind)[0] != GONE:
            kinds.append(kind)
    return kinds


def tunnel_cmd(kind, exe=None):
    if kind == "ngrok":
        return [exe or "ngrok", "http", "127.0.0.1:8790", "--log", "stdout"]
    if kind == "tailscale":
        return [exe or "tailscale", "funnel", "--bg", "8790"]
    return [exe or "cloudflared", "tunnel", "--no-autoupdate", "--metrics", CLOUDFLARED_METRICS, "--url",
            "http://127.0.0.1:8790"]


HOW = {"ngrok": "install ngrok and sign in to it yourself",
       "tailscale": "install Tailscale, sign in to it yourself and enable Funnel for this machine in the Tailscale "
                    "admin console",
       "cloudflared": "install cloudflared yourself (a quick tunnel needs no account)"}


def tunnel_preflight(kind):
    """-> (exe, None) or (None, refusal text): the binary must be on PATH; tailscale must be logged in and running."""
    exe = shutil.which(kind)
    if not exe:
        return None, f"{kind} not found on PATH ({HOW[kind]}); or: review.py up --no-ngrok (local only)"
    if kind == "tailscale":
        state, dns = tailscale_status(exe)
        if state != "Running" or not dns:
            return None, (f"tailscale is not logged in or not running (state {state or 'unknown'}): {HOW[kind]}; "
                          f"or another tunnel: --tunnel ngrok|cloudflared")
    return exe, None


def start_tunnel(kind, exe):
    """-> (url or None, error or None)."""
    if kind == "ngrok":
        url = ngrok_url()
        if not url:
            os.makedirs(STATE, exist_ok=True)
            proc = subprocess.Popen(tunnel_cmd(kind, exe), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                    stderr=subprocess.DEVNULL, **detach_kw())
            with open(NGROK_PID, "w", encoding="utf-8") as f:
                f.write(str(proc.pid))
            for _ in range(30):
                time.sleep(0.5)
                url = ngrok_url()
                if url:
                    break
        return url, None if url else f"ngrok started but no tunnel to 8790 is listed at {NGROK_API}"
    if kind == "tailscale":
        try:
            r = subprocess.run(tunnel_cmd(kind, exe), capture_output=True, timeout=45, text=True, encoding="utf-8",
                               errors="replace", **({"creationflags": NO_WINDOW} if os.name == "nt" else {}))
        except subprocess.TimeoutExpired:
            return None, ("tailscale funnel did not return in 45 s: it probably waits for Funnel to be enabled for "
                          "this machine (Tailscale admin console); enable it, then run up again")
        except OSError as e:
            return None, f"tailscale funnel failed ({e})"
        if r.returncode:
            tail = " ".join((r.stderr or r.stdout or "").split())[:300]
            return None, f"tailscale funnel failed (exit {r.returncode}): {tail}"
        _, dns = tailscale_status(exe)
        return (f"https://{dns}/", None) if dns else (None, "tailscale funnel runs but the DNS name is unknown")
    url = cloudflared_url() if cloudflared_pid() else None
    if not url:
        os.makedirs(STATE, exist_ok=True)
        proc = start_detached(tunnel_cmd(kind, exe), CLOUDFLARED_PID, CLOUDFLARED_LOG, "cloudflared", fresh_log=True)
        for _ in range(60):
            time.sleep(0.5)
            url = cloudflared_url(proc.pid if proc.poll() is None else None)
            if url:
                break
    return url, None if url else f"cloudflared started but no quick tunnel URL yet (log {CLOUDFLARED_LOG})"


def stop_tunnels(kinds=None):
    """Stop the tunnels `up` started (kinds: these only; default every one): our ngrok/cloudflared (pid verified, with
    their process tree), our tailscale funnel (only when tunnel.json records it). -> the kinds that could not be
    stopped (they stay in tunnel.json, so the next `down` tries again)."""
    tunnels = tunnel_state()
    left = []
    for kind in kinds or TUNNELS:
        if kind in ("ngrok", "cloudflared"):
            pid_file, verify = (NGROK_PID, is_ngrok) if kind == "ngrok" else (CLOUDFLARED_PID, is_cloudflared)
            state, pid = pid_check(pid_file, verify, kind)   # a reused pid of another program is never killed
            if state == OURS:
                kill(pid, tree=True)
                say(f"stopped {kind} (pid {pid})")
                remove(pid_file)
            elif state == UNKNOWN:
                left.append(kind)
                continue
        elif kind == "tailscale" and kind in tunnels:
            exe = shutil.which("tailscale")
            if not exe:
                err("tailscale not found on PATH: the funnel may still be public; "
                    "run: tailscale funnel --https=443 off")
                left.append(kind)
                continue
            try:
                r = subprocess.run([exe, "funnel", "--https=443", "off"], capture_output=True, timeout=30)
                if r.returncode:
                    raise subprocess.SubprocessError(f"exit {r.returncode}")
                say("stopped the tailscale funnel (https 443)")
            except (OSError, subprocess.SubprocessError) as e:
                err(f"tailscale funnel off failed ({type(e).__name__}: {e}); run: tailscale funnel --https=443 off")
                left.append(kind)
                continue
        tunnels.pop(kind, None)
    write_tunnels(tunnels)
    return left


def current_urls():
    """[(kind, url or None)] of every recorded tunnel, plus a running ngrok's tunnel to 8790."""
    out = []
    for kind, rec in tunnel_state().items():
        if kind == "cloudflared":
            out.append((kind, cloudflared_url()))
        elif kind == "tailscale":
            out.append((kind, rec.get("url")))
        else:
            out.append((kind, ngrok_url()))
    if "ngrok" not in dict(out):
        url = ngrok_url()
        if url:
            out.append(("ngrok", url))
    return out


def current_url():
    urls = current_urls()
    for kind, url in urls:
        if url:
            return url, kind
    return None, (urls[0][0] if urls else None)


# ------------------------------------------------------------------ commands
def cmd_up(a):
    tunnel = "none" if a.no_ngrok else a.tunnel
    problems = vendor_three.verify()
    if problems:
        msg = "three.js is not vendored: " + "; ".join(problems[:3]) + (" ..." if len(problems) > 3 else "")
        fix = "python tools/review/vendor_three.py --from <three package dir> (e.g. node_modules/three, 0.186.1)"
        if not a.dry_run:
            err(f"refused: {msg}\nreview: run {fix}")
            return 2
        say(f"WARNING {msg} (up would refuse; {fix})")
    media = media_dir()
    up = compose_cmd("up", "-d", "--build")
    if a.dry_run:
        say(f"mkdir {media}")
        say(f"mount {media} -> /media (read-only; env {MOUNT_ENV})")
        print(show(up))
        if not a.no_monitor:
            print(show(monitor_cmd(a)) + "   # detached; pid in " + MONITOR_PID)
        if tunnel != "none":
            print(show(tunnel_cmd(tunnel)) + ("   # detached" if tunnel != "tailscale" else "   # background funnel"))
        say("dry-run: nothing started")
        return 0
    exe = None
    if tunnel != "none" and not (tunnel == "ngrok" and ngrok_url()):
        exe, why = tunnel_preflight(tunnel)
        if why:
            err(f"refused: {why}")
            return 2
    if tunnel != "none":               # one public tunnel at a time: switching kinds stops the earlier one first
        others = [k for k in active_tunnels() if k != tunnel]
        if others:
            say(f"switching to {tunnel}: stopping the earlier tunnel ({', '.join(others)})")
            left = stop_tunnels(others)
            if left:
                err(f"refused: the earlier tunnel ({', '.join(left)}) could not be stopped and may still be public; "
                    f"stop it, then run up again")
                return 1
    os.makedirs(media, exist_ok=True)
    if not shutil.which("docker"):
        err("docker not found on PATH (start Docker Desktop)")
        return 1
    say(f"media folder: {media} (mounted read-only at /media)")
    say(show(up))
    r = subprocess.run(up, cwd=LAB, env=dict(os.environ, **{MOUNT_ENV: media}))
    if r.returncode:
        err(f"docker compose failed (exit {r.returncode})")
        return 1
    if wait_health():
        say(f"server ok: {PUBLIC} (local)")
    else:
        err(f"the container started but {PUBLIC}/api/health does not answer yet "
            f"(docker compose -f {COMPOSE} logs film-lab-review)")
        return 1
    if not a.no_monitor:
        start_monitor(a)
    if tunnel == "none":
        active = active_tunnels()
        if active:
            say(f"WARNING a public tunnel from an earlier `up` is still active ({', '.join(active)}): the dashboard is "
                f"still public; stop it with: python tools/review/review.py down")
        else:
            say("no tunnel: local only")
        return 0
    url, why = start_tunnel(tunnel, exe or shutil.which(tunnel))
    if not url:
        err(why)
        return 1
    save_tunnel(tunnel, url)
    say(f"public URL via {tunnel} (anyone with the link sees every published build, no login):")
    print(url)
    return 0


def wait_health(seconds=40):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        try:
            if get_json(PUBLIC + "/api/health", timeout=2).get("ok"):
                return True
        except Exception:
            pass
        time.sleep(1)
    return False


def cmd_down(a):
    cmd = compose_cmd("down")
    if a.dry_run:
        print(show(cmd))
        return 0
    stop_monitor()
    rc = 0
    if shutil.which("docker"):
        say(show(cmd))
        rc = subprocess.run(cmd, cwd=LAB, env=dict(os.environ, **{MOUNT_ENV: media_dir()})).returncode
    else:
        err("docker not found on PATH")
        rc = 1
    left = stop_tunnels()
    if left:
        err(f"not stopped: {', '.join(left)} (may still be public); run down again or stop it yourself")
    return 1 if rc or left else 0


def cmd_url(a):
    url, kind = current_url()
    if not url:
        err(f"no public tunnel to 8790 ({kind or 'ngrok'}); start one with: python tools/review/review.py up")
        return 1
    print(url)
    return 0


def cmd_status(a):
    try:
        builds = get_json(PUBLIC + "/api/builds").get("builds", [])
    except Exception as e:
        err(f"the review server does not answer at {PUBLIC} ({e}); start it: python tools/review/review.py up")
        builds = None
    for b in builds or []:
        job = b.get("job") or {}
        jtxt = f" · {job.get('tool')} {job.get('status')}" if job else ""
        chips = " ".join(f"{g}:{','.join(v)}" for g, v in (b.get("tags") or {}).items() if v)
        print(f"{b['id']:24} {b['status']:9} {round(100 * (b.get('progress') or 0)):3d}%  {b.get('steps', 0):3d} steps "
              f"{b.get('renders', 0):2d} renders  {b.get('name') or b.get('title', '')}{jtxt}"
              + (f"  [{chips}]" if chips else ""))
    if builds == []:
        say("no builds yet")
    say_media()
    pid = monitor_pid()
    say(f"monitor: running (pid {pid})" if pid else "monitor: not running (python tools/review/review.py monitor)")
    for project, wpid in watchers():
        say(f"watch: {project} (pid {wpid})")
    if builds is not None:
        try:
            say_machine(get_json(PUBLIC + "/api/metrics?window=10m"), get_json(PUBLIC + "/api/comfy"))
        except Exception:
            pass
    urls = [(k, u) for k, u in current_urls() if u]
    for kind, url in urls:
        say(f"public URL ({kind}): {url}")
    if len(urls) > 1:
        say("WARNING more than one public tunnel is active; `down` stops them all")
    if not urls:
        say("no public tunnel (local only)")
    return 0 if builds is not None else 1


def say_media():
    """Where clients write and what the container mounts; a warning when they differ (new images would 404)."""
    mine = media_dir()
    say(f"media: clients write to {mine}")
    mount = container_media_mount()
    if mount is None:
        say("media: the container's mount is unknown (container not running, or docker inspect failed)")
    elif same_path(mount, mine):
        say(f"media: the container mounts the same folder ({mount})")
    else:
        say(f"WARNING media: the container mounts {mount}, not {mine}: new files 404. Run "
            f"`python tools/review/review.py up` again (it mounts the main checkout's out/_review/media, or "
            f"FILM_REVIEW_MEDIA), or set FILM_REVIEW_MEDIA to the mounted folder")


def say_machine(m, c):
    s = m.get("latest") or {}
    if s:
        g = (s.get("gpus") or [{}])[0]

        def gb(b):
            return f"{b / 2 ** 30:.1f}" if b is not None else "?"
        disks = " ".join(f"{d['name']} {gb(d['free'])} GB free" for d in s.get("disks") or [])
        jobs = ", ".join(p["name"] + (f" x{p['count']}" if p["count"] > 1 else "") for p in s.get("procs") or [])
        owner = s.get("gpu_owner") or {}
        say(f"machine ({'live' if m.get('online') else 'stale'}, {m.get('age')} s ago): CPU {s.get('cpu')}% · "
            f"RAM {gb(s.get('ram_used'))}/{gb(s.get('ram_total'))} GB · GPU {g.get('util')}% · VRAM "
            f"{gb(g.get('mem_used'))}/{gb(g.get('mem_total'))} GB · {g.get('temp')} C · {g.get('power')} W · "
            f"{disks}{' · jobs: ' + jobs if jobs else ''} · GPU lock: {owner.get('label') or 'free'}")
    cs = c.get("comfy") or {}
    if cs:
        cur = cs.get("current") or {}
        say(f"ComfyUI: {'up' if cs.get('up') else 'down'} · running {cs.get('running')} · pending {cs.get('pending')}"
            + (f" · step {cur['step']}/{cur['total']} ({cur.get('s_per_step')} s/step)" if cur else ""))


def mp4_duration(path):
    """Seconds from the mp4's mvhd box (None when it cannot be read)."""
    try:
        with open(path, "rb") as f:
            data = f.read(64 << 20)
    except OSError:
        return None

    def boxes(buf, start, end):
        i = start
        while i + 8 <= end:
            size, typ = struct.unpack(">I4s", buf[i:i + 8])
            hdr = 8
            if size == 1:
                size = struct.unpack(">Q", buf[i + 8:i + 16])[0]
                hdr = 16
            elif size == 0:
                size = end - i
            if size < hdr:
                return
            yield typ, i + hdr, min(i + size, end)
            i += size

    for typ, s, e in boxes(data, 0, len(data)):
        if typ == b"moov":
            for t2, s2, e2 in boxes(data, s, e):
                if t2 == b"mvhd":
                    ver = data[s2]
                    if ver == 1:
                        scale, dur = struct.unpack(">IQ", data[s2 + 20:s2 + 32])
                    else:
                        scale, dur = struct.unpack(">II", data[s2 + 12:s2 + 20])
                    return round(dur / scale, 3) if scale else None
    return None


def glb_stats(path):
    """{'verts', 'tris', 'meshes', 'materials', 'animations'} from a .glb's JSON chunk (None when unreadable)."""
    try:
        with open(path, "rb") as f:
            head = f.read(20)
            magic, _, _, clen, ctype = struct.unpack("<4sIII4s", head)
            if magic != b"glTF" or ctype != b"JSON":
                return None
            gltf = json.loads(f.read(clen).decode("utf-8"))
    except (OSError, ValueError, struct.error):
        return None
    acc = gltf.get("accessors") or []
    verts = tris = 0
    for mesh in gltf.get("meshes") or []:
        for prim in mesh.get("primitives") or []:
            pos = (prim.get("attributes") or {}).get("POSITION")
            if pos is not None and pos < len(acc):
                verts += acc[pos].get("count", 0)
            idx = prim.get("indices")
            n = acc[idx].get("count", 0) if idx is not None and idx < len(acc) else (
                acc[pos].get("count", 0) if pos is not None and pos < len(acc) else 0)
            if prim.get("mode", 4) == 4:
                tris += n // 3
    return {"verts": verts, "tris": tris, "meshes": len(gltf.get("meshes") or []),
            "materials": len(gltf.get("materials") or []), "animations": len(gltf.get("animations") or [])}


def build_exists(bid):
    try:
        get_json(f"{PUBLIC}/api/builds/{bid}", timeout=2)
        return True
    except Exception:
        return False


def parse_tags(items):
    """['engine=blender', 'episode=q01t03', 'subject=a,b'] -> {group: [values]} (client.normalize_tags checks them)."""
    out = {}
    for it in items or []:
        g, sep, v = str(it).partition("=")
        if not sep or not g.strip():
            client.tag_warn(f"--tag {it!r} is not group=value: ignored")
            continue
        out.setdefault(g.strip(), []).extend(x for x in v.split(",") if x.strip())
    return out


def _review(a, kind):
    """An existing build keeps its title and kind unless --title is given; a new one is named after the label."""
    tags = parse_tags(a.tag) or None
    if a.title or not build_exists(a.build):
        return client.Review(a.build, a.title or a.label or a.build, kind, project=a.project, tags=tags)
    return client.Review(a.build, None, None, project=a.project, tags=tags)


def cmd_publish_video(a):
    if not os.path.isfile(a.mp4):
        err(f"refused: no such file {a.mp4}")
        return 2
    rv = _review(a, "clip")
    dur = mp4_duration(a.mp4)
    ok = rv.render(a.label, video=a.mp4, duration=dur, fps=a.fps, frames=round(dur * a.fps) if dur and a.fps else None,
                   engine=a.engine)
    if ok and not a.open:
        ok = rv.done()
    if not ok:
        err(f"not delivered ({rv.last_error}); is the server up? python tools/review/review.py up --no-ngrok")
        return 1
    say(f"published {a.mp4} -> build {a.build} ({a.label}{f', {dur:g} s' if dur else ''})")
    return 0


def cmd_publish_model(a):
    if not os.path.isfile(a.glb):
        err(f"refused: no such file {a.glb}")
        return 2
    rv = _review(a, "model")
    stats = glb_stats(a.glb) or {}
    ok = rv.step(a.label or os.path.splitext(os.path.basename(a.glb))[0], glb=a.glb, stats=stats)
    if ok and not a.open:
        ok = rv.done()
    if not ok:
        err(f"not delivered ({rv.last_error}); is the server up? python tools/review/review.py up --no-ngrok")
        return 1
    say(f"published {a.glb} -> build {a.build} ({stats.get('verts', '?')} verts)")
    return 0


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="backslashreplace")
        except (AttributeError, ValueError):
            pass
    p = argparse.ArgumentParser(prog="review.py", description=__doc__.split("\n\n")[0],
                                formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    sp = p.add_subparsers(dest="cmd", required=True)
    q = sp.add_parser("up", help="verify vendor files, docker compose up -d --build, monitor, then a public tunnel")
    q.add_argument("--tunnel", choices=TUNNELS, default="ngrok", help="public tunnel (default ngrok)")
    q.add_argument("--no-ngrok", action="store_true", help="no tunnel: local only (http://127.0.0.1:8790)")
    q.add_argument("--no-monitor", action="store_true", help="do not start monitor.py (machine metrics, ComfyUI)")
    q.add_argument("--dry-run", action="store_true", help="print the commands, start nothing")
    q.add_argument("--comfy-log", default=None, help="ComfyUI log for monitor.py (default: comfy.py start's log)")
    q.add_argument("--interval", type=float, default=None, help="monitor.py interval (default 2 s)")
    q = sp.add_parser("monitor", help="start (or --stop) only monitor.py, detached; pid in out/_review/monitor.pid")
    q.add_argument("--stop", action="store_true")
    q.add_argument("--restart", action="store_true", help="stop the running monitor first (new options)")
    q.add_argument("--comfy-log", default=None)
    q.add_argument("--interval", type=float, default=None)
    q.add_argument("--dry-run", action="store_true")
    q = sp.add_parser("watch", help="watch out/<project>/ and publish work in progress (watch.py, detached)")
    q.add_argument("project", help="the folder under out/ (e.g. son-hai-kinh)")
    q.add_argument("--episode", default=None, help="episode folder whose renders3d/ is watched (e.g. q01t03)")
    q.add_argument("--dir", action="append", default=None,
                   help="a folder to watch, relative to out/<project>/ (repeatable; default characters, locations "
                        "and <episode>/renders3d)")
    q.add_argument("--interval", type=float, default=None, help="seconds between scans (default 5)")
    q.add_argument("--since", type=float, default=None, help="first run: publish files changed in the last N hours")
    q.add_argument("--blender", default=None, help="Blender for the GLB export (default FILM_BLENDER or found)")
    q.add_argument("--no-glb", action="store_true", help="do not export GLB when a <slug>.blend is saved")
    q.add_argument("--max-glb-mb", type=float, default=None, help="decimate a GLB larger than this (default 60)")
    q.add_argument("--decimate", type=float, default=None, help="always decimate to this ratio (0.05..1)")
    q.add_argument("--once", action="store_true", help="scan twice (3 s apart) in the foreground, then exit")
    q.add_argument("--stop", action="store_true")
    q.add_argument("--restart", action="store_true")
    q.add_argument("--dry-run", action="store_true")
    q = sp.add_parser("down", help="docker compose down (keeps the database volume) and stop our tunnel")
    q.add_argument("--dry-run", action="store_true")
    sp.add_parser("url", help="the public URL (ngrok API, cloudflared metrics or the tailscale funnel)")
    sp.add_parser("status", help="builds, media mount, monitor, watchers, tunnel")
    pv = sp.add_parser("publish-video", help="publish a .mp4 to a build (marks the build done unless --open)")
    pm = sp.add_parser("publish-model", help="publish a .glb to a build (marks the build done unless --open)")
    for q, arg in ((pv, "mp4"), (pm, "glb")):
        q.add_argument(arg)
        q.add_argument("--build", required=True, help="build id ([A-Za-z0-9][A-Za-z0-9._-]{0,63})")
        q.add_argument("--label", required=(arg == "mp4"), default=None)
        q.add_argument("--title", default=None, help="build title (default: the label)")
        q.add_argument("--project", default=None)
        q.add_argument("--tag", action="append", default=None, metavar="GROUP=VALUE",
                       help="a tag chip (tools/review/tags.json), e.g. --tag engine=blender --tag episode=q01t03")
        q.add_argument("--open", action="store_true", help="leave the build open (do not mark it done)")
        if arg == "mp4":
            q.add_argument("--fps", type=float, default=24.0)
            q.add_argument("--engine", default=None, help="e.g. blender, comfy:h3-i2v")
    a = p.parse_args(argv)
    if getattr(a, "build", None) and not client.BUILD_ID.match(a.build):
        err("refused: --build must match [A-Za-z0-9][A-Za-z0-9._-]{0,63}")
        return 2
    fn = {"up": cmd_up, "down": cmd_down, "monitor": cmd_monitor, "watch": cmd_watch, "url": cmd_url,
          "status": cmd_status, "publish-video": cmd_publish_video, "publish-model": cmd_publish_model}[a.cmd]
    return fn(a)


if __name__ == "__main__":
    sys.exit(main())
